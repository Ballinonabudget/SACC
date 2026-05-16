"""
compress_jordans.py — SACC Proxy Compression (ffmpeg-direct, v2)
=================================================================
Generates low-bitrate HEVC proxies for every renamed video file in a
source folder. Proxies are the transient assets uploaded to Gemini /
Vertex AI; the hi-res master remains untouched on the NAS.

This module replaced an earlier Apple Compressor pipeline (v1) that
spawned one Compressor.app process per file and hung unpredictably
when batches grew past ~20 clips. The v2 implementation calls ffmpeg
directly via subprocess and parallelises encodes via ThreadPoolExecutor.

Why ffmpeg, not Compressor
--------------------------
- No GUI/daemon dependency  (compressord is opaque and hangs)
- ~5-10× faster on Apple Silicon via hevc_videotoolbox hardware encoder
- Synchronous: encoding either completes or errors immediately — no
  "is it still working?" polling required
- Parallelism cap is exact (ThreadPoolExecutor max_workers)
- Library is already bundled (./ffmpeg) and used by venue_anchor.py

Proxy naming contract (unchanged from v1)
-----------------------------------------
  The proxy MUST inherit the EXACT filename of its renamed source.
  This makes the filename the relational key between:
    - the hi-res master on Synology
    - the low-bitrate proxy sent to Gemini / Vertex AI
    - the JSON output that permanently indexes both

Public API (unchanged from v1, so sacc_pipeline.py needs no edits)
------------------------------------------------------------------
  run_compression(source_folder, json_folder=None) -> list of dicts
  wait_for_proxies(results, ...)                   -> same list
  cleanup_proxies(source_folder)                   -> int

Status outcomes
---------------
  run_compression sets one of:
    "ready"        — proxy encoded successfully
    "exists"       — proxy was already on disk (G1 dedup)
    "analysed"     — JSON already written (G2 dedup, never queued)
    "archived"     — source moved to Processed_RAW/ (G3 dedup)
    "failed"       — ffmpeg exited non-zero (msg captured in entry["error"])
  wait_for_proxies is a near-no-op kept for API stability — it
  re-verifies that "ready" files still exist on disk.

Tuning
------
  PROXY_PARALLEL  — env var, default = min(4, cpu_count). Hardware HEVC
                    encoder doesn't scale linearly with concurrency, so
                    going above 4 buys little. Software libx265 scales
                    further if you set this higher manually.
"""

from __future__ import annotations    # PEP 604 unions + PEP 585 generics on Py 3.9

import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# Module-level annotated assignments are evaluated regardless of __future__,
# so the cache variable's annotation needs the runtime-safe form.
_video_encoder_cache: Optional[str] = None

# ── Paths ─────────────────────────────────────────────────────────────────────
_THIS_DIR      = os.path.dirname(os.path.abspath(__file__))
PROXY_DIR_NAME = "_proxy"
VIDEO_EXTS     = {".mov", ".mp4", ".m4v"}

# ── Tuning ────────────────────────────────────────────────────────────────────
_DEFAULT_PARALLEL = max(2, min(4, os.cpu_count() or 4))
PROXY_PARALLEL    = max(1, int(os.getenv("PROXY_PARALLEL", str(_DEFAULT_PARALLEL))))
PROXY_HEIGHT      = int(os.getenv("PROXY_HEIGHT", "720"))     # output height in px
PROXY_BITRATE     = os.getenv("PROXY_BITRATE", "3M")          # target video bitrate
PROXY_AUDIO_BR    = os.getenv("PROXY_AUDIO_BR", "64k")        # audio bitrate (kept for Gemini price_audio)
ENCODE_TIMEOUT    = int(os.getenv("ENCODE_TIMEOUT", "600"))   # per-clip ffmpeg timeout in seconds


# ── ffmpeg discovery ──────────────────────────────────────────────────────────

def _ffmpeg_exe() -> str:
    local = os.path.join(_THIS_DIR, "ffmpeg")
    return local if os.path.exists(local) else "ffmpeg"


def _detect_video_encoder() -> str:
    """
    Pick the best available HEVC encoder. Hardware (videotoolbox) on
    Apple Silicon, software (libx265) elsewhere. Cached after first call.
    """
    global _video_encoder_cache
    if _video_encoder_cache is not None:
        return _video_encoder_cache
    try:
        out = subprocess.check_output(
            [_ffmpeg_exe(), "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT, timeout=5,
        ).decode("utf-8", errors="replace")
        if "hevc_videotoolbox" in out:
            _video_encoder_cache = "hevc_videotoolbox"
        elif "libx265" in out:
            _video_encoder_cache = "libx265"
        else:
            _video_encoder_cache = "libx264"   # last-ditch fallback
    except Exception:
        _video_encoder_cache = "libx264"
    return _video_encoder_cache


# ── Encode worker ─────────────────────────────────────────────────────────────

def _encode_args(src_path: str, dst_path: str, video_encoder: str) -> list[str]:
    """Build the ffmpeg command line for a single proxy encode.

    Robustness notes:
      -fflags +genpts        : regenerate presentation timestamps (some
                                Sony a6300 files have non-monotonic PTS)
      -map 0:v:0 -map 0:a?   : take only the first video stream and any
                                audio streams. Skips data/timecode tracks
                                that confuse hardware encoders.
      -allow_sw 1            : videotoolbox-only; permits fallback to
                                software when the hardware path can't
                                build a session for a given clip.
      -tag:v hvc1            : QuickTime-compatible HEVC stream tag.
      -movflags +faststart   : moves moov atom to file start (streaming-
                                friendly upload).
    """
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-fflags", "+genpts",
        "-i", src_path,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", video_encoder,
    ]
    if video_encoder == "hevc_videotoolbox":
        cmd += ["-allow_sw", "1"]
    cmd += [
        "-b:v", PROXY_BITRATE,
        "-tag:v", "hvc1",
        "-vf", f"scale=-2:{PROXY_HEIGHT}",
        "-c:a", "aac",
        "-b:a", PROXY_AUDIO_BR,
        "-ac", "1",
        "-movflags", "+faststart",
        dst_path,
    ]
    return cmd


def _encode_one(entry: dict, video_encoder: str) -> dict:
    """
    Encode one proxy. Mutates and returns `entry` with terminal status:
        "ready"  on success
        "failed" on ffmpeg error or timeout (entry["error"] holds the msg)
    """
    src = entry["original_path"]
    dst = entry["proxy_path"]
    try:
        proc = subprocess.run(
            _encode_args(src, dst, video_encoder),
            check=False,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            timeout=ENCODE_TIMEOUT,
        )
        if proc.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            entry["status"] = "ready"
        else:
            entry["status"] = "failed"
            err = proc.stderr.decode("utf-8", errors="replace").strip() or \
                  f"ffmpeg exit {proc.returncode}, no output file"
            entry["error"] = err[:300]
            # Clean up zero-byte / partial outputs
            try:
                if os.path.exists(dst):
                    os.unlink(dst)
            except OSError:
                pass
    except subprocess.TimeoutExpired:
        entry["status"] = "failed"
        entry["error"]  = f"ffmpeg timeout after {ENCODE_TIMEOUT}s"
        try:
            if os.path.exists(dst):
                os.unlink(dst)
        except OSError:
            pass
    except Exception as e:
        entry["status"] = "failed"
        entry["error"]  = f"{type(e).__name__}: {e}"
    return entry


# ── Public API ────────────────────────────────────────────────────────────────

def run_compression(source_folder: str, json_folder: str | None = None) -> list[dict]:
    """
    Scan source_folder for renamed video files and encode HEVC proxies in
    parallel via ffmpeg. Proxies are written to source_folder/_proxy/ using
    the source stem with .mp4 extension.

    Args:
        source_folder : folder containing renamed .mov/.mp4 masters
        json_folder   : folder where pipeline JSON outputs land (used for
                        G2 dedup). Defaults to source_folder/json/.

    Returns:
        list of dicts, one per source file:
            {
                "original_file" : str,   # renamed source filename (relational key)
                "original_path" : str,   # absolute path to hi-res master
                "proxy_path"    : str,   # absolute path to proxy
                "status"        : str,   # see module docstring
                "error"         : str,   # only present when status == "failed"
            }
    """
    ffmpeg = _ffmpeg_exe()
    try:
        subprocess.check_output([ffmpeg, "-version"], stderr=subprocess.STDOUT, timeout=5)
    except Exception:
        print(f"[compress] ERROR — ffmpeg not found or not executable: {ffmpeg}")
        return [{"original_file": None, "original_path": None,
                 "proxy_path": None, "status": "no_ffmpeg"}]

    proxy_dir = os.path.join(source_folder, PROXY_DIR_NAME)
    os.makedirs(proxy_dir, exist_ok=True)

    if json_folder is None:
        json_folder = os.path.join(source_folder, "json")

    # G2: stems already analysed → JSON exists
    analysed_stems: set = set()
    if os.path.isdir(json_folder):
        for f in os.listdir(json_folder):
            if f.lower().endswith(".json"):
                analysed_stems.add(os.path.splitext(f)[0].lower())

    # G3: stems already archived → original moved to Processed_RAW/
    archived_stems: set = set()
    archived_dir = os.path.join(source_folder, "Processed_RAW")
    if os.path.isdir(archived_dir):
        for f in os.listdir(archived_dir):
            archived_stems.add(os.path.splitext(f)[0].lower())

    # Collect source files
    try:
        source_files = sorted(
            f for f in os.listdir(source_folder)
            if (Path(f).suffix.lower() in VIDEO_EXTS
                and not f.startswith(".")
                and os.path.isfile(os.path.join(source_folder, f)))
        )
    except OSError as e:
        print(f"[compress] ERROR — cannot list {source_folder}: {e}")
        return []

    if not source_files:
        print("[compress] No video files found in source folder.")
        return []

    encoder = _detect_video_encoder()
    print(f"[compress] {len(source_files)} source file(s) → proxy dir: {proxy_dir}")
    print(f"[compress] encoder={encoder}  parallel={PROXY_PARALLEL}  "
          f"target={PROXY_HEIGHT}p@{PROXY_BITRATE}")

    results: list[dict] = []
    to_encode: list[dict] = []

    for filename in source_files:
        stem        = os.path.splitext(filename)[0]
        source_path = os.path.join(source_folder, filename)
        proxy_path  = os.path.join(proxy_dir, stem + ".mp4")

        entry = {
            "original_file": filename,
            "original_path": source_path,
            "proxy_path":    proxy_path,
            "status":        None,
        }

        # G1 — proxy already exists
        if os.path.exists(proxy_path) and os.path.getsize(proxy_path) > 0:
            entry["status"] = "exists"
            results.append(entry)
            continue
        # G2 — JSON already written
        if stem.lower() in analysed_stems:
            entry["status"] = "analysed"
            results.append(entry)
            continue
        # G3 — original archived
        if stem.lower() in archived_stems:
            entry["status"] = "archived"
            results.append(entry)
            continue

        to_encode.append(entry)
        results.append(entry)

    if not to_encode:
        print(f"[compress] All {len(results)} file(s) already cached "
              f"(G1/G2/G3 dedup) — nothing to encode.")
        return results

    print(f"[compress] Encoding {len(to_encode)} proxy(ies) in parallel "
          f"({PROXY_PARALLEL} worker(s))…")
    start  = time.time()
    done   = 0
    failed = 0
    total  = len(to_encode)

    with ThreadPoolExecutor(max_workers=PROXY_PARALLEL) as ex:
        futures = {ex.submit(_encode_one, e, encoder): e for e in to_encode}
        for fut in as_completed(futures):
            entry = futures[fut]
            try:
                fut.result()
            except Exception as e:
                entry["status"] = "failed"
                entry["error"]  = f"{type(e).__name__}: {e}"
            done += 1
            if entry["status"] == "ready":
                size_mb = os.path.getsize(entry["proxy_path"]) / 1_048_576
                print(f"  [{done}/{total}] ✓ {os.path.basename(entry['proxy_path'])} "
                      f"({size_mb:.1f} MB)")
            else:
                failed += 1
                print(f"  [{done}/{total}] ✗ {entry['original_file']} "
                      f"— {entry.get('error','unknown error')}")

    elapsed = time.time() - start
    rate = (len(to_encode) - failed) / max(elapsed, 1)
    print(f"[compress] Done in {elapsed:.1f}s — "
          f"{len(to_encode) - failed} ready, {failed} failed "
          f"({rate:.2f} clips/sec avg)")
    return results


def wait_for_proxies(results: list[dict], timeout: int = 3600,
                     poll_interval: int = 10,
                     hang_threshold: int = 300,
                     stable_threshold: int = 30) -> list[dict]:
    """
    Verification pass after run_compression. With ffmpeg-direct, encoding
    completes synchronously inside run_compression, so this function only
    re-checks that "ready" outputs are still on disk. Kept for API
    compatibility with the old Compressor pipeline.

    Args are accepted but unused in v2 (they were Compressor-specific
    polling knobs).
    """
    for r in results:
        if r["status"] == "ready":
            path = r.get("proxy_path") or ""
            if not (os.path.isfile(path) and os.path.getsize(path) > 0):
                # File vanished or empty between encode and now — mark failed
                r["status"] = "failed"
                r["error"]  = "proxy missing or empty after encode"
    return results


def cleanup_proxies(source_folder: str) -> int:
    """
    Delete the _proxy/ directory after pipeline analysis is complete.
    Proxies are transient — the JSON index is the permanent record.

    Returns the number of files removed (0 if no proxy dir).
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
    test_folder = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"[compress] ffmpeg            = {_ffmpeg_exe()}")
    print(f"[compress] detected encoder  = {_detect_video_encoder()}")
    print(f"[compress] PROXY_PARALLEL    = {PROXY_PARALLEL}")
    print(f"[compress] PROXY_HEIGHT      = {PROXY_HEIGHT}")
    print(f"[compress] PROXY_BITRATE     = {PROXY_BITRATE}")
    print(f"[compress] Test folder       = {test_folder}")
    out = run_compression(test_folder)
    for r in out:
        print(f"  {r['status']:10}  {r.get('original_file','?')}"
              + (f"  ({r.get('error')})" if r.get('error') else ''))
