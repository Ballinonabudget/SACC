#!/usr/bin/env python3
"""
import_sneaker_db.py — One-time import of sneaker_database.json → SQLite clips table.

Bridges the consolidated Gemini-output JSON (keyed by original stem like "C0015")
into the SACCDB schema. Run once; re-running is safe (upserts on stem).

Usage:
    python3 import_sneaker_db.py                        # dry-run preview
    python3 import_sneaker_db.py --apply                # write to DB
    python3 import_sneaker_db.py --apply --verbose      # show every row
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

SOURCE_JSON  = "/Volumes/Team Bank 12/Sneeaker Solo/sneaker_database.json"
ORIGINALS    = "/Volumes/Team Bank 12/Sneeaker Solo/Sneaker solo Orginals"
DB_PATH      = "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db"


def _model_string(entry: dict) -> str:
    brand      = (entry.get("brand") or "").strip()
    silhouette = (entry.get("silhouette") or "").strip()

    # Skip brand prefix when silhouette already starts with it (Gemini sometimes duplicates)
    if silhouette.lower().startswith(brand.lower()):
        return silhouette
    return f"{brand} {silhouette}".strip()


def _nonempty(val) -> str:
    """Return stripped string, or empty string if blank/None."""
    return (val or "").strip()


def build_rows(data: dict, originals_dir: str) -> list[dict]:
    # Index actual files on disk by uppercase stem for fast lookup
    on_disk = {}
    for fname in os.listdir(originals_dir):
        stem = Path(fname).stem.upper()
        on_disk[stem] = fname  # e.g. "C0015" → "C0015.MP4"

    rows = []
    for file_id, entry in data.items():
        stem = file_id  # original stem IS the relational key

        # Find the actual video file (case-insensitive stem match)
        disk_fname = on_disk.get(stem.upper())
        original_file = disk_fname or f"{stem}.MP4"

        model        = _model_string(entry)
        colorway     = _nonempty(entry.get("colorway_name"))
        sku          = _nonempty(entry.get("style_code"))
        price        = _nonempty(entry.get("retail_price"))
        release_date = _nonempty(entry.get("release_date"))
        # When no loc_code, store the new_filename as-is (no UNKNOWN_ prefix)
        fcp          = _nonempty(entry.get("new_filename")) or original_file

        rows.append({
            "stem":          stem,
            "original_file": original_file,
            "fcp_filename":  fcp,
            "folder_path":   originals_dir,
            "json_path":     None,          # no per-file JSON — source is sneaker_database.json
            "shoot_date":    "",
            "cam_make":      "",
            "cam_model":     "",
            "loc_code":      "",
            "loc_name":      "",
            "loc_source":    "unknown",
            "loc_confidence": None,
            "loc_visual":    None,
            "loc_audio":     None,
            "model":         model,
            "colorway":      colorway or None,
            "sku":           sku or None,
            "size":          None,
            "price":         price or None,
            "release_date":  release_date or None,
            "proxy_file":    None,
            "proxy_deleted": 0,
            "analysed_at":   _nonempty(entry.get("timestamp")) or None,
        })

    return rows


def main():
    ap = argparse.ArgumentParser(description="Import sneaker_database.json into SQLite")
    ap.add_argument("--apply",   action="store_true", help="Write to DB (default: dry-run)")
    ap.add_argument("--verbose", action="store_true", help="Print every row")
    ap.add_argument("--source",  default=SOURCE_JSON,   help="Path to sneaker_database.json")
    ap.add_argument("--originals", default=ORIGINALS,   help="Path to video originals folder")
    ap.add_argument("--db",      default=DB_PATH,       help="Path to sacc.db")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"Source JSON not found: {args.source}")
    if not os.path.isdir(args.originals):
        sys.exit(f"Originals folder not found: {args.originals}")

    print(f"\n  Source  : {args.source}")
    print(f"  Originals: {args.originals}")
    print(f"  Database: {args.db}")
    print(f"  Mode    : {'APPLY (writing to DB)' if args.apply else 'DRY-RUN (no changes)'}\n")

    with open(args.source) as fh:
        data = json.load(fh)

    print(f"  Loaded {len(data)} entries from sneaker_database.json")

    rows = build_rows(data, args.originals)

    # Stats preview
    has_sku   = sum(1 for r in rows if r["sku"])
    has_price = sum(1 for r in rows if r["price"])
    on_disk   = sum(1 for r in rows if os.path.exists(os.path.join(args.originals, r["original_file"])))
    print(f"  Has SKU       : {has_sku}/{len(rows)}")
    print(f"  Has price     : {has_price}/{len(rows)}")
    print(f"  Video on disk : {on_disk}/{len(rows)}")

    if args.verbose:
        print()
        for r in rows[:10]:
            print(f"  {r['stem']:20}  {r['model'][:50]:50}  sku={r['sku'] or '-':15}  file={r['original_file']}")
        if len(rows) > 10:
            print(f"  … and {len(rows) - 10} more")

    if not args.apply:
        print("\n  Dry-run complete — pass --apply to write to database.\n")
        return

    from db import SACCDB
    db = SACCDB(args.db)

    inserted = updated = errors = 0
    for row in rows:
        try:
            action = db._upsert(row)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            errors += 1
            print(f"  ✗ {row['stem']}: {e}")

    print(f"\n  ✓ Inserted : {inserted}")
    print(f"  ✓ Updated  : {updated}")
    print(f"  ✗ Errors   : {errors}")

    s = db.stats()
    print(f"\n  DB total clips : {s['total']}")
    print(f"  Has model      : {s['has_model']}")
    print(f"  Has SKU        : {s['has_sku']}")
    print()


if __name__ == "__main__":
    main()
