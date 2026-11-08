"""
Automated tests for the SACC Footwear Library Search Pilot.
Validates:
- Line, model, colorway, and exact SKU discovery.
- Multi-select year filtering, unchecking, and empty-set behavior.
- Confirmed store branch narrowing.
- Wall shots returning once while linking all individual shoes.
- Repeat sightings preserved across distinct months/years.
- API endpoints on the local boundary.
"""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from sacc_takeout.library import LibraryDB
from sacc_takeout.pilot_fixtures import create_pilot_database


class LibrarySearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name).resolve() / "test-search-catalog.sqlite3"
        create_pilot_database(self.db_path)
        self.db = LibraryDB(self.db_path)

    def test_search_by_shoe_line_kobe(self):
        """Searching 'Kobe' discovers solo, repeat, wall shot, and undated captures across models."""
        res = self.db.search_footwear(q="Kobe")
        self.assertEqual(res["total"], 5)
        titles = {r["display_title"] for r in res["results"]}
        self.assertIn("Kobe 11 Bruce Lee", titles)
        self.assertIn("Kobe 9 Elite Perspective", titles)
        self.assertIn("Nike Multiples", titles)

    def test_search_by_model_kobe_11(self):
        """Searching 'Kobe 11' narrows to Kobe 11 instances, excluding Kobe 9."""
        res = self.db.search_footwear(q="Kobe 11")
        self.assertEqual(res["total"], 4)
        for r in res["results"]:
            shoe_names = [s["display_name"] for s in r["shoes"]]
            self.assertTrue(any("Kobe 11" in name for name in shoe_names))
            self.assertFalse(any("Kobe 9" in name for name in shoe_names))

    def test_search_by_colorway_bruce_lee(self):
        """Searching colorway 'Bruce Lee' returns solo, repeat, and wall shot."""
        res = self.db.search_footwear(q="Bruce Lee")
        self.assertEqual(res["total"], 3)
        for r in res["results"]:
            shoe_names = [s["display_name"] for s in r["shoes"]]
            self.assertTrue(any("Bruce Lee" in name for name in shoe_names))

    def test_search_by_exact_and_normalized_sku(self):
        """Exact style code matching preserves leading zeros and accepts normalized formats."""
        res1 = self.db.search_footwear(q="822675-706")
        self.assertEqual(res1["total"], 3)

        res2 = self.db.search_footwear(q="822675706")
        self.assertEqual(res2["total"], 3)

        res3 = self.db.search_footwear(q="378037-100")
        self.assertEqual(res3["total"], 2)  # AJ11 Concord solo + Jordan Multiples wall shot

    def test_narrow_by_store(self):
        """Filtering by store restricts results to that confirmed retail branch."""
        # Marketplace clearance
        res_mkt = self.db.search_footwear(q="Kobe", store="store-mkt")
        self.assertEqual(res_mkt["total"], 4)
        for r in res_mkt["results"]:
            self.assertEqual(r["store"]["id"], "store-mkt")

        # I-Drive factory
        res_idr = self.db.search_footwear(q="Kobe", store="store-idr")
        self.assertEqual(res_idr["total"], 1)
        self.assertEqual(res_idr["results"][0]["store"]["id"], "store-idr")
        self.assertEqual(res_idr["results"][0]["display_title"], "Kobe 9 Elite Perspective")

    def test_multi_year_selection_and_empty_behavior(self):
        """Multiple capture years can be checked, unchecked, or undated."""
        # Check 2015 and 2016
        res_both = self.db.search_footwear(q="Kobe", years=["2015", "2016"])
        self.assertEqual(res_both["total"], 4)  # 2015 Kobe 9 + 3x 2016 Kobe 11 occurrences

        # Uncheck 2015 -> only 2016
        res_2016 = self.db.search_footwear(q="Kobe", years=["2016"])
        self.assertEqual(res_2016["total"], 3)
        for r in res_2016["results"]:
            self.assertEqual(r["capture_year"], 2016)

        # Only Undated
        res_undated = self.db.search_footwear(q="Kobe", years=["undated"])
        self.assertEqual(res_undated["total"], 1)
        self.assertEqual(res_undated["results"][0]["capture_month_year"], "Undated")

        # Uncheck all years -> empty list yields 0 results per design spec
        res_empty = self.db.search_footwear(q="Kobe", years=[])
        self.assertEqual(res_empty["total"], 0)
        self.assertEqual(len(res_empty["results"]), 0)

    def test_wall_shot_returns_once_with_all_shoes(self):
        """Wall shots appear once in search results, representing each identified shoe."""
        res = self.db.search_footwear(q="Nike Multiples")
        self.assertEqual(res["total"], 1)
        wall_shot = res["results"][0]
        self.assertTrue(wall_shot["is_wall_shot"])
        self.assertEqual(wall_shot["display_title"], "Nike Multiples")
        self.assertEqual(len(wall_shot["shoes"]), 3)
        shoe_models = {s["model"] for s in wall_shot["shoes"]}
        self.assertEqual(shoe_models, {"Kobe 11", "KD 8", "LeBron 13"})

        # The same wall shot is discoverable via KD 8
        res_kd = self.db.search_footwear(q="KD 8")
        self.assertEqual(res_kd["total"], 1)
        self.assertEqual(res_kd["results"][0]["id"], wall_shot["id"])

    def test_repeat_sightings_separate_with_month_year(self):
        """Repeat sightings of the same shoe at the same store appear separately with capture dates."""
        res = self.db.search_footwear(q="822675-706", store="store-mkt")
        # 3 occurrences: May 2016 solo, June 2016 wall shot, August 2016 repeat solo
        self.assertEqual(res["total"], 3)
        solo_sightings = [r for r in res["results"] if not r["is_wall_shot"]]
        self.assertEqual(len(solo_sightings), 2)

        sighting_dates = [r["capture_month_year"] for r in solo_sightings]
        self.assertEqual(sighting_dates, ["May 2016", "August 2016"])

        # Check observed price on the repeat sighting
        may_sighting = next(r for r in solo_sightings if "May" in r["capture_month_year"])
        aug_sighting = next(r for r in solo_sightings if "August" in r["capture_month_year"])
        self.assertEqual(may_sighting["shoes"][0]["price_observed"], 160.00)
        self.assertEqual(aug_sighting["shoes"][0]["price_observed"], 119.99)

    def test_pilot_api_endpoints(self):
        """Test local FastAPI pilot search and facets routes."""
        import main
        from unittest.mock import patch
        
        client = TestClient(main.app, base_url="http://127.0.0.1:5174")
        with patch("sacc_takeout.library_api.get_pilot_db", return_value=self.db), \
             patch("sacc_takeout.library_api.LibraryDB", return_value=self.db):
            # Authorize session
            s_res = client.get("/api/library/session", headers={"Origin": "http://127.0.0.1:5174"})
            self.assertEqual(s_res.status_code, 200)
            csrf = s_res.json()["csrf_token"]

            # Pilot search
            search_res = client.get(
                "/api/library/pilot/search?q=Kobe&years=2015,2016&store=store-mkt",
                headers={"X-SACC-Library-Token": csrf, "Origin": "http://127.0.0.1:5174"},
            )
            self.assertEqual(search_res.status_code, 200)
            data = search_res.json()
            self.assertEqual(data["total"], 3)

            # Pilot facets
            facets_res = client.get(
                "/api/library/pilot/facets?q=Kobe",
                headers={"X-SACC-Library-Token": csrf, "Origin": "http://127.0.0.1:5174"},
            )
            self.assertEqual(facets_res.status_code, 200)
            fdata = facets_res.json()
            self.assertTrue(any(y["value"] == "2016" for y in fdata["years"]))
            self.assertTrue(any(s["code"] == "ORL-MKT-CLR" for s in fdata["stores"]))
            self.assertEqual(facets_res.status_code, 200)
            fdata = facets_res.json()
            self.assertTrue(any(y["value"] == "2016" for y in fdata["years"]))
            self.assertTrue(any(s["code"] == "ORL-MKT-CLR" for s in fdata["stores"]))


if __name__ == "__main__":
    unittest.main()
