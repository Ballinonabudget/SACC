#!/usr/bin/env python3
"""
SACC Store Photo Scanner & Local Recognition Engine
===================================================
Scans photos at specified retail store locations using Apple Vision OCR & CLIP
leveraging the canonical Outlet Plug store directories and historical archives.

Usage:
    python3 scripts/scan_store_photos.py --store KSM-NC192-CLR
    python3 scripts/scan_store_photos.py --store ORL-IDR-FAC --limit 500
    python3 scripts/scan_store_photos.py --store all --limit 100
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from typing import List, Dict, Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
OCR_BINARY = REPO_ROOT / "bin" / "apple_vision_ocr"
PILOT_DB_PATH = Path("/Users/daplug/Documents/SACC_Data/library/staging/sacc-library-pilot.sqlite3")
LIVE_DB_PATH = Path("/Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3")

from sacc_takeout.store_directory_resolver import (
    STORE_REGISTRY,
    resolve_store_for_occurrence,
    haversine_m,
)

NIKE_SKU_REGEX = re.compile(r'\b(\d{6})[-\s](\d{3})\b')
PRICE_REGEX = re.compile(r'\$\s*(\d+(\.\d{2})?)')
CATEGORIES = ["RUNNING", "BASKETBALL", "SPORTSWEAR", "TRAINING", "FOOTBALL", "SOCCER", "SKATEBOARDING"]
KNOWN_LINES = ["KOBE", "LEBRON", "JORDAN", "KD", "KYRIE", "AIR MAX", "FREE", "FLYKNIT", "DUNK", "FOAMPOSITE", "RETRO"]


def ensure_recognition_schema(con: sqlite3.Connection):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS library_photo_recognitions (
        occurrence_id TEXT PRIMARY KEY,
        filename TEXT,
        capture_utc TEXT,
        has_box_label INTEGER DEFAULT 0,
        has_price_tag INTEGER DEFAULT 0,
        primary_sku TEXT,
        detected_skus_json TEXT,
        detected_category TEXT,
        detected_model TEXT,
        observed_price REAL,
        raw_text_json TEXT,
        recognition_source TEXT,
        cluster_id TEXT,
        processed_at TEXT,
        store_code TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_rec_sku ON library_photo_recognitions(primary_sku);
    CREATE INDEX IF NOT EXISTS idx_rec_category ON library_photo_recognitions(detected_category);
    CREATE INDEX IF NOT EXISTS idx_rec_cluster ON library_photo_recognitions(cluster_id);
    CREATE INDEX IF NOT EXISTS idx_rec_store ON library_photo_recognitions(store_code);
    """)
    # Check if store_code exists in case table was created earlier without it
    cur = con.cursor()
    cur.execute("PRAGMA table_info(library_photo_recognitions)")
    cols = [r[1] for r in cur.fetchall()]
    if "store_code" not in cols:
        con.execute("ALTER TABLE library_photo_recognitions ADD COLUMN store_code TEXT")
        con.execute("CREATE INDEX IF NOT EXISTS idx_rec_store ON library_photo_recognitions(store_code)")


def parse_timestamp(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.timestamp()
    except Exception:
        return None


def get_photos_for_store(con: sqlite3.Connection, store_def: Dict[str, Any], limit: Optional[int] = None) -> List[Tuple[Any, ...]]:
    """Retrieve all physical geotagged photos within the store's geofence and active dates."""
    cur = con.cursor()
    # Bounding box filter for fast DB index scan (approx +/- 0.01 deg = ~1.1 km)
    lat = store_def["lat"]
    lon = store_def["lon"]
    delta = 0.012

    cur.execute(
        """
        SELECT id, original_name, recovered_path, capture_utc, file_size_bytes, gps_lat, gps_lon, effective_date
        FROM library_occurrences
        WHERE media_type = 'image'
          AND gps_lat BETWEEN ? AND ?
          AND gps_lon BETWEEN ? AND ?
        ORDER BY capture_utc ASC
        """,
        (lat - delta, lat + delta, lon - delta, lon + delta),
    )
    rows = cur.fetchall()

    matches = []
    v_from = store_def.get("valid_from")
    v_to = store_def.get("valid_to")
    radius_m = store_def.get("radius_m", 450)

    for r in rows:
        oid, orig_name, rec_path, cap_utc, size_bytes, plat, plon, eff_date = r
        if not rec_path or not Path(rec_path).is_file():
            continue

        # Check temporal window if store is historical/defunct or newly opened
        cdate = (eff_date or (cap_utc[:10] if cap_utc else None))
        if cdate:
            if v_from and cdate < v_from:
                continue
            if v_to and cdate > v_to:
                continue

        # Check precise Haversine distance
        dist = haversine_m(plat, plon, lat, lon)
        if dist <= radius_m:
            matches.append((oid, orig_name, rec_path, cap_utc, size_bytes, round(dist, 1)))

    if limit and limit > 0:
        matches = matches[:limit]

    return matches


def scan_store(
    store_code: str,
    pilot_db: Path = PILOT_DB_PATH,
    live_db: Path = LIVE_DB_PATH,
    limit: Optional[int] = None,
    batch_size: int = 64,
) -> Dict[str, Any]:
    """Scan photos for a store and record recognitions into staging database."""
    target_store = next((s for s in STORE_REGISTRY if s["code"] == store_code or s["id"] == store_code), None)
    if not target_store:
        raise ValueError(f"Unknown store code or ID: {store_code}")

    print(f"\n=======================================================")
    print(f"STORE SCAN: {target_store['label']} ({target_store['code']})")
    print(f"Status: {target_store.get('status', 'active').upper()} | Type: {target_store.get('type')}")
    print(f"Location: {target_store.get('address')} ({target_store['lat']}, {target_store['lon']})")
    print(f"Active Window: {target_store.get('valid_from', 'N/A')} to {target_store.get('valid_to', 'N/A')}")
    print(f"=======================================================")

    live_con = sqlite3.connect(live_db)
    photos = get_photos_for_store(live_con, target_store, limit=limit)
    live_con.close()

    total_photos = len(photos)
    print(f"Found {total_photos} photos at {target_store['label']}.")
    if total_photos == 0:
        return {"store": target_store, "scanned": 0, "skus": 0, "prices": 0, "duration": 0.0}

    pilot_con = sqlite3.connect(pilot_db)
    ensure_recognition_schema(pilot_con)

    start_time = time.time()
    total_processed = 0
    total_sku_hits = 0
    total_price_hits = 0

    current_cluster_id: Optional[str] = None
    last_timestamp: Optional[float] = None
    cluster_active_sku: Optional[str] = None
    cluster_active_model: Optional[str] = None

    discovered_skus: Dict[str, Dict[str, Any]] = {}

    for i in range(0, total_photos, batch_size):
        batch = photos[i : i + batch_size]
        batch_paths = [r[2] for r in batch if r[2] and Path(r[2]).is_file()]

        if not batch_paths:
            continue

        # Run native Apple Vision OCR on the batch
        try:
            cmd = [str(OCR_BINARY)] + batch_paths
            raw_out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            ocr_results = {item["file"]: item.get("text", []) for item in json.loads(raw_out)}
        except Exception as e:
            print(f"OCR error on batch {i}: {e}")
            ocr_results = {}

        now_str = datetime.now(timezone.utc).isoformat()
        records_to_insert = []

        for row in batch:
            occ_id, orig_name, rec_path, cap_utc, size_bytes, dist_m = row
            texts = ocr_results.get(rec_path, [])

            # Check timestamp for clustering (session boundary = 5 minutes gap)
            ts = parse_timestamp(cap_utc)
            if ts is not None and last_timestamp is not None:
                if (ts - last_timestamp) > 300:  # > 5 minutes gap
                    current_cluster_id = f"clust_{int(ts)}"
                    cluster_active_sku = None
                    cluster_active_model = None
            elif ts is not None and current_cluster_id is None:
                current_cluster_id = f"clust_{int(ts)}"

            if ts is not None:
                last_timestamp = ts

            # Extract SKUs
            skus: List[str] = []
            for t in texts:
                for m in NIKE_SKU_REGEX.finditer(t):
                    formatted = f"{m.group(1)}-{m.group(2)}"
                    if formatted not in skus:
                        skus.append(formatted)

            # Extract category
            cat_match = None
            for t in texts:
                upper = t.upper()
                for c in CATEGORIES:
                    if c in upper:
                        cat_match = c
                        break
                if cat_match:
                    break

            # Extract price
            price_val = None
            for t in texts:
                p_match = PRICE_REGEX.search(t)
                if p_match:
                    try:
                        price_val = float(p_match.group(1))
                        break
                    except ValueError:
                        pass

            # Extract shoe line or model text
            model_text = None
            for t in texts:
                upper = t.upper()
                for kw in KNOWN_LINES:
                    if kw in upper:
                        model_text = t
                        break
                if model_text:
                    break

            has_box = len(skus) > 0 or any("BOX" in t.upper() for t in texts)
            has_price = price_val is not None

            if skus:
                total_sku_hits += 1
                cluster_active_sku = skus[0]
                if model_text:
                    cluster_active_model = model_text
                source = "exact_box_ocr"
                for s in skus:
                    if s not in discovered_skus:
                        discovered_skus[s] = {
                            "sku": s,
                            "filename": orig_name,
                            "date": cap_utc,
                            "model": model_text,
                            "price": price_val,
                        }
            elif has_price:
                total_price_hits += 1
                source = "price_tag_ocr"
            elif cluster_active_sku:
                source = "session_clustered"
            else:
                source = "shelf_view"

            primary_sku = skus[0] if skus else (cluster_active_sku if source == "session_clustered" else None)
            final_model = model_text or (f"Cluster: {cluster_active_model}" if cluster_active_model and source == "session_clustered" else None)

            records_to_insert.append((
                occ_id, orig_name, cap_utc, int(has_box), int(has_price),
                primary_sku, json.dumps(skus), cat_match, final_model,
                price_val, json.dumps(texts[:10]), source, current_cluster_id, now_str,
                target_store["code"]
            ))

        pilot_con.executemany("""
        INSERT OR REPLACE INTO library_photo_recognitions (
            occurrence_id, filename, capture_utc, has_box_label, has_price_tag,
            primary_sku, detected_skus_json, detected_category, detected_model,
            observed_price, raw_text_json, recognition_source, cluster_id, processed_at,
            store_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records_to_insert)
        pilot_con.commit()

        total_processed += len(batch)
        rate = total_processed / max(time.time() - start_time, 0.001)
        print(f"Processed {total_processed}/{total_photos} photos ({rate:.1f} photos/s) - SKU hits: {total_sku_hits}, Price hits: {total_price_hits}", end="\r")

    elapsed = time.time() - start_time
    pilot_con.close()

    print(f"\nCompleted scan of {target_store['label']} in {elapsed:.1f}s ({total_processed / max(elapsed, 0.001):.1f} photos/s).")
    print(f"Total photos processed : {total_processed}")
    print(f"Exact SKU box hits     : {total_sku_hits}")
    print(f"Price markdown tags    : {total_price_hits}")
    print(f"Discovered unique SKUs : {len(discovered_skus)}")

    if discovered_skus:
        print("\nDiscovered Sneaker Sightings:")
        for sku, info in list(discovered_skus.items())[:8]:
            p_str = f"${info['price']:.2f}" if info['price'] else "N/A"
            print(f"  • SKU {sku} | {info['filename']} | {info['date'][:10] if info['date'] else 'Undated'} | Price: {p_str} | Text: {info['model']}")

    return {
        "store": target_store,
        "scanned": total_processed,
        "skus": total_sku_hits,
        "prices": total_price_hits,
        "unique_skus": len(discovered_skus),
        "duration": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan store photos using native Apple Vision OCR.")
    parser.add_argument("--store", type=str, default="KSM-NC192-CLR", help="Store code or ID (e.g. KSM-NC192-CLR, ORL-IDR-FAC, all)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of photos to scan")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size for OCR binary")
    args = parser.parse_args()

    if args.store == "all":
        print("Scanning all stores in registry...")
        for s in STORE_REGISTRY:
            try:
                scan_store(s["code"], limit=args.limit, batch_size=args.batch_size)
            except Exception as e:
                print(f"Error scanning {s['code']}: {e}")
    else:
        scan_store(args.store, limit=args.limit, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
