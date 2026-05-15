"""
sacc_pipeline.py — SACC Full Pipeline Orchestrator
====================================================
Pipeline sequence (strict order — do not reorder):

  STAGE 1 ── FCP Inspector rename    (manual, done before consolidation)
  STAGE 2 ── FCP consolidation       (FCP drops files into Inbox/)
  STAGE 3 ── Batch rename            → two modes:
             [classic]  run_vibe_renamer()     --loc + --id  required
             [fcp]      run_fcp_renamer()      --fcp flag    GPS auto-detect
             Establishes the permanent SACC filename as the relational key.
             ALL downstream assets inherit this name.
  STAGE 4 ── Folder organisation     → move renamed files to /SACC/YYYY/YYYYMMDD/
  STAGE 5 ── Pre-Flight gate         → ffprobe checks duration + motion
  STAGE 6 ── Proxy compression       → run_compression()
             Creates low-bitrate _proxy/<same_filename>.mp4
             Proxy inherits the EXACT renamed source filename.
  STAGE 7 ── Wait for proxies        → wait_for_proxies()
  STAGE 8 ── Vertex AI / Gemini      → analyze_sneaker_video()
             JSON output keyed by original_file (relational key to hi-res master).
  STAGE 9 ── Proxy cleanup           → cleanup_proxies()
             _proxy/ directory deleted. Proxies are transient assets.
  STAGE 10 ─ JSON index              → permanent record lives in /json/
             JSON stem == source filename stem → points back to hi-res master.

Naming contract — FCP mode (GPS auto-detect, recommended)
----------------------------------------------------------
  [Custom Name]   = GPS geofence → location shorthand  e.g. PDM-MALL
  [Date]          = YYYYMMDD (from original shoot metadata)
  [Model Name]    = camera device                       e.g. iPhone15ProMax
  [Original Name] = source filename stem                e.g. IMG_3439

  Source  : /2026/20241221/PDM-MALL_20241221_iPhone15ProMax_IMG_3439.mov
  Proxy   : /2026/20241221/_proxy/PDM-MALL_20241221_iPhone15ProMax_IMG_3439.mp4
  JSON    : /2026/20241221/json/PDM-MALL_20241221_iPhone15ProMax_IMG_3439.json
            └── "original_file": "PDM-MALL_...IMG_3439.mov"  ← permanent relational key

Naming contract — Classic mode (manual loc + id)
-------------------------------------------------
  Source  : /2026/260423/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.mov

Usage (FCP mode — GPS auto-detect):
  python sacc_pipeline.py --fcp \\
                          --inbox "/Volumes/Team Bank 12/SACC/Inbox" \\
                          --root  "/Volumes/Team Bank 12/SACC"

Usage (Classic mode — manual identifier):
  python sacc_pipeline.py --inbox "/Volumes/Team Bank 12/SACC/Inbox" \\
                          --root  "/Volumes/Team Bank 12/SACC"       \\
                          --loc   FLM                                  \\
                          --id    "Air Jordan 1 Chicago"

  python sacc_pipeline.py --dry-run  (preview only)
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Local imports ─────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from renamer_logic      import run_vibe_renamer, extract_metadata
from compress_jordans   import run_compression, wait_for_proxies, cleanup_proxies
from gemini_pipeline    import analyze_sneaker_video
from fcp_namer          import run_fcp_renamer, LOCATION_DB
from metadata_extractor import extract_locations_batch, dominant_loc_code
from venue_anchor       import scan_folder_anchor

# ── Constants ─────────────────────────────────────────────────────────────────
SYNOLOGY_ROOT = os.getenv("SACC_ROOT",  "/Volumes/Team Bank 12/SACC")
INBOX_PATH    = os.getenv("SACC_INBOX", os.path.join(SYNOLOGY_ROOT, "Inbox"))
VIDEO_EXTS    = {".mov", ".mp4", ".m4v"}

# Pre-Flight thresholds (Stage 3 — Pre-Flight 2.0)
MIN_DURATION_SECS    = 2          # clips shorter than this are too brief to analyse
MIN_FPS              = 1          # framerate sanity — 0 means broken stream
MIN_BITRATE_PER_PX   = 0.02       # bits per pixel-second; below this is likely a frozen / black clip
                                  # (1080p @ 30fps with 0.02 bpps ≈ 1.2 Mbps — anything lower is static-ish)


# ── Folder helpers ────────────────────────────────────────────────────────────

def dated_folder(root, date_str):
    """
    Returns (and creates) /root/YYYY/DATE_STR/ and the json/ subfolder.

    Accepts both FCP-mode YYYYMMDD (e.g. "20241221") and classic YYMMDD
    (e.g. "241221").  The parent YYYY directory is always derived correctly.
    """
    if len(date_str) == 8:          # YYYYMMDD → FCP mode
        year = date_str[:4]
    else:                            # YYMMDD   → classic mode
        year = "20" + date_str[:2]
    path = os.path.join(root, year, date_str)
    os.makedirs(os.path.join(path, "json"), exist_ok=True)
    return path


def inbox_files(inbox):
    """Flat list of video files directly inside inbox/."""
    if not os.path.isdir(inbox):
        return []
    return [
        os.path.join(inbox, f)
        for f in sorted(os.listdir(inbox))
        if not f.startswith(".") and Path(f).suffix.lower() in VIDEO_EXTS
        and os.path.isfile(os.path.join(inbox, f))
    ]


def resolve_inbox_folders(inbox):
    """
    Return the list of folders the pipeline should process.

    Flat inbox  → [inbox]
    FCP library → [inbox/Final Cut Original Media/YYYY-MM-DD, ...]  (one per date folder)

    An FCP library is detected when the inbox contains no direct video files
    but has a 'Final Cut Original Media/' subdirectory with dated subfolders.
    """
    if not os.path.isdir(inbox):
        return []

    if inbox_files(inbox):
        return [inbox]

    fcpom = os.path.join(inbox, "Final Cut Original Media")
    if os.path.isdir(fcpom):
        date_folders = sorted([
            os.path.join(fcpom, d)
            for d in os.listdir(fcpom)
            if not d.startswith(".") and os.path.isdir(os.path.join(fcpom, d))
        ])
        if date_folders:
            total = sum(len(inbox_files(d)) for d in date_folders)
            print(f"[pipeline] FCP library detected — {total} file(s) across "
                  f"{len(date_folders)} date folder(s) in 'Final Cut Original Media/'")
            return date_folders

    return []


# ── Pre-Flight gate ───────────────────────────────────────────────────────────

def preflight_check(file_path):
    """
    Stage 3 — Pre-Flight 2.0.

    Returns (pass: bool, reasons: list[str]).

    Checks:
      1. Duration >= MIN_DURATION_SECS
      2. Framerate >= MIN_FPS  (sanity — broken streams report 0)
      3. Bits-per-pixel-second >= MIN_BITRATE_PER_PX
         (cheap static-content proxy: encoders compress frozen footage
         aggressively, so very low bpps almost always means no motion)

    Note on motion detection: previous implementation called
    nb_read_frames / duration which (a) was effectively framerate, not
    motion, and (b) needed -count_frames to even populate. Bitrate-per-px
    catches the actual failure mode (frozen / black / sticker-only clips)
    without an extra ffprobe pass.
    """
    ffprobe = os.path.join(_DIR, "ffprobe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"

    cmd = [ffprobe, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", file_path]
    try:
        data     = json.loads(subprocess.check_output(cmd, stderr=subprocess.DEVNULL))
        fmt      = data.get("format", {}) or {}
        duration = float(fmt.get("duration", 0) or 0)
        if duration < MIN_DURATION_SECS:
            return False, [f"duration {duration:.1f}s < {MIN_DURATION_SECS}s minimum"]

        streams  = data.get("streams", []) or []
        vid      = next((s for s in streams if s.get("codec_type") == "video"), {}) or {}

        # Framerate sanity (avg_frame_rate is a fraction like "30000/1001")
        afr = (vid.get("avg_frame_rate") or vid.get("r_frame_rate") or "0/1")
        try:
            num, den = afr.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0
        if fps < MIN_FPS:
            return False, [f"framerate {fps:.1f} < {MIN_FPS} — broken or static stream"]

        # Static-content proxy via bits per pixel-second
        bitrate = float(fmt.get("bit_rate", 0) or 0)
        width   = int(vid.get("width",  0) or 0)
        height  = int(vid.get("height", 0) or 0)
        if width and height and bitrate:
            bpps = bitrate / (width * height * max(fps, 1))
            if bpps < MIN_BITRATE_PER_PX:
                return False, [f"bits/px·s {bpps:.4f} < {MIN_BITRATE_PER_PX} — "
                               f"likely frozen / static content"]

        return True, []
    except Exception as e:
        # ffprobe failure is non-blocking — pass the file through
        print(f"  [preflight] ffprobe error on {os.path.basename(file_path)}: {e}")
        return True, []


def _already_analysed(dest_dir: str, original_file: str) -> bool:
    """
    Stage 1 — Idempotency guard.

    Returns True if a completed JSON already exists for `original_file` in
    <dest_dir>/json/. "Completed" means: file exists, parseable, has a
    non-null `analysed_at` timestamp, and no top-level `error` field.

    Used by stage_vertex() to skip clips that have already been processed
    in a prior run. Protects against re-burning Gemini quota on resume.
    """
    if not original_file:
        return False
    stem      = Path(original_file).stem
    json_path = os.path.join(dest_dir, "json", f"{stem}.json")
    if not os.path.isfile(json_path):
        return False
    try:
        with open(json_path) as f:
            d = json.load(f)
    except Exception:
        return False
    return bool(d.get("analysed_at")) and "error" not in d


# ── Pipeline stages ───────────────────────────────────────────────────────────

def stage_gps_extract(files: list) -> str:
    """
    STAGE 0 — Extract GPS coordinates from video metadata and resolve the
    dominant retail location for this recording session.

    Uses metadata_extractor.py which reads ISO6709 GPS data embedded by
    iPhones in QuickTime atoms (com.apple.quicktime.location.ISO6709).

    Strategy:
      • Run GPS extraction on all files in the batch simultaneously.
      • iPhone clips with GPS coordinates are geofenced to a SACC loc_code.
      • dominant_loc_code() propagates the winning location to the full
        session — covers Sony/DJI cameras that don't embed GPS.

    Returns the winning loc_code string (e.g. "VLD") or "" on total miss.
    """
    if not files:
        return ""

    print(f"\n[STAGE 0] GPS extraction — {len(files)} file(s)")
    gps_results = extract_locations_batch(files)

    hits  = [r for r in gps_results.values() if r.get("loc_code")]
    total = len(gps_results)
    print(f"  GPS hits: {len(hits)}/{total} file(s) resolved")

    loc, _ = dominant_loc_code(gps_results)

    if loc:
        print(f"  Session location → {loc}  "
              f"(propagated to all {total} file(s))")
    else:
        print("  No GPS fix — location will fall back to --loc flag or remain UNKNOWN")

    return loc or ""


def stage_rename_fcp(inbox, loc_override=None):
    """
    STAGE 3 (FCP mode) — GPS-aware batch rename using fcp_namer.

    Token map:
      [Custom Name]   = GPS geofence → LOC-TYPE shorthand (e.g. PDM-MALL)
      [Date]          = YYYYMMDD from original shoot metadata
      [Model Name]    = camera device (e.g. iPhone15ProMax, SonyA7IV)
      [Original Name] = original filename stem

    GPS from iPhone clips propagates to non-GPS devices (Sony, DJI, GoPro)
    within the same recording session (SESSION_WINDOW_HOURS).

    loc_override bypasses GPS lookup — useful when Inbox has no iPhone clips.
    Returns list of new absolute paths.
    """
    print(f"\n[STAGE 3] FCP rename — GPS auto-detect"
          + (f"  loc_override={loc_override}" if loc_override else ""))

    renamed = []
    for result in run_fcp_renamer(inbox, loc_override=loc_override, dry_run=False):
        if result.get("error") and not result.get("done"):
            print(f"  [fcp] ERROR: {result['error']}")
            return []
        if result.get("done"):
            print(f"  [fcp] Done — {result['renamed']} file(s) renamed, "
                  f"{result['skipped']} skipped")
            break
        if result.get("status") in ("renamed", "skipped"):
            new_name = result.get("new") or result.get("original")
            renamed.append(os.path.join(inbox, new_name))

    return renamed


def stage_rename(inbox, loc_code, identifier):
    """
    STAGE 3 — Batch rename all files in Inbox.
    This establishes the permanent SACC filename that all downstream
    assets (proxy, JSON) will inherit as the relational key.
    Returns list of new absolute paths.
    """
    print(f"\n[STAGE 3] Batch rename — loc={loc_code}  id='{identifier}'")
    renamed = []
    for result in run_vibe_renamer(inbox, loc_code, identifier):
        if result.get("error"):
            print(f"  [rename] ERROR: {result['error']}")
            return []
        if not result.get("done"):
            orig = result.get("original", "")
            new  = result.get("new", "")
            print(f"  [rename] {result['current']}/{result['total']}  {orig} → {new}")
            renamed.append(os.path.join(inbox, new))
    print(f"  [rename] Done — {len(renamed)} file(s) renamed")
    return renamed


def stage_organise(inbox, root, files):
    """
    STAGE 4 — Move renamed files from Inbox → /root/YYYY/DATE_STR/.
    Supports both FCP-mode YYYYMMDD and classic YYMMDD date strings.
    Date is read directly from the file's metadata via extract_metadata().
    Returns dict: original_path → destination_path.
    """
    print(f"\n[STAGE 4] Organising files into dated folders under {root}")
    moved = {}
    for fp in files:
        raw_date, _ = extract_metadata(fp)
        # FCP mode produces YYYYMMDD; classic produces YYMMDD — dated_folder handles both
        dest_dir    = dated_folder(root, raw_date)
        dest_path   = os.path.join(dest_dir, os.path.basename(fp))
        if os.path.exists(dest_path):
            print(f"  [organise] Already exists — skipping: {os.path.basename(fp)}")
        else:
            shutil.move(fp, dest_path)
            print(f"  [organise] {os.path.basename(fp)} → {dest_dir}/")
        moved[fp] = dest_path
    return moved


def stage_preflight(files):
    """
    STAGE 5 — Filter clips that would waste Compressor / API quota.
    Returns (approved, skipped) path lists.
    """
    print(f"\n[STAGE 5] Pre-Flight — checking {len(files)} file(s)")
    approved, skipped = [], []
    for fp in files:
        ok, reasons = preflight_check(fp)
        tag = "✓ PASS" if ok else "⚠ SKIP"
        detail = "" if ok else f" — {', '.join(reasons)}"
        print(f"  {tag}  {os.path.basename(fp)}{detail}")
        (approved if ok else skipped).append(fp)
    print(f"  Pre-Flight: {len(approved)} approved, {len(skipped)} skipped")
    return approved, skipped


def stage_compress(dest_dir):
    """
    STAGE 6 + 7 — Queue Apple Compressor proxy jobs and wait.

    Proxy naming rule enforced here:
      proxy stem == source stem (same filename, forced .mp4 extension)
    Returns list of result dicts from compress_jordans.run_compression().
    """
    json_dir = os.path.join(dest_dir, "json")
    print(f"\n[STAGE 6] Queuing proxy jobs — source: {dest_dir}")

    results = run_compression(dest_dir, json_folder=json_dir)
    if not results:
        print("  [compress] Nothing to compress.")
        return []

    # Surface summary
    for r in results:
        print(f"  [{r['status'].upper():10}] {r['original_file']}")

    print(f"\n[STAGE 7] Waiting for Compressor to finish…")
    results = wait_for_proxies(results, timeout=3600, poll_interval=15)
    return results


def stage_vertex(compress_results, dest_dir):
    """
    STAGE 8 — Route proxies to Vertex AI via the logic router, then enrich
    each result with KicksDB product metadata (Stage 8b).

    The router automatically selects:
      < 50 files  → standard per-file API (immediate)
      >= 50 files → Vertex AI Batch Prediction (async, 50% cheaper)

    Gemini outputs: SKU, Is_Hash_Wall, Price_Observed, Price_Audio,
    Price_Type, Price_Retail, drop_events.  Location is resolved upstream
    at Stage 0 (GPS) and written into the filename — not extracted here.

    After Gemini, each SKU is sent to KicksDB (Stage 8b) to append:
      Model, colorway, release_date, MSRP (kdb_* keys + top-level promotion).
    KicksDB enrichment is a no-op if KICKSDB_API_KEY is not set.

    JSON written per file uses the ORIGINAL renamed filename as stem
    (permanent relational key back to the hi-res master).

    Returns list of paths to written JSON files.
    """
    from gemini_pipeline import route_analysis, BATCH_THRESHOLD
    from kicksdb_enricher import enrich_result as kdb_enrich, cache_stats as kdb_cache_stats
    import os as _os
    _kdb_enabled = bool(_os.getenv("KICKSDB_API_KEY"))

    json_dir = os.path.join(dest_dir, "json")
    os.makedirs(json_dir, exist_ok=True)

    ready = [r for r in compress_results
             if r["status"] in ("ready", "exists") and r.get("proxy_path")]

    if not ready:
        print("\n[STAGE 8] No proxies ready — skipping Vertex AI analysis.")
        return []

    # ── Stage 1 idempotency: skip clips with a completed JSON on disk ────────
    pending, skipped_idem = [], []
    for r in ready:
        if _already_analysed(dest_dir, r.get("original_file", "")):
            skipped_idem.append(r)
        else:
            pending.append(r)
    if skipped_idem:
        print(f"\n[STAGE 8] Idempotency: {len(skipped_idem)} clip(s) already analysed — skipping.")
        for r in skipped_idem[:5]:
            print(f"    • {Path(r['original_file']).stem}.json present")
        if len(skipped_idem) > 5:
            print(f"    … and {len(skipped_idem) - 5} more")
    ready = pending

    if not ready:
        print("\n[STAGE 8] All proxies already analysed — nothing to do.")
        return []

    n = len(ready)
    mode = "Batch API (async)" if n >= BATCH_THRESHOLD else "Standard API"
    print(f"\n[STAGE 8] Vertex AI analysis — {n} proxy file(s) via {mode}")

    # Build the input structures the router expects
    proxy_files  = [r["proxy_path"] for r in ready]
    original_map = {
        r["proxy_path"]: (r["original_file"], r["original_path"])
        for r in ready
    }

    results = route_analysis(proxy_files, original_map)

    # ── Load anchor verdict for Stage 9 cross-check ──────────────────────────
    anchor = _load_anchor(dest_dir)
    if anchor:
        print(f"  [stage9] anchor: loc={anchor.get('loc_code') or 'UNKNOWN'} "
              f"env={anchor.get('brand_environment','Unknown')} "
              f"conf={anchor.get('confidence',0.0)}")

    # ── Write JSON files + print summary ─────────────────────────────────────
    saved = []
    kdb_hits  = 0
    conflicts = 0
    reviews   = 0
    for result in results:
        if result.get("error"):
            print(f"  [vertex] ERROR: {result['error']}")
            continue

        # ── Stage 7: KicksDB enrichment with v2.1 ↔ legacy bridging ──────
        sku = result.get("sku_visible") or ""
        if _kdb_enabled and sku:
            _kdb_bridge_in(result)
            result = kdb_enrich(result)
            if result.get("kdb_verified"):
                kdb_hits += 1
            _kdb_bridge_out(result)

        # ── Stage 9: Cross-check + v2.1 metadata ─────────────────────────
        _apply_v21_metadata_and_conflicts(result, anchor)
        if result.get("conflict_detected"):
            conflicts += 1
        if result.get("needs_review"):
            reviews += 1

        original_file = result.get("original_file", "")
        json_stem     = Path(original_file).stem
        json_path     = os.path.join(json_dir, f"{json_stem}.json")

        with open(json_path, "w") as f:
            json.dump(result, f, indent=2)

        kdb_tag     = f"  kdb={'✓' if result.get('kdb_verified') else '✗'}" if _kdb_enabled else ""
        hw_tag      = "  🔴hash_wall" if result.get("is_hash_wall") else ""
        discount    = result.get("hash_wall_discount_pct")
        hw_discount = f"(-{discount}%)" if discount else ""
        conf_tag    = "  ⚠CONFLICT" if result.get("conflict_detected") else ""
        rev_tag     = "  👁review"   if result.get("needs_review") and not result.get("conflict_detected") else ""
        print(f"  ✓  {json_stem}.json  "
              f"sku={sku or '—'}  hint={result.get('product_hint') or '—'}"
              + kdb_tag + hw_tag + hw_discount + conf_tag + rev_tag)
        saved.append(json_path)

    if conflicts or reviews:
        print(f"  [stage9] {conflicts} conflict(s), {reviews} flagged for review")

    if _kdb_enabled:
        stats = kdb_cache_stats()
        print(f"  [kicksdb] {kdb_hits}/{n} enriched  "
              f"(cache: {stats['cached']} SKUs, {stats['hits']} hits, {stats['misses']} misses)")
    print(f"  [vertex] {len(saved)}/{n} JSON file(s) written → {json_dir}")

    # ── Stage 10 hint ─────────────────────────────────────────────────────────
    unknown_with_loc = sum(
        1 for jp in saved
        if os.path.basename(jp).startswith("UNKNOWN")
        and _json_has_loc(jp)
    )
    if unknown_with_loc:
        print(f"\n  [vertex] {unknown_with_loc} UNKNOWN file(s) have confirmed "
              f"locations — Stage 10 will rename them automatically.")

    return saved


def _json_has_loc(json_path):
    try:
        with open(json_path) as fh:
            return bool(json.load(fh).get("loc_code_confirmed"))
    except Exception:
        return False


# ── Stage 9 helpers — Logic Cross-Check ───────────────────────────────────────

# SKU prefix → expected brand. Used by Stage 9 to flag clips whose SKU brand
# disagrees with the anchor scan's brand_environment. Ordered most-specific
# first; the bare 6-char form (e.g. "BB7822", "AT5386") is ambiguous between
# Nike and Adidas in isolation, so we lean toward Adidas because the bare
# unhyphenated short form is far more common for Adidas in modern catalogs.
# False positives get caught by the human reviewer; we'd rather flag than miss.
_SKU_BRAND_PATTERNS = [
    # (regex, brand) — first match wins
    (r"^[A-Z]{2}\d{4}-\d{3}$",     "Nike"),     # AH8462-400, DZ4549-400 (definitive)
    (r"^\d{6}-\d{3}$",             "Nike"),     # 555088-101, 378037-116 (definitive)
    (r"^[A-Z]\d{5}$",              "Adidas"),   # B27871, B37520 (definitive)
    (r"^FZ\d{4}",                  "Adidas"),   # Yeezy line
    (r"^[A-Z]{2}\d{4}$",           "Adidas"),   # BB7822 — ambiguous; lean Adidas
]


def _brand_from_sku(sku: str) -> str:
    """Infer brand from SKU format. Returns '' if no pattern matches."""
    if not sku:
        return ""
    import re as _re
    for pattern, brand in _SKU_BRAND_PATTERNS:
        if _re.match(pattern, sku):
            return brand
    return ""


def _load_anchor(dest_dir: str) -> dict:
    """Read <dest_dir>/_anchor.json from Stage 2. Returns {} if absent."""
    p = os.path.join(dest_dir, "_anchor.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _kdb_bridge_in(result: dict) -> None:
    """
    Stage 7 bridge — populate legacy keys that kicksdb_enricher reads,
    using the v2.1 snake_case keys from Gemini. Mutates in place.
    """
    if "SKU" not in result and result.get("sku_visible"):
        result["SKU"] = result["sku_visible"]
    if "Is_Hash_Wall" not in result:
        result["Is_Hash_Wall"] = bool(result.get("is_hash_wall"))
    if "Price_Observed" not in result and result.get("price_observed"):
        result["Price_Observed"] = result["price_observed"]
    if "Price_Audio" not in result and result.get("price_audio"):
        result["Price_Audio"] = result["price_audio"]


def _kdb_bridge_out(result: dict) -> None:
    """
    Stage 7 bridge — promote KicksDB's authoritative legacy keys back into
    the v2.1 schema (only when the v2.1 field is empty — Gemini's direct
    observation, if any, wins over KicksDB's canonical for hint/colorway).
    Cleans up the legacy aliases at the end.
    """
    if not result.get("product_hint") and result.get("Model"):
        result["product_hint"] = result["Model"]
    if not result.get("colorway_dominant") and result.get("colorway"):
        result["colorway_dominant"] = result["colorway"]
    # KicksDB MSRP is authoritative for price_retail (Gemini's read of the
    # tag may be wrong; the catalog MSRP is the ground truth).
    if result.get("Price_Retail"):
        result["price_retail"] = result["Price_Retail"]
    # Strip the legacy aliases — keep the JSON in v2.1 shape
    for k in ("SKU", "Is_Hash_Wall", "Price_Observed", "Price_Audio",
              "Price_Retail", "Model", "colorway"):
        result.pop(k, None)


def _apply_v21_metadata_and_conflicts(result: dict, anchor: dict) -> dict:
    """
    Stage 9 — Logic Cross-Check.

    Mutates `result` (a Gemini-parsed dict) in place to:
      1. Inject loc_code_anchor from the folder's anchor verdict.
      2. Compare visible_brands + SKU-prefix-derived brand against the
         anchor's brand_environment. Flag conflict_detected = True on
         a real mismatch (e.g. Adidas SKU at an Nike-only anchor).
      3. Set needs_review = True if conflict_detected OR no SKU OR
         low-confidence anchor.

    Returns the same dict (in-place + returned for chaining).
    """
    anchor_loc   = anchor.get("loc_code", "") or ""
    anchor_env   = anchor.get("brand_environment", "Unknown") or "Unknown"
    anchor_conf  = float(anchor.get("confidence", 0.0) or 0.0)

    result.setdefault("loc_code_anchor", anchor_loc)

    # ── Brand evidence: union of Gemini's visible_brands + SKU-inferred brand
    visible_brands = list(result.get("visible_brands") or [])
    sku_brand      = _brand_from_sku(result.get("sku_visible") or "")
    if sku_brand and sku_brand not in visible_brands:
        visible_brands.append(sku_brand)

    conflict = False
    conflict_reasons: list[str] = []

    if anchor_env == "Nike-only":
        wrong = [b for b in visible_brands if b not in ("Nike", "Jordan", "Converse")]
        if wrong:
            conflict = True
            conflict_reasons.append(f"non-Nike brand {wrong} at Nike-only anchor")
    elif anchor_env == "Adidas-focused":
        wrong = [b for b in visible_brands if b == "Nike"]
        if wrong:
            conflict = True
            conflict_reasons.append(f"Nike brand at Adidas-focused anchor")
    # Multi-brand / Unknown: no conflict possible from brand evidence alone

    result["conflict_detected"] = conflict
    needs_review = (
        conflict
        or anchor_conf < 0.5
        or not result.get("sku_visible")
    )
    result["needs_review"] = bool(needs_review)
    if conflict_reasons:
        result.setdefault("warnings", []).extend(conflict_reasons)

    return result


def stage_proxy_cleanup(dest_dir, json_paths):
    """
    STAGE 9 — Delete _proxy/ after all JSON files are confirmed written.
    Marks proxy_deleted=True in each JSON to record lifecycle completion.
    """
    print(f"\n[STAGE 9] Proxy cleanup")

    # Mark proxy_deleted=True in every JSON written this run
    for jp in json_paths:
        try:
            with open(jp) as f:
                data = json.load(f)
            data["proxy_deleted"] = True
            with open(jp, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"  [cleanup] Could not update {os.path.basename(jp)}: {e}")

    count = cleanup_proxies(dest_dir)
    if count == 0:
        print("  [cleanup] No proxy files to delete.")


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_pipeline(inbox, root, loc_code, identifier,
                 dry_run=False, fcp_mode=False, no_move=False):
    """
    Full SACC pipeline — enforces rename-first, proxy-same-name, proxy-delete.

    Args:
        inbox      : Inbox watch folder (FCP consolidation target)
        root       : SACC root on Synology (/Volumes/Team Bank 12/SACC)
        loc_code   : Location code — used in classic mode, or as GPS fallback
                     in fcp_mode when no iPhone GPS is available in the batch
        identifier : Shoe identifier string — classic mode only
        dry_run    : Print plan only — no renames, moves, compressions, or API calls
        fcp_mode   : Use GPS-aware FCP naming engine (recommended)
                     Token map: [Custom Name]_[Date]_[Model Name]_[Original Name]
        no_move    : Skip Stage 4 — originals renamed in place, _proxy/ and json/
                     written alongside them. Use for FCP library sources where
                     relocating originals would break media links.
    """
    start = time.time()
    mode_label = "FCP (GPS auto-detect)" if fcp_mode else "Classic (manual --loc/--id)"
    print("=" * 60)
    print("SACC Pipeline — Starting")
    print(f"  Inbox      : {inbox}")
    print(f"  Root       : {root}")
    print(f"  Mode       : {mode_label}")
    if not fcp_mode:
        print(f"  Location   : {loc_code}")
        print(f"  Identifier : {identifier}")
    else:
        if loc_code:
            print(f"  GPS fallback loc : {loc_code}")
    print(f"  Dry run    : {dry_run}")
    print(f"  No-move    : {no_move}")
    print("=" * 60)

    # Resolve which folders actually contain videos.
    # For FCP libraries this expands to individual date subfolders.
    effective_inboxes = resolve_inbox_folders(inbox)
    if not effective_inboxes:
        print("[pipeline] Inbox is empty — nothing to process.")
        return

    total_files = sum(len(inbox_files(d)) for d in effective_inboxes)
    print(f"[pipeline] {total_files} file(s) found across {len(effective_inboxes)} folder(s)")

    if dry_run:
        for eff_inbox in effective_inboxes:
            files = inbox_files(eff_inbox)
            if fcp_mode:
                for _ in run_fcp_renamer(eff_inbox, loc_override=loc_code or None,
                                         dry_run=True):
                    pass
            else:
                for f in files:
                    print(f"  DRY-RUN: would process {os.path.basename(f)}")
        return

    # ── Per-folder processing ─────────────────────────────────────────────────
    all_dest_dirs: dict[str, list] = {}

    for eff_inbox in effective_inboxes:
        files = inbox_files(eff_inbox)
        if not files:
            continue

        # ── STAGE 0: GPS extraction — resolve session location from metadata ──
        # Run on raw (pre-rename) files so we can derive the loc_code before
        # the filename is locked in at Stage 3.
        if fcp_mode:
            gps_loc = stage_gps_extract(files)

            # ── STAGE 2: Venue Anchor Scan ────────────────────────────────────
            # When GPS misses (typical for archival / non-iPhone footage),
            # sample a few clips and ask Gemini what store environment is
            # visible. Result drives the rename's loc_code, so the venue
            # is baked into the filename from the start.
            anchor_loc = ""
            if not gps_loc:
                anchor_verdict = scan_folder_anchor(eff_inbox)
                anchor_loc = anchor_verdict.get("loc_code", "")

            # Precedence: explicit --loc > GPS > Anchor > UNKNOWN
            effective_loc = loc_code or gps_loc or anchor_loc
            if effective_loc:
                source = ("manual override" if effective_loc == loc_code and loc_code
                          else "GPS" if effective_loc == gps_loc and gps_loc
                          else "anchor scan")
                print(f"  Resolved loc_code → {effective_loc}  (source: {source})")
        else:
            effective_loc = loc_code

        # ── STAGE 3: Rename first — establishes permanent relational key ──────
        if fcp_mode:
            renamed = stage_rename_fcp(eff_inbox, loc_override=effective_loc or None)
        else:
            renamed = stage_rename(eff_inbox, loc_code, identifier)

        if not renamed:
            print(f"[pipeline] Rename stage failed for {eff_inbox} — skipping.")
            continue

        # ── STAGE 4: Organise into dated folders (skipped in no-move mode) ──────
        if no_move:
            print(f"\n[STAGE 4] Skipped (--no-move) — originals stay in {eff_inbox}")
            for fp in renamed:
                all_dest_dirs.setdefault(os.path.dirname(fp), []).append(fp)
        else:
            moved = stage_organise(eff_inbox, root, renamed)
            for fp in moved.values():
                all_dest_dirs.setdefault(os.path.dirname(fp), []).append(fp)

    if not all_dest_dirs:
        print("[pipeline] No files organised — aborting.")
        return

    for dest_dir, batch in all_dest_dirs.items():
        print(f"\n── Batch: {dest_dir}  ({len(batch)} file(s)) ──")

        # ── STAGE 5: Pre-Flight ───────────────────────────────────────────────
        approved, skipped = stage_preflight(batch)
        if skipped:
            log_path = os.path.join(dest_dir, "preflight_skipped.json")
            with open(log_path, "w") as f:
                json.dump([os.path.basename(s) for s in skipped], f, indent=2)
            print(f"  Skipped files logged → {log_path}")

        if not approved:
            print("  No files passed Pre-Flight — skipping compression and API stages.")
            continue

        # ── STAGES 6+7: Compress → proxy inherits renamed filename ────────────
        compress_results = stage_compress(dest_dir)
        if not compress_results:
            print("  No proxies ready — skipping API stage.")
            continue

        # ── STAGE 8: Vertex AI → JSON keyed by original_file ─────────────────
        #   Gemini outputs SKU + pricing + drop events.
        #   Location is in the filename already (from Stage 0 GPS).
        #   Stage 8b (KicksDB) appends Model, colorway, MSRP, release_date.
        json_paths = stage_vertex(compress_results, dest_dir)

        # ── STAGE 9: Delete proxies — they are transient assets ───────────────
        if json_paths:
            stage_proxy_cleanup(dest_dir, json_paths)
        else:
            print("  No JSON written — proxies NOT deleted (safe to retry).")

        # NOTE: legacy Stage 10 (apply_confirmed_locations) removed in the v2.1
        # rewrite. Venue resolution now happens upstream at Stage 2 (anchor
        # scan), so loc_code is baked into the filename before rename.
        # Gemini no longer outputs `loc_code_confirmed`, so the old loop was
        # a dead-letter check that ran on every batch and confirmed nothing.

    elapsed = round(time.time() - start, 1)
    print(f"\n{'=' * 60}")
    print(f"SACC Pipeline — Complete in {elapsed}s")
    print(f"{'=' * 60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SACC Pipeline — rename → compress → Vertex AI → JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # FCP mode — GPS auto-detect (recommended)
  python sacc_pipeline.py --fcp --inbox "/Volumes/Team Bank 12/SACC/Inbox" \\
                          --root "/Volumes/Team Bank 12/SACC"

  # FCP dry-run
  python sacc_pipeline.py --fcp --dry-run

  # Classic mode — manual loc + id
  python sacc_pipeline.py --inbox "/Volumes/Team Bank 12/SACC/Inbox" \\
                          --root  "/Volumes/Team Bank 12/SACC"       \\
                          --loc   FLM --id "Air Jordan 1 Chicago"
        """
    )
    parser.add_argument("--inbox",   default=INBOX_PATH,    help="Inbox watch folder")
    parser.add_argument("--root",    default=SYNOLOGY_ROOT, help="SACC root on Synology")
    parser.add_argument("--fcp",     action="store_true",
                        help="FCP mode: GPS geofence auto-detects location token. "
                             "Propagates to non-GPS devices in same session.")
    parser.add_argument("--loc",     default="",
                        help="Classic mode: location code e.g. FLM. "
                             "FCP mode: GPS fallback when no iPhone clips present.")
    parser.add_argument("--id",      default="",
                        help="Classic mode: shoe identifier (e.g. 'Air Jordan 1 Chicago')")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no changes")
    parser.add_argument("--no-move",  action="store_true",
                        help="Skip Stage 4 — originals renamed in place, "
                             "_proxy/ and json/ written alongside them. "
                             "Use for FCP library sources.")
    args = parser.parse_args()

    # Validation
    if not args.fcp:
        if not args.id and not args.dry_run:
            print("ERROR: --id is required in classic mode  "
                  "(e.g. --id 'Air Jordan 1 Chicago')")
            print("       Use --fcp for GPS auto-detect mode.")
            sys.exit(1)
        if not args.loc:
            print("ERROR: --loc is required in classic mode  (e.g. --loc FLM)")
            sys.exit(1)

    run_pipeline(
        inbox      = args.inbox,
        root       = args.root,
        loc_code   = args.loc,
        identifier = args.id,
        dry_run    = args.dry_run,
        fcp_mode   = args.fcp,
        no_move    = args.no_move,
    )
