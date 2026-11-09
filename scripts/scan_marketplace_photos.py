#!/usr/bin/env python3
"""
SACC Marketplace Photo Scanner & Local Recognition Indexer
===========================================================
Scans recovered retail photos taken at Nike Clearance Store - Marketplace:
1. High-speed local OCR via Apple Vision (20 photos/sec).
2. Extracts printed SKUs, clearance tags, categories (SPORTSWEAR, RUNNING, BASKETBALL), and prices.
3. Groups photos into temporal shopping sessions (within 5 minutes).
4. Records structured recognitions into the pilot staging catalog.
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

NIKE_SKU_REGEX = re.compile(r'\b(\d{6})[-\s](\d{3})\b')
TIMBERLAND_REGEX = re.compile(r'\b(TB0[A-Z0-9]{5,6})\b')
PRICE_REGEX = re.compile(r'\$\s*(\d+(\.\d{2})?)')

CATEGORIES = ["RUNNING", "BASKETBALL", "SPORTSWEAR", "TRAINING", "FOOTBALL", "SOCCER"]


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
        processed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_rec_sku ON library_photo_recognitions(primary_sku);
    CREATE INDEX IF NOT EXISTS idx_rec_category ON library_photo_recognitions(detected_category);
    CREATE INDEX IF NOT EXISTS idx_rec_cluster ON library_photo_recognitions(cluster_id);
    """)


def parse_timestamp(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    try:
        # ISO timestamp format
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def scan_marketplace(
    limit: int = 500,
    batch_size: int = 50,
    pilot_db: Path = PILOT_DB_PATH,
    live_db: Path = LIVE_DB_PATH,
):
    if not OCR_BINARY.is_file():
        sys.exit(f"OCR binary not found at {OCR_BINARY}. Build it first.")

    print(f"Connecting to live catalog: {live_db}")
    live_con = sqlite3.connect(live_db)
    live_cur = live_con.cursor()

    # Query Marketplace photos
    query = """
    SELECT id, original_name, recovered_path, capture_utc, file_size_bytes
    FROM library_occurrences
    WHERE gps_lat BETWEEN 28.47 AND 28.48 AND gps_lon BETWEEN -81.46 AND -81.44
      AND media_type = 'image'
    ORDER BY capture_utc ASC
    """
    if limit > 0:
        query += f" LIMIT {limit}"

    live_cur.execute(query)
    photos = live_cur.fetchall()
    live_con.close()

    total_photos = len(photos)
    print(f"Found {total_photos} photos at Nike Clearance Store - Marketplace.")

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
            occ_id, orig_name, rec_path, cap_utc, size_bytes = row
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
                for tb in TIMBERLAND_REGEX.finditer(t):
                    code = tb.group(1)
                    if code not in skus:
                        skus.append(code)

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

            # Extract shoe model text
            model_text = None
            for t in texts:
                upper = t.upper()
                if any(k in upper for k in ["LEBRON", "KOBE", "JORDAN", "FREE", "FLYKNIT", "AIR MAX", "EUROHIKER"]):
                    model_text = t
                    break

            has_box = len(skus) > 0 or any("BOX" in t.upper() for t in texts)
            has_price = price_val is not None

            if skus:
                total_sku_hits += 1
                cluster_active_sku = skus[0]
                if model_text:
                    cluster_active_model = model_text
                source = "exact_box_ocr"
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
                price_val, json.dumps(texts[:10]), source, current_cluster_id, now_str
            ))

        pilot_con.executemany("""
        INSERT OR REPLACE INTO library_photo_recognitions (
            occurrence_id, filename, capture_utc, has_box_label, has_price_tag,
            primary_sku, detected_skus_json, detected_category, detected_model,
            observed_price, raw_text_json, recognition_source, cluster_id, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records_to_insert)
        pilot_con.commit()

        total_processed += len(batch)
        elapsed = time.time() - start_time
        fps = total_processed / elapsed if elapsed > 0 else 0
        pct = (total_processed / total_photos) * 100
        print(f"[{total_processed:4d}/{total_photos}] {pct:5.1f}% | Rate: {fps:4.1f} photos/s | SKUs: {total_sku_hits} | Prices: {total_price_hits}")

    pilot_con.close()
    elapsed = time.time() - start_time
    print(f"\nScan completed in {elapsed:.1f}s.")
    print(f"Total photos processed: {total_processed}")
    print(f"Total exact SKUs extracted: {total_sku_hits}")
    print(f"Total price tags read: {total_price_hits}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan Marketplace store photos")
    parser.add_argument("--limit", type=int, default=500, help="Number of photos to scan (default: 500, 0 for all)")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size (default: 50)")
    args = parser.parse_args()

    scan_marketplace(limit=args.limit, batch_size=args.batch_size)
