"""
venue_anchor.py — Stage 2: Venue Anchor Scan
============================================
Pre-resolve a folder's loc_code BEFORE per-shoe Gemini calls.

Samples K representative clips, generates quick anchor proxies via direct
ffmpeg, calls Gemini with a venue-focused prompt, and aggregates the
responses into a single loc_code for the entire folder.

Cost rationale
--------------
Before: every clip pays for location extraction in its per-shoe Gemini call.
After:  K (default 5) anchor calls per folder + zero per-clip location work.
For a 30-50 clip folder this is ~85-90% reduction on venue cost.

Resolution precedence (highest to lowest)
-----------------------------------------
  1. Explicit signage match (Gemini reads a store name, confidence >= 0.7)
  2. Fingerprint match      (shelf_layout + brand_environment -> known venue)
  3. caller-supplied fallback (e.g. --loc override)
  4. "" (UNKNOWN)

Idempotency
-----------
Writes _anchor.json to the folder. On re-runs, returns cached result unless
force=True. Costs nothing extra and protects against re-burning Gemini quota.
"""

import os
import json
import re
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

from fcp_namer import LOCATION_DB, VENUE_FINGERPRINTS

# ── Tuning ────────────────────────────────────────────────────────────────────
DEFAULT_SAMPLE_SIZE        = 5
ANCHOR_CLIP_DURATION_SEC   = 10        # only sample first N seconds per clip
ANCHOR_PROXY_DIR           = "_anchor_proxies"
ANCHOR_RESULT_FILE         = "_anchor.json"
MIN_SIGNAGE_CONFIDENCE     = 0.7
VIDEO_EXTS                 = {".mov", ".mp4", ".m4v"}

_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Gemini anchor prompt (venue-focused, NO shoe extraction) ──────────────────
_ANCHOR_PROMPT = """
Watch this short video clip. You are scanning for store-environment cues,
NOT for shoes or products. Return ONLY a JSON object with these fields:

{
  "store_signage": [],     // Any visible store names / signage text.
                           // Examples: ["Nike Factory Store"], ["Footlocker"],
                           //           ["Champs"], ["Jimmy Jazz"], ["Clearance"]
  "brand_logos": [],       // Brand marks on signage, walls, banners.
                           // Examples: ["Nike"], ["Adidas"], ["Jordan"], ["Converse"]
  "shelf_layout": "",      // ONE of:
                           //   "top-loading"  = shoe-on-box-on-shelf (mall stores)
                           //   "multi-rack"   = open racks of mixed inventory (clearance)
                           //   "wall-display" = featured shoes mounted on walls
                           //   "hash_wall"    = colored sticker discount wall (deep clearance)
                           //   "unknown"
  "brand_environment": "", // ONE of: "Nike-only" | "Multi-brand"
                           //         | "Adidas-focused" | "Unknown"
  "confidence": 0.0        // 0.0-1.0 how confident you are overall
}

Rules:
- Base everything on what is visible or audible.
- If nothing is visible/audible, return empty lists and "unknown".
- No commentary, no markdown fences. JSON ONLY.
"""


# ── ffprobe / ffmpeg helpers ──────────────────────────────────────────────────

def _ffprobe_exe() -> str:
    local = os.path.join(_DIR, "ffprobe")
    return local if os.path.exists(local) else "ffprobe"


def _ffmpeg_exe() -> str:
    local = os.path.join(_DIR, "ffmpeg")
    return local if os.path.exists(local) else "ffmpeg"


def _duration_sec(path: str) -> float:
    """Return clip duration in seconds, or 0.0 on failure."""
    try:
        out = subprocess.check_output(
            [_ffprobe_exe(), "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            stderr=subprocess.DEVNULL, timeout=10,
        )
        return float(json.loads(out).get("format", {}).get("duration", 0.0))
    except Exception:
        return 0.0


def _build_anchor_proxy(src_path: str, dst_path: str,
                        duration_sec: int = ANCHOR_CLIP_DURATION_SEC) -> bool:
    """
    Build a tiny 640px/CRF28/no-audio proxy for venue scan only.
    Returns True on success, False otherwise.
    """
    cmd = [
        _ffmpeg_exe(),
        "-y", "-loglevel", "error",
        "-i", src_path,
        "-t", str(duration_sec),
        "-vf", "scale=640:-2",
        "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
        "-an",
        dst_path,
    ]
    try:
        subprocess.check_call(cmd, stderr=subprocess.DEVNULL, timeout=120)
        return os.path.isfile(dst_path) and os.path.getsize(dst_path) > 0
    except Exception as e:
        print(f"  [anchor] ffmpeg failed on {os.path.basename(src_path)}: {e}")
        return False


# ── Sampling ──────────────────────────────────────────────────────────────────

def _sample_clips(folder: str, k: int = DEFAULT_SAMPLE_SIZE) -> list[str]:
    """
    Pick K clips most likely to carry venue cues.

    Heuristic: longest-duration clips (wide / static framing tends to be
    longer than fast-cut shoe close-ups), then even temporal spacing
    across the remainder so we don't sample from a single moment.
    """
    candidates = [
        os.path.join(folder, f) for f in sorted(os.listdir(folder))
        if not f.startswith(".")
        and Path(f).suffix.lower() in VIDEO_EXTS
        and os.path.isfile(os.path.join(folder, f))
    ]
    if not candidates:
        return []
    if len(candidates) <= k:
        return candidates

    # Score each clip: duration weight + position spread
    durations = [(c, _duration_sec(c)) for c in candidates]
    # Top-half by duration
    durations.sort(key=lambda x: x[1], reverse=True)
    pool = [c for c, _ in durations[: max(k * 3, len(durations) // 2)]]

    # Even-spaced pick from pool (preserves file order, not duration order)
    pool.sort(key=lambda p: candidates.index(p))
    step = max(1, len(pool) // k)
    picks = pool[::step][:k]
    return picks


# ── Gemini anchor call ────────────────────────────────────────────────────────

def _call_anchor_gemini(proxy_path: str) -> dict:
    """
    Send one anchor proxy to Gemini, return parsed JSON dict or {} on failure.
    Reuses the auth/config logic from gemini_pipeline.
    """
    try:
        from gemini_pipeline import (
            _USE_VERTEX, _VERTEX_MODEL_NAME, _GEMINI_MODEL_NAME,
            _retry, _parse_response, genai, _gemini_key,
        )
    except ImportError as e:
        print(f"  [anchor] gemini_pipeline import failed: {e}")
        return {}

    if _USE_VERTEX:
        try:
            from vertexai.generative_models import GenerativeModel, Part
            with open(proxy_path, "rb") as f:
                video_bytes = f.read()
            video_part = Part.from_data(data=video_bytes, mime_type="video/mp4")

            def _call():
                model = GenerativeModel(_VERTEX_MODEL_NAME)
                resp  = model.generate_content(
                    [video_part, _ANCHOR_PROMPT],
                    generation_config={"response_mime_type": "application/json"},
                )
                return resp.text
            return _parse_anchor_response(_retry(_call))
        except Exception as e:
            print(f"  [anchor] vertex error: {e}")
            return {}

    if genai is not None and _gemini_key:
        try:
            def _upload():
                vf = genai.upload_file(path=proxy_path)
                for _ in range(60):
                    if vf.state.name == "ACTIVE":
                        break
                    if vf.state.name == "FAILED":
                        raise ValueError(f"upload failed: {proxy_path}")
                    time.sleep(2)
                    vf = genai.get_file(vf.name)
                return vf

            video_file = _retry(_upload)

            def _infer():
                model = genai.GenerativeModel(_GEMINI_MODEL_NAME)
                resp  = model.generate_content(
                    [video_file, _ANCHOR_PROMPT],
                    request_options={"timeout": 90},
                )
                return resp.text

            raw = _retry(_infer)
            try:
                genai.delete_file(video_file.name)
            except Exception:
                pass
            return _parse_anchor_response(raw)
        except Exception as e:
            print(f"  [anchor] gemini error: {e}")
            return {}

    print("  [anchor] no Gemini backend configured")
    return {}


def _parse_anchor_response(raw: str) -> dict:
    """Strip markdown fences and parse anchor-scan JSON."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        d = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}

    def _list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []
    def _str(v):
        return str(v).strip() if v not in (None, "", "null") else ""
    def _flt(v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    return {
        "store_signage":     _list(d.get("store_signage")),
        "brand_logos":       _list(d.get("brand_logos")),
        "shelf_layout":      _str(d.get("shelf_layout")) or "unknown",
        "brand_environment": _str(d.get("brand_environment")) or "Unknown",
        "confidence":        _flt(d.get("confidence")),
    }


# ── Signage → loc_code lookup ─────────────────────────────────────────────────

def _signage_to_loc_code(signage: list[str]) -> str:
    """
    Map free-text store-signage strings to a SACC loc_code via LOCATION_DB
    name matching. Returns "" if no match.

    Match strategy: case-insensitive substring on the LOCATION_DB name and
    on the loc_code itself. First match wins.
    """
    if not signage:
        return ""
    sig_text = " | ".join(s.lower() for s in signage)
    # First try direct name substring matches
    for code, info in LOCATION_DB.items():
        name = info.get("name", "").lower()
        if name and name in sig_text:
            return code
        # Try without parenthetical suffix
        bare = re.sub(r"\s*\(.*\)\s*$", "", name).strip()
        if bare and bare in sig_text:
            return code
    # Then loc_code match (rare but possible — "NC192" appearing in signage text)
    for code in LOCATION_DB:
        if code.lower() in sig_text:
            return code
    return ""


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(samples: list[dict]) -> dict:
    """
    Aggregate K anchor results into a single venue verdict.

    Precedence:
      1. Any sample with signage match AND confidence >= MIN_SIGNAGE_CONFIDENCE
      2. Majority shelf_layout + brand_environment → VENUE_FINGERPRINTS lookup
      3. ("", confidence=0.0) — caller falls back to --loc override
    """
    if not samples:
        return {"loc_code": "", "method": "no_samples", "confidence": 0.0,
                "signage": [], "shelf_layout": "unknown",
                "brand_environment": "Unknown"}

    # 1. Signage-driven match — strongest signal
    for s in samples:
        if s.get("confidence", 0.0) >= MIN_SIGNAGE_CONFIDENCE:
            code = _signage_to_loc_code(s.get("store_signage", []))
            if code:
                return {
                    "loc_code":          code,
                    "method":            "signage",
                    "confidence":        s["confidence"],
                    "signage":           s.get("store_signage", []),
                    "shelf_layout":      s.get("shelf_layout", "unknown"),
                    "brand_environment": s.get("brand_environment", "Unknown"),
                }

    # 2. Fingerprint vote — count layout/env pairs
    pairs = {}
    for s in samples:
        key = (s.get("shelf_layout", "unknown"),
               s.get("brand_environment", "Unknown"))
        pairs[key] = pairs.get(key, 0) + s.get("confidence", 0.0)
    if pairs:
        (layout, env), score = max(pairs.items(), key=lambda kv: kv[1])
        candidates = VENUE_FINGERPRINTS.get((layout, env), [])
        if candidates:
            return {
                "loc_code":          candidates[0],   # first candidate is most-specific
                "method":            "fingerprint",
                "confidence":        round(score / len(samples), 3),
                "signage":           [],
                "shelf_layout":      layout,
                "brand_environment": env,
                "fingerprint_candidates": candidates,
            }

    # 3. No verdict
    return {
        "loc_code":          "",
        "method":            "no_match",
        "confidence":        0.0,
        "signage":           sum((s.get("store_signage", []) for s in samples), []),
        "shelf_layout":      samples[0].get("shelf_layout", "unknown"),
        "brand_environment": samples[0].get("brand_environment", "Unknown"),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def scan_folder_anchor(folder: str, sample_size: int = DEFAULT_SAMPLE_SIZE,
                       force: bool = False) -> dict:
    """
    Resolve the venue (loc_code) for an entire folder of clips.

    Args:
        folder       : absolute path to the folder containing raw video files.
        sample_size  : how many clips to sample for the anchor scan.
        force        : if True, ignore cached _anchor.json and re-run.

    Returns dict shape (also written to <folder>/_anchor.json):
      {
        "loc_code":          "NC192",
        "method":            "signage" | "fingerprint" | "no_match",
        "confidence":        0.0-1.0,
        "signage":           [...],
        "shelf_layout":      "...",
        "brand_environment": "...",
        "samples":           [ { "file": "...", ...sample fields }, ... ],
        "scanned_at":        "ISO-8601",
        "sample_size":       N
      }
    """
    cache_path = os.path.join(folder, ANCHOR_RESULT_FILE)
    if not force and os.path.isfile(cache_path):
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            print(f"  [anchor] cached result reused → loc_code={cached.get('loc_code') or 'UNKNOWN'}")
            return cached
        except Exception:
            pass    # fall through to fresh scan

    print(f"\n[STAGE 2] Venue Anchor Scan — sampling up to {sample_size} clip(s)")
    picks = _sample_clips(folder, k=sample_size)
    if not picks:
        print("  [anchor] no clips found — skipping.")
        return {"loc_code": "", "method": "no_clips", "confidence": 0.0}

    print(f"  [anchor] {len(picks)} clip(s) selected:")
    for p in picks:
        print(f"    • {os.path.basename(p)}")

    # Build temp anchor proxies
    proxy_dir = os.path.join(folder, ANCHOR_PROXY_DIR)
    os.makedirs(proxy_dir, exist_ok=True)

    samples = []
    try:
        for i, src in enumerate(picks, 1):
            stem  = Path(src).stem
            proxy = os.path.join(proxy_dir, f"{stem}.mp4")
            print(f"  [{i}/{len(picks)}] proxy → {os.path.basename(proxy)}")
            if not _build_anchor_proxy(src, proxy):
                print(f"    skipped (ffmpeg failure)")
                continue

            parsed = _call_anchor_gemini(proxy)
            if not parsed:
                print(f"    skipped (no gemini response)")
                continue
            parsed["file"] = os.path.basename(src)
            samples.append(parsed)
            print(f"    signage={parsed['store_signage']}  layout={parsed['shelf_layout']}  "
                  f"env={parsed['brand_environment']}  conf={parsed['confidence']}")

    finally:
        # Always clean the temp proxies — they are not archival assets
        try:
            for f in os.listdir(proxy_dir):
                os.unlink(os.path.join(proxy_dir, f))
            os.rmdir(proxy_dir)
        except Exception:
            pass

    verdict = _aggregate(samples)
    verdict["samples"]     = samples
    verdict["scanned_at"]  = datetime.now(timezone.utc).isoformat()
    verdict["sample_size"] = len(samples)

    try:
        with open(cache_path, "w") as f:
            json.dump(verdict, f, indent=2)
    except Exception as e:
        print(f"  [anchor] WARNING — could not write {cache_path}: {e}")

    code = verdict.get("loc_code") or "UNKNOWN"
    method = verdict.get("method", "?")
    conf = verdict.get("confidence", 0.0)
    print(f"  [anchor] VERDICT → loc_code={code}  method={method}  confidence={conf}")
    return verdict


# ── CLI test harness ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python venue_anchor.py <folder> [sample_size] [--force]")
        sys.exit(1)

    folder      = sys.argv[1]
    sample_size = DEFAULT_SAMPLE_SIZE
    force       = False
    for arg in sys.argv[2:]:
        if arg == "--force":
            force = True
        elif arg.isdigit():
            sample_size = int(arg)

    result = scan_folder_anchor(folder, sample_size=sample_size, force=force)
    print("\n── Verdict ──")
    print(json.dumps(result, indent=2))
