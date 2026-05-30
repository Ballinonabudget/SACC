#!/usr/bin/env python3
"""
One-shot healer for the 5/15 buggy-strip damage on iPhone files.

The pre-fix _strip_sacc_prefix regex greedily consumed the `IMG_` segment
when re-renaming already-renamed iPhone files, producing names like
  NC192-NCS_20190128_Unknown_8783.mov
instead of leaving
  NC192-NCS_20190128_iPhone8Plus_IMG_8783.mov
alone. The ac871e0 fix prevents recurrence on new work but cannot recover
the IMG_ segment from a name where it's already been deleted.

This script:
  - finds every *_Unknown_<digits>.mov under the given root
  - derives shoot date from the filename, looks up the correct camera via
    fcp_namer.CAMERA_TIMELINE on `IMG_<digits>` + that date
  - renames the .mov to <prefix>_<date>_<camera>_IMG_<digits>.mov
  - if a matching <camera>_IMG_<digits>.json sidecar already exists
    (from the 5/14 good run), deletes the duplicate _Unknown_<digits>.json
  - otherwise renames the _Unknown_<digits>.json to align with the new mov

Default mode is dry-run. Pass --apply to actually move files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fcp_namer import _resolve_camera_from_timeline


BROKEN_RE = re.compile(
    r"^(?P<prefix>[A-Z0-9]+-[A-Z]+)_(?P<date>\d{8})_Unknown_(?P<num>\d+)\.mov$"
)


def plan(root: Path) -> list[dict]:
    """Walk `root` and return one plan entry per broken .mov found."""
    entries: list[dict] = []
    for mov in sorted(root.rglob("*_Unknown_*.mov")):
        m = BROKEN_RE.match(mov.name)
        if not m:
            continue
        prefix = m.group("prefix")
        date = m.group("date")
        num = m.group("num")

        # Derive correct camera via CAMERA_TIMELINE on IMG_<num> + date
        candidate = f"IMG_{num}.mov"
        cam_model = _resolve_camera_from_timeline(candidate, date)
        if cam_model is None:
            entries.append({
                "src_mov": mov, "skip": True,
                "reason": f"no CAMERA_TIMELINE rule for IMG_+{date}",
            })
            continue
        cam = cam_model.replace(" ", "")

        new_mov_name = f"{prefix}_{date}_{cam}_IMG_{num}.mov"
        new_mov = mov.with_name(new_mov_name)

        # Sidecars live in the sibling json/ folder
        json_dir = mov.parent / "json"
        old_json = json_dir / f"{prefix}_{date}_Unknown_{num}.json"
        new_json = json_dir / f"{prefix}_{date}_{cam}_IMG_{num}.json"

        if old_json.exists():
            if new_json.exists():
                sidecar_action = ("delete_dup", old_json, None)
            else:
                sidecar_action = ("rename", old_json, new_json)
        else:
            sidecar_action = ("none", None, None)

        entries.append({
            "src_mov": mov,
            "dst_mov": new_mov,
            "mov_exists": new_mov.exists(),
            "sidecar": sidecar_action,
            "skip": False,
        })
    return entries


def print_plan(entries: list[dict]) -> dict:
    counts = {"mov_rename": 0, "json_delete": 0, "json_rename": 0,
              "json_none": 0, "skip": 0, "mov_collision": 0}
    for e in entries:
        if e.get("skip"):
            counts["skip"] += 1
            print(f"SKIP   {e['src_mov']}   — {e['reason']}")
            continue
        src = e["src_mov"]
        dst = e["dst_mov"]
        collision = " [COLLISION]" if e["mov_exists"] else ""
        if e["mov_exists"]:
            counts["mov_collision"] += 1
        else:
            counts["mov_rename"] += 1
        print(f"MV     {src.name}  ->  {dst.name}{collision}")
        action, a, b = e["sidecar"]
        if action == "delete_dup":
            counts["json_delete"] += 1
            print(f"  RM   json/{a.name}   (duplicate of existing target sidecar)")
        elif action == "rename":
            counts["json_rename"] += 1
            print(f"  MV   json/{a.name}  ->  json/{b.name}")
        else:
            counts["json_none"] += 1
            print(f"  --   no _Unknown_ sidecar to clean")
    print()
    print("SUMMARY:")
    for k, v in counts.items():
        print(f"  {k:15s} {v}")
    return counts


def apply_plan(entries: list[dict]) -> None:
    for e in entries:
        if e.get("skip"):
            continue
        src = e["src_mov"]; dst = e["dst_mov"]
        if e["mov_exists"]:
            print(f"SKIP (collision) {dst.name}")
            continue
        os.rename(src, dst)
        action, a, b = e["sidecar"]
        if action == "delete_dup":
            os.remove(a)
        elif action == "rename":
            os.rename(a, b)
    print("done.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True,
                    help="Folder to walk (e.g. '/Volumes/Team Bank 12/Test 1 Jan 2019')")
    ap.add_argument("--apply", action="store_true",
                    help="Actually rename/delete (default: dry-run)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        sys.exit(2)

    entries = plan(root)
    if not entries:
        print("no *_Unknown_<digits>.mov files found — nothing to heal.")
        return
    counts = print_plan(entries)
    if args.apply:
        if counts["mov_collision"] > 0:
            print(f"\nABORT: {counts['mov_collision']} collisions — refusing to apply.",
                  file=sys.stderr)
            sys.exit(3)
        print("\n--apply set; renaming...")
        apply_plan(entries)
    else:
        print("\n(dry-run; pass --apply to execute)")


if __name__ == "__main__":
    main()
