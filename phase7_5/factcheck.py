"""Backtest harness: re-identify existing clips with Path B and compare to stored SKUs.

Usage:
  python -m phase7_5.factcheck \
    --db "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db" \
    --limit 10 \
    --stratified \
    --out factcheck_smoke.csv
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

from .orchestrator import _norm_sku, verify_clip


def find_video(folder_path: str, stem: str) -> str | None:
    """Locate the source video for a clip stem inside its folder."""
    if not folder_path:
        return None
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return None
    candidates = [f"{stem}{ext}" for ext in (".MP4", ".mp4", ".MOV", ".mov", ".m4v", ".avi")]
    for name in candidates:
        p = folder / name
        if p.exists():
            return str(p)
    # case-insensitive fallback
    target_lower = stem.lower()
    try:
        for f in folder.iterdir():
            if f.is_file() and f.stem.lower() == target_lower:
                return str(f)
    except Exception:
        pass
    return None


def fetch_rows(conn: sqlite3.Connection, limit: int, stratified: bool,
               random: bool = False, offset: int = 0,
               seed: int = 0) -> list[sqlite3.Row]:
    if random:
        # SQLite RANDOM() with a seedable workaround: shuffle by hashing id+seed
        sql = """
            SELECT * FROM clips
            WHERE sku IS NOT NULL AND sku != ''
            GROUP BY sku
            ORDER BY (id * 2654435761 + ?) % 100000
            LIMIT ? OFFSET ?
        """
        return conn.execute(sql, (seed, limit, offset)).fetchall()
    if stratified:
        sql = """
            SELECT * FROM clips
            WHERE sku IS NOT NULL AND sku != ''
            GROUP BY sku
            ORDER BY id
            LIMIT ? OFFSET ?
        """
    else:
        sql = """
            SELECT * FROM clips
            WHERE sku IS NOT NULL AND sku != ''
            ORDER BY id
            LIMIT ? OFFSET ?
        """
    return conn.execute(sql, (limit, offset)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",     required=True, help="path to sacc.db")
    ap.add_argument("--limit",  type=int, default=10)
    ap.add_argument("--offset", type=int, default=0,
                    help="Skip the first N rows.")
    ap.add_argument("--stratified", action="store_true",
                    help="One clip per unique SKU (broader coverage)")
    ap.add_argument("--random", action="store_true",
                    help="Random sample across the dataset (use --seed for reproducibility)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out",    default="phase7_5_factcheck.csv")
    ap.add_argument("--save-query-images", default="",
                    help="If set, save the cropped query image used for DINOv2 to this dir.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = fetch_rows(conn, args.limit, args.stratified,
                      random=args.random, offset=args.offset, seed=args.seed)
    print(f"Loaded {len(rows)} clips from {args.db}")
    mode = "random" if args.random else ("stratified" if args.stratified else "sequential")
    print(f"Mode: {mode}  offset={args.offset}  seed={args.seed}")
    print()

    out_rows: list[dict] = []
    started = time.time()

    for i, row in enumerate(rows, 1):
        stem          = row["stem"]
        existing_sku  = (row["sku"] or "").upper()
        existing_mdl  = row["model"] or ""
        existing_cw   = row["colorway"] or ""
        folder_path   = row["folder_path"] or ""

        video = find_video(folder_path, stem)
        elapsed = time.time() - started
        print(f"[{i:>3}/{len(rows)}] {stem:<14}  existing_sku={existing_sku}  ({elapsed:.0f}s elapsed)")

        if not video:
            out_rows.append({
                "stem":            stem,
                "existing_sku":    existing_sku,
                "existing_model":  existing_mdl,
                "existing_cw":     existing_cw,
                "path":            "",
                "label_sku":       "",
                "chosen_sku":      "",
                "chosen_model":    "",
                "similarity":      "",
                "verdict":         "no_video",
                "agree":           "",
                "top_candidates":  "",
                "error":           f"video not found in {folder_path}",
            })
            continue

        try:
            result = verify_clip(video, verbose=args.verbose)
        except Exception as e:
            out_rows.append({
                "stem":            stem,
                "existing_sku":    existing_sku,
                "existing_model":  existing_mdl,
                "existing_cw":     existing_cw,
                "path":            "",
                "label_sku":       "",
                "chosen_sku":      "",
                "chosen_model":    "",
                "similarity":      "",
                "verdict":         "error",
                "agree":           "",
                "top_candidates":  "",
                "error":           f"{type(e).__name__}: {e}",
            })
            continue

        chosen   = (result.get("chosen_sku") or "").upper()
        sim      = result.get("visual_similarity") or 0.0
        verdict  = result.get("verdict")

        if args.save_query_images:
            qdir = Path(args.save_query_images)
            qdir.mkdir(parents=True, exist_ok=True)
            if result.get("query_bytes"):
                (qdir / f"{stem}_crop.jpg").write_bytes(result["query_bytes"])
            if result.get("best_frame_bytes"):
                (qdir / f"{stem}_frame.jpg").write_bytes(result["best_frame_bytes"])
        if not chosen:
            agree = "NULL"
        elif _norm_sku(chosen) == _norm_sku(existing_sku):
            agree = "YES"
        else:
            agree = "NO"

        top3 = ", ".join(
            f"{c['sku']}@{c['similarity']:.2f}"
            for c in (result.get("candidates_scored") or [])[:3]
        )

        bbox = result.get("shoe_bbox")
        filtered = result.get("candidates_filtered_out") or []
        out_rows.append({
            "stem":             stem,
            "existing_sku":     existing_sku,
            "existing_model":   existing_mdl,
            "existing_cw":      existing_cw,
            "video_date":       result.get("video_date") or "",
            "path":             result.get("path") or "",
            "label_sku":        result.get("label_sku") or "",
            "best_frame_t":     result.get("best_frame_time") or "",
            "best_frame_reason":result.get("best_frame_reason") or "",
            "bbox":             json.dumps(bbox) if bbox else "",
            "chosen_sku":       chosen,
            "chosen_model":     result.get("chosen_model") or "",
            "similarity":       f"{sim:.3f}",
            "verdict":          verdict,
            "agree":            agree,
            "top_candidates":   top3,
            "n_filtered":       len(filtered),
            "filtered_skus":    ", ".join(f"{f['sku']}({f['release_date']})" for f in filtered[:5]),
            "error":            result.get("error") or "",
        })

        print(f"     path={result.get('path')}  chosen={chosen or '-':<14}  sim={sim:.3f}  "
              f"verdict={verdict:<22}  agree={agree}")
        if top3:
            print(f"     top: {top3}")

    # ── Write CSV ───────────────────────────────────────────────────────────
    out_path = Path(args.out).resolve()
    if out_rows:
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            w.writerows(out_rows)

    # ── Summary ─────────────────────────────────────────────────────────────
    agree    = sum(1 for r in out_rows if r["agree"] == "YES")
    disagree = sum(1 for r in out_rows if r["agree"] == "NO")
    null     = sum(1 for r in out_rows if r["agree"] == "NULL")
    nv       = sum(1 for r in out_rows if r["verdict"] == "no_video")
    err      = sum(1 for r in out_rows if r["verdict"] == "error")

    print()
    print("=" * 60)
    print(f"  Total clips :   {len(out_rows)}")
    print(f"  Agree       :   {agree}")
    print(f"  Disagree    :   {disagree}    (review: Path B may be right OR wrong)")
    print(f"  No SKU found:   {null}")
    print(f"  No video    :   {nv}")
    print(f"  Errors      :   {err}")
    print(f"  Elapsed     :   {time.time() - started:.0f}s")
    print(f"  Report      :   {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
