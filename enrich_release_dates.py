#!/usr/bin/env python3
"""
enrich_release_dates.py — Enrich sacc.db release_date from StockX JSON files.

Matches by SKU (style_code). Currently jordan1_og_stockx.json has 2 matchable
items. dump.json contains Next.js app config — no product data.

Usage:
    python3 enrich_release_dates.py                  # dry-run
    python3 enrich_release_dates.py --apply          # write to DB
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH     = "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db"
SOURCES     = [
    "/Users/miniman/SACC/jordan1_og_stockx.json",
]


def load_release_map(sources: list[str]) -> dict[str, str]:
    """Build {style_code: release_date} from all source files."""
    release_map = {}
    for path in sources:
        if not os.path.exists(path):
            print(f"  ⚠ Not found: {path}")
            continue
        with open(path) as fh:
            data = json.load(fh)
        items = data if isinstance(data, list) else list(data.values())
        for item in items:
            sku  = (item.get("style_code") or "").strip()
            date = (item.get("_raw_release") or item.get("release_date") or "").strip()
            if sku and date:
                release_map[sku] = date
        print(f"  Loaded {len(release_map)} SKU→date entries from {os.path.basename(path)}")
    return release_map


def main():
    ap = argparse.ArgumentParser(description="Enrich release_date from StockX data")
    ap.add_argument("--apply", action="store_true", help="Write to DB (default: dry-run)")
    ap.add_argument("--db",    default=DB_PATH)
    args = ap.parse_args()

    print(f"\n  Database: {args.db}")
    print(f"  Mode    : {'APPLY' if args.apply else 'DRY-RUN'}\n")

    release_map = load_release_map(SOURCES)
    if not release_map:
        print("  No release dates found — nothing to do.\n")
        return

    from db import SACCDB
    db = SACCDB(args.db)

    matched = unmatched = 0
    for sku, date in release_map.items():
        rows = db.list_all(limit=10000)
        hits = [r for r in rows if r.get("sku") == sku]
        if hits:
            matched += len(hits)
            for r in hits:
                print(f"  {'APPLY' if args.apply else 'WOULD'} {r['stem']} · sku={sku} → release_date={date}")
                if args.apply:
                    db.patch(r["stem"], {"release_date": date})
        else:
            unmatched += 1
            print(f"  NO MATCH for sku={sku} date={date}")

    print(f"\n  Matched : {matched} record(s)")
    print(f"  No match: {unmatched} SKU(s) not in DB")
    if not args.apply:
        print("\n  Dry-run — pass --apply to write.\n")
    else:
        print()


if __name__ == "__main__":
    main()
