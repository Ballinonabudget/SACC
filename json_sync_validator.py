#!/usr/bin/env python3
"""
json_sync_validator.py — SACC JSON Sync Health Check
=====================================================
Run this directly against any SACC output folder to verify JSON database
integrity and video↔JSON pairing status.

Usage
-----
  python3 json_sync_validator.py /Volumes/Team\ Bank\ 12/Sneeaker\ Solo
  python3 json_sync_validator.py /path/to/folder --json-dir custom_json/
  python3 json_sync_validator.py /path/to/folder --full

Checks performed
----------------
  1. Video↔JSON pairing     — every .mov/.mp4/.MP4/.MOV has a companion JSON
  2. Orphan JSON             — JSON files with no matching video
  3. Required field presence — original_file, Model, SKU, analysed_at,
                               proxy_deleted, loc_code_confirmed
  4. UNKNOWN location flag   — files pending Stage 10 location confirmation
  5. Relational key integrity — JSON filename stem matches original_file stem
  6. Proxy cleanup status    — proxy_deleted flag tracking

Output legend
-------------
  ✓  OK
  ✗  Error / missing
  ⚠  Warning / needs attention
  ◉  AI confirmed location
  ●  Manual location
  ○  Unknown / unresolved location
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime

# ── Required JSON fields ───────────────────────────────────────────────────────
REQUIRED_FIELDS = [
    "original_file",
    "analysed_at",
    "proxy_deleted",
    "Model",
    "SKU",
]

# Fields present after Stage 8 location detection
LOCATION_FIELDS = [
    "loc_code_confirmed",
    "Location_Visual",
    "Location_Audio",
    "Location_Confidence",
]

VIDEO_EXTS = {".mov", ".mp4", ".MOV", ".MP4", ".mts", ".MTS", ".avi", ".AVI"}

# ── ANSI colour helpers ────────────────────────────────────────────────────────
_RESET = "\033[0m"
_GREEN = "\033[32m"
_RED   = "\033[31m"
_AMBER = "\033[33m"
_GREY  = "\033[90m"
_BOLD  = "\033[1m"
_CYAN  = "\033[36m"

def _c(text, colour): return f"{colour}{text}{_RESET}"
def ok(t):   return _c(f"✓  {t}", _GREEN)
def err(t):  return _c(f"✗  {t}", _RED)
def warn(t): return _c(f"⚠  {t}", _AMBER)
def info(t): return _c(f"   {t}", _GREY)
def head(t): return _c(t, _BOLD + _CYAN)


# ── Helpers ────────────────────────────────────────────────────────────────────

def stem(filename: str) -> str:
    """Return filename without extension."""
    return os.path.splitext(filename)[0]


def is_unknown(filename: str) -> bool:
    """True if filename starts with UNKNOWN_ (pending Stage 10)."""
    return os.path.basename(filename).startswith("UNKNOWN_")


def loc_symbol(record: dict) -> str:
    src = record.get("loc_source", "")
    code = record.get("loc_code_confirmed", "")
    if src == "manual":
        return "●"
    if src == "ai_confirmed" or code:
        return "◉"
    return "○"


# ── Core validator ─────────────────────────────────────────────────────────────

def validate_folder(folder: str, json_dir: str = None, full: bool = False) -> dict:
    """
    Validate a SACC output folder and return a structured report dict.

    Args:
        folder   : root folder containing video files
        json_dir : path to JSON subfolder (default: <folder>/json/)
        full     : include per-file detail for passing files

    Returns:
        dict with keys: summary, errors, warnings, records
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return {"fatal": f"Folder not found: {folder}"}

    json_dir = json_dir or os.path.join(folder, "json")
    json_exists = os.path.isdir(json_dir)

    # Collect video files (top-level only, not _proxy/)
    videos = {}
    for f in os.listdir(folder):
        ext = os.path.splitext(f)[1]
        if ext in VIDEO_EXTS and not f.startswith("."):
            videos[stem(f)] = f

    # Collect JSON files
    jsons = {}
    if json_exists:
        for f in os.listdir(json_dir):
            if f.endswith(".json") and not f.startswith("."):
                jsons[stem(f)] = f

    # ── Per-file analysis ──────────────────────────────────────────────────────
    records = []
    errors  = []
    warnings = []

    for vstem, vfile in sorted(videos.items()):
        rec = {
            "video": vfile,
            "stem":  vstem,
            "has_json": vstem in jsons,
            "is_unknown": is_unknown(vfile),
            "issues": [],
            "info": [],
            "data": {},
        }

        if not rec["has_json"]:
            msg = f"{vfile} — no companion JSON (Stage 8 not yet run)"
            rec["issues"].append(msg)
            errors.append(msg)
            records.append(rec)
            continue

        # Load JSON
        jpath = os.path.join(json_dir, jsons[vstem])
        try:
            with open(jpath) as fh:
                data = json.load(fh)
            rec["data"] = data
        except Exception as e:
            msg = f"{jsons[vstem]} — JSON parse error: {e}"
            rec["issues"].append(msg)
            errors.append(msg)
            records.append(rec)
            continue

        # Required field check
        for field in REQUIRED_FIELDS:
            val = data.get(field)
            if val is None or val == "":
                msg = f"{vfile} — missing field '{field}'"
                rec["issues"].append(msg)
                errors.append(msg)

        # Relational key integrity: JSON filename stem == original_file stem
        orig_file = data.get("original_file", "")
        orig_stem = stem(orig_file) if orig_file else ""
        if orig_stem and orig_stem != vstem:
            msg = (f"{vfile} — relational key mismatch: "
                   f"JSON filename stem='{vstem}' but original_file='{orig_file}'")
            rec["issues"].append(msg)
            warnings.append(msg)
        elif orig_stem:
            rec["info"].append(f"Relational key OK → {orig_file}")

        # UNKNOWN location
        if rec["is_unknown"]:
            code = data.get("loc_code_confirmed", "")
            if code:
                msg = (f"{vfile} — UNKNOWN prefix but loc_code_confirmed='{code}': "
                       f"run Stage 10 to rename")
                rec["issues"].append(msg)
                warnings.append(msg)
            else:
                msg = f"{vfile} — location unresolved (Stage 8 may not have returned a confident match)"
                rec["issues"].append(msg)
                warnings.append(msg)

        # loc_code_confirmed present but file NOT renamed yet
        if not rec["is_unknown"] and data.get("loc_code_confirmed"):
            rec["info"].append(
                f"Location confirmed: {data['loc_code_confirmed']} "
                f"[{data.get('Location_Confidence','?')}]"
            )

        # proxy_deleted flag
        if data.get("proxy_deleted") is True:
            rec["info"].append("Proxy deleted ✓")
        else:
            rec["info"].append("Proxy not yet deleted (or pipeline still running)")

        # analysed_at timestamp
        at = data.get("analysed_at", "")
        if at:
            rec["info"].append(f"Analysed at: {at}")

        records.append(rec)

    # ── Orphan JSON (no matching video) ───────────────────────────────────────
    orphan_jsons = []
    for jstem, jfile in sorted(jsons.items()):
        if jstem not in videos:
            msg = f"{jfile} — orphan JSON (no matching video in folder)"
            warnings.append(msg)
            orphan_jsons.append(jfile)

    # ── Summary counts ─────────────────────────────────────────────────────────
    total       = len(videos)
    paired      = sum(1 for r in records if r["has_json"])
    unpaired    = total - paired
    unknown_ct  = sum(1 for r in records if r["is_unknown"])
    confirmed   = sum(1 for r in records
                      if r["data"].get("loc_code_confirmed"))
    complete    = sum(1 for r in records
                      if r["has_json"] and not r["issues"])
    proxy_done  = sum(1 for r in records
                      if r["data"].get("proxy_deleted") is True)

    return {
        "folder":     folder,
        "json_dir":   json_dir,
        "summary": {
            "total_videos":    total,
            "paired":          paired,
            "unpaired":        unpaired,
            "unknown_loc":     unknown_ct,
            "loc_confirmed":   confirmed,
            "complete_records":complete,
            "orphan_jsons":    len(orphan_jsons),
            "proxy_deleted":   proxy_done,
        },
        "errors":   errors,
        "warnings": warnings,
        "orphans":  orphan_jsons,
        "records":  records,
        "full":     full,
    }


# ── Printer ────────────────────────────────────────────────────────────────────

def print_report(report: dict, full: bool = False):
    if "fatal" in report:
        print(err(report["fatal"]))
        sys.exit(1)

    s = report["summary"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print()
    print(head("━" * 60))
    print(head("  SACC JSON SYNC VALIDATOR"))
    print(head("━" * 60))
    print(info(f"Folder   : {report['folder']}"))
    print(info(f"JSON dir : {report['json_dir']}"))
    print(info(f"Run at   : {now}"))
    print()

    # ── Summary table ──────────────────────────────────────────────────────────
    print(head("  SUMMARY"))
    print(head("  -------"))
    paired_pct   = int(s["paired"]   / s["total_videos"] * 100) if s["total_videos"] else 0
    complete_pct = int(s["complete_records"] / s["total_videos"] * 100) if s["total_videos"] else 0

    print(f"  Total videos      : {s['total_videos']}")
    print(f"  Paired with JSON  : {s['paired']}  ({paired_pct}%)")
    print(f"  Unpaired (no JSON): {s['unpaired']}")
    print(f"  Complete records  : {s['complete_records']}  ({complete_pct}%)")
    print(f"  Orphan JSONs      : {s['orphan_jsons']}")
    print()
    print(f"  ○ UNKNOWN location : {s['unknown_loc']}")
    print(f"  ◉ Loc confirmed    : {s['loc_confirmed']}")
    print(f"  Proxy deleted      : {s['proxy_deleted']}")
    print()

    # ── Errors ─────────────────────────────────────────────────────────────────
    if report["errors"]:
        print(head("  ERRORS"))
        print(head("  ------"))
        for e in report["errors"]:
            print(err(e))
        print()

    # ── Warnings ───────────────────────────────────────────────────────────────
    if report["warnings"]:
        print(head("  WARNINGS"))
        print(head("  --------"))
        for w in report["warnings"]:
            print(warn(w))
        print()

    # ── Per-file detail ────────────────────────────────────────────────────────
    if full or report["errors"] or report["warnings"]:
        print(head("  PER-FILE STATUS"))
        print(head("  ---------------"))
        for rec in report["records"]:
            sym  = loc_symbol(rec["data"]) if rec["data"] else "○"
            icon = "✗" if rec["issues"] else "✓"
            colour = _RED if rec["issues"] else _GREEN
            label = _c(f"{icon} {sym} {rec['video']}", colour)
            print(f"  {label}")
            for issue in rec["issues"]:
                print(f"      {_c('⚠ ' + issue, _AMBER)}")
            if full:
                for note in rec["info"]:
                    print(f"      {_c(note, _GREY)}")
        print()

    # ── Orphan JSONs ───────────────────────────────────────────────────────────
    if report["orphans"]:
        print(head("  ORPHAN JSON FILES (no matching video)"))
        print(head("  -------------------------------------"))
        for o in report["orphans"]:
            print(warn(o))
        print()

    # ── Next steps ─────────────────────────────────────────────────────────────
    print(head("  NEXT STEPS"))
    print(head("  ----------"))
    if s["unpaired"] > 0:
        print(warn(f"{s['unpaired']} video(s) missing JSON — run Stage 8 (Vertex AI analysis):"))
        print(info("  python3 sacc_pipeline.py --fcp --src <folder>"))
    if s["unknown_loc"] > 0:
        print(warn(f"{s['unknown_loc']} file(s) with UNKNOWN location — run Stage 10 after AI confirms:"))
        print(info("  python3 fcp_namer.py --apply-loc --dest <folder>"))
    if s["unpaired"] == 0 and s["unknown_loc"] == 0 and not report["errors"]:
        print(ok("All videos paired, all fields complete, all locations resolved."))
    print()
    print(head("━" * 60))
    print()


# ── Machine-readable JSON output ──────────────────────────────────────────────

def print_json_report(report: dict):
    """Print report as JSON for programmatic consumption."""
    import copy
    out = copy.deepcopy(report)
    # Remove large per-record data blobs unless needed
    for rec in out.get("records", []):
        rec.pop("data", None)
    print(json.dumps(out, indent=2, default=str))


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Validate SACC JSON database sync for a folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("folder",
                   help="Path to SACC output folder containing video files")
    p.add_argument("--json-dir", default=None,
                   help="Custom path to JSON subfolder (default: <folder>/json/)")
    p.add_argument("--full", action="store_true",
                   help="Show per-file detail for ALL files, not just issues")
    p.add_argument("--json-out", action="store_true",
                   help="Emit machine-readable JSON instead of human report")
    p.add_argument("--exit-code", action="store_true",
                   help="Exit 1 if any errors found (for CI/CD use)")

    args = p.parse_args()

    report = validate_folder(
        folder   = args.folder,
        json_dir = args.json_dir,
        full     = args.full,
    )

    if args.json_out:
        print_json_report(report)
    else:
        print_report(report, full=args.full)

    if args.exit_code and (report.get("errors") or report.get("fatal")):
        sys.exit(1)


if __name__ == "__main__":
    main()
