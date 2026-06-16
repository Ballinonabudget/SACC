"""
build_tier_calibration_deck.py — Tier 3/4 duration-threshold calibration

Pulls a stratified sample of clips from a folder's stage0 output, generates
a 3-frame strip per clip (25/50/75% positions), and writes a single HTML
index sorted ascending by `duration_with_shoe_visible_sec`. The operator
scrolls the page, finds the row where their answer to
"can I tell what shoe this is?" flips from No → Yes, and reports back the
duration value at the flip. That value becomes the Tier 3/4 cutoff.

Usage:
    python scripts/build_tier_calibration_deck.py \\
        --stage0-root "/Volumes/Team Bank 12/5 May 2019/Final Cut Original Media/2019-05-21" \\
        --out         /tmp/stage0_calib
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import cv2


VIDEO_EXTS = {".mov", ".mp4", ".m4v"}


def _load_stage0(stage0_root: str) -> list[dict]:
    out = []
    for dirpath, dirnames, filenames in os.walk(stage0_root):
        if os.path.basename(dirpath) != "stage0":
            continue
        for f in sorted(filenames):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(dirpath, f)) as fh:
                    out.append(json.load(fh))
            except Exception:
                continue
    return out


def _stratified_pick(records: list[dict], n: int = 20) -> list[dict]:
    """Pick ~n records across the duration_with_shoe_visible_sec spectrum
    with a bias toward the calibration-relevant short end (0-10s)."""
    shoe_recs = [r for r in records if r.get("shoe_present")]
    shoe_recs.sort(key=lambda r: r.get("duration_with_shoe_visible_sec", 0.0))
    if not shoe_recs:
        return []

    # Bucket targets (start, end, target_count). Open-ended end as inf.
    buckets = [
        (0.0,    1.5,  4),    # below current Tier 4 guess
        (1.5,    3.0,  4),    # boundary zone — most informative
        (3.0,    6.0,  4),
        (6.0,   12.0,  4),
        (12.0, 1e9,    4),
    ]
    picked: list[dict] = []
    for lo, hi, k in buckets:
        in_bucket = [r for r in shoe_recs
                     if lo <= r.get("duration_with_shoe_visible_sec", 0.0) < hi]
        if not in_bucket:
            continue
        # Pick k evenly across the bucket
        step = max(1, len(in_bucket) // k)
        bucket_picks = in_bucket[::step][:k]
        picked.extend(bucket_picks)
    # Dedup and cap
    seen = set()
    deduped = []
    for r in picked:
        s = r["clip_stem"]
        if s not in seen:
            seen.add(s)
            deduped.append(r)
        if len(deduped) >= n:
            break
    return deduped


def _make_strip(clip_path: str, dest_jpg: str, strip_h: int = 240) -> bool:
    """Write a horizontally-concatenated 3-frame strip (25/50/75%) to dest_jpg."""
    cap = cv2.VideoCapture(clip_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 1:
        cap.release()
        return False
    frames = []
    for pct in (0.25, 0.50, 0.75):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * pct))
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        h, w = fr.shape[:2]
        scale = strip_h / h
        fr = cv2.resize(fr, (int(w * scale), strip_h))
        frames.append(fr)
    cap.release()
    if not frames:
        return False
    # Equalise widths
    min_w = min(f.shape[1] for f in frames)
    frames = [f[:, :min_w] for f in frames]
    import numpy as np
    strip = np.concatenate(frames, axis=1)
    return cv2.imwrite(dest_jpg, strip, [cv2.IMWRITE_JPEG_QUALITY, 80])


def _write_html(records: list[dict], out_dir: str) -> str:
    html_path = os.path.join(out_dir, "index.html")
    rows = []
    for r in records:
        stem    = r["clip_stem"]
        d_clip  = r.get("duration_sec", 0.0)
        d_shoe  = r.get("duration_with_shoe_visible_sec", 0.0)
        shoe_c  = r.get("shoe_max_conf", 0.0)
        hand_c  = r.get("hand_max_conf", 0.0)
        hand_i  = r.get("hand_interaction", False)
        path    = r["clip_path"]
        rows.append(f"""
<div class="row">
  <div class="meta">
    <div class="d_shoe">shoe visible: <b>{d_shoe:.1f}s</b></div>
    <div class="d_clip">clip length: {d_clip:.1f}s</div>
    <div class="conf">shoe_conf {shoe_c:.2f}  ·  hand_conf {hand_c:.2f}  ·  hand_interaction {"YES" if hand_i else "no"}</div>
    <div class="stem">{stem}</div>
    <div class="path">{path}</div>
  </div>
  <img src="thumbnails/{stem}.jpg" loading="lazy" />
</div>""")

    template = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Stage 0 — Tier 3/4 calibration</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 0; background: #111; color: #eee; }}
header {{ position: sticky; top: 0; background: #222; padding: 12px 20px; border-bottom: 1px solid #333; z-index: 10; }}
header h1 {{ margin: 0; font-size: 16px; }}
header p  {{ margin: 4px 0 0; color: #999; font-size: 13px; }}
.row {{ display: flex; gap: 16px; padding: 18px 20px; border-bottom: 1px solid #222; }}
.meta {{ flex: 0 0 280px; font-size: 13px; }}
.meta .d_shoe {{ font-size: 16px; margin-bottom: 4px; }}
.meta .conf  {{ color: #999; margin-top: 6px; font-size: 12px; }}
.meta .stem  {{ color: #888; margin-top: 12px; font-size: 11px; }}
.meta .path  {{ color: #555; margin-top: 4px; font-size: 10px; word-break: break-all; }}
.row img {{ height: 240px; border-radius: 4px; }}
</style></head>
<body>
<header>
  <h1>Stage 0 — Tier 3/4 calibration deck</h1>
  <p>Sorted ascending by <b>shoe-visible duration</b>. Scroll down. Find the row where your answer to <i>"can I tell what shoe this is?"</i> flips from <b>No → Yes</b>. The <code>shoe visible</code> seconds value at that flip becomes the Tier 3/4 cutoff. Open the clip path in Finder/QuickLook if a strip alone isn't enough to judge.</p>
</header>
{''.join(rows)}
</body></html>"""
    with open(html_path, "w") as f:
        f.write(template)
    return html_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage0-root", required=True,
                    help="Folder root containing stage0/<stem>.json files")
    ap.add_argument("--out", default="/tmp/stage0_calib",
                    help="Output directory for thumbnails + index.html")
    ap.add_argument("--n", type=int, default=20,
                    help="Sample size target (default 20)")
    args = ap.parse_args()

    out_dir = args.out
    thumb_dir = os.path.join(out_dir, "thumbnails")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(thumb_dir, exist_ok=True)

    print(f"[deck] loading stage0 JSONs from {args.stage0_root}")
    records = _load_stage0(args.stage0_root)
    print(f"[deck] {len(records)} stage0 records found")

    picks = _stratified_pick(records, args.n)
    picks.sort(key=lambda r: r.get("duration_with_shoe_visible_sec", 0.0))
    print(f"[deck] picked {len(picks)} clips across the duration spectrum")

    for r in picks:
        stem = r["clip_stem"]
        thumb = os.path.join(thumb_dir, f"{stem}.jpg")
        ok = _make_strip(r["clip_path"], thumb)
        d_shoe = r.get("duration_with_shoe_visible_sec", 0.0)
        print(f"  shoe_d={d_shoe:5.1f}s  thumb={'OK' if ok else 'FAIL'}  {stem}")

    html_path = _write_html(picks, out_dir)
    print()
    print(f"[deck] HTML index → {html_path}")
    print(f"[deck] open with: open {html_path}")


if __name__ == "__main__":
    main()
