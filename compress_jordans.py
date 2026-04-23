"""
compress_jordans.py — Apple Compressor integration for SACC pipeline
Source: /Users/miniman/Documents/Sneaker_Scripts/compress_jordans.py
Copied into SACC repo for pipeline portability.

Uses Apple Compressor with API_Ready_HEVC.compressorsetting to produce
720p HEVC outputs named {original}_Gemini_API.mp4 ready for Gemini API submission.

3 Duplicate Guards:
  G1 — _Gemini_API.mp4 output already exists
  G2 — Renamed/final version already exists in Compressed_Files/
  G3 — Original RAW already moved to Processed_RAW/
"""

import os
import subprocess
import time

# ── Paths ─────────────────────────────────────────────────────────────────────
# Setting file lives alongside this script; falls back to Sneaker_Scripts location
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR  = "/Users/miniman/Documents/Sneaker_Scripts"

SETTING_NAME = "API_Ready_HEVC.compressorsetting"
SETTING_PATH = (
    os.path.join(_THIS_DIR, SETTING_NAME)
    if os.path.exists(os.path.join(_THIS_DIR, SETTING_NAME))
    else os.path.join(_SCRIPT_DIR, SETTING_NAME)
)
COMPRESSOR_EXE = "/Applications/Compressor.app/Contents/MacOS/Compressor"


def run_compression(source_folder, output_folder=None):
    """
    Scans source_folder for .MP4/.MOV files and queues them in Apple Compressor.
    Returns a list of dicts with info about each queued or skipped file.

    Each result dict:
        {
            "original":        str,   # original filename
            "compressed_path": str,   # expected output path
            "status":          str,   # "queued" | "exists" | "already_renamed"
                                      # | "already_archived" | "failed" | "no_compressor"
        }
    """
    if not os.path.exists(COMPRESSOR_EXE):
        print(f"[ERROR] Apple Compressor not found at {COMPRESSOR_EXE}")
        return [{"original": None, "compressed_path": None, "status": "no_compressor"}]

    if not os.path.exists(SETTING_PATH):
        print(f"[ERROR] Compressor setting not found: {SETTING_PATH}")
        return [{"original": None, "compressed_path": None, "status": "no_setting"}]

    if not output_folder:
        output_folder = os.path.join(source_folder, "Compressed_Files")

    os.makedirs(output_folder, exist_ok=True)
    print(f"[compress] output → {output_folder}")

    # Guard 2: basenames already in Compressed_Files (catches renamed finals too)
    already_compressed = set()
    for f in os.listdir(output_folder):
        already_compressed.add(os.path.splitext(f)[0].lower())

    # Guard 3: originals already archived to Processed_RAW/
    archived_raw_folder = os.path.join(source_folder, "Processed_RAW")
    already_archived = set()
    if os.path.exists(archived_raw_folder):
        for f in os.listdir(archived_raw_folder):
            already_archived.add(os.path.splitext(f.replace("RAW_", ""))[0].lower())

    files = [
        f for f in os.listdir(source_folder)
        if f.lower().endswith(('.mov', '.mp4')) and not f.startswith('.')
    ]

    results = []

    if not files:
        print("[compress] No video files found in source folder.")
        return results

    for filename in files:
        input_path      = os.path.join(source_folder, filename)
        base_name       = os.path.splitext(filename)[0]
        output_filename = f"{base_name}_Gemini_API.mp4"
        output_path     = os.path.join(output_folder, output_filename)

        # Guard 1
        if os.path.exists(output_path):
            print(f"[SKIP-G1] Already compressed: {output_filename}")
            results.append({"original": filename, "compressed_path": output_path, "status": "exists"})
            continue

        # Guard 2
        if base_name.lower() in already_compressed:
            print(f"[SKIP-G2] Already renamed in Compressed_Files: {base_name}")
            results.append({"original": filename, "compressed_path": output_path, "status": "already_renamed"})
            continue

        # Guard 3
        if base_name.lower() in already_archived:
            print(f"[SKIP-G3] Original already in Processed_RAW: {filename}")
            results.append({"original": filename, "compressed_path": output_path, "status": "already_archived"})
            continue

        cmd = [
            COMPRESSOR_EXE,
            "-batchname",    "SACC_Batch_Processing",
            "-jobpath",      input_path,
            "-settingpath",  SETTING_PATH,
            "-locationpath", output_path,
        ]

        try:
            subprocess.Popen(cmd)
            print(f"[QUEUED] {output_filename}")
            results.append({"original": filename, "compressed_path": output_path, "status": "queued"})
            time.sleep(1)  # stagger Compressor job submissions
        except Exception as e:
            print(f"[ERROR] Could not queue {filename}: {e}")
            results.append({"original": filename, "compressed_path": None, "status": "failed"})

    return results


def wait_for_compression(results, timeout=3600, poll_interval=10):
    """
    Blocks until all queued Compressor jobs produce their output files,
    or until timeout seconds have elapsed.

    Returns the same results list with 'status' updated to 'ready' or 'timeout'.
    """
    queued = [r for r in results if r["status"] == "queued"]
    if not queued:
        return results

    print(f"[compress] Waiting for {len(queued)} Compressor job(s)…")
    deadline = time.time() + timeout

    while time.time() < deadline:
        pending = [r for r in queued if not os.path.exists(r["compressed_path"] or "")]
        if not pending:
            print("[compress] All jobs complete ✓")
            for r in queued:
                r["status"] = "ready"
            return results

        remaining = len(pending)
        done = len(queued) - remaining
        print(f"[compress] {done}/{len(queued)} done — waiting ({remaining} pending)…")
        time.sleep(poll_interval)

    # Timeout
    for r in queued:
        if not os.path.exists(r["compressed_path"] or ""):
            r["status"] = "timeout"
    return results


if __name__ == "__main__":
    # Quick test against the Sneeaker Solo batch folder
    test_folder = "/Volumes/Team Bank 12/Sneeaker Solo"
    print(f"Testing run_compression on: {test_folder}")
    results = run_compression(test_folder)
    for r in results:
        print(r)
