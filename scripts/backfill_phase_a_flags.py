"""
backfill_phase_a_flags.py — Phase A flag backfill
=================================================
Re-applies the corrected v2.1 metadata logic to every JSON under <root>:

  - schema_version            : normalised to the string "2.1"
  - conflict_detected         : recomputed from current visible_brands + anchor
  - is_archivable_as_is       : NEW — set on non-shoe (B-roll) clips
  - needs_review              : recomputed — only True on shoe-bearing clips
                                with a missing SKU OR brand conflict OR low
                                anchor confidence
  - loc_code_anchor           : injected from the folder's _anchor.json if absent

The script is idempotent (re-running yields the same result) and does NOT
re-run Gemini, OCR, or anything else costly. It only mutates JSONs already
on disk. Use after applying Phase A fixes to bring legacy artifacts up to
the new schema without re-burning API quota.

Usage:
    python scripts/backfill_phase_a_flags.py \\
        --root "/Volumes/Team Bank 12/5 May 2019/"

    # Preview only
    python scripts/backfill_phase_a_flags.py --root ... --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from sacc_pipeline import _apply_v21_metadata_and_conflicts  # noqa: E402


def _load_anchor(folder: str) -> dict:
    path = os.path.join(folder, "_anchor.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _is_clip_json(name: str) -> bool:
    return name.endswith(".json") and not name.startswith("_")


def backfill(root: str, dry_run: bool = False) -> dict:
    if not os.path.isdir(root):
        raise SystemExit(f"root not found: {root}")

    stats = {
        "folders_scanned":          0,
        "json_scanned":             0,
        "needs_review_pre_true":    0,
        "needs_review_post_true":   0,
        "archivable_post_true":     0,
        "conflict_post_true":       0,
        "schema_version_normalised": 0,
        "rewritten":                0,
        "errors":                   [],
    }

    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_proxy"]
        if "json" not in dirnames:
            continue

        json_dir = os.path.join(dirpath, "json")
        anchor   = _load_anchor(dirpath)
        stats["folders_scanned"] += 1

        for fname in sorted(os.listdir(json_dir)):
            if not _is_clip_json(fname):
                continue
            jpath = os.path.join(json_dir, fname)
            try:
                with open(jpath) as fh:
                    data = json.load(fh)
            except Exception as e:
                stats["errors"].append(f"{fname}: read failed — {e}")
                continue

            stats["json_scanned"] += 1
            if data.get("needs_review") is True:
                stats["needs_review_pre_true"] += 1

            # Skip stage-9 logic for failure stubs — they're already shaped
            # correctly by Fix #3 and don't carry the brand/anchor signals.
            is_failure_stub = data.get("status") == "failed"

            changed = False

            # Normalise schema_version → string "2.1"
            sv = data.get("schema_version")
            if sv != "2.1":
                data["schema_version"] = "2.1"
                stats["schema_version_normalised"] += 1
                changed = True

            if not is_failure_stub:
                # Snapshot the keys we recompute so we can detect a real diff
                before = (
                    data.get("conflict_detected"),
                    data.get("needs_review"),
                    data.get("is_archivable_as_is"),
                    data.get("loc_code_anchor"),
                )
                _apply_v21_metadata_and_conflicts(data, anchor)
                after = (
                    data.get("conflict_detected"),
                    data.get("needs_review"),
                    data.get("is_archivable_as_is"),
                    data.get("loc_code_anchor"),
                )
                if before != after:
                    changed = True

            if data.get("needs_review") is True:
                stats["needs_review_post_true"] += 1
            if data.get("is_archivable_as_is") is True:
                stats["archivable_post_true"] += 1
            if data.get("conflict_detected") is True:
                stats["conflict_post_true"] += 1

            if changed and not dry_run:
                try:
                    with open(jpath, "w") as fh:
                        json.dump(data, fh, indent=2)
                    stats["rewritten"] += 1
                except Exception as e:
                    stats["errors"].append(f"{fname}: write failed — {e}")
            elif changed:
                stats["rewritten"] += 1  # would-rewrite, accounting only

    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True,
                    help="Folder to walk (e.g. '/Volumes/Team Bank 12/5 May 2019/')")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute the diff without writing JSONs back to disk")
    args = ap.parse_args()

    print(f"[backfill] root    : {args.root}")
    print(f"[backfill] dry_run : {args.dry_run}")
    print("-" * 60)

    stats = backfill(args.root, dry_run=args.dry_run)

    for k, v in stats.items():
        if k == "errors":
            continue
        print(f"  {k:30s} {v}")
    errs = stats["errors"]
    if errs:
        print(f"  errors                         {len(errs)}")
        for e in errs[:5]:
            print(f"    • {e}")


if __name__ == "__main__":
    main()
