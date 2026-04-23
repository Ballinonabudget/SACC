"""
sacc_test.py — SACC Workflow Test Tool
========================================
Tests two things against an existing batch folder:

  MODE 1: search   — Load existing JSON outputs as master list,
                     run test queries, show what the search engine finds.

  MODE 2: rename   — Read existing JSON outputs to pull shoe IDs,
                     rename matching video files using SACC convention.
                     NO Gemini API call. NO compression.

  MODE 3: inspect  — Just print what's in the folder (JSON + video files),
                     no changes made.

Usage:
  # See what's in the folder
  python sacc_test.py inspect --folder "/Volumes/Team Bank 12/Sneeaker Solo"

  # Test search against existing JSON outputs
  python sacc_test.py search  --folder "/Volumes/Team Bank 12/Sneeaker Solo" --query "Jordan 1"
  python sacc_test.py search  --folder "/Volumes/Team Bank 12/Sneeaker Solo" --query "555088-101"

  # Rename videos using JSON data as identifier source (no Gemini call)
  python sacc_test.py rename  --folder "/Volumes/Team Bank 12/Sneeaker Solo" --loc FLM
"""

import os
import sys
import json
import argparse
import re
from pathlib import Path
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from renamer_logic import extract_metadata, LOCATION_DATA

VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
JSON_EXTS  = {".json"}


# ── Folder scanning ────────────────────────────────────────────────────────────

def scan_folder(folder):
    """
    Returns (json_records, video_files) from a batch folder.

    json_records: list of dicts — each JSON file read and parsed,
                  with '_source_json' key added (the filename).
    video_files:  list of absolute paths to video files.
    """
    if not os.path.isdir(folder):
        print(f"[ERROR] Folder not found: {folder}")
        sys.exit(1)

    all_files = [f for f in os.listdir(folder) if not f.startswith('.')]
    json_files  = [f for f in all_files if Path(f).suffix.lower() in JSON_EXTS]
    video_files = [os.path.join(folder, f)
                   for f in all_files if Path(f).suffix.lower() in VIDEO_EXTS]

    json_records = []
    for jf in sorted(json_files):
        path = os.path.join(folder, jf)
        try:
            with open(path) as f:
                raw = f.read().strip()
                # Strip markdown code fences if Gemini returned them
                raw = re.sub(r"^```json\s*", "", raw)
                raw = re.sub(r"```\s*$", "", raw)
                data = json.loads(raw)
                data["_source_json"] = jf
                json_records.append(data)
        except Exception as e:
            print(f"  [WARN] Could not parse {jf}: {e}")

    return json_records, sorted(video_files)


# ── Normalise keys ────────────────────────────────────────────────────────────
# Gemini sometimes returns "model", "Model", "shoe_model" etc.
# Normalise to consistent keys.

def norm(record):
    """Return a normalised copy of a Gemini JSON record."""
    r = {k.lower().replace(" ", "_"): v for k, v in record.items()}

    def pick(*keys):
        for k in keys:
            if r.get(k): return str(r[k]).strip()
        return ""

    return {
        "Model": pick("model", "model_name", "shoe_model", "shoe", "name"),
        "SKU":   pick("sku", "style_code", "style", "sku_code", "product_code"),
        "Size":  pick("size", "shoe_size"),
        "Price": pick("price", "retail_price", "retail"),
        "source_file":   record.get("source_file", ""),
        "_source_json":  record.get("_source_json", ""),
        "_raw":          record,
    }


# ── MODE: inspect ─────────────────────────────────────────────────────────────

def mode_inspect(folder):
    print(f"\n{'='*60}")
    print(f"INSPECT: {folder}")
    print(f"{'='*60}")

    json_records, video_files = scan_folder(folder)

    print(f"\n── JSON outputs ({len(json_records)} files) ──")
    for r in json_records:
        n = norm(r)
        print(f"  {r['_source_json']}")
        print(f"    Model : {n['Model'] or '(empty)'}")
        print(f"    SKU   : {n['SKU']   or '(empty)'}")
        print(f"    Size  : {n['Size']  or '(empty)'}")
        print(f"    Price : {n['Price'] or '(empty)'}")
        if n["source_file"]:
            print(f"    Source: {n['source_file']}")
        # Show raw keys if model/sku are missing (helps debug junk output)
        if not n["Model"] and not n["SKU"]:
            print(f"    RAW   : {json.dumps(r, indent=None)[:120]}…")

    print(f"\n── Video files ({len(video_files)} files) ──")
    for vf in video_files:
        size_mb = os.path.getsize(vf) / (1024 * 1024)
        print(f"  {os.path.basename(vf)}  ({size_mb:.0f} MB)")

    print(f"\n── Summary ──")
    print(f"  JSON records : {len(json_records)}")
    print(f"  Video files  : {len(video_files)}")
    matched, unmatched = match_json_to_videos(json_records, video_files)
    print(f"  Matched pairs: {len(matched)}")
    print(f"  Unmatched    : {len(unmatched['json'])} JSON, {len(unmatched['video'])} video")


# ── Matching logic ────────────────────────────────────────────────────────────

def match_json_to_videos(json_records, video_files):
    """
    Attempts to pair JSON records with video files by:
      1. source_file field in JSON matches video filename (exact)
      2. JSON filename stem matches video filename stem (fuzzy)
    Returns (matched: list of (json_record, video_path), unmatched: dict)
    """
    matched   = []
    used_json = set()
    used_vid  = set()

    video_map = {Path(vf).stem.lower(): vf for vf in video_files}

    for r in json_records:
        n = norm(r)
        # Try source_file field first
        source = Path(n["source_file"]).stem.lower() if n["source_file"] else ""
        # Try JSON filename stem (e.g. "555088-101_Air_Jordan_1.json" → "555088-101_Air_Jordan_1")
        json_stem = Path(r["_source_json"]).stem.lower()

        matched_vid = None
        for candidate in [source, json_stem]:
            if candidate and candidate in video_map:
                matched_vid = video_map[candidate]
                break

        if matched_vid and matched_vid not in used_vid:
            matched.append((r, matched_vid))
            used_json.add(r["_source_json"])
            used_vid.add(matched_vid)

    unmatched_json  = [r for r in json_records if r["_source_json"] not in used_json]
    unmatched_video = [v for v in video_files if v not in used_vid]

    return matched, {"json": unmatched_json, "video": unmatched_video}


# ── MODE: search ──────────────────────────────────────────────────────────────

def mode_search(folder, query):
    print(f"\n{'='*60}")
    print(f"SEARCH: '{query}'  in  {folder}")
    print(f"{'='*60}")

    json_records, _ = scan_folder(folder)
    if not json_records:
        print("No JSON records found in folder.")
        return

    q = query.lower()

    def score(record):
        n = norm(record)
        fields = [
            n["Model"], n["SKU"], n["Size"], n["Price"],
            n["source_file"], record.get("_source_json", ""),
        ]
        # Also search all raw values
        fields += [str(v) for v in record.get("_raw", {}).values()]
        s = 0
        for f in fields:
            fl = f.lower()
            if fl == q:          s += 10
            elif fl.startswith(q): s += 5
            elif q in fl:         s += 1
        return s

    results = [(score(r), r) for r in json_records]
    results = [(s, r) for s, r in results if s > 0]
    results.sort(key=lambda x: -x[0])

    if not results:
        print(f"\n  No matches found for '{query}'")
        print(f"  Available models: {[norm(r)['Model'] for r in json_records[:5]]}")
        return

    print(f"\n  {len(results)} match(es):\n")
    for rank, (s, r) in enumerate(results, 1):
        n = norm(r)
        print(f"  [{rank}] score={s}  {r['_source_json']}")
        print(f"       Model : {n['Model']}")
        print(f"       SKU   : {n['SKU']}")
        print(f"       Size  : {n['Size']}   Price: {n['Price']}")
        if n["source_file"]:
            print(f"       Video : {n['source_file']}")
        print()


# ── MODE: rename ──────────────────────────────────────────────────────────────

def mode_rename(folder, loc_code, dry_run=True):
    """
    Rename video files using JSON records as the identifier source.
    No Gemini API call. No compression.

    Naming convention: {LOC}-{TYPE}_{YYMMDD}_{Model-clean}_{CamModel}_{orig}{ext}
    """
    print(f"\n{'='*60}")
    print(f"RENAME{' (DRY RUN)' if dry_run else ''}: {folder}")
    print(f"Location: {loc_code}")
    print(f"{'='*60}")

    if loc_code not in LOCATION_DATA:
        print(f"[ERROR] Unknown location code '{loc_code}'")
        print(f"  Valid codes: {list(LOCATION_DATA.keys())}")
        sys.exit(1)

    loc  = LOCATION_DATA[loc_code]
    loc_header = f"{loc_code}-{loc['type']}"

    json_records, video_files = scan_folder(folder)

    if not json_records:
        print("[ERROR] No JSON records found — cannot determine shoe identifiers.")
        print("  Run 'inspect' mode first to check folder contents.")
        sys.exit(1)

    if not video_files:
        print("[INFO] No video files found to rename.")
        return

    matched, unmatched = match_json_to_videos(json_records, video_files)

    print(f"\nMatched {len(matched)} video+JSON pair(s)")
    if unmatched["video"]:
        print(f"Unmatched videos ({len(unmatched['video'])} — will use folder-level identifier):")
        for v in unmatched["video"]:
            print(f"  {os.path.basename(v)}")

    renamed = []
    skipped = []

    # ── Rename matched pairs ──
    for r, video_path in matched:
        n      = norm(r)
        model  = n["Model"] or "Unknown"
        sku    = n["SKU"]   or "NOSKU"

        # Build identifier: "Air Jordan 1 Chicago" → "Air-Jordan-1-Chicago"
        identifier_clean = re.sub(r"\s+", "-", model.strip())

        filename = os.path.basename(video_path)
        base, ext = os.path.splitext(filename)

        # Strip existing SACC prefixes to avoid double-naming
        prefix_pat = r"^([A-Z0-9]+-[A-Z]+_\d{6}_[A-Za-z0-9-]+_[A-Za-z0-9]+_)+"
        base_clean = re.sub(prefix_pat, "", base)

        date_str, cam_model = extract_metadata(video_path)

        new_name = f"{loc_header}_{date_str}_{identifier_clean}_{cam_model}_{base_clean}{ext}"
        new_path = os.path.join(folder, new_name)

        print(f"\n  {'[DRY]' if dry_run else '[RENAME]'}")
        print(f"    FROM : {filename}")
        print(f"    TO   : {new_name}")
        print(f"    SKU  : {sku}   Model: {model}")

        if not dry_run:
            if os.path.exists(new_path):
                print(f"    SKIP : destination already exists")
                skipped.append(video_path)
            else:
                os.rename(video_path, new_path)
                renamed.append((video_path, new_path))
                print(f"    ✓ Done")

    # ── Unmatched videos: use folder name as identifier ──
    if unmatched["video"]:
        folder_id = re.sub(r"\s+", "-", os.path.basename(folder).strip())
        print(f"\n── Unmatched videos — using folder name as identifier: '{folder_id}' ──")
        for video_path in unmatched["video"]:
            filename = os.path.basename(video_path)
            base, ext = os.path.splitext(filename)
            base_clean = re.sub(r"^([A-Z0-9]+-[A-Z]+_\d{6}_[A-Za-z0-9-]+_[A-Za-z0-9]+_)+", "", base)
            date_str, cam_model = extract_metadata(video_path)
            new_name = f"{loc_header}_{date_str}_{folder_id}_{cam_model}_{base_clean}{ext}"
            new_path = os.path.join(folder, new_name)

            print(f"\n  {'[DRY]' if dry_run else '[RENAME]'}")
            print(f"    FROM : {filename}")
            print(f"    TO   : {new_name}")

            if not dry_run:
                if os.path.exists(new_path):
                    print(f"    SKIP : destination already exists")
                    skipped.append(video_path)
                else:
                    os.rename(video_path, new_path)
                    renamed.append((video_path, new_path))
                    print(f"    ✓ Done")

    # ── Summary ──
    print(f"\n── Summary ──")
    if dry_run:
        total = len(matched) + len(unmatched["video"])
        print(f"  DRY RUN — {total} file(s) would be renamed")
        print(f"  Re-run without --dry-run to apply changes")
    else:
        print(f"  Renamed : {len(renamed)}")
        print(f"  Skipped : {len(skipped)}")
        # Write rename log
        log_path = os.path.join(folder, "sacc_rename_log.json")
        with open(log_path, "w") as f:
            json.dump([
                {"from": os.path.basename(src), "to": os.path.basename(dst)}
                for src, dst in renamed
            ], f, indent=2)
        print(f"  Log     : {log_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SACC Test Tool — inspect / search / rename")
    sub = parser.add_subparsers(dest="mode", required=True)

    # inspect
    p_inspect = sub.add_parser("inspect", help="Show folder contents, no changes")
    p_inspect.add_argument("--folder", required=True)

    # search
    p_search = sub.add_parser("search", help="Query existing JSON records")
    p_search.add_argument("--folder", required=True)
    p_search.add_argument("--query",  required=True, help="Search term: SKU, model, size, etc.")

    # rename
    p_rename = sub.add_parser("rename", help="Rename videos using JSON IDs (no Gemini)")
    p_rename.add_argument("--folder",    required=True)
    p_rename.add_argument("--loc",       default="FLM", help="Location code e.g. FLM")
    p_rename.add_argument("--dry-run",   action="store_true", default=True,
                          help="Preview only — no files changed (default: ON)")
    p_rename.add_argument("--apply",     action="store_true",
                          help="Actually rename files (overrides --dry-run)")

    args = parser.parse_args()

    if args.mode == "inspect":
        mode_inspect(args.folder)

    elif args.mode == "search":
        mode_search(args.folder, args.query)

    elif args.mode == "rename":
        dry = not args.apply
        mode_rename(args.folder, args.loc, dry_run=dry)
