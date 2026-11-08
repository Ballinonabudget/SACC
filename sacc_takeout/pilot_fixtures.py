"""
Synthetic test fixtures for the SACC Footwear Search Pilot.
Seeds a private staging database with verified scenarios:
- Kobe line searches (solo, repeat sightings, multi-shoe wall shots, undated).
- Multi-year filter scenarios (2015, 2016, 2017, 2018, undated).
- Confirmed store filtering (Marketplace Clearance vs I-Drive Factory).
- Exact SKU equality (e.g. 822675-706).
- Wall shots returning once while indexing each contained shoe.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Optional

from .library import LibraryDB, SCHEMA, DEFAULT_ROOT, DEFAULT_RECOVERY
from .library_search import ensure_catalog_schema

PILOT_DB_PATH = DEFAULT_ROOT / "sacc-library-pilot.sqlite3"


def create_pilot_database(db_path: Optional[Path] = None) -> Path:
    """Create and seed the private staging database with synthetic test records."""
    target = Path(db_path or PILOT_DB_PATH).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        target.unlink()

    con = sqlite3.connect(target)
    try:
        con.executescript(SCHEMA)
        ensure_catalog_schema(con)

        # 1. Seed Stores
        stores = [
            ("store-mkt", "STORE-MKT", "ORL-MKT-CLR", "Nike Clearance Store - Marketplace",
             "2014-01-01", "2025-12-31", json.dumps(["Marketplace", "Marketplace Clearance", "Nike Clearance"])),
            ("store-idr", "STORE-IDR", "ORL-IDR-FAC", "Nike Factory Store - International Drive",
             "2014-01-01", "2025-12-31", json.dumps(["I-Drive", "I Drive Factory", "Nike I-Drive"])),
            ("store-adi", "STORE-ADI", "ORL-ADI-OUT", "Adidas Outlet - Orlando International",
             "2015-01-01", "2025-12-31", json.dumps(["Adidas Outlet", "Adidas I-Drive"])),
        ]
        con.executemany(
            """
            INSERT INTO library_stores (id, store_id, code, label, valid_from, valid_to, aliases_json, payload_json, directory_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 'dir-fixture-1')
            """,
            stores,
        )

        # 2. Seed Shoes
        shoes = [
            ("shoe_kobe_11_bl", "Nike", "Kobe", "Kobe 11", "Bruce Lee", "822675-706",
             "Basketball", "Kobe 11 Bruce Lee", json.dumps(["Kobe XI", "Kobe 11 Low", "Bruce Lee 11"])),
            ("shoe_kobe_9_persp", "Nike", "Kobe", "Kobe 9", "Perspective", "630847-400",
             "Basketball", "Kobe 9 Elite Perspective", json.dumps(["Kobe IX", "Perspective 9"])),
            ("shoe_kobe_11_mamba", "Nike", "Kobe", "Kobe 11", "Mambacurial", "844130-102",
             "Basketball", "Kobe 11 Mambacurial", json.dumps(["Mambacurial", "Kobe XI FC"])),
            ("shoe_kd_8_hunt", "Nike", "KD", "KD 8", "Hunt's Hill Sunrise", "749375-807",
             "Basketball", "KD 8 Hunt's Hill Sunrise", json.dumps(["KD8", "Sunrise"])),
            ("shoe_lebron_13_written", "Nike", "LeBron", "LeBron 13", "Written in the Stars", "807219-500",
             "Basketball", "LeBron 13 Written in the Stars", json.dumps(["LBJ13", "LeBron XIII"])),
            ("shoe_aj1_chicago", "Jordan", "Air Jordan", "Air Jordan 1", "Chicago", "555088-101",
             "Basketball", "Air Jordan 1 Retro High OG Chicago", json.dumps(["AJ1", "Jordan 1", "AJ1 Chicago"])),
            ("shoe_aj11_concord", "Jordan", "Air Jordan", "Air Jordan 11", "Concord", "378037-100",
             "Basketball", "Air Jordan 11 Concord", json.dumps(["AJ11", "Jordan 11", "Concord 11"])),
            ("shoe_ub_triple_white", "Adidas", "Ultraboost", "Ultraboost 3.0", "Triple White", "BA8841",
             "Running", "Ultraboost 3.0 Triple White", json.dumps(["UB3", "Triple White Boost"])),
        ]
        con.executemany(
            """
            INSERT INTO library_shoes (id, brand, line, model, colorway, sku, category, display_name, aliases_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            shoes,
        )

        # 3. Seed Occurrences & Associations
        recovery_root = DEFAULT_RECOVERY
        objects_dir = recovery_root / "objects"

        # Base import and media rows for foreign keys
        con.execute(
            """
            INSERT INTO library_imports (id, plan_id, watermark, report_sha, source_root, summary_json)
            VALUES ('imp-pilot-1', 'plan-pilot', 1, 'sha-fixture', ?, '{}')
            """,
            (str(recovery_root),)
        )

        occurrences = [
            # 1. Solo still: Kobe 11 Bruce Lee at Marketplace (May 2016)
            ("occ_kobe11_may16", "med_1", "IMG_20160514_KOBE11.JPG",
             "e279bc799af78c6f1fcff7cdc98b5228d945f250d354d03a61ff2b1bf9383163.png",
             "image", "image/png", "2016-05-14T15:30:00Z", "2016-05-14", "store-mkt",
             "Kobe 11 Bruce Lee Marketplace May 2016"),

            # 2. Repeat sighting: Kobe 11 Bruce Lee at Marketplace (August 2016) with price drop
            ("occ_kobe11_aug16", "med_2", "IMG_20160822_KOBE11.JPG",
             "0c0be8945c6b47be9f80cc79faf07970ec79d77b42a0e098843b639bac15b165.png",
             "image", "image/png", "2016-08-22T17:15:00Z", "2016-08-22", "store-mkt",
             "Kobe 11 Bruce Lee Marketplace August 2016"),

            # 3. Wall shot: Nike Multiples (Kobe 11 + KD 8 + LeBron 13) at Marketplace (June 2016)
            ("occ_wall_june16", "med_3", "IMG_20160618_WALL.JPG",
             "406542de439372ca6f590198d2aa1c605b6d3488fe5d18d4f037a2eba84b4a60.png",
             "image", "image/png", "2016-06-18T14:00:00Z", "2016-06-18", "store-mkt",
             "Nike Basketball Clearance Wall June 2016 Multiple Shoes"),

            # 4. Solo still: Kobe 9 Elite at I-Drive (July 2015)
            ("occ_kobe9_jul15", "med_4", "IMG_20150710_KOBE9.JPG",
             "c14373c142d1180fd2ed3958f1aa6f0b16119b720d914ac2f6c271159f811316.png",
             "image", "image/png", "2015-07-10T11:45:00Z", "2015-07-10", "store-idr",
             "Kobe 9 Elite Perspective I-Drive July 2015"),

            # 5. Solo still: Air Jordan 11 Concord at I-Drive (December 2018)
            ("occ_aj11_dec18", "med_5", "IMG_20181208_CONCORD.JPG",
             "f2d744b1a4fc9f7429ed4be9594a3d723cc8262cd612c7bbfe559eba9a7fff9c.jpg",
             "image", "image/jpeg", "2018-12-08T16:20:00Z", "2018-12-08", "store-idr",
             "Air Jordan 11 Concord I-Drive December 2018"),

            # 6. Wall shot: Jordan Multiples (AJ1 + AJ11) at I-Drive (November 2018)
            ("occ_wall_nov18", "med_6", "IMG_20181124_JORDANWALL.JPG",
             "f75e16205553b491f0eda986f1d5668b884b87ce62c5da1e7d6aadb7b364926b.png",
             "image", "image/png", "2018-11-24T18:00:00Z", "2018-11-24", "store-idr",
             "Jordan Multiples Wall Display November 2018"),

            # 7. Undated solo still: Kobe 11 Mambacurial at Marketplace
            ("occ_kobe11_undated", "med_7", "IMG_UNDATED_MAMBACURIAL.JPG",
             "0a89a16abd87f4c13b291fcb1f2530ce8be46266bd6c6d393ee84b1f718fcd1c.png",
             "image", "image/png", None, None, "store-mkt",
             "Kobe 11 Mambacurial Marketplace Undated"),

            # 8. Solo still: Ultraboost at Adidas Outlet (October 2017)
            ("occ_ub_oct17", "med_8", "IMG_20171015_BOOST.JPG",
             "cd237c105bc3388200cea536624430d6e5f495ef9911d494f34ae3e675f9050a.png",
             "image", "image/png", "2017-10-15T13:10:00Z", "2017-10-15", "store-adi",
             "Adidas Ultraboost 3.0 Triple White October 2017"),
        ]

        for oid, mid, name, obj_file, mtype, mime, cap_utc, eff_date, store_id, stext in occurrences:
            obj_path = objects_dir / obj_file
            if obj_path.exists():
                st = obj_path.stat()
                file_size = st.st_size
                mtime_ns = st.st_mtime_ns
                rec_path = str(obj_path)
            else:
                file_size = 1024000
                mtime_ns = 1000000
                rec_path = f"/synthetic/rec/{name}"

            con.execute(
                """
                INSERT OR IGNORE INTO library_media (id, account_id, source_sha256, remote_eligible)
                VALUES (?, 'acc-1', ?, 0)
                """,
                (mid, f"sha-{mid}"),
            )
            con.execute(
                """
                INSERT INTO library_occurrences (
                    id, media_id, import_id, plan_id, source_root, original_path, original_name,
                    media_type, mime_type, recovered_path, final_sha256, file_size_bytes, mtime_ns,
                    capture_utc, source_date, source_date_trusted, effective_date, date_basis,
                    date_trusted, gps_lat, gps_lon, screenshot, privacy, store_version_id,
                    review_revision, needs_attention, embedding_status, raw_json, overrides_json, search_text
                ) VALUES (
                    ?, ?, 'imp-pilot-1', 'plan-pilot', ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, 1, ?, 'exif_timestamp',
                    1, 28.47, -81.45, 0, 'non_personal', ?,
                    0, 0, 'metadata_write_readback_passed', '{"review_reasons":[]}', '{}', ?
                )
                """,
                (
                    oid, mid, str(recovery_root), f"/synthetic/orig/{name}", name,
                    mtype, mime, rec_path, f"fsha-{oid}", file_size, mtime_ns,
                    cap_utc, eff_date, eff_date, store_id, stext,
                ),
            )

        # 4. Seed Associations
        associations = [
            # 1. Solo: Kobe 11 Bruce Lee (May 2016)
            ("assoc_1", "occ_kobe11_may16", "shoe_kobe_11_bl", "solo", None, 1.0, "Verified tongue tag", 160.00),

            # 2. Repeat: Kobe 11 Bruce Lee (August 2016) - Clearance price $119.99
            ("assoc_2", "occ_kobe11_aug16", "shoe_kobe_11_bl", "solo", None, 1.0, "Shelf markdown sticker", 119.99),

            # 3. Wall shot (June 2016): Kobe 11 Bruce Lee + KD 8 + LeBron 13
            ("assoc_3a", "occ_wall_june16", "shoe_kobe_11_bl", "wall_item", "Nike Multiples", 0.95, "Wall shelf view", 139.99),
            ("assoc_3b", "occ_wall_june16", "shoe_kd_8_hunt", "wall_item", "Nike Multiples", 0.95, "Wall shelf view", 129.99),
            ("assoc_3c", "occ_wall_june16", "shoe_lebron_13_written", "wall_item", "Nike Multiples", 0.95, "Wall shelf view", 149.99),

            # 4. Solo: Kobe 9 Elite Perspective (July 2015)
            ("assoc_4", "occ_kobe9_jul15", "shoe_kobe_9_persp", "solo", None, 1.0, "Box label", 199.99),

            # 5. Solo: Air Jordan 11 Concord (December 2018)
            ("assoc_5", "occ_aj11_dec18", "shoe_aj11_concord", "solo", None, 1.0, "Display pair", 220.00),

            # 6. Wall shot (November 2018): AJ1 Chicago + AJ11 Concord
            ("assoc_6a", "occ_wall_nov18", "shoe_aj1_chicago", "wall_item", "Jordan Multiples", 0.98, "Clearance row", 160.00),
            ("assoc_6b", "occ_wall_nov18", "shoe_aj11_concord", "wall_item", "Jordan Multiples", 0.98, "Clearance row", 220.00),

            # 7. Undated Solo: Kobe 11 Mambacurial
            ("assoc_7", "occ_kobe11_undated", "shoe_kobe_11_mamba", "solo", None, 1.0, "Catalog still", None),

            # 8. Solo: Adidas Ultraboost 3.0 (October 2017)
            ("assoc_8", "occ_ub_oct17", "shoe_ub_triple_white", "solo", None, 1.0, "Display table", 129.99),
        ]

        con.executemany(
            """
            INSERT INTO library_shoe_associations (
                id, occurrence_id, shoe_id, tag_type, group_descriptor, confidence, evidence, price_observed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            associations,
        )

        con.commit()
    finally:
        con.close()

    return target


if __name__ == "__main__":
    db_file = create_pilot_database()
    print(f"Successfully seeded pilot database: {db_file}")
