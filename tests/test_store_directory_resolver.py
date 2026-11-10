#!/usr/bin/env python3
"""
Unit tests for SACC Store Directory & Location Resolver.
"""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sacc_takeout.store_directory_resolver import (
    STORE_REGISTRY,
    haversine_m,
    resolve_store_for_occurrence,
    seed_store_directory,
)
from sacc_takeout.pilot_fixtures import SCHEMA


class StoreDirectoryResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test_store_resolver.sqlite3"
        self.con = sqlite3.connect(self.db_path)
        self.con.executescript(SCHEMA)

    def tearDown(self):
        self.con.close()

    def test_haversine_distance_calculation(self):
        # Distance between Marketplace (28.468446, -81.451038) and I-Drive (28.476218, -81.449292) is ~880m
        dist = haversine_m(28.468446, -81.451038, 28.476218, -81.449292)
        self.assertGreater(dist, 800)
        self.assertLess(dist, 950)

    def test_resolve_active_marketplace_store(self):
        # Exact Marketplace coordinates
        res = resolve_store_for_occurrence(28.468446, -81.451038, "2015-12-17")
        self.assertIsNotNone(res)
        self.assertEqual(res["store"]["code"], "ORL-MKT-CLR")
        self.assertEqual(res["store"]["status"], "active")

    def test_resolve_historical_nc192_vs_loop_temporal_window(self):
        # Historical US-192 location (28.318078, -81.468856) in 2016 -> resolves to NC192 (defunct)
        res_old = resolve_store_for_occurrence(28.318078, -81.468856, "2016-07-07")
        self.assertIsNotNone(res_old)
        self.assertEqual(res_old["store"]["code"], "KSM-NC192-CLR")
        self.assertEqual(res_old["store"]["status"], "defunct")
        self.assertEqual(res_old["store"]["predecessor_to"], "KSM-NCLP-CLR")

        # The Loop location (28.343809, -81.429050) in 2021 -> resolves to NCLP (active)
        res_loop = resolve_store_for_occurrence(28.343809, -81.429050, "2021-04-01")
        self.assertIsNotNone(res_loop)
        self.assertEqual(res_loop["store"]["code"], "KSM-NCLP-CLR")
        self.assertEqual(res_loop["store"]["status"], "active")
        self.assertEqual(res_loop["store"]["successor_to"], "KSM-NC192-CLR")

    def test_seed_store_directory_idempotence(self):
        # First seed
        count1 = seed_store_directory(self.con)
        self.assertEqual(count1, len(STORE_REGISTRY))

        # Re-seed (idempotent)
        count2 = seed_store_directory(self.con)
        self.assertEqual(count2, len(STORE_REGISTRY))

        # Verify DB records
        cur = self.con.cursor()
        cur.execute("SELECT count(*) FROM library_stores")
        self.assertEqual(cur.fetchone()[0], len(STORE_REGISTRY))

        # Verify defunct flag and historical note in DB
        cur.execute("SELECT code, payload_json FROM library_stores WHERE code = 'KSM-NC192-CLR'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertIn('"status": "defunct"', row[1])
        self.assertIn("US-192", row[1])


if __name__ == "__main__":
    unittest.main()
