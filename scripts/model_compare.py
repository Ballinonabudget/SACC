#!/usr/bin/env python3
"""
Gemini A/B harness — compare SKU-extraction accuracy across two Gemini models
on the same set of clips.

Two modes:

  Mode 1 — live A vs live B (recommended for true A/B):
    --baseline-model + --candidate-model both set
    For each clip, run BOTH models live and compare SKU_A vs SKU_B.
    Cost: 2N calls. Use when you want apples-to-apples on identical input.

  Mode 2 — live B vs DB-stored baseline (fast):
    Only --candidate-model set.
    For each clip, run candidate live and compare against the SKU already
    stored in clips.sku (presumed from prior pro/baseline runs).
    Cost: N calls.

Usage:
  # Mode 1 — live A vs B
  python scripts/model_compare.py \\
      --baseline-model  gemini-2.5-flash \\
      --candidate-model gemini-3.1-flash-lite-preview \\
      --n 15 \\
      --db-path "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db"

  # Mode 2 — candidate vs DB
  python scripts/model_compare.py \\
      --candidate-model gemini-3.1-flash-lite-preview \\
      --n 15 \\
      --db-path "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db"

The harness:
  1. Samples N rows from the DB that already have a non-empty SKU.
  2. Locates each clip's video on disk (proxy in <folder>/_proxy/ if present,
     else the renamed master in <folder>/).
  3. Runs Gemini analysis with each requested model by patching the module-
     level model name on gemini_pipeline (late-bound inside the call site).
  4. Reports per-row diff and aggregate accuracy.

Cost note: each call uploads the full video to Gemini. Keep N small until
you trust the candidate, especially on -preview models with tighter quotas.
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def find_video(folder, stem, original_file):
    """Locate the best video file for a row. Prefer proxy, fall back to master."""
    folder_p = Path(folder)
    if not folder_p.is_dir():
        return None
    proxy = folder_p / "_proxy" / f"{stem}.mp4"
    if proxy.is_file():
        return str(proxy)
    if original_file:
        cand = folder_p / original_file
        if cand.is_file():
            return str(cand)
    for ext in (".mov", ".mp4", ".MOV", ".MP4"):
        cand = folder_p / f"{stem}{ext}"
        if cand.is_file():
            return str(cand)
    return None


def sample_rows(db_path, n, seed):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT stem, original_file, folder_path, sku, model, colorway
        FROM clips
        WHERE sku IS NOT NULL AND sku != ''
    """).fetchall()
    con.close()
    rng = random.Random(seed)
    rng.shuffle(rows)
    return [dict(r) for r in rows[:n]]


def normalize_sku(s):
    return (s or "").strip().upper().replace(" ", "")


def _run_with_model(gp, model_id, video, original_file):
    """Patch the module-level model name then call analyze_sneaker_video.
    The model name is read inside _call/_infer at call time (late binding),
    so patching the module attribute before each call is sufficient."""
    gp._VERTEX_MODEL_NAME = model_id
    gp._GEMINI_MODEL_NAME = (
        model_id if model_id.startswith("models/") else f"models/{model_id}"
    )
    return gp.analyze_sneaker_video(
        proxy_path=video, original_file=original_file, original_path=video,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate-model", required=True,
                    help="Exact API model ID to test, e.g. 'gemini-3.1-flash-lite-preview'")
    ap.add_argument("--baseline-model", default="",
                    help="Optional second model. If set, runs live A vs B "
                         "per clip; otherwise compares candidate against DB SKU.")
    ap.add_argument("--n", type=int, default=15, help="Sample size (default 15)")
    ap.add_argument("--db-path", required=True, help="Path to a SACC sacc.db")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    ap.add_argument("--out", default="", help="Optional path to write per-row JSONL log")
    args = ap.parse_args()

    if not os.path.isfile(args.db_path):
        sys.exit(f"db not found: {args.db_path}")

    # Set initial env so module init picks a valid default; per-call patching
    # below switches between baseline and candidate via attribute writes.
    os.environ["GEMINI_MODEL"] = args.candidate_model
    os.environ["VERTEX_MODEL"] = args.candidate_model
    import gemini_pipeline as gp  # noqa: E402

    rows = sample_rows(args.db_path, args.n, args.seed)
    if not rows:
        sys.exit("no rows in DB have a non-empty sku — nothing to compare against")

    live_ab = bool(args.baseline_model)
    print(f"Sampled {len(rows)} rows from {args.db_path}")
    print(f"Mode: {'live A vs live B' if live_ab else 'candidate vs DB-stored SKU'}")
    if live_ab:
        print(f"  Model A (baseline) : {args.baseline_model}")
        print(f"  Model B (candidate): {args.candidate_model}")
    else:
        print(f"  Candidate          : {args.candidate_model}")
        print(f"  Baseline           : SKUs in clips.sku")
    print()

    ab_matches = 0          # A == B (live mode)
    cand_db_matches = 0     # candidate == DB
    base_db_matches = 0     # baseline  == DB (live mode bonus)
    missing_video = 0
    errored = 0
    log_lines = []
    t0 = time.time()

    for i, r in enumerate(rows, 1):
        db_sku = normalize_sku(r["sku"])
        video = find_video(r["folder_path"] or "", r["stem"] or "", r["original_file"] or "")
        if not video:
            missing_video += 1
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  SKIP (no video on disk)")
            log_lines.append({"stem": r["stem"], "status": "no_video"})
            continue

        of = r["original_file"] or os.path.basename(video)

        # Always run candidate (model B)
        try:
            res_b = _run_with_model(gp, args.candidate_model, video, of)
        except Exception as e:
            errored += 1
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  ERROR(B): {e}")
            log_lines.append({"stem": r["stem"], "status": "error_b", "msg": str(e)})
            continue
        if res_b.get("error"):
            errored += 1
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  ERROR(B): {res_b['error'][:60]}")
            log_lines.append({"stem": r["stem"], "status": "error_b", "msg": res_b["error"]})
            continue
        sku_b = normalize_sku(res_b.get("SKU") or res_b.get("sku"))

        if not live_ab:
            # Mode 2: candidate vs DB
            ok = (sku_b == db_sku)
            cand_db_matches += int(ok)
            verdict = "MATCH " if ok else "MISS  "
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  {verdict}  "
                  f"db={db_sku!r}  B={sku_b!r}  ({r['model'] or '?'}  {r['colorway'] or ''})")
            log_lines.append({
                "stem": r["stem"], "status": "ok",
                "db_sku": db_sku, "candidate_sku": sku_b,
                "match_cand_db": ok,
                "model": r["model"], "colorway": r["colorway"],
            })
            continue

        # Mode 1: also run baseline (model A)
        try:
            res_a = _run_with_model(gp, args.baseline_model, video, of)
        except Exception as e:
            errored += 1
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  ERROR(A): {e}")
            log_lines.append({"stem": r["stem"], "status": "error_a", "msg": str(e)})
            continue
        if res_a.get("error"):
            errored += 1
            print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  ERROR(A): {res_a['error'][:60]}")
            log_lines.append({"stem": r["stem"], "status": "error_a", "msg": res_a["error"]})
            continue
        sku_a = normalize_sku(res_a.get("SKU") or res_a.get("sku"))

        ab_ok    = (sku_a == sku_b)
        a_db_ok  = (sku_a == db_sku)
        b_db_ok  = (sku_b == db_sku)
        ab_matches      += int(ab_ok)
        base_db_matches += int(a_db_ok)
        cand_db_matches += int(b_db_ok)
        verdict = "AGREE " if ab_ok else "DIFFER"
        print(f"[{i:2}/{len(rows)}] {r['stem']:>10}  {verdict}  "
              f"A={sku_a!r}  B={sku_b!r}  db={db_sku!r}  "
              f"({r['model'] or '?'}  {r['colorway'] or ''})")
        log_lines.append({
            "stem": r["stem"], "status": "ok",
            "db_sku": db_sku, "baseline_sku": sku_a, "candidate_sku": sku_b,
            "match_ab": ab_ok, "match_a_db": a_db_ok, "match_b_db": b_db_ok,
            "model": r["model"], "colorway": r["colorway"],
        })

    elapsed = time.time() - t0
    scored = len(rows) - missing_video - errored
    print(f"\n── Summary ──")
    print(f"  sampled            : {len(rows)}")
    print(f"  no_video           : {missing_video}")
    print(f"  errored            : {errored}")
    print(f"  scored             : {scored}")
    if live_ab:
        pct = lambda m: (m/scored*100.0) if scored else 0.0
        print(f"  A == B  (agreement): {ab_matches}/{scored} ({pct(ab_matches):.1f}%)")
        print(f"  A == db            : {base_db_matches}/{scored} ({pct(base_db_matches):.1f}%)")
        print(f"  B == db            : {cand_db_matches}/{scored} ({pct(cand_db_matches):.1f}%)")
    else:
        pct = (cand_db_matches / scored * 100.0) if scored else 0.0
        print(f"  exact SKU match    : {cand_db_matches}/{scored} ({pct:.1f}%)")
    print(f"  elapsed            : {elapsed:.1f}s")

    if args.out:
        with open(args.out, "w") as fh:
            for line in log_lines:
                fh.write(json.dumps(line) + "\n")
        print(f"  per-row log        : {args.out}")


if __name__ == "__main__":
    main()
