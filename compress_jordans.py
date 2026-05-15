"""
compress_jordans.py — SACC Proxy Compression for Vertex AI Ingestion
======================================================================
Purpose
-------
Source footage files frequently exceed the Vertex AI / Gemini API upload
limit. This module creates low-bitrate HEVC *proxy* files that are used
solely for API ingestion and are DELETED after the JSON output is written.

Proxy naming contract
---------------------
  The proxy MUST inherit the EXACT filename of its renamed source.
  This makes the filename the relational key between:
    - the hi-res master on Synology
    - the low-bitrate proxy sent to Vertex AI
    - the JSON output that permanently indexes both

  Source  : /SACC/2026/260423/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.mov
  Proxy   : /SACC/2026/260423/_proxy/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.mp4
  JSON    : /SACC/2026/260423/json/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.json
            └── "original_file": "FLM-MALL_260423_..._IMG_3439.mov"  ← relational key

Lifecycle
---------
  1. rename_stage  → source file gets its permanent SACC name
  2. compress      → proxy created in _proxy/ with same stem, .mp4 ext
  3. vertex_upload → proxy uploaded; JSON written with original_file key
  4. proxy_cleanup → _proxy/ directory deleted entirely
  5. JSON persists → permanent index pointing back to hi-res master

Duplicate Guards
----------------
  G1 — proxy already exists (e.g. pipeline restarted mid-run)
  G2 — JSON output for this file already exists (already analysed)
  G3 — source moved to Processed_RAW/ (already archived)
"""

import os
import subprocess
import shutil
import time

# ── Paths ─────────────────────────────────────────────────────────────────────
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))

SETTING_NAME   = "API_Ready_HEVC.compressorsetting"
SETTING_PATH   = os.path.join(_THIS_DIR, SETTING_NAME)
COMPRESSOR_EXE = "/Applications/Compressor.app/Contents/MacOS/Compressor"
PROXY_DIR_NAME = "_proxy"   # temporary subfolder inside the dated batch folder


# ── Public API ────────────────────────────────────────────────────────────────

def run_compression(source_folder, json_folder=None):
    """
    Scans source_folder for renamed video files and queues low-bitrate
    proxy jobs in Apple Compressor.

    The proxy is written to source_folder/_proxy/ using the SAME filename
    as the source (stem preserved, extension forced to .mp4) so it acts
    as the relational key to the hi-res master.

    Args:
        source_folder : folder containing renamed .mov/.mp4 masters
        json_folder   : folder where Vertex AI JSON outputs will land
                        (used for G2 duplicate guard). Defaults to
                        source_folder/json/.

    Returns:
        list of dicts, one per file:
        {
            "original_file" : str,   # renamed source filename (relational key)
            "original_path" : str,   # absolute path to hi-res master
            "proxy_path"    : str,   # absolute path to proxy (may not exist yet)
            "status"        : str,   # "queued" | "exists" | "analysed" |
                                     # "archived" | "failed" |
                                     # "no_compressor" | "no_setting"
        }
    """
    if not os.path.exists(COMPRESSOR_EXE):
        print(f"[compress] ERROR — Apple Compressor not found: {COMPRESSOR_EXE}")
        return [{"original_file": None, "original_path": None,
                 "proxy_path": None, "status": "no_compressor"}]

    if not os.path.exists(SETTING_PATH):
        print(f"[compress] ERROR — Compressor setting not found: {SETTING_PATH}")
        print(f"  Copy {SETTING_NAME} into the SACC repo root to resolve this.")
        return [{"original_file": None, "original_path": None,
                 "proxy_path": None, "status": "no_setting"}]

    proxy_dir  = os.path.join(source_folder, PROXY_DIR_NAME)
    os.makedirs(proxy_dir, exist_ok=True)

    if json_folder is None:
        json_folder = os.path.join(source_folder, "json")

    # G2: basenames already analysed → JSON exists
    analysed_stems = set()
    if os.path.isdir(json_folder):
        for f in os.listdir(json_folder):
            if f.lower().endswith(".json"):
                analysed_stems.add(os.path.splitext(f)[0].lower())

    # G3: originals already archived to Processed_RAW/
    archived_stems = set()
    archived_dir = os.path.join(source_folder, "Processed_RAW")
    if os.path.isdir(archived_dir):
        for f in os.listdir(archived_dir):
            archived_stems.add(os.path.splitext(f)[0].lower())

    # Collect source files — skip the proxy subfolder itself
    source_files = [
        f for f in os.listdir(source_folder)
        if (f.lower().endswith((".mov", ".mp4", ".m4v"))
            and not f.startswith(".")
            and os.path.isfile(os.path.join(source_folder, f)))
    ]

    results = []

    if not source_files:
        print("[compress] No video files found in source folder.")
        return results

    print(f"[compress] {len(source_files)} source file(s) → proxy dir: {proxy_dir}")

    for filename in source_files:
        stem            = os.path.splitext(filename)[0]
        source_path     = os.path.join(source_folder, filename)
        # Proxy keeps exact stem of renamed source, forced to .mp4
        proxy_filename  = stem + ".mp4"
        proxy_path      = os.path.join(proxy_dir, proxy_filename)

        entry = {
            "original_file": filename,      # ← relational key
            "original_path": source_path,
            "proxy_path":    proxy_path,
            "status":        None,
        }

        # G1 — proxy already exists (previous partial run)
        if os.path.exists(proxy_path):
            print(f"  [G1-SKIP] Proxy exists: {proxy_filename}")
            entry["status"] = "exists"
            results.append(entry)
            continue

        # G2 — JSON already written → already analysed
        if stem.lower() in analysed_stems:
            print(f"  [G2-SKIP] Already analysed: {stem}")
            entry["status"] = "analysed"
            results.append(entry)
            continue

        # G3 — original archived
        if stem.lower() in archived_stems:
            print(f"  [G3-SKIP] Original archived: {filename}")
            entry["status"] = "archived"
            results.append(entry)
            continue

        # Queue in Apple Compressor
        cmd = [
            COMPRESSOR_EXE,
            "-batchname",    "SACC_Proxy_Batch",
            "-jobpath",      source_path,
            "-settingpath",  SETTING_PATH,
            "-locationpath", proxy_path,
        ]

        try:
            subprocess.Popen(cmd)
            print(f"  [QUEUED] {filename} → _proxy/{proxy_filename}")
            entry["status"] = "queued"
            time.sleep(1)   # stagger Compressor job submissions
        except Exception as e:
            print(f"  [ERROR] Could not queue {filename}: {e}")
            entry["status"] = "failed"

        results.append(entry)

    return results


def wait_for_proxies(results, timeout=3600, poll_interval=10,
                     hang_threshold=300, stable_threshold=30):
    """
    Wait for queued proxy jobs with per-job hang detection.

    A proxy is classified as:
      - "ready"   : file exists, non-empty, and hasn't changed size for
                    `stable_threshold` seconds (encoder has finished).
      - "hung"    : no growth (no file appearance or no size change) for
                    `hang_threshold` seconds. Compressor jobs that wedge
                    on a problematic source clip end up here instead of
                    blocking the whole batch until timeout.
      - "timeout" : neither ready nor hung when the overall `timeout` elapses
                    (rare — usually means the file is still growing slowly).

    Late-completing jobs (file exists with size>0 but `stable_threshold`
    hadn't elapsed when timeout hit) are promoted to "ready" before return,
    so a useful batch is never abandoned just because the deadline arrived.
    This fixes the 2019-01-11 failure mode where 16 proxies finished but
    were silently dropped because the loop exited with them still tagged
    "queued".

    Args:
        results          : list from run_compression()
        timeout          : overall hard limit in seconds (default 1 hour)
        poll_interval    : seconds between polls (default 10)
        hang_threshold   : seconds of no growth before marking "hung" (default 300)
        stable_threshold : seconds of no growth before marking "ready" (default 30)

    Returns the same results list with status updated.
    """
    queued = [r for r in results if r["status"] == "queued"]
    if not queued:
        return results

    print(f"[compress] Waiting for {len(queued)} proxy job(s)…  "
          f"(hang threshold: {hang_threshold}s without growth)")

    # Per-path progress tracking: last seen size + timestamp of last growth.
    progress: dict = {}
    for r in queued:
        path = r["proxy_path"] or ""
        try:
            sz = os.path.getsize(path) if os.path.exists(path) else -1
        except OSError:
            sz = -1
        progress[path] = {"size": sz, "since": time.time()}

    deadline = time.time() + timeout

    while time.time() < deadline:
        now = time.time()
        unresolved = 0

        for r in queued:
            if r["status"] in ("ready", "hung"):
                continue

            path = r["proxy_path"] or ""
            try:
                size = os.path.getsize(path) if os.path.exists(path) else -1
            except OSError:
                size = -1

            track = progress[path]
            if size > track["size"]:
                track["size"]  = size
                track["since"] = now

            # READY: file is non-empty and has been stable for stable_threshold
            if size > 0 and (now - track["since"]) >= stable_threshold:
                r["status"] = "ready"
                print(f"  [READY] {os.path.basename(path)} ({size:,} bytes)")
                continue

            # HUNG: no growth for hang_threshold seconds — either the file
            # never appeared or it stopped growing while still incomplete.
            if (now - track["since"]) >= hang_threshold:
                r["status"] = "hung"
                detail = f"size={size}" if size >= 0 else "no file"
                print(f"  [HUNG] {r['original_file']} — no progress in "
                      f"{int(now - track['since'])}s ({detail})")
                continue

            unresolved += 1

        n_ready = sum(1 for r in queued if r["status"] == "ready")
        n_hung  = sum(1 for r in queued if r["status"] == "hung")

        if unresolved == 0:
            print(f"[compress] All jobs settled — {n_ready} ready, {n_hung} hung")
            return results

        print(f"[compress] {n_ready}/{len(queued)} ready, {n_hung} hung, "
              f"{unresolved} pending…")
        time.sleep(poll_interval)

    # Deadline reached. Promote anything with a non-empty file to "ready"
    # (don't abandon completed work just because the clock ran out), and
    # mark the rest "timeout".
    print(f"[compress] Timeout reached — finalising remaining jobs…")
    for r in queued:
        if r["status"] in ("ready", "hung"):
            continue
        path = r["proxy_path"] or ""
        try:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                r["status"] = "ready"
                print(f"  [READY-late] {os.path.basename(path)}")
            else:
                r["status"] = "timeout"
                print(f"  [TIMEOUT] {r['original_file']}")
        except OSError:
            r["status"] = "timeout"
            print(f"  [TIMEOUT] {r['original_file']}")

    return results


def cleanup_proxies(source_folder):
    """
    Deletes the entire _proxy/ directory after Vertex AI analysis is complete.
    Proxies are transient assets — the JSON index is the permanent record.

    Returns the number of proxy files deleted.
    """
    proxy_dir = os.path.join(source_folder, PROXY_DIR_NAME)
    if not os.path.isdir(proxy_dir):
        return 0

    count = sum(1 for f in os.listdir(proxy_dir) if not f.startswith("."))
    shutil.rmtree(proxy_dir)
    print(f"[compress] Proxy cleanup — deleted {count} file(s) from {proxy_dir}")
    return count


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    test_folder = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/Team Bank 12/Sneeaker Solo"
    print(f"[compress] Dry-check: COMPRESSOR_EXE exists = {os.path.exists(COMPRESSOR_EXE)}")
    print(f"[compress] Dry-check: SETTING_PATH exists   = {os.path.exists(SETTING_PATH)}")
    print(f"[compress] Test folder: {test_folder}")
    results = run_compression(test_folder)
    for r in results:
        print(r)
