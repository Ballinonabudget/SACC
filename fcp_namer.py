"""
fcp_namer.py — SACC FCP Naming Preset Engine
=============================================
Replicates Final Cut Pro's "Naming Preset" token system so that physical
filenames stay in sync with FCP library metadata.

Token map
---------
  [Custom Name]   ← Manual --loc flag  OR  AI-confirmed post-Stage 8
                    (GPS geofencing was rescinded — coordinate inaccuracy)
  [Date]          ← File creation_time → YYYYMMDD (original shoot date)
  [Model Name]    ← Device metadata   → CamModel (e.g. iPhone15ProMax)
  [Original Name] ← Source filename   → Original stem (e.g. IMG_3439)

Output template
---------------
  [Custom Name]_[Date]_[Model Name]_[Original Name].[ext]

  Examples:
    PDM-MALL_20241221_iPhone15ProMax_IMG_3439.mov    ← loc confirmed at Stage 3
    UNKNOWN_20241221_iPhone15ProMax_IMG_3439.mov     ← loc deferred to Stage 8 AI

[Custom Name] determination
----------------------------
GPS geofencing was removed due to coordinate inaccuracy.  Location is now
resolved by ONE of two methods — in priority order:

  1. Manual override (--loc flag)
     Pass a loc_code at pipeline launch. Suitable when the operator knows
     the shoot location. Immediately usable at Stage 3 rename.

  2. AI visual + audio analysis (Stage 8 — Gemini / Vertex AI)
     The Gemini prompt reads store signage, storefronts, mall directories,
     Nike branding, and audio transcript to identify the retail location.
     The resolved loc_code is written into the JSON output.

     When Stage 3 runs WITHOUT a --loc, filenames use 'UNKNOWN' as the
     [Custom Name] placeholder.  After Stage 8, run:

       python fcp_namer.py --apply-loc --folder <dest_dir>

     This reads each file's companion JSON, looks up 'loc_code_confirmed',
     and renames both the source file and its JSON to the final name.

Session grouping
----------------
Files are grouped into recording sessions by creation_time proximity
(SESSION_WINDOW_HOURS).  This preserves multi-camera session context
and is used for future AI-assisted cross-device propagation.

Location database
-----------------
LOCATION_DB maps loc_codes to display names and store types.
GPS centroid fields have been removed.  The database is still used for:
  - Converting loc_code → [Custom Name] header (e.g. PDM → PDM-MALL)
  - Validating loc_code values at CLI / pipeline entry
  - Powering the SCAA search/filter UI

Usage (CLI)
-----------
  # Dry-run — show what would be renamed (loc required for non-UNKNOWN output)
  python fcp_namer.py --folder "/Volumes/Team Bank 12/SACC/Inbox" --loc PDM --dry-run

  # Apply renames (Stage 3)
  python fcp_namer.py --folder "/Volumes/Team Bank 12/SACC/Inbox" --loc PDM --apply

  # Post-Stage-8: apply AI-confirmed locations from companion JSON files
  python fcp_namer.py --apply-loc --folder "/Volumes/Team Bank 12/SACC/2024/20241221"

Usage (library — Stage 3)
--------------------------
  from fcp_namer import run_fcp_renamer
  for result in run_fcp_renamer(folder, loc_override="PDM", dry_run=False):
      print(result)

Usage (library — Stage 10 post-rename)
---------------------------------------
  from fcp_namer import apply_confirmed_locations
  renamed = apply_confirmed_locations(dest_dir)
"""

from __future__ import annotations

import os
import re
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

# ── Constants ─────────────────────────────────────────────────────────────────

VIDEO_EXTS           = {".mov", ".mp4", ".m4v", ".mxf", ".avi", ".mkv"}
SESSION_WINDOW_HOURS = 4       # hours — max gap between clips in same session
DATE_FMT             = "%Y%m%d"

_UNKNOWN_LOC = "UNKNOWN"       # placeholder when no loc_code is available at rename time

# DJI Pocket 3 native stem: DJI_YYYYMMDDHHMMSS_NNNN_D[_...]
_DJI_STEM_PAT = re.compile(r'^DJI_\d{14}_(\d{4}.*)$', re.IGNORECASE)

def _normalize_cam_stem(stem: str) -> str:
    """Collapse DJI_YYYYMMDDHHMMSS_NNNN… → DJI3_NNNN… in original stems."""
    m = _DJI_STEM_PAT.match(stem)
    return f"DJI3_{m.group(1)}" if m else stem

# ── Location database (name + type only — GPS centroids removed) ──────────────
#
# GPS geofencing was rescinded (2026-04-23) due to coordinate inaccuracy.
# [Custom Name] is now determined by manual --loc flag or AI visual/audio
# analysis (Stage 8 Gemini prompt).
#
# This dict is still the authoritative source for:
#   - loc_code → [Custom Name] header  (e.g. "PDM" → "PDM-MALL")
#   - CLI / pipeline input validation
#   - SCAA search + filter UI population
#
LOCATION_DB: dict[str, dict] = {
    "FLM":   {"name": "The Florida Mall",                 "type": "MALL", "region": "Orlando"},
    "MAM":   {"name": "Mall at Millenia",                 "type": "MALL", "region": "Orlando"},
    "OFS":   {"name": "Orlando Fashion Square",           "type": "MALL", "region": "Orlando"},
    "WOM":   {"name": "West Oaks Mall",                   "type": "MALL", "region": "Orlando"},
    "VLD":   {"name": "Vineland Premium Outlets",         "type": "NFS",  "region": "Orlando"},
    "IDR":   {"name": "International Drive",              "type": "NFS",  "region": "Orlando"},
    "LBV":   {"name": "Lake Buena Vista",                 "type": "NFS",  "region": "Orlando"},
    "WFL":   {"name": "Waterford Lakes",                  "type": "MALL", "region": "Orlando"},
    "WGN":   {"name": "Winter Garden Village",            "type": "MALL", "region": "Orlando"},
    "OMP":   {"name": "Orlando Marketplace (I-Drive)",    "type": "NCS",  "region": "Orlando"},
    "SEM":   {"name": "Seminole Towne Center",            "type": "MALL", "region": "Sanford"},
    "LKL":   {"name": "Lakeland Square Mall",             "type": "MALL", "region": "Lakeland"},
    "PDM":   {"name": "Paddock Mall",                     "type": "MALL", "region": "Ocala"},
    "THL":   {"name": "Tallahassee Mall",                 "type": "MALL", "region": "Tallahassee"},
    "BTC":   {"name": "Brandon Exchange (Brandon Town Center)",  "type": "MALL", "region": "Tampa"},
    "INP":   {"name": "International Plaza",              "type": "MALL", "region": "Tampa"},
    "UNM":   {"name": "University Mall",                  "type": "MALL", "region": "Tampa"},
    "TPA":   {"name": "Tampa Premium Outlets",            "type": "NFS",  "region": "Tampa"},
    "HVP":   {"name": "Hyde Park Village",                "type": "NIKE", "region": "Tampa"},
    "AVE":   {"name": "Aventura Mall",                    "type": "NIKE", "region": "Miami"},
    "LCN":   {"name": "Lincoln Road",                     "type": "NIKE", "region": "Miami"},
    "DOL":   {"name": "Dolphin Mall",                     "type": "NFS",  "region": "Miami"},
    "GVA":   {"name": "Gainesville (Celebration Pointe)", "type": "NFS",  "region": "Gainesville"},
    "CEL-K": {"name": "Celebration (Kissimmee)",          "type": "NFS",  "region": "Kissimmee"},
    "KSM":   {"name": "Kissimmee (Osceola Pkwy)",         "type": "NCS",  "region": "Kissimmee"},
    "NC192": {"name": "Nike Clearance Store 192 (US-192, defunct, pre-Loop)", "type": "NCS", "region": "Kissimmee"},
    "NCLP":  {"name": "Nike Clearance Store at the Loop",                     "type": "NCS", "region": "Kissimmee"},
}

_DIR = os.path.dirname(os.path.abspath(__file__))

# Optional runtime extension: location_db.json in SACC root can add new codes
_DB_OVERRIDE = os.path.join(_DIR, "location_db.json")
if os.path.isfile(_DB_OVERRIDE):
    try:
        with open(_DB_OVERRIDE) as _f:
            _overrides = json.load(_f)
        LOCATION_DB.update(_overrides)
    except Exception as _e:
        print(f"[fcp_namer] WARNING — could not load {_DB_OVERRIDE}: {_e}")


# ── Venue fingerprints (shelf_layout, brand_environment) → loc_code candidates ─
# Consumed by venue_anchor.scan_folder_anchor() when no explicit signage match
# is found in the anchor scan. The first candidate in each list is the most
# specific guess; downstream logic may use the rest for ranking or fall-through.
#
# Keep this list small and high-signal. Add a (layout, env) row only when
# the combination is genuinely diagnostic of a known venue.
VENUE_FINGERPRINTS: dict[tuple[str, str], list[str]] = {
    ("multi-rack",  "Nike-only"):       ["NC192", "NCLP", "KSM", "OMP"],   # Nike Clearance family
    ("hash_wall",   "Nike-only"):       ["NC192", "NCLP", "KSM", "OMP"],   # deep-clearance sticker walls
    ("multi-rack",  "Multi-brand"):     ["BTC"],                            # mall multi-brand stores (Footlocker / Champs / Jimmy Jazz)
    ("top-loading", "Multi-brand"):     ["BTC"],
    ("top-loading", "Nike-only"):       ["HVP", "AVE", "LCN"],              # mainline Nike stores (clean shelving)
    ("wall-display","Nike-only"):       ["HVP", "AVE", "LCN"],
    ("wall-display","Multi-brand"):     ["BTC"],
}


# ── Camera hardware timeline ──────────────────────────────────────────────────
# Fallback rules for archival footage that lacks EXIF device tags.
# Each rule: (filename_prefix, start_YYYYMMDD, end_YYYYMMDD, model_name).
# First match wins. Model name follows the "space-stripped" filename convention
# (e.g. "Sony a6300" -> "Sonya6300", matching the iPhone15ProMax pattern).
# Extend this list as confirmed purchase/use dates are established.
CAMERA_TIMELINE: list[tuple[str, str, str, str]] = [
    # Sony a6300 — primary B-roll camera, 2019–2022
    ("C",    "20190101", "20221231", "Sony a6300"),
    # iPhone Pro Max line — handheld/photo b-roll, IMG_-prefixed
    ("IMG_", "20180301", "20190930", "iPhone 8 Plus"),
    ("IMG_", "20191001", "20201130", "iPhone 11 Pro Max"),
    ("IMG_", "20201201", "20211031", "iPhone 12 Pro Max"),
    ("IMG_", "20211101", "20230831", "iPhone 13 Pro Max"),
    ("IMG_", "20230901", "20241130", "iPhone 15 Pro Max"),
    ("IMG_", "20241201", "20991231", "iPhone 16 Pro Max"),
]


def _resolve_camera_from_timeline(filename: str, date_str: str | None) -> str | None:
    """Match filename prefix + shoot date against CAMERA_TIMELINE.
    Returns the model name (with spaces) or None if no rule applies."""
    if not filename or not date_str:
        return None
    for prefix, start, end, model in CAMERA_TIMELINE:
        if filename.startswith(prefix) and start <= date_str <= end:
            return model
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_loc_header(loc_code: str) -> str:
    """Return 'PDM-MALL' style header for a loc_code, or the code itself if unknown."""
    info = LOCATION_DB.get(loc_code)
    if not info:
        return loc_code
    return f"{loc_code}-{info['type']}"


def validate_loc_code(loc_code: str) -> bool:
    return loc_code in LOCATION_DB


_SACC_PREFIX_RE = re.compile(r"^[A-Z0-9]+-[A-Z]+_\d{6,8}_[A-Za-z0-9-]+_")
_SACC_DATECAM_RE = re.compile(r"^\d{6,8}_[A-Za-z0-9-]+_")
_SACC_LOC_ONLY_RE = re.compile(r"^[A-Z0-9]+-[A-Z]+_")


def _strip_sacc_prefix(stem: str) -> str:
    """Remove any existing SACC prefix(es) to recover the original stem.

    Handles three shapes idempotently:
      1. Single-rename : LOC-TYPE_DATE_CAMERA_ORIGSTEM → ORIGSTEM
      2. Doubled       : LOC-TYPE_DATE_CAMERA_DATE_CAMERA_ORIGSTEM → ORIGSTEM
                         (leftover from prior buggy rename runs)
      3. Loc-only      : LOC-TYPE_ORIGSTEM → ORIGSTEM

    Returns the cleanest form by applying strip patterns until no change.
    """
    prev = None
    while prev != stem:
        prev = stem
        # Full SACC prefix (LOC-TYPE_DATE_CAMERA_)
        stem = _SACC_PREFIX_RE.sub("", stem)
        # Leftover date+camera from a doubled rename
        stem = _SACC_DATECAM_RE.sub("", stem)
    # Final fallback: bare LOC-TYPE_ with nothing structured after it
    stem = _SACC_LOC_ONLY_RE.sub("", stem)
    return stem


# ── ffprobe helpers ────────────────────────────────────────────────────────────

def _ffprobe_candidates() -> list[str]:
    local = os.path.join(_DIR, "ffprobe")
    return ([local] if os.path.exists(local) else []) + ["ffprobe"]


def _run_ffprobe(file_path: str) -> dict | None:
    args = ["-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", "-select_streams", "v:0", file_path]
    for exe in _ffprobe_candidates():
        try:
            raw = subprocess.check_output([exe] + args, stderr=subprocess.STDOUT)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            continue
    return None


def _get_tags(data: dict) -> dict:
    tags = {}
    for src in [data.get("format", {}), *(data.get("streams", [{}])[:1])]:
        tags.update(src.get("tags", {}))
    return tags


# ── Clip metadata ─────────────────────────────────────────────────────────────

class ClipMeta:
    """All metadata needed for FCP naming, extracted from one video file."""

    __slots__ = (
        "path", "filename", "stem", "ext",
        "creation_dt",   # datetime | None
        "date_str",      # YYYYMMDD
        "cam_model",     # e.g. "iPhone15ProMax"
        "cam_make",      # e.g. "apple" (lower-cased)
    )

    def __init__(self, file_path: str, ffprobe_data: dict | None):
        self.path     = file_path
        self.filename = os.path.basename(file_path)
        p             = Path(file_path)
        self.stem     = p.stem
        self.ext      = p.suffix.lower()

        self.creation_dt = None
        self.date_str    = None
        self.cam_model   = None
        self.cam_make    = ""

        if ffprobe_data is not None:
            tags = _get_tags(ffprobe_data)

            # ── Creation time — prefer quicktime.creationdate (original shoot date)
            raw_time = (tags.get("com.apple.quicktime.creationdate") or
                        tags.get("creation_time"))
            if raw_time:
                norm = re.sub(r"[Zz]$", "", raw_time.strip())
                norm = re.sub(r"[+-]\d{2}:\d{2}$", "", norm)
                norm = re.sub(r"\.\d+$", "", norm)
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        self.creation_dt = datetime.strptime(norm, fmt)
                        self.date_str    = self.creation_dt.strftime(DATE_FMT)
                        break
                    except ValueError:
                        continue

            # ── Camera make / model
            make  = (tags.get("com.apple.quicktime.make") or tags.get("make") or "").lower()
            model = (tags.get("com.apple.quicktime.model") or
                     tags.get("com.apple.proapps.modelname") or
                     tags.get("model") or "")
            self.cam_make = make
            if model:
                self.cam_model = model.replace(" ", "")

        # ── Date fallback chain: parent folder name → file mtime → today
        if self.date_str is None:
            parent_name = p.parent.name
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", parent_name)
            if m:
                try:
                    self.creation_dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    self.date_str    = self.creation_dt.strftime(DATE_FMT)
                except ValueError:
                    pass
        if self.date_str is None:
            try:
                mtime = os.path.getmtime(file_path)
                self.creation_dt = datetime.fromtimestamp(mtime)
                self.date_str    = self.creation_dt.strftime(DATE_FMT)
            except OSError:
                pass
        if self.date_str is None:
            self.date_str = datetime.now().strftime(DATE_FMT)

        # ── Camera timeline fallback (filename prefix + date range)
        # Use the stripped original stem so the C/IMG_ prefix detection still
        # works on files that have already been SACC-renamed once (otherwise
        # the leading "NC192-NCS_…" would mask the original prefix).
        if self.cam_model is None:
            original_stem = _strip_sacc_prefix(self.stem)
            timeline_model = _resolve_camera_from_timeline(
                original_stem + self.ext, self.date_str
            )
            if timeline_model:
                self.cam_model = timeline_model.replace(" ", "")

        # ── Camera fallback: explicit "Unknown" when no device tags
        if self.cam_model is None:
            self.cam_model = "Unknown"


def extract_clip_meta(file_path: str) -> ClipMeta:
    return ClipMeta(file_path, _run_ffprobe(file_path))


# ── Session grouping ───────────────────────────────────────────────────────────

class RecordingSession:
    """
    A group of clips filmed within SESSION_WINDOW_HOURS of each other.
    Location (loc_code) is set by manual override or AI confirmation —
    not by GPS.
    """
    def __init__(self):
        self.clips:    list[ClipMeta] = []
        self.loc_code: str | None     = None

    def add(self, clip: ClipMeta) -> None:
        self.clips.append(clip)

    def set_location(self, loc_code: str | None) -> None:
        self.loc_code = loc_code


def build_sessions(clips: list[ClipMeta]) -> list[RecordingSession]:
    """Group clips by creation_time proximity into recording sessions."""
    dated   = sorted([c for c in clips if c.creation_dt], key=lambda c: c.creation_dt)
    undated = [c for c in clips if c.creation_dt is None]
    window  = timedelta(hours=SESSION_WINDOW_HOURS)
    sessions: list[RecordingSession] = []

    for clip in dated:
        placed = False
        for sess in reversed(sessions):
            latest = max((c.creation_dt for c in sess.clips if c.creation_dt),
                         default=None)
            if latest and clip.creation_dt - latest <= window:
                sess.add(clip)
                placed = True
                break
        if not placed:
            s = RecordingSession()
            s.add(clip)
            sessions.append(s)

    if undated:
        s = RecordingSession()
        for c in undated:
            s.add(c)
        sessions.append(s)

    return sessions


# ── FCP token builder ─────────────────────────────────────────────────────────

def build_fcp_name(clip: ClipMeta, loc_code: str | None) -> str:
    """
    Assemble the FCP naming preset output:
      [Custom Name]_[Date]_[Model Name]_[Original Name].[ext]

    If loc_code is None or not in LOCATION_DB, uses 'UNKNOWN' as placeholder.
    The AI analysis stage (Stage 8) will confirm the real location and
    apply_confirmed_locations() will rename files at that point.
    """
    if loc_code and loc_code in LOCATION_DB:
        custom_name = get_loc_header(loc_code)
    else:
        custom_name = _UNKNOWN_LOC

    return (f"{custom_name}_{clip.date_str}_{clip.cam_model}"
            f"_{_normalize_cam_stem(_strip_sacc_prefix(clip.stem))}{clip.ext}")


# ── Stage 3 renamer ───────────────────────────────────────────────────────────

def run_fcp_renamer(
    folder: str,
    loc_override: str | None = None,
    dry_run: bool = True,
) -> Iterator[dict]:
    """
    Walk *folder* and rename every video file using the FCP naming preset.

    [Custom Name] comes from loc_override (manual --loc) if provided.
    When loc_override is None, [Custom Name] is set to 'UNKNOWN' — the
    file will be renamed again at Stage 10 once AI analysis confirms
    the location from visual/audio content.

    Yields one dict per file:
    {
        "original"   : str,
        "new"        : str | None,
        "loc_code"   : str | None,
        "loc_source" : "manual" | "unknown",
        "date"       : str,           # YYYYMMDD
        "cam_model"  : str,
        "status"     : "renamed" | "dry" | "skipped" | "error",
        "error"      : str | None,
    }
    Final summary dict: {"done": True, "renamed": n, "skipped": n, "total": n}
    """
    if not os.path.isdir(folder):
        yield {"error": f"Folder not found: {folder}"}
        return

    all_files = sorted([
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if (not f.startswith(".")
            and Path(f).suffix.lower() in VIDEO_EXTS
            and os.path.isfile(os.path.join(folder, f)))
    ])

    if not all_files:
        yield {"error": "No video files found in folder."}
        return

    loc_source = "manual" if loc_override else "unknown"
    loc_label  = loc_override or _UNKNOWN_LOC

    if loc_override and loc_override not in LOCATION_DB:
        yield {"error": f"Unknown location code '{loc_override}'. "
                        f"Valid codes: {sorted(LOCATION_DB.keys())}"}
        return

    print(f"[fcp_namer] Extracting metadata from {len(all_files)} file(s)…")
    clips = [extract_clip_meta(fp) for fp in all_files]
    for c in clips:
        print(f"  {c.filename}  [{c.cam_make or 'unknown'}]  "
              f"date={c.date_str}  model={c.cam_model}")

    sessions = build_sessions(clips)
    for sess in sessions:
        sess.set_location(loc_override)

    path_to_sess = {c.path: sess for sess in sessions for c in sess.clips}

    print(f"\n[fcp_namer] {'DRY RUN — ' if dry_run else ''}"
          f"Renaming {len(clips)} file(s)  "
          f"[Custom Name] = {loc_label}  [{loc_source}]\n")

    renamed_count = 0
    skipped_count = 0

    for clip in clips:
        sess     = path_to_sess[clip.path]
        new_name = build_fcp_name(clip, sess.loc_code)
        new_path = os.path.join(folder, new_name)

        result = {
            "original":   clip.filename,
            "new":        new_name,
            "loc_code":   sess.loc_code,
            "loc_source": loc_source,
            "date":       clip.date_str,
            "cam_model":  clip.cam_model,
            "status":     None,
            "error":      None,
        }

        if new_name == clip.filename:
            print(f"  [SKIP] {clip.filename}  (already correctly named)")
            result["status"] = "skipped"
            skipped_count += 1
            yield result
            continue

        action = "[DRY]" if dry_run else "[RENAME]"
        print(f"  {action}")
        print(f"    FROM : {clip.filename}")
        print(f"    TO   : {new_name}")

        if dry_run:
            result["status"] = "dry"
            renamed_count += 1
        else:
            try:
                if os.path.exists(new_path):
                    print(f"    SKIP : destination already exists")
                    result["status"] = "skipped"
                    skipped_count += 1
                else:
                    os.rename(clip.path, new_path)
                    result["status"] = "renamed"
                    renamed_count += 1
                    print(f"    ✓ Done")
            except Exception as e:
                result["status"] = "error"
                result["error"]  = str(e)
                print(f"    ERROR: {e}")

        yield result

    print(f"\n[fcp_namer] {'DRY RUN ' if dry_run else ''}Complete — "
          f"{renamed_count} file(s) {'would be ' if dry_run else ''}renamed, "
          f"{skipped_count} skipped")
    yield {"done": True, "total": len(clips),
           "renamed": renamed_count, "skipped": skipped_count, "dry_run": dry_run}


# ── Stage 10 — post-AI location confirmation rename ───────────────────────────

def apply_confirmed_locations(dest_dir: str, dry_run: bool = False) -> list[dict]:
    """
    Stage 10 rename: reads companion JSON files in <dest_dir>/json/,
    finds files whose [Custom Name] is 'UNKNOWN', and renames them to the
    AI-confirmed location code (field: 'loc_code_confirmed' in JSON).

    Also renames the JSON file itself to keep stems in sync.

    Returns list of rename dicts:
    {
        "original_video" : str,
        "new_video"      : str,
        "original_json"  : str,
        "new_json"       : str,
        "loc_code"       : str,
        "status"         : "renamed" | "dry" | "skipped" | "error",
    }
    """
    json_dir   = os.path.join(dest_dir, "json")
    results    = []

    if not os.path.isdir(json_dir):
        print(f"[fcp_namer:apply-loc] No json/ dir found at {dest_dir}")
        return results

    json_files = [f for f in os.listdir(json_dir) if f.endswith(".json")]
    if not json_files:
        print(f"[fcp_namer:apply-loc] No JSON files in {json_dir}")
        return results

    print(f"\n[fcp_namer:apply-loc] {'DRY RUN — ' if dry_run else ''}"
          f"Checking {len(json_files)} JSON file(s) for confirmed locations…")

    for jf in sorted(json_files):
        json_path = os.path.join(json_dir, jf)
        try:
            with open(json_path) as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [WARN] Could not read {jf}: {e}")
            continue

        loc_confirmed = data.get("loc_code_confirmed")
        original_file = data.get("original_file", "")

        if not loc_confirmed:
            print(f"  [SKIP] {jf} — no loc_code_confirmed in JSON")
            continue

        if not original_file.startswith(_UNKNOWN_LOC):
            print(f"  [SKIP] {jf} — original_file already has a confirmed location")
            continue

        if loc_confirmed not in LOCATION_DB:
            print(f"  [WARN] {jf} — loc_code_confirmed='{loc_confirmed}' "
                  f"not in LOCATION_DB, skipping")
            continue

        # Build new filenames
        old_stem      = Path(original_file).stem
        ext           = Path(original_file).suffix
        loc_header    = get_loc_header(loc_confirmed)
        # Replace leading UNKNOWN with confirmed loc header
        new_stem      = re.sub(r"^UNKNOWN", loc_header, old_stem)
        new_video     = new_stem + ext
        new_json      = new_stem + ".json"

        video_old_path = os.path.join(dest_dir, original_file)
        video_new_path = os.path.join(dest_dir, new_video)
        json_new_path  = os.path.join(json_dir, new_json)

        entry = {
            "original_video": original_file,
            "new_video":      new_video,
            "original_json":  jf,
            "new_json":       new_json,
            "loc_code":       loc_confirmed,
            "status":         None,
        }

        action = "[DRY]" if dry_run else "[RENAME]"
        print(f"\n  {action}")
        print(f"    VIDEO : {original_file} → {new_video}")
        print(f"    JSON  : {jf} → {new_json}")
        print(f"    LOC   : {loc_confirmed}  (AI visual/audio confirmed)")

        if dry_run:
            entry["status"] = "dry"
        else:
            try:
                # Update JSON internal fields before renaming
                data["original_file"] = new_video
                data["loc_code_applied"] = loc_confirmed
                with open(json_path, "w") as f:
                    json.dump(data, f, indent=2)

                # Rename video
                if os.path.exists(video_old_path):
                    os.rename(video_old_path, video_new_path)
                else:
                    print(f"    WARN: video file not found: {video_old_path}")

                # Rename JSON
                os.rename(json_path, json_new_path)
                entry["status"] = "renamed"
                print(f"    ✓ Done")
            except Exception as e:
                entry["status"] = "error"
                entry["error"]  = str(e)
                print(f"    ERROR: {e}")

        results.append(entry)

    total = len([r for r in results if r["status"] in ("renamed", "dry")])
    print(f"\n[fcp_namer:apply-loc] {total} file(s) "
          f"{'would be ' if dry_run else ''}confirmed\n")
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(
        description="SACC FCP Naming Preset Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  Stage 3 rename (--loc known at shoot time):
    python fcp_namer.py --folder <inbox> --loc PDM --dry-run
    python fcp_namer.py --folder <inbox> --loc PDM --apply

  Stage 3 rename (loc unknown — AI will confirm later):
    python fcp_namer.py --folder <inbox> --dry-run     # outputs UNKNOWN_...
    python fcp_namer.py --folder <inbox> --apply

  Stage 10 post-AI confirmation rename:
    python fcp_namer.py --apply-loc --folder <dest_dir>
    python fcp_namer.py --apply-loc --folder <dest_dir> --dry-run
        """
    )
    parser.add_argument("--folder",    required=True)
    parser.add_argument("--loc",       default=None,
                        help="Location code override (e.g. PDM). "
                             "Omit to defer location to AI analysis.")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--apply",     action="store_true",
                        help="Apply renames (Stage 3)")
    parser.add_argument("--apply-loc", action="store_true",
                        help="Apply AI-confirmed location renames (Stage 10)")
    args = parser.parse_args()

    if args.apply_loc:
        apply_confirmed_locations(args.folder, dry_run=args.dry_run)
    else:
        dry = not args.apply
        results = list(run_fcp_renamer(args.folder, loc_override=args.loc, dry_run=dry))
        if not dry:
            log = [r for r in results if not r.get("done")]
            log_path = os.path.join(args.folder, "sacc_fcp_rename_log.json")
            with open(log_path, "w") as fh:
                json.dump(log, fh, indent=2)
            print(f"  Log → {log_path}")
