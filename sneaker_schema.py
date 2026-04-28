"""
sneaker_schema.py
-----------------
Manages sneaker metadata. Keeps CSV + JSON in sync.
Renames original image files to match shoe metadata.

File name format : Silhouette_Colorway      (e.g. AirJordan1HighOG_Bred.jpg)
Folder structure : Brand/Silhouette         (e.g. Nike/AirJordan1HighOG)

Modes:
  init     — create empty CSV + JSON with correct schema
  rename   — rename image files using CSV data, update both files
  sync     — re-sync JSON from CSV (or CSV from JSON)
  example  — print an example row for reference

Usage:
  python sneaker_schema.py --mode rename --images ./images
  python sneaker_schema.py --mode rename --images ./images --dry-run
  python sneaker_schema.py --mode init
  python sneaker_schema.py --mode sync --sync-direction csv-to-json
  python sneaker_schema.py --mode example
"""

import csv
import json
import os
import re
import shutil
import argparse
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------------------------

FIELDS = [
    "brand",
    "silhouette",
    "colorway_name",
    "style_code",
    "retail_price",
    "release_date",
    "new_file_name",
    "folder_path",
    "verification_status",
]

VERIFICATION_VALUES = ["VERIFIED", "IMAGE_ONLY", "MANUAL_REVIEW", ""]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Known acronyms that should stay uppercase in file names
ACRONYMS = {"OG", "SP", "SE", "QS", "GS", "PS", "TD", "PF", "PE",
            "SB", "ACG", "NSW", "NRG", "MID", "LOW", "HI"}


# ---------------------------------------------------------------------------
# SLUGIFY — CamelCase, slash-aware, acronym-preserving
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """
    Convert display text to a clean CamelCase filename segment.
      Air Jordan 1 High OG      ->  AirJordan1HighOG
      Black/Dark Mercury        ->  BlackDarkMercury
      Magnet with Atlantic      ->  MagnetWithAtlantic
    """
    if not text:
        return "Unknown"
    cleaned = re.sub(r"[^\w\s/]", "", text.strip())
    words = re.split(r"[\s/]+", cleaned)
    parts = []
    for word in words:
        if not word:
            continue
        if word.upper() in ACRONYMS:
            parts.append(word.upper())
        else:
            parts.append(word[0].upper() + word[1:] if len(word) > 1 else word.upper())
    return "".join(parts) or "Unknown"


# ---------------------------------------------------------------------------
# NAME BUILDERS
# ---------------------------------------------------------------------------

def build_file_name(row: dict) -> str:
    """Silhouette_Colorway  (no brand, no style code)"""
    silhouette = slugify(row.get("silhouette", ""))
    colorway   = slugify(row.get("colorway_name", ""))
    parts = [p for p in [silhouette, colorway] if p and p != "Unknown"]
    return "_".join(parts)


def build_folder_path(row: dict, base_path: str = "") -> str:
    """base_path/Brand/Silhouette"""
    brand     = slugify(row.get("brand", "Unknown"))
    silhouette = slugify(row.get("silhouette", "Unknown"))
    parts = [p for p in [base_path, brand, silhouette] if p]
    return "/".join(parts)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{field: row.get(field, "") for field in FIELDS}
                for row in csv.DictReader(f)]


def write_csv(path: str, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [CSV]  {len(rows)} rows → {path}")


def init_csv(path: str) -> None:
    if os.path.exists(path):
        print(f"  [CSV]  Already exists: {path}")
        return
    write_csv(path, [])


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def read_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [{field: row.get(field, "") for field in FIELDS}
                for row in json.load(f)]


def write_json(path: str, rows: list) -> None:
    ordered = [{field: row.get(field, "") for field in FIELDS} for row in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=2, ensure_ascii=False)
    print(f"  [JSON] {len(rows)} records → {path}")


def init_json(path: str) -> None:
    if os.path.exists(path):
        print(f"  [JSON] Already exists: {path}")
        return
    write_json(path, [])


# ---------------------------------------------------------------------------
# SYNC
# ---------------------------------------------------------------------------

def sync_csv_to_json(csv_path: str, json_path: str) -> None:
    print("  Syncing CSV → JSON")
    write_json(json_path, read_csv(csv_path))


def sync_json_to_csv(json_path: str, csv_path: str) -> None:
    print("  Syncing JSON → CSV")
    write_csv(csv_path, read_json(json_path))


# ---------------------------------------------------------------------------
# IMAGE FINDER
# ---------------------------------------------------------------------------

def find_image(identifier: str, images_dir: Path):
    """
    Find an image file by:
      1. Style code substring in filename   (U9060GM → U9060GM.jpg)
      2. Exact filename match               (IMG_4821.jpg)
      3. Current new_file_name match        (AirJordan1HighOG_Bred.jpg)
    Returns Path or None.
    """
    if not identifier:
        return None
    clean_id = identifier.replace(" ", "")
    for f in images_dir.iterdir():
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if clean_id.lower() in f.name.lower():
            return f
    return None


# ---------------------------------------------------------------------------
# RENAME WORKFLOW
# ---------------------------------------------------------------------------

def rename_images(csv_path: str, json_path: str, images_dir: str,
                  base_path: str = "", dry_run: bool = False) -> None:
    """
    For each CSV row:
      - Find the image by style_code or existing new_file_name
      - Build new name: Silhouette_Colorway.ext
      - Rename file (unless dry_run)
      - Write updated new_file_name + folder_path back to CSV + JSON
    """
    rows = read_csv(csv_path)
    if not rows:
        print("  No rows in CSV. Nothing to rename.")
        return

    img_dir  = Path(images_dir)
    renamed  = skipped = errors = 0

    for i, row in enumerate(rows):
        style_code    = row.get("style_code", "").strip()
        existing_name = row.get("new_file_name", "").strip()

        img = find_image(style_code, img_dir) or find_image(existing_name, img_dir)

        if not img:
            label = style_code or existing_name or f"row {i+1}"
            print(f"  [Row {i+1}] SKIP — image not found ({label})")
            skipped += 1
            continue

        new_stem = build_file_name(row)
        if not new_stem:
            print(f"  [Row {i+1}] SKIP — missing silhouette or colorway")
            skipped += 1
            continue

        ext      = img.suffix.lower()
        new_name = new_stem + ext
        new_path = img_dir / new_name

        # Collision guard: append timestamp if another file already has this name
        if new_path.exists() and new_path != img:
            ts       = datetime.now().strftime("%H%M%S")
            new_name = f"{new_stem}_{ts}{ext}"
            new_path = img_dir / new_name

        action = "PREVIEW" if dry_run else "RENAME"
        print(f"  [Row {i+1}] {action}: {img.name}  →  {new_name}")

        if not dry_run:
            try:
                shutil.move(str(img), str(new_path))
                renamed += 1
            except Exception as e:
                print(f"    ERROR: {e}")
                errors += 1
                continue
        else:
            renamed += 1

        rows[i]["new_file_name"] = new_name
        rows[i]["folder_path"]   = build_folder_path(row, base_path)

    print()
    if not dry_run:
        write_csv(csv_path, rows)
        write_json(json_path, rows)
    else:
        print("  Dry run complete — no files modified.")

    summary = "Previewed" if dry_run else "Renamed"
    print(f"  {summary}: {renamed}  |  Skipped: {skipped}  |  Errors: {errors}\n")


# ---------------------------------------------------------------------------
# EXAMPLE ROW
# ---------------------------------------------------------------------------

EXAMPLE = {
    "brand":               "Nike",
    "silhouette":          "Air Jordan 1 High OG",
    "colorway_name":       "Bred",
    "style_code":          "555088-610",
    "retail_price":        "$160",
    "release_date":        "2016-09",
    "new_file_name":       "AirJordan1HighOG_Bred.jpg",
    "folder_path":         "Nike/AirJordan1HighOG",
    "verification_status": "VERIFIED",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Sneaker CSV/JSON manager + file renamer")
    p.add_argument("--mode", choices=["init", "rename", "sync", "example"], default="rename")
    p.add_argument("--csv",  default="sneakers.csv")
    p.add_argument("--json", default="sneakers.json")
    p.add_argument("--images",  default="./images", help="Folder containing image files")
    p.add_argument("--base-path", default="", help="Prepended to folder_path (e.g. /Volumes/NAS/Sneakers)")
    p.add_argument("--dry-run",   action="store_true", help="Preview renames, write nothing")
    p.add_argument("--sync-direction", choices=["csv-to-json", "json-to-csv"], default="csv-to-json")
    args = p.parse_args()

    print(f"\nSneaker Schema Manager  |  mode={args.mode}")
    if args.dry_run:
        print("  DRY RUN — nothing will be written\n")

    if args.mode == "init":
        init_csv(args.csv)
        init_json(args.json)

    elif args.mode == "rename":
        rename_images(args.csv, args.json, args.images,
                      base_path=args.base_path, dry_run=args.dry_run)

    elif args.mode == "sync":
        if args.sync_direction == "csv-to-json":
            sync_csv_to_json(args.csv, args.json)
        else:
            sync_json_to_csv(args.json, args.csv)

    elif args.mode == "example":
        row = {f: EXAMPLE.get(f, "") for f in FIELDS}
        print("\n--- Schema fields ---")
        for field in FIELDS:
            print(f"  {field}")
        print("\n--- CSV header ---")
        print(",".join(FIELDS))
        print("\n--- Example row (CSV) ---")
        print(",".join(f'"{row[f]}"' for f in FIELDS))
        print("\n--- Example record (JSON) ---")
        print(json.dumps(row, indent=2))
        print(f"\n--- Name builder output ---")
        print(f"  new_file_name  →  {build_file_name(EXAMPLE)}.jpg")
        print(f"  folder_path    →  {build_folder_path(EXAMPLE)}")
        print()

if __name__ == "__main__":
    main()
