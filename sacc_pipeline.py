"""
sacc_pipeline.py — SACC Full Pipeline Orchestrator
====================================================
Pipeline sequence (per design spec):

  1. FCP Inspector rename  →  (manual, done before consolidation)
  2. Consolidation         →  FCP drops files into Inbox/ on Team Bank 12
  3. Batch Rename          →  run_vibe_renamer() applies LOC-TYPE_YYMMDD_ID_Cam_orig naming
  4. Folder organisation   →  files moved to /SACC/{YEAR}/{YYMMDD}/
  5. Apple Compressor      →  run_compression() queues 720p HEVC jobs → _Gemini_API.mp4
  6. Wait for completion   →  wait_for_compression() polls until outputs exist
  7. Gemini API analysis   →  analyze_sneaker_video() → JSON with Model/SKU/Size/Price
  8. JSON output           →  saved to /SACC/{YEAR}/{YYMMDD}/json/{sku}_{model}.json
  9. Pre-Flight gate       →  clips flagged by ffprobe (duration < 3s, motion 0) are skipped

Usage:
  python sacc_pipeline.py --inbox "/Volumes/Team Bank 12/SACC/Inbox" \\
                          --root  "/Volumes/Team Bank 12/SACC"       \\
                          --loc   FLM                                  \\
                          --id    "Air Jordan 1 Chicago"

  Or run via sacc_watcher.py for fully automated folder-watch mode.
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# ── Local imports ─────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from renamer_logic   import run_vibe_renamer, extract_metadata
from compress_jordans import run_compression, wait_for_compression
from gemini_pipeline import analyze_sneaker_video

# ── Constants ─────────────────────────────────────────────────────────────────
SYNOLOGY_ROOT = "/Volumes/Team Bank 12/SACC"
INBOX_PATH    = os.path.join(SYNOLOGY_ROOT, "Inbox")
VIDEO_EXTS    = {".mov", ".mp4", ".m4v"}

# Pre-Flight thresholds (mirrors frontend PreFlightPanel logic)
MIN_DURATION_SECS = 3
MIN_MOTION_SCORE  = 1   # 0 = no detectable movement → skip


# ── Folder structure helpers ──────────────────────────────────────────────────

def dated_folder(root, date_str):
    """
    Returns (and creates) /root/YYYY/YYMMDD/ from a YYMMDD string.
    e.g. date_str="250111" → /root/2025/250111/
    """
    year = "20" + date_str[:2]
    path = os.path.join(root, year, date_str)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "json"), exist_ok=True)
    return path


def inbox_files(inbox):
    """Return all video files currently in the Inbox folder (non-recursive)."""
    if not os.path.isdir(inbox):
        return []
    return [
        os.path.join(inbox, f)
        for f in os.listdir(inbox)
        if not f.startswith('.') and Path(f).suffix.lower() in VIDEO_EXTS
    ]


# ── Pre-Flight gate ───────────────────────────────────────────────────────────

def preflight_check(file_path):
    """
    Runs a minimal ffprobe check on a single file.
    Returns (pass: bool, reasons: list[str])

    Flags (auto-skip):  duration < 3s, motion_score == 0
    Exempt (not flagged): audio absence, file size
    """
    ffprobe = os.path.join(_DIR, "ffprobe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"  # fall back to system ffprobe

    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        file_path
    ]

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out)

        duration = float(data.get("format", {}).get("duration", 999))
        if duration < MIN_DURATION_SECS:
            return False, [f"duration {duration:.1f}s < {MIN_DURATION_SECS}s"]

        # Motion score: approximated by nb_read_frames / duration
        # A real implementation would use scene-change detection;
        # here we use stream frame count as a proxy.
        streams = data.get("streams", [])
        vid = next((s for s in streams if s.get("codec_type") == "video"), {})
        nb_frames = int(vid.get("nb_read_frames", vid.get("nb_frames", 999)) or 999)
        motion_proxy = min(100, int(nb_frames / max(duration, 1)))
        if motion_proxy < MIN_MOTION_SCORE:
            return False, ["motion score 0 — no detectable movement"]

        return True, []

    except Exception as e:
        # If ffprobe fails, don't block the file — pass it through
        print(f"  [preflight] ffprobe error on {os.path.basename(file_path)}: {e}")
        return True, []


# ── Pipeline stages ───────────────────────────────────────────────────────────

def stage_rename(inbox, loc_code, identifier):
    """
    Stage 3: Run batch rename on all files in Inbox.
    Returns list of new file paths after rename.
    """
    print(f"\n[STAGE 3] Batch rename — loc={loc_code}, id='{identifier}'")
    renamed = []
    for result in run_vibe_renamer(inbox, loc_code, identifier):
        if result.get("error"):
            print(f"  [rename] ERROR: {result['error']}")
            return []
        if not result.get("done"):
            print(f"  [rename] {result['current']}/{result['total']} "
                  f"{result.get('original')} → {result.get('new')}")
            renamed.append(os.path.join(inbox, result["new"]))
    print(f"  [rename] Done — {len(renamed)} file(s) renamed")
    return renamed


def stage_organise(inbox, root, files):
    """
    Stage 4: Move renamed files from Inbox → /root/YYYY/YYMMDD/.
    Returns dict mapping original_path → destination_path.
    """
    print(f"\n[STAGE 4] Organising files into dated folders under {root}")
    moved = {}
    for fp in files:
        date_str, _ = extract_metadata(fp)
        dest_dir = dated_folder(root, date_str)
        dest_path = os.path.join(dest_dir, os.path.basename(fp))
        if os.path.exists(dest_path):
            print(f"  [organise] Already exists, skipping: {os.path.basename(fp)}")
            moved[fp] = dest_path
            continue
        shutil.move(fp, dest_path)
        print(f"  [organise] {os.path.basename(fp)} → {dest_dir}/")
        moved[fp] = dest_path
    return moved


def stage_preflight(files):
    """
    Pre-Flight gate: filter out clips that would waste Compressor / Gemini quota.
    Returns (approved, skipped) lists of file paths.
    """
    print(f"\n[PRE-FLIGHT] Checking {len(files)} file(s)…")
    approved, skipped = [], []
    for fp in files:
        ok, reasons = preflight_check(fp)
        if ok:
            print(f"  ✓ PASS  {os.path.basename(fp)}")
            approved.append(fp)
        else:
            print(f"  ⚠ SKIP  {os.path.basename(fp)} — {', '.join(reasons)}")
            skipped.append(fp)
    print(f"  Pre-Flight: {len(approved)} approved, {len(skipped)} skipped")
    return approved, skipped


def stage_compress(dest_dir):
    """
    Stage 5 + 6: Queue Apple Compressor jobs and wait for completion.
    Returns list of ready compressed file paths.
    """
    print(f"\n[STAGE 5] Queueing Apple Compressor jobs from {dest_dir}")
    results = run_compression(dest_dir)
    if not results:
        print("  [compress] Nothing to compress.")
        return []

    for r in results:
        print(f"  [{r['status'].upper()}] {r['original']} → {os.path.basename(r['compressed_path'] or '')}")

    print(f"\n[STAGE 6] Waiting for Compressor to finish…")
    results = wait_for_compression(results, timeout=3600, poll_interval=15)

    ready = [r["compressed_path"] for r in results
             if r["status"] in ("ready", "exists") and r.get("compressed_path")]
    print(f"  [compress] {len(ready)} file(s) ready for Gemini")
    return ready


def stage_gemini(compressed_files, json_root):
    """
    Stage 7 + 8: Send each compressed file to Gemini API and save JSON output.
    Returns list of saved JSON file paths.
    """
    print(f"\n[STAGE 7] Gemini API analysis — {len(compressed_files)} file(s)")
    saved_jsons = []

    for fp in compressed_files:
        print(f"  → Analysing: {os.path.basename(fp)}")
        result = analyze_sneaker_video(fp)

        if result.get("error"):
            print(f"  [gemini] ERROR: {result['error']}")
            continue

        # Annotate with source file and timestamp
        result["source_file"] = os.path.basename(fp)
        result["analysed_at"] = datetime.utcnow().isoformat() + "Z"

        sku   = result.get("SKU", "UNKNOWN").replace("/", "-")
        model = result.get("Model", "Unknown").replace(" ", "_")[:40]
        json_name = f"{sku}_{model}.json"
        json_path = os.path.join(json_root, json_name)

        with open(json_path, "w") as f:
            json.dump(result, f, indent=2)

        print(f"  [gemini] ✓ {json_name}")
        print(f"           Model: {result.get('Model')} | SKU: {sku} | "
              f"Size: {result.get('Size')} | Price: {result.get('Price')}")
        saved_jsons.append(json_path)

    print(f"  [gemini] {len(saved_jsons)} JSON file(s) saved to {json_root}")
    return saved_jsons


# ── Main pipeline entry point ─────────────────────────────────────────────────

def run_pipeline(inbox, root, loc_code, identifier, dry_run=False):
    """
    Full SACC pipeline: rename → organise → preflight → compress → Gemini → JSON.

    Args:
        inbox     : Path to the Inbox folder (watch target)
        root      : SACC root on Synology (e.g. /Volumes/Team Bank 12/SACC)
        loc_code  : Location code (e.g. "FLM")
        identifier: Shoe identifier (e.g. "Air Jordan 1 Chicago")
        dry_run   : If True, print plan but don't rename/move/compress/call API
    """
    start = time.time()
    print("=" * 60)
    print("SACC Pipeline — Starting")
    print(f"  Inbox      : {inbox}")
    print(f"  Root       : {root}")
    print(f"  Location   : {loc_code}")
    print(f"  Identifier : {identifier}")
    print(f"  Dry run    : {dry_run}")
    print("=" * 60)

    files_in_inbox = inbox_files(inbox)
    if not files_in_inbox:
        print("[pipeline] Inbox is empty — nothing to process.")
        return

    print(f"[pipeline] Found {len(files_in_inbox)} file(s) in Inbox")

    if dry_run:
        for f in files_in_inbox:
            print(f"  DRY-RUN: would process {os.path.basename(f)}")
        return

    # Stage 3: Batch rename
    renamed_files = stage_rename(inbox, loc_code, identifier)
    if not renamed_files:
        print("[pipeline] Rename stage failed — aborting.")
        return

    # Stage 4: Organise into dated folders on Synology
    moved = stage_organise(inbox, root, renamed_files)
    dest_files = list(moved.values())

    if not dest_files:
        print("[pipeline] No files to continue processing.")
        return

    # Group by destination directory
    dest_dirs = {}
    for fp in dest_files:
        d = os.path.dirname(fp)
        dest_dirs.setdefault(d, []).append(fp)

    for dest_dir, batch in dest_dirs.items():
        json_dir = os.path.join(dest_dir, "json")
        os.makedirs(json_dir, exist_ok=True)

        print(f"\n── Processing batch in {dest_dir} ({len(batch)} file(s)) ──")

        # Pre-Flight gate
        approved, skipped = stage_preflight(batch)
        if skipped:
            skipped_log = os.path.join(dest_dir, "preflight_skipped.json")
            with open(skipped_log, "w") as f:
                json.dump([os.path.basename(s) for s in skipped], f, indent=2)
            print(f"  Skipped files logged → {skipped_log}")

        if not approved:
            print("  No files passed Pre-Flight — skipping compression and Gemini stages.")
            continue

        # Stage 5 + 6: Compress
        compressed = stage_compress(dest_dir)
        if not compressed:
            print("  No compressed files ready — skipping Gemini stage.")
            continue

        # Stage 7 + 8: Gemini API + JSON output
        stage_gemini(compressed, json_dir)

    elapsed = round(time.time() - start, 1)
    print(f"\n{'='*60}")
    print(f"SACC Pipeline — Complete in {elapsed}s")
    print(f"{'='*60}\n")


# ── CLI entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SACC Pipeline — FCP consolidation → rename → compress → Gemini → JSON"
    )
    parser.add_argument("--inbox",   default=INBOX_PATH,    help="Inbox watch folder path")
    parser.add_argument("--root",    default=SYNOLOGY_ROOT, help="SACC root on Synology")
    parser.add_argument("--loc",     default="FLM",         help="Location code (e.g. FLM)")
    parser.add_argument("--id",      default="",            help="Shoe identifier string")
    parser.add_argument("--dry-run", action="store_true",   help="Print plan only, no changes")
    args = parser.parse_args()

    if not args.id:
        print("ERROR: --id is required (e.g. --id 'Air Jordan 1 Chicago')")
        sys.exit(1)

    run_pipeline(
        inbox      = args.inbox,
        root       = args.root,
        loc_code   = args.loc,
        identifier = args.id,
        dry_run    = args.dry_run,
    )
