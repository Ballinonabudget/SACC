#!/usr/bin/env python3
"""
sync_sneeaker_solo.py — One-shot sync: Sneeaker Solo folder → sacc.db
======================================================================
Imports all JSON outputs from a prior Gemini run into the SQLite clips table
so the SACC search view has live data.

Usage:
    python3 sync_sneeaker_solo.py

    # Dry-run (count only, no write):
    python3 sync_sneeaker_solo.py --dry-run

    # Custom folder:
    python3 sync_sneeaker_solo.py --folder "/Volumes/Team Bank 12/SACC/2024"
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

FOLDER_DEFAULT  = "/Volumes/Team Bank 12/Sneeaker Solo"
DB_NAME         = "sacc.db"


def main():
    parser = argparse.ArgumentParser(description="Sync Sneeaker Solo folder into sacc.db")
    parser.add_argument("--folder",  default=FOLDER_DEFAULT, help="NAS folder to sync")
    parser.add_argument("--dry-run", action="store_true",    help="Count JSONs without writing to DB")
    args = parser.parse_args()

    folder = args.folder

    if not os.path.isdir(folder):
        print(f"[ERROR] Folder not found: {folder}")
        print("        Is the NAS mounted at /Volumes/Team Bank 12/?")
        sys.exit(1)

    # Count JSON files first
    import glob
    json_files = glob.glob(os.path.join(folder, "**", "*.json"), recursive=True)
    # Exclude sacc.db, sacc-data.json and other non-clip JSONs
    clip_jsons = [
        j for j in json_files
        if not os.path.basename(j).startswith("sacc")
        and not os.path.basename(j).startswith("whitelist")
    ]

    print(f"[sync_sneeaker_solo] Folder : {folder}")
    print(f"[sync_sneeaker_solo] JSON files found: {len(clip_jsons)}")

    if args.dry_run:
        print("[sync_sneeaker_solo] DRY-RUN — no changes written.")
        for j in clip_jsons[:20]:
            print(f"  {os.path.relpath(j, folder)}")
        if len(clip_jsons) > 20:
            print(f"  ... and {len(clip_jsons) - 20} more")
        return

    try:
        from db import SACCDB
    except ImportError:
        print("[ERROR] Cannot import db.py — run from /Users/miniman/SACC/")
        sys.exit(1)

    db_path = os.path.join(folder, DB_NAME)
    print(f"[sync_sneeaker_solo] DB     : {db_path}")

    db = SACCDB(db_path)
    result = db.sync_from_folder(folder)

    print(f"[sync_sneeaker_solo] Result : {result}")
    stats = db.stats()
    print(f"[sync_sneeaker_solo] Stats  : {stats}")
    print("[sync_sneeaker_solo] Done.")


if __name__ == "__main__":
    main()
