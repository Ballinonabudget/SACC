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

        # 1. Seed Stores via Canonical Store Directory Resolver
        from sacc_takeout.store_directory_resolver import seed_store_directory
        seed_store_directory(con)

        # 2. Seed Shoes
        shoes = [
            ("shoe_kobe_11_bl", "Nike", "Kobe", "Kobe 11", "Bruce Lee", "822675-706",
             "Basketball", "Kobe 11 Bruce Lee", json.dumps(["Kobe XI", "Kobe 11 Low", "Bruce Lee 11"])),
            ("shoe_kobe_9_persp", "Nike", "Kobe", "Kobe 9", "Perspective", "630847-400",
             "Basketball", "Kobe 9 Elite Perspective", json.dumps(["Kobe IX", "Perspective 9"])),
            ("shoe_kobe_11_mamba", "Nike", "Kobe", "Kobe 11", "Mambacurial", "844130-102",
             "Basketball", "Kobe 11 Mambacurial", json.dumps(["Mambacurial", "Kobe XI FC"])),
            ("shoe_lebron_12_low", "Nike", "LeBron", "LeBron 12 Low", "Court Purple", "724557-565",
             "Basketball", "LeBron 12 Low Court Purple", json.dumps(["LeBron XII Low", "LBJ 12 Low", "LeBron 12 Low Court Purple", "724557-565", "724557 565"])),
            ("shoe_kd_8_hunt", "Nike", "KD", "KD 8", "Hunt's Hill Sunrise", "749375-807",
             "Basketball", "KD 8 Hunt's Hill Sunrise", json.dumps(["KD8", "Sunrise"])),
            ("shoe_lebron_13_written", "Nike", "LeBron", "LeBron 13", "Written in the Stars", "807219-500",
             "Basketball", "LeBron 13 Written in the Stars", json.dumps(["LBJ13", "LeBron XIII"])),
            ("shoe_kobe_9_elite", "Nike", "Kobe", "Kobe 9 Elite", "Wolf Grey/White", "630847-077",
             "Basketball", "Kobe 9 Elite", json.dumps(["Kobe IX Elite", "Kobe 9 High", "630847-077"])),
            ("shoe_aj13_retro", "Jordan", "Air Jordan", "Air Jordan 13 Retro", "Black/Gym Red", "414571-038",
             "Basketball", "Air Jordan 13 Retro", json.dumps(["AJ13", "Jordan 13", "414571-038"])),
            ("shoe_aj1_mid", "Jordan", "Air Jordan", "Air Jordan 1 Mid", "White/Cool Grey", "554724-030",
             "Basketball", "Air Jordan 1 Mid", json.dumps(["AJ1 Mid", "Jordan 1 Mid", "554724-030"])),
            ("shoe_kd8_usa", "Nike", "KD", "KD 8", "USA / 4th of July", "811363-123",
             "Basketball", "Nike KD 8 USA", json.dumps(["KD8", "KD 8 USA", "811363-123"])),
            ("shoe_free_flyknit", "Nike", "Free", "Free 3.0 Flyknit", "Black/White", "718418-002",
             "Running", "Nike Free 3.0 Flyknit", json.dumps(["Free 3.0", "Flyknit 3.0", "718418-002"])),
            ("shoe_air_max_lunar90", "Nike", "Air Max", "Air Max Lunar90", "Infrared / Black", "705302-003",
             "Running", "Nike Air Max Lunar90", json.dumps(["Lunar90", "Air Max 90", "705302-003"])),
            ("shoe_air_max_tr180", "Nike", "Air Max", "Air Max TR180 AMP", "Black/Gum", "723973-002",
             "Training", "Nike Air Max TR180 AMP", json.dumps(["TR180", "Air Max TR", "723973-002"])),
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
            # 1. Solo camera shot: Kobe 11 Bruce Lee at Marketplace (May 2016)
            ("occ_kobe11_may16", "med_1", "Kobe(1).png",
             "0a89a16abd87f4c13b291fcb1f2530ce8be46266bd6c6d393ee84b1f718fcd1c.png",
             "image", "image/png", "2016-05-14T15:30:00Z", "2016-05-14", "store-mkt",
             "in_store_photo", "Apple iPhone 8 Plus", "4032×3024",
             "Kobe 11 Bruce Lee Marketplace May 2016 In-Store Sighting"),

            # 2. Repeat camera sighting: Kobe 11 Bruce Lee at Marketplace (August 2016) with price drop
            ("occ_kobe11_aug16", "med_2", "Kobe.png",
             "497278057f4e48c21e2c9067f446e01b4fd9240ad97a9e9811620c57dde8544d.png",
             "image", "image/png", "2016-08-22T17:15:00Z", "2016-08-22", "store-mkt",
             "in_store_photo", "Apple iPhone", "4032×3024",
             "Kobe 11 Bruce Lee Marketplace August 2016 Clearance Repeat Sighting"),

            # 3. Wall camera shot: Nike Multiples (Kobe 11 + KD 8 + LeBron 13) at Marketplace (June 2016)
            ("occ_wall_june16", "med_3", "Kobe(2).png",
             "768f1452453bf6739e4a3b52e550478a3924480de82ff571f546cc18c0ba3a18.png",
             "image", "image/png", "2016-06-18T14:00:00Z", "2016-06-18", "store-mkt",
             "in_store_photo", "Apple iPhone", "1466×836",
             "Nike Basketball Clearance Wall June 2016 Multiple Shoes Shelf View"),

            # 4. Solo camera shot: Kobe 9 Elite at I-Drive (July 2015)
            ("occ_kobe9_jul15", "med_4", "Kobe_AD_ID_final_side.png",
             "c14373c142d1180fd2ed3958f1aa6f0b16119b720d914ac2f6c271159f811316.png",
             "image", "image/png", "2015-07-10T11:45:00Z", "2015-07-10", "store-idr",
             "studio_cutout", "Studio Render (Cutout)", "640×640",
             "Kobe 9 Elite Perspective I-Drive July 2015 In-Store Sighting"),

            # 5. Authentic in-store camera shot: LeBron 12 Low Box Label at Marketplace (Jan 2016)
            ("occ_lebron12_box_jan16", "med_lb12_box", "IMG_7995.JPG",
             "fcaa8b9fcfd74549d07695117315f5076f5ee51a1e78e5f217422968d2572bdd.jpg",
             "image", "image/jpeg", "2016-01-01T22:47:05Z", "2016-01-01", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "LeBron 12 Low Court Purple Marketplace Box Label 724557-565 In-Store"),

            # 6. Authentic in-store camera shot: LeBron 12 Low Pair Sighting with Crown Logo at Marketplace (Jan 2016)
            ("occ_lebron12_pair_jan16", "med_lb12_pair", "IMG_7999.JPG",
             "998cba2e33e75cbeaf828a00e2dd42f1a2c8f4fbd13d831cdddad2085c3e47ca.jpg",
             "image", "image/jpeg", "2016-01-01T22:51:59Z", "2016-01-01", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "LeBron 12 Low Court Purple Marketplace Pair Sighting Crown Logo In-Store"),

            # 7. Authentic in-store camera shot: LeBron 12 Low Clearance Markdown at Marketplace (Aug 2016)
            ("occ_lebron12_rep_aug16", "med_lb12_rep", "IMG_7996.JPG",
             "ef1fe9beb16a8a8d5889ea94415e5b3422dcb833ba83619f099dcd02570842c7.jpg",
             "image", "image/jpeg", "2016-08-22T17:15:00Z", "2016-08-22", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "LeBron 12 Low Court Purple Marketplace Clearance Repeat Sighting 724557-565"),

            # 8. Solo camera shot: Air Jordan 11 Concord at I-Drive (December 2018)
            ("occ_aj11_dec18", "med_5", "IMG_8009.JPG",
             "6480140833f78c3084779507c1e5e8da3121e760699d0e1b06a942a1211e5ab8.jpg",
             "image", "image/jpeg", "2018-12-08T16:20:00Z", "2018-12-08", "store-idr",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "Air Jordan 11 Concord I-Drive December 2018 In-Store Sighting"),

            # 9. Wall camera shot: Jordan Multiples (AJ1 + AJ11) at I-Drive (November 2018)
            ("occ_wall_nov18", "med_6", "IMG_8004.JPG",
             "1f15f2c1f33c35268b0bbfe52e1b5ac97e78275b4521d35b7fd93961ace7d2b0.jpg",
             "image", "image/jpeg", "2018-11-24T18:00:00Z", "2018-11-24", "store-idr",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "Jordan Multiples Wall Display November 2018 In-Store"),

            # 10. Studio Cutout: Kobe 11 Mambacurial at Marketplace (Background removed render)
            ("occ_kobe11_undated", "med_7", "Kobe_AD_ID_final.png",
             "e279bc799af78c6f1fcff7cdc98b5228d945f250d354d03a61ff2b1bf9383163.png",
             "image", "image/png", None, None, "store-mkt",
             "studio_cutout", "Studio Render (Cutout)", "640×640",
             "Kobe 11 Mambacurial Marketplace Undated Studio Cutout"),

            # 11. Studio Cutout: Ultraboost 3.0 Triple White (Background removed render)
            ("occ_ub_oct17", "med_8", "Kobe_profile_render.png",
             "0c0be8945c6b47be9f80cc79faf07970ec79d77b42a0e098843b639bac15b165.png",
             "image", "image/png", "2017-10-15T13:10:00Z", "2017-10-15", "store-adi",
             "studio_cutout", "Studio Render (Cutout)", "640×640",
             "Adidas Ultraboost 3.0 Triple White October 2017 Studio Cutout"),

            # 12. Authentic in-store camera shot: Kobe 9 Elite Box Label at Marketplace (Dec 2015) - Markdown $199.99
            ("occ_kobe9_elite_dec15", "med_k9_dec15", "IMG_6604.JPG",
             "61444f0c06f5050ee2eae40afd68e188f05e4e7fbf932a2af9fce5360493512e.jpg",
             "image", "image/jpeg", "2015-12-17T20:25:00Z", "2015-12-17", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "KOBE IX ELITE 630847-077 Marketplace Clearance Box Label $199.99 Sighting"),

            # 13. Authentic in-store camera shot: Air Jordan 13 Retro Box Tag at Marketplace (Dec 2018)
            ("occ_aj13_dec18", "med_aj13_dec18", "IMG_8177.JPG",
             "dd3ae18b772031e15bb03d1b1b7383f4c373013fe3ec29a48947ceb4e41d162f.jpg",
             "image", "image/jpeg", "2018-12-19T21:10:00Z", "2018-12-19", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "AIR JORDAN 13 RETRO 414571-038 Marketplace In-Store Box Tag"),

            # 14. Authentic in-store camera shot: Air Jordan 1 Mid Box Tag at Marketplace (Dec 2015)
            ("occ_aj1_mid_dec15", "med_aj1m_dec15", "IMG_6626.JPG",
             "9e2f08c1ebcc8b717702bd1450ee10466456e3b67346962d934d6ddc32c0a9c3.jpg",
             "image", "image/jpeg", "2015-12-17T20:40:00Z", "2015-12-17", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "AIR JORDAN 1 MID 554724-030 Marketplace In-Store Box Tag $110"),

            # 15. Authentic in-store camera shot: Nike KD 8 USA Rack Label at Marketplace (Dec 2015)
            ("occ_kd8_dec15", "med_kd8_dec15", "IMG_6606.JPG",
             "28d6ff8071da89af661a965d0c3d2d47d643976877a43eae8a107b30019f591a.jpg",
             "image", "image/jpeg", "2015-12-17T20:26:00Z", "2015-12-17", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "NIKE KD 8 USA 811363-123 Marketplace In-Store Rack Label"),

            # 16. Authentic in-store camera shot: Nike Free 3.0 Flyknit Box Label at Marketplace (Jan 2016)
            ("occ_free_jan16", "med_free_jan16", "IMG_7988.JPG",
             "98d6948c8d925a32724408f055a835e4bf777dc0922c52d7b16a9f2a98395aea.jpg",
             "image", "image/jpeg", "2016-01-01T22:42:00Z", "2016-01-01", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "NIKE FREE 3.0 FLYKNIT 718418-002 Marketplace In-Store Box Label $140"),

            # 17. Authentic in-store camera shot: Nike Air Max Lunar90 Clearance Rack Tag (Sep 2015)
            ("occ_lunar90_sep15", "med_lunar90_sep15", "2015-09-15 22.24.21.jpg",
             "776c661fc806a49b9a72f4eb555b1b3a91cf37e7455421e581563e06acd716ce.jpg",
             "image", "image/jpeg", "2015-09-16T02:24:21Z", "2015-09-15", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "NIKE AIR MAX LUNAR90 705302-003 Marketplace Clearance Rack Tag $89"),

            # 18. Authentic in-store camera shot: Nike Air Max TR180 AMP Box Label at Marketplace (Jan 2016)
            ("occ_tr180_jan16", "med_tr180_jan16", "IMG_8001.JPG",
             "cf9127d2c55f91ea9adbca6b796217f6451d7a72d0b3a49653efc944ec5b2d7d.jpg",
             "image", "image/jpeg", "2016-01-01T22:53:00Z", "2016-01-01", "store-mkt",
             "in_store_photo", "Apple iPhone 6", "3264×2448",
             "NIKE AIR MAX TR180 AMP 723973-002 Marketplace In-Store Box Label $104.99"),
        ]

        denivic_dir = Path("/Users/daplug/Documents/SACC_Data/recovery/denivic/objects")
        for oid, mid, name, obj_file, mtype, mime, cap_utc, eff_date, store_id, ctype, cam_model, res, stext in occurrences:
            obj_path = objects_dir / obj_file
            if not obj_path.exists():
                dpath = denivic_dir / obj_file
                if dpath.exists():
                    obj_path = dpath

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
                    review_revision, needs_attention, embedding_status, raw_json, overrides_json, search_text,
                    capture_type, camera_model, photo_resolution
                ) VALUES (
                    ?, ?, 'imp-pilot-1', 'plan-pilot', ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, 1, ?, 'exif_timestamp',
                    1, 28.47, -81.45, 0, 'non_personal', ?,
                    0, 0, 'metadata_write_readback_passed', '{"review_reasons":[]}', '{}', ?,
                    ?, ?, ?
                )
                """,
                (
                    oid, mid, str(recovery_root), f"/synthetic/orig/{name}", name,
                    mtype, mime, rec_path, f"fsha-{oid}", file_size, mtime_ns,
                    cap_utc, eff_date, eff_date, store_id, stext,
                    ctype, cam_model, res,
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

            # 9. Authentic In-Store LeBron 12 Low Sightings at Marketplace (Box Label, Crown Pair, Repeat Markdown)
            ("assoc_lb12_box", "occ_lebron12_box_jan16", "shoe_lebron_12_low", "solo", None, 1.0, "Verified retail box label: LEBRON XII LOW (724557 565), MSRP $175.00", 175.00),
            ("assoc_lb12_pair", "occ_lebron12_pair_jan16", "shoe_lebron_12_low", "solo", None, 1.0, "Retail box pair with visible LeBron James crown logo ('LJ')", 139.99),
            ("assoc_lb12_rep", "occ_lebron12_rep_aug16", "shoe_lebron_12_low", "solo", None, 1.0, "Clearance rack repeat markdown", 99.99),

            # 10. Discovered Real Marketplace Store Sightings from 3,161 Photo Scan
            ("assoc_kobe9_elite", "occ_kobe9_elite_dec15", "shoe_kobe_9_elite", "solo", None, 1.0, "Verified in-store box label: KOBE IX ELITE (630847-077), clearance $199.99 from $225", 199.99),
            ("assoc_aj13_retro", "occ_aj13_dec18", "shoe_aj13_retro", "solo", None, 1.0, "Verified in-store box tag: AIR JORDAN 13 RETRO (414571-038)", None),
            ("assoc_aj1_mid", "occ_aj1_mid_dec15", "shoe_aj1_mid", "solo", None, 1.0, "Verified in-store box tag: AIR JORDAN 1 MID (554724-030), $110.00", 110.00),
            ("assoc_kd8_usa", "occ_kd8_dec15", "shoe_kd8_usa", "solo", None, 1.0, "Verified in-store rack label: KD 8 USA (811363-123)", 129.99),
            ("assoc_free_flyknit", "occ_free_jan16", "shoe_free_flyknit", "solo", None, 1.0, "Verified in-store box label: NIKE FREE 3.0 FLYKNIT (718418-002), $140.00", 140.00),
            ("assoc_air_max_lunar90", "occ_lunar90_sep15", "shoe_air_max_lunar90", "solo", None, 1.0, "Verified clearance price tag: NIKE AIR MAX LUNAR90 (705302-003), $89.00", 89.00),
            ("assoc_air_max_tr180", "occ_tr180_jan16", "shoe_air_max_tr180", "solo", None, 1.0, "Verified in-store box label: NIKE AIR MAX TR180 AMP (723973-002), MSRP $175.00 observed $104.99", 104.99),
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
