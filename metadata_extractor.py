"""
metadata_extractor.py — SACC Video Metadata + GPS Location Engine
=================================================================
Stage 0 of the SACC pipeline (runs before any AI calls).

Responsibilities
----------------
  1. Extract GPS coordinates embedded in video file metadata
     (QuickTime ISO6709 tag — written by iPhone, GoPro, DJI, etc.)
  2. Map GPS coordinates to a SACC location code using Haversine
     geofencing against the Florida retail network centroids
  3. Extract shoot timestamp from original creation_time metadata

This module replaces Gemini's visual/audio location detection for clips
that contain GPS data.  For clips without GPS (Sony, DSLR, etc.), the
pipeline falls back to manual --loc flag or remains UNKNOWN.

GPS Centroid Data
-----------------
Each location entry includes:
  lat, lon    — approximate centroid of the retail complex
  radius_m    — geofence radius in metres (parking lot + building)

GPS accuracy from iPhone video: ±5–15m (excellent).
The radius_m values are intentionally generous to cover car park edges
and multi-building outlet complexes.

Usage (standalone test)
-----------------------
  python metadata_extractor.py /path/to/video.mov
  python metadata_extractor.py /Volumes/Team Bank 12/SACC/Inbox/IMG_3439.mov
"""

import os
import re
import json
import math
import subprocess
from pathlib import Path

_DIR = os.path.dirname(os.path.abspath(__file__))

# ── GPS centroids — Florida retail network ────────────────────────────────────
#
# lat/lon = approximate geographic centroid of the retail complex.
# radius_m = geofence radius.  Outlet malls get larger radii (spread-out
# buildings + large car parks).  Street-front locations get smaller radii.
#
GPS_CENTROIDS: dict[str, dict] = {
    # ── Orlando metro ─────────────────────────────────────────────────────────
    "FLM":   {"lat": 28.4441, "lon": -81.4259, "radius_m": 600,
              "name": "The Florida Mall"},
    "MAM":   {"lat": 28.5012, "lon": -81.4361, "radius_m": 500,
              "name": "Mall at Millenia"},
    "OFS":   {"lat": 28.5614, "lon": -81.3534, "radius_m": 450,
              "name": "Orlando Fashion Square"},
    "WOM":   {"lat": 28.5406, "lon": -81.5342, "radius_m": 450,
              "name": "West Oaks Mall"},
    "VLD":   {"lat": 28.3695, "lon": -81.4980, "radius_m": 800,
              "name": "Vineland Premium Outlets"},
    "IDR":   {"lat": 28.4565, "lon": -81.4671, "radius_m": 400,
              "name": "International Drive"},
    "LBV":   {"lat": 28.3853, "lon": -81.5194, "radius_m": 700,
              "name": "Lake Buena Vista Factory Stores"},
    "WFL":   {"lat": 28.5608, "lon": -81.1811, "radius_m": 500,
              "name": "Waterford Lakes Town Center"},
    "WGN":   {"lat": 28.5389, "lon": -81.5911, "radius_m": 500,
              "name": "Winter Garden Village"},
    "OMP":   {"lat": 28.4300, "lon": -81.4200, "radius_m": 400,
              "name": "Orlando Marketplace"},
    "SEM":   {"lat": 28.7897, "lon": -81.3534, "radius_m": 500,
              "name": "Seminole Towne Center"},
    # ── Central Florida (other) ───────────────────────────────────────────────
    "LKL":   {"lat": 28.0837, "lon": -81.9626, "radius_m": 500,
              "name": "Lakeland Square Mall"},
    "PDM":   {"lat": 29.1872, "lon": -82.1338, "radius_m": 500,
              "name": "Paddock Mall (Ocala)"},
    "CEL-K": {"lat": 28.3011, "lon": -81.5390, "radius_m": 500,
              "name": "Celebration (Kissimmee)"},
    "KSM":   {"lat": 28.2619, "lon": -81.3950, "radius_m": 400,
              "name": "Kissimmee (Osceola Pkwy)"},
    # ── Tampa Bay area ────────────────────────────────────────────────────────
    "BTC":   {"lat": 27.9370, "lon": -82.3090, "radius_m": 500,
              "name": "Brandon Exchange (Brandon Town Center)"},
    "INP":   {"lat": 27.9514, "lon": -82.5219, "radius_m": 550,
              "name": "International Plaza (Tampa)"},
    "UNM":   {"lat": 28.0621, "lon": -82.4046, "radius_m": 450,
              "name": "University Mall (Tampa)"},
    "TPA":   {"lat": 28.1766, "lon": -82.6547, "radius_m": 800,
              "name": "Tampa Premium Outlets"},
    "HVP":   {"lat": 27.9392, "lon": -82.4665, "radius_m": 300,
              "name": "Hyde Park Village (Tampa)"},
    # ── North Florida ─────────────────────────────────────────────────────────
    "THL":   {"lat": 30.4833, "lon": -84.3001, "radius_m": 500,
              "name": "Tallahassee Mall"},
    "GVA":   {"lat": 29.6285, "lon": -82.4020, "radius_m": 500,
              "name": "Gainesville (Celebration Pointe)"},
    # ── South Florida ─────────────────────────────────────────────────────────
    "AVE":   {"lat": 25.9576, "lon": -80.1430, "radius_m": 600,
              "name": "Aventura Mall"},
    "LCN":   {"lat": 25.7906, "lon": -80.1374, "radius_m": 350,
              "name": "Lincoln Road (Miami Beach)"},
    "DOL":   {"lat": 25.7625, "lon": -80.4229, "radius_m": 700,
              "name": "Dolphin Mall (Miami)"},
}


# ── Haversine distance ────────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in metres between two GPS points."""
    R = 6_371_000  # Earth radius in metres
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── GPS parsing ───────────────────────────────────────────────────────────────

def parse_iso6709(raw: str):  # -> tuple[float, float] | None
    """
    Parse an ISO 6709 location string into (lat, lon).

    iPhone QuickTime format examples:
      "+28.5383-081.3792+051.062/"   → (28.5383, -81.3792)
      "+28.5383-081.3792/"           → (28.5383, -81.3792)
      "+2832.298-08122.752/"         → parsed from DDMM.MMM notation

    Returns (lat, lon) as floats, or None on parse failure.
    """
    if not raw:
        return None
    raw = raw.strip().rstrip("/")

    # Pattern: ±DD.DDDD±DDD.DDDD (decimal degrees — most common from iPhone)
    m = re.match(
        r"^([+-]\d{1,3}\.\d+)"   # latitude  e.g. +28.5383
        r"([+-]\d{1,3}\.\d+)"   # longitude e.g. -081.3792
        r"(?:[+-]\d+\.?\d*)?$", # altitude  (optional)
        raw,
    )
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass

    # Pattern: ±DDMM.MMM±DDDMM.MMM (degrees + decimal minutes)
    m = re.match(
        r"^([+-])(\d{2})(\d{2}\.\d+)"   # lat: sign, DD, MM.MMM
        r"([+-])(\d{3})(\d{2}\.\d+)",   # lon: sign, DDD, MM.MMM
        raw,
    )
    if m:
        try:
            lat_sign = 1 if m.group(1) == "+" else -1
            lat = lat_sign * (float(m.group(2)) + float(m.group(3)) / 60)
            lon_sign = 1 if m.group(4) == "+" else -1
            lon = lon_sign * (float(m.group(5)) + float(m.group(6)) / 60)
            return lat, lon
        except ValueError:
            pass

    return None


# ── ffprobe GPS extraction ────────────────────────────────────────────────────

def _ffprobe_exe() -> str:
    local = os.path.join(_DIR, "ffprobe")
    return local if os.path.exists(local) else "ffprobe"


def extract_gps(video_path: str):  # -> dict | None
    """
    Run ffprobe on *video_path* and extract GPS coordinates.

    Returns a dict on success:
      {
        "lat":    float,       # decimal degrees, positive = North
        "lon":    float,       # decimal degrees, negative = West
        "raw":    str,         # raw ISO6709 string from metadata
        "source": str,         # which metadata tag was used
      }

    Returns None if no GPS data is found or ffprobe fails.
    """
    try:
        cmd = [
            _ffprobe_exe(),
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]
        raw_bytes = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=15)
        data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            json.JSONDecodeError, FileNotFoundError):
        return None

    # Collect all tags from format + streams
    tags: dict = {}
    for src in [data.get("format", {})] + data.get("streams", []):
        tags.update(src.get("tags", {}))

    # Priority order — most specific / accurate first
    gps_tag_candidates = [
        ("com.apple.quicktime.location.ISO6709", "apple_quicktime"),
        ("location",                              "location_generic"),
        ("Location",                              "location_generic"),
        ("GPS",                                   "gps_generic"),
        ("com.apple.quicktime.location",          "apple_location"),
    ]

    for tag_key, source_label in gps_tag_candidates:
        raw = tags.get(tag_key, "")
        if not raw:
            continue
        coords = parse_iso6709(raw)
        if coords:
            lat, lon = coords
            return {"lat": lat, "lon": lon, "raw": raw, "source": source_label}

    return None


# ── Geofencing ────────────────────────────────────────────────────────────────

def gps_to_loc_code(lat: float, lon: float):  # -> dict | None
    """
    Map GPS coordinates to the nearest SACC location code.

    Returns a dict when a match is found within radius:
      {
        "loc_code":    str,    # e.g. "FLM"
        "loc_name":    str,    # e.g. "The Florida Mall"
        "distance_m":  float,  # metres from centroid
        "confidence":  str,    # "high" | "medium" | "low"
      }

    Returns None if no SACC location is within its geofence radius.

    Confidence bands:
      high   — within 33% of radius  (clearly inside the complex)
      medium — within 66% of radius  (on-site, possibly parking)
      low    — within 100% of radius (edge of geofence)
    """
    best_loc  = None
    best_dist = float("inf")

    for code, entry in GPS_CENTROIDS.items():
        d = haversine_m(lat, lon, entry["lat"], entry["lon"])
        if d <= entry["radius_m"] and d < best_dist:
            best_dist = d
            best_loc  = (code, entry, d)

    if best_loc is None:
        return None

    code, entry, dist = best_loc
    radius = entry["radius_m"]
    if dist <= radius * 0.33:
        confidence = "high"
    elif dist <= radius * 0.66:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "loc_code":   code,
        "loc_name":   entry["name"],
        "distance_m": round(dist, 1),
        "confidence": confidence,
    }


# ── Full extraction pipeline ──────────────────────────────────────────────────

def extract_location(video_path: str):  # -> dict
    """
    Full pipeline: extract GPS from video → map to SACC location code.

    Always returns a dict:
      On success:
        {
          "loc_code":     str,      # e.g. "FLM"
          "loc_name":     str,
          "gps_lat":      float,
          "gps_lon":      float,
          "gps_source":   str,      # which metadata tag
          "distance_m":   float,
          "loc_confidence": str,    # "high" | "medium" | "low"
          "loc_source":   "gps",
        }
      On GPS miss (no coordinates in file):
        {"loc_source": "none", "gps_miss_reason": "no_gps_tag"}

      On geofence miss (has GPS but not near any SACC location):
        {
          "gps_lat": ..., "gps_lon": ..., "gps_source": ...,
          "loc_source": "none",
          "gps_miss_reason": "outside_geofence",
        }
    """
    gps = extract_gps(video_path)
    if gps is None:
        return {"loc_source": "none", "gps_miss_reason": "no_gps_tag"}

    match = gps_to_loc_code(gps["lat"], gps["lon"])
    if match is None:
        return {
            "gps_lat":          gps["lat"],
            "gps_lon":          gps["lon"],
            "gps_source":       gps["source"],
            "gps_raw":          gps["raw"],
            "loc_source":       "none",
            "gps_miss_reason":  "outside_geofence",
        }

    return {
        "loc_code":       match["loc_code"],
        "loc_name":       match["loc_name"],
        "gps_lat":        gps["lat"],
        "gps_lon":        gps["lon"],
        "gps_source":     gps["source"],
        "gps_raw":        gps["raw"],
        "distance_m":     match["distance_m"],
        "loc_confidence": match["confidence"],
        "loc_source":     "gps",
    }


def extract_locations_batch(video_paths: list) -> dict:
    """
    Run extract_location() on a list of video files.

    Returns a dict keyed by file path:
      {
        "/path/to/file.mov": { ...extract_location result... },
        ...
      }

    Also prints a per-file summary to stdout.
    """
    results = {}
    hits = 0
    print(f"\n[meta] GPS extraction — {len(video_paths)} file(s)")
    for path in video_paths:
        name   = os.path.basename(path)
        result = extract_location(path)
        results[path] = result
        if result.get("loc_code"):
            hits += 1
            print(f"  ✓ GPS  {name:<45}  {result['loc_code']} "
                  f"({result['loc_confidence']}, {result['distance_m']}m)")
        else:
            reason = result.get("gps_miss_reason", "unknown")
            print(f"  – miss {name:<45}  ({reason})")
    print(f"  [meta] GPS hit rate: {hits}/{len(video_paths)} "
          f"({round(100*hits/max(len(video_paths),1))}%)\n")
    return results


def dominant_loc_code(results: dict, min_confidence: str = "medium"):
    """
    Given a batch result dict, return the most common loc_code among
    GPS hits with at least *min_confidence*.

    Use this to infer the session location from a set of clips where
    some devices (Sony, GoPro) don't embed GPS — if 3 of 5 iPhone clips
    agree on FLM, the whole session is FLM.

    Returns (loc_code, count) or (None, 0).
    """
    conf_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank  = conf_rank.get(min_confidence, 2)
    counts: dict = {}
    for v in results.values():
        if v.get("loc_source") == "gps" and v.get("loc_code"):
            if conf_rank.get(v.get("loc_confidence", "low"), 0) >= min_rank:
                counts[v["loc_code"]] = counts.get(v["loc_code"], 0) + 1
    if not counts:
        return None, 0
    best = max(counts, key=lambda k: counts[k])
    return best, counts[best]


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python metadata_extractor.py <video_file_or_folder>")
        print("\nKnown SACC locations and their centroids:")
        for code, entry in GPS_CENTROIDS.items():
            print(f"  {code:<8}  {entry['lat']:>9.4f}, {entry['lon']:>10.4f}  "
                  f"r={entry['radius_m']}m  {entry['name']}")
        sys.exit(0)

    target = sys.argv[1]

    if os.path.isfile(target):
        print(f"\n[meta] Analyzing: {target}")
        result = extract_location(target)
        print(json.dumps(result, indent=2))

    elif os.path.isdir(target):
        VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mxf", ".avi", ".mkv"}
        files = sorted([
            os.path.join(target, f)
            for f in os.listdir(target)
            if Path(f).suffix.lower() in VIDEO_EXTS
            and not f.startswith(".")
        ])
        if not files:
            print(f"No video files found in {target}")
            sys.exit(1)
        batch = extract_locations_batch(files)
        loc, count = dominant_loc_code(batch)
        if loc:
            print(f"[meta] Dominant location: {loc}  ({count}/{len(files)} clips agree)")
        else:
            print("[meta] No dominant GPS location found — use --loc flag at pipeline launch")

    else:
        print(f"Path not found: {target}")
        sys.exit(1)
