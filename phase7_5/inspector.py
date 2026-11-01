"""Visual inspection HTML — keyframe vs existing-DB image vs Path B chosen image.

Usage:
  python -m phase7_5.inspector \
    --csv /tmp/factcheck_smoke5_v2.csv \
    --db "/Volumes/Team Bank 12/Sneeaker Solo/sacc.db" \
    --out /tmp/factcheck_inspector.html
"""
from __future__ import annotations

import argparse
import base64
import csv
import sqlite3
import tempfile
from pathlib import Path

from .keyframe import extract_keyframe
from .kicksdb_search import fetch_image, gallery_urls, search_by_description


def _b64_image(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _load_video_paths(db_path: str) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT stem, folder_path FROM clips").fetchall()
    conn.close()
    return {r["stem"]: (r["folder_path"] or "") for r in rows}


def _find_video(folder_path: str, stem: str) -> str | None:
    if not folder_path:
        return None
    folder = Path(folder_path)
    if not folder.exists():
        return None
    for ext in (".MP4", ".mp4", ".MOV", ".mov", ".m4v", ".avi"):
        p = folder / f"{stem}{ext}"
        if p.exists():
            return str(p)
    target_lower = stem.lower()
    try:
        for f in folder.iterdir():
            if f.is_file() and f.stem.lower() == target_lower:
                return str(f)
    except Exception:
        pass
    return None


def _kicksdb_image(sku: str) -> bytes | None:
    """Resolve a SKU to its canonical product image bytes (first gallery URL)."""
    if not sku:
        return None
    for source in ("goat", "stockx"):
        results = search_by_description(sku, max_results=1, source=source)
        for p in results:
            urls = gallery_urls(p, max_urls=1)
            if urls:
                data = fetch_image(urls[0])
                if data:
                    return data
    return None


def _keyframe_bytes(video_path: str) -> bytes | None:
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            kf_path = f.name
        extract_keyframe(video_path, kf_path)
        with open(kf_path, "rb") as fh:
            return fh.read()
    except Exception:
        return None
    finally:
        try:
            Path(kf_path).unlink(missing_ok=True)
        except Exception:
            pass


def _read_or_none(p: Path) -> bytes | None:
    try:
        if p.exists():
            return p.read_bytes()
    except Exception:
        pass
    return None


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Phase 7.5 Inspector — {csv_name}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background:#1a1a1a; color:#e8e8e8; margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 16px; color:#eee; }}
  .meta {{ color:#888; font-size:13px; margin-bottom:24px; }}
  .clip {{ background:#262626; border-radius:10px; padding:16px;
           margin-bottom:18px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }}
  .clip h2 {{ font-size:15px; margin:0 0 10px; color:#fff; font-weight:600; }}
  .clip .row {{ display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:14px; }}
  .panel {{ background:#1a1a1a; border:1px solid #333; border-radius:8px;
            padding:10px; }}
  .panel h3 {{ font-size:12px; margin:0 0 8px; color:#aaa;
               text-transform:uppercase; letter-spacing:0.5px; }}
  .panel .label {{ font-size:13px; margin:6px 0; }}
  .panel .label b {{ color:#fff; }}
  .panel img {{ width:100%; height:auto; border-radius:4px; background:#000;
                display:block; }}
  .panel.missing {{ display:flex; align-items:center; justify-content:center;
                    min-height:200px; color:#666; font-style:italic; }}
  .verdict {{ display:inline-block; padding:2px 8px; border-radius:3px;
              font-size:11px; font-weight:600; text-transform:uppercase;
              letter-spacing:0.5px; }}
  .verdict.verified         {{ background:#2d5d2d; color:#d4f7d4; }}
  .verdict.needs_review     {{ background:#5d5524; color:#f7eda4; }}
  .verdict.unverified       {{ background:#5d2d2d; color:#f7d4d4; }}
  .verdict.mismatch_label_vs_shoe {{ background:#5d2d2d; color:#f7d4d4; }}
  .agree-YES  {{ color:#7fd47f; font-weight:600; }}
  .agree-NO   {{ color:#f47878; font-weight:600; }}
  .agree-NULL {{ color:#aaa;    font-weight:600; }}
  .sim {{ font-family: "SF Mono", Menlo, monospace; }}
  .summary {{ background:#262626; border-radius:8px; padding:12px 16px;
              margin-bottom:18px; font-size:14px; }}
  .summary span {{ margin-right: 18px; }}
</style>
</head>
<body>
<h1>Phase 7.5 — Visual Inspector</h1>
<div class="meta">CSV: {csv_path} · DB: {db_path} · {n} clips</div>
<div class="summary">
  <span>Total: <b>{n}</b></span>
  <span>Agree: <b class="agree-YES">{n_yes}</b></span>
  <span>Disagree: <b class="agree-NO">{n_no}</b></span>
  <span>No SKU: <b class="agree-NULL">{n_null}</b></span>
</div>
{clips}
</body>
</html>
"""

_CLIP = """<div class="clip">
  <h2>{stem} · existing <span class="agree-{agree}">{existing_sku}</span> ({existing_model})
      → chosen <b>{chosen_sku}</b> ({chosen_model})
      · sim <span class="sim">{similarity}</span>
      · <span class="verdict {verdict}">{verdict}</span>
      · agree <span class="agree-{agree}">{agree}</span></h2>
  <div class="row">
    <div class="panel">
      <h3>Best frame Gemini picked</h3>
      {frame_img}
      <div class="label">t={best_frame_t}s</div>
    </div>
    <div class="panel">
      <h3>Cropped query (DINOv2 input)</h3>
      {crop_img}
      <div class="label">bbox: {bbox}</div>
    </div>
    <div class="panel">
      <h3>Existing DB ({existing_sku})</h3>
      {existing_img}
      <div class="label"><b>{existing_model}</b><br>{existing_cw}</div>
    </div>
    <div class="panel">
      <h3>Path B chose ({chosen_sku})</h3>
      {chosen_img}
      <div class="label"><b>{chosen_model}</b><br>top: {top_candidates}</div>
    </div>
  </div>
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--db",  required=True)
    ap.add_argument("--query-images-dir", default="",
                    help="Dir where factcheck saved <stem>_crop.jpg and <stem>_frame.jpg.")
    ap.add_argument("--out", default="/tmp/factcheck_inspector.html")
    args = ap.parse_args()

    csv_path = Path(args.csv).resolve()
    db_path  = Path(args.db).resolve()
    out_path = Path(args.out).resolve()

    folders = _load_video_paths(str(db_path))

    rows: list[dict] = []
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))

    print(f"Inspector — processing {len(rows)} rows")
    clip_blocks: list[str] = []
    n_yes = sum(1 for r in rows if r.get("agree") == "YES")
    n_no  = sum(1 for r in rows if r.get("agree") == "NO")
    n_null = sum(1 for r in rows if r.get("agree") == "NULL")

    qdir = Path(args.query_images_dir) if args.query_images_dir else None

    for i, r in enumerate(rows, 1):
        stem = r["stem"]
        existing_sku = r.get("existing_sku", "")
        chosen_sku   = r.get("chosen_sku",   "")
        folder_path  = folders.get(stem, "")
        video        = _find_video(folder_path, stem)

        print(f"[{i}/{len(rows)}] {stem} — fetching images")

        # Frame: prefer saved chosen frame, else extract midpoint from video
        frame_bytes = _read_or_none(qdir / f"{stem}_frame.jpg") if qdir else None
        if frame_bytes is None and video:
            frame_bytes = _keyframe_bytes(video)

        crop_bytes = _read_or_none(qdir / f"{stem}_crop.jpg") if qdir else None
        ex_bytes   = _kicksdb_image(existing_sku)
        ch_bytes   = _kicksdb_image(chosen_sku)

        def _img(data):
            if data is None:
                return '<div class="panel missing">no image</div>'
            return f'<img src="{_b64_image(data)}" alt="">'

        clip_blocks.append(_CLIP.format(
            stem            = stem,
            agree           = r.get("agree", "") or "NULL",
            existing_sku    = existing_sku or "—",
            existing_model  = r.get("existing_model", "") or "",
            existing_cw     = r.get("existing_cw", "")    or "",
            chosen_sku      = chosen_sku or "—",
            chosen_model    = r.get("chosen_model", "")   or "",
            similarity      = r.get("similarity", "")     or "",
            verdict         = r.get("verdict", "")        or "unverified",
            top_candidates  = r.get("top_candidates", "") or "",
            best_frame_t    = r.get("best_frame_t", "")   or "?",
            bbox            = r.get("bbox", "")           or "—",
            frame_img       = _img(frame_bytes),
            crop_img        = _img(crop_bytes),
            existing_img    = _img(ex_bytes),
            chosen_img      = _img(ch_bytes),
        ))

    html = _HTML.format(
        csv_name = csv_path.name,
        csv_path = str(csv_path),
        db_path  = str(db_path),
        n        = len(rows),
        n_yes    = n_yes,
        n_no     = n_no,
        n_null   = n_null,
        clips    = "\n".join(clip_blocks),
    )

    out_path.write_text(html)
    print(f"\nWrote {out_path}  ({out_path.stat().st_size // 1024} KB)")
    print(f"Open it: open {out_path}")


if __name__ == "__main__":
    main()
