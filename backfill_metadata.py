#!/usr/bin/env python3
"""
backfill_metadata.py — SKU-first metadata enrichment.

For every clip that has a SKU but is missing colorway, price, or release_date,
query an external source and write the result back to sacc.db.

Sources
-------
  ebay   — eBay Finding API (free, no OAuth; requires EBAY_APP_ID in .env)
  google — Google Custom Search JSON API (requires GOOGLE_API_KEY + GOOGLE_CX in .env)
  csv    — Import from a local CSV file: sku,colorway,price,release_date

Usage
-----
  python3 backfill_metadata.py --source ebay   --dry-run
  python3 backfill_metadata.py --source ebay   --apply
  python3 backfill_metadata.py --source google --apply
  python3 backfill_metadata.py --source csv    --csv enrichment.csv --apply
  python3 backfill_metadata.py --sku 555088-101 --source google --apply   # single SKU
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

DB_PATH = "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db"


# ── Source implementations ────────────────────────────────────────────────────

def _fetch_ebay(sku: str) -> dict:
    """Query eBay Finding API for a SKU. Returns partial metadata dict."""
    app_id = os.environ.get("EBAY_APP_ID", "")
    if not app_id:
        raise RuntimeError("EBAY_APP_ID not set in .env")

    params = urllib.parse.urlencode({
        "OPERATION-NAME":       "findItemsByKeywords",
        "SERVICE-VERSION":      "1.0.0",
        "SECURITY-APPNAME":     app_id,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords":             sku,
        "paginationInput.entriesPerPage": "3",
    })
    url = f"https://svcs.ebay.com/services/search/FindingService/v1?{params}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())

    items = (data
             .get("findItemsByKeywordsResponse", [{}])[0]
             .get("searchResult", [{}])[0]
             .get("item", []))

    if not items:
        return {}

    item = items[0]
    title = item.get("title", [""])[0]
    price = item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", "")

    # Extract colorway from title: everything after the model name / SKU region
    colorway = _colorway_from_title(title, sku)
    return {
        "colorway":    colorway or "",
        "price":       price or "",
        "release_date": "",   # eBay listings don't reliably expose release dates
        "_source":     f"ebay:{title[:60]}",
    }


def _fetch_google(sku: str) -> dict:
    """Query Google Custom Search for a SKU + 'sneaker release date colorway'."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cx      = os.environ.get("GOOGLE_CX", "")
    if not api_key or not cx:
        raise RuntimeError("GOOGLE_API_KEY and GOOGLE_CX must be set in .env")

    query  = urllib.parse.quote(f"{sku} sneaker colorway release date")
    url    = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}&num=3"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())

    items = data.get("items", [])
    if not items:
        return {}

    snippet   = items[0].get("snippet", "")
    title_txt = items[0].get("title", "")
    full_text = f"{title_txt} {snippet}"

    colorway     = _colorway_from_title(full_text, sku)
    release_date = _extract_date(full_text)
    price        = _extract_price(full_text)

    return {
        "colorway":    colorway or "",
        "price":       price or "",
        "release_date":release_date or "",
        "_source":     f"google:{title_txt[:60]}",
    }


def _load_csv(path: str) -> dict[str, dict]:
    """Load a CSV with columns: sku, colorway, price, release_date → {sku: {...}}."""
    result = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sku = (row.get("sku") or row.get("SKU") or "").strip()
            if sku:
                result[sku] = {
                    "colorway":    (row.get("colorway") or "").strip(),
                    "price":       (row.get("price") or row.get("retail_price") or "").strip(),
                    "release_date":(row.get("release_date") or "").strip(),
                    "_source":     f"csv:{path}",
                }
    return result


# ── Text parsing helpers ──────────────────────────────────────────────────────

_KNOWN_COLORWAYS = [
    "Chicago", "Bred", "Royal", "Shadow", "Travis Scott", "Mocha", "University Blue",
    "Court Purple", "Shattered Backboard", "Off-White", "Concord", "Legend Blue",
    "Metallic Gold", "Pine Green", "Starfish", "Taxi", "Flu Game", "Space Jam",
    "Hyper Grape", "Lucky Green", "Midnight Navy", "Ghost", "Olive", "Volt",
    "Phantom", "Sail", "Wheat", "Linen", "Dark Mocha", "Black Toe", "White Cement",
]

def _colorway_from_title(text: str, sku: str = "") -> str:
    text_lower = text.lower()
    for cw in _KNOWN_COLORWAYS:
        if cw.lower() in text_lower:
            return cw
    # Fallback: look for "Color: X" or quoted colorway pattern
    m = re.search(r'colorway[:\s]+([A-Za-z /\-]+)', text, re.I)
    if m:
        return m.group(1).strip()[:40]
    return ""

def _extract_date(text: str) -> str:
    # ISO date
    m = re.search(r'(20\d{2}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    # Month Day, Year
    m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(20\d{2})', text, re.I)
    if m:
        return m.group(0)
    # Just year
    m = re.search(r'\b(20\d{2})\b', text)
    if m:
        return m.group(1)
    return ""

def _extract_price(text: str) -> str:
    m = re.search(r'\$\s*(\d{2,4}(?:\.\d{2})?)', text)
    return m.group(1) if m else ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="SKU-based metadata backfill")
    ap.add_argument("--source", choices=["ebay", "google", "csv"], default="google")
    ap.add_argument("--csv",    default="",        help="Path to enrichment CSV (--source csv)")
    ap.add_argument("--db",     default=DB_PATH)
    ap.add_argument("--sku",    default="",        help="Enrich only this SKU")
    ap.add_argument("--apply",  action="store_true")
    ap.add_argument("--delay",  type=float, default=1.0, help="Seconds between API calls")
    args = ap.parse_args()

    print(f"\n  Database : {args.db}")
    print(f"  Source   : {args.source}")
    print(f"  Mode     : {'APPLY' if args.apply else 'DRY-RUN'}\n")

    from db import SACCDB
    db = SACCDB(args.db)

    # Candidates: have SKU but missing at least one of colorway/price/release_date
    all_rows = db.list_all(limit=10000)
    if args.sku:
        candidates = [r for r in all_rows if r.get("sku") == args.sku]
    else:
        candidates = [
            r for r in all_rows
            if r.get("sku")
            and (not r.get("colorway") or not r.get("price") or not r.get("release_date"))
        ]

    print(f"  Candidates with SKU but incomplete data: {len(candidates)}")

    if args.source == "csv":
        if not args.csv or not os.path.exists(args.csv):
            sys.exit(f"  ✗ CSV file not found: {args.csv}")
        enrichment_map = _load_csv(args.csv)
    else:
        enrichment_map = None

    found = updated = skipped = errors = 0

    for r in candidates:
        sku = r["sku"]
        try:
            if enrichment_map is not None:
                result = enrichment_map.get(sku, {})
            elif args.source == "ebay":
                result = _fetch_ebay(sku)
                time.sleep(args.delay)
            else:
                result = _fetch_google(sku)
                time.sleep(args.delay)

            if not result:
                skipped += 1
                continue

            # Only write fields that are currently empty
            patch = {}
            for field in ("colorway", "price", "release_date"):
                if result.get(field) and not r.get(field):
                    patch[field] = result[field]

            if not patch:
                skipped += 1
                continue

            found += 1
            src = result.get("_source", args.source)
            print(f"  {'PATCH' if args.apply else 'WOULD'} {r['stem']:16} sku={sku:18} → {patch}  [{src}]")

            if args.apply:
                db.patch(r["stem"], patch)
                updated += 1

        except Exception as e:
            errors += 1
            print(f"  ✗ {sku}: {e}")

    print(f"\n  Candidates  : {len(candidates)}")
    print(f"  Found data  : {found}")
    print(f"  Updated     : {updated}")
    print(f"  Skipped     : {skipped}")
    print(f"  Errors      : {errors}")
    if not args.apply and found > 0:
        print(f"\n  Dry-run — pass --apply to write {found} update(s) to DB.\n")
    print()


if __name__ == "__main__":
    main()
