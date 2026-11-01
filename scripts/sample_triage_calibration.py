#!/usr/bin/env python3
"""
scripts/sample_triage_calibration.py
===================================
Run local M4 open-vocabulary vision triage (YOLO-World v2 on MPS) across
a 500-file stratified sample from SACC's recovered media catalog.

Separates:
  1. Sneaker Candidate (Shoe/Sneaker/Shoebox detected, no person)
  2. Sneaker with Person (Shoe detected alongside person, e.g. on-foot)
  3. Personal / Family (Person/Face/Baby detected, no shoe)
  4. Other / Unclassified (Neither detected with confidence)

Generates:
  - JSON results: /Users/daplug/Documents/SACC_Data/calibration/sample_500_results.json
  - Visual HTML Deck: /Users/daplug/Documents/SACC_Data/calibration/sample_500_deck.html
"""

import os
import sys
import json
import time
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

import cv2
import torch
from ultralytics import YOLOWorld

DB_PATH = Path.home() / "Documents/SACC_Data/library/staging/sacc-library.sqlite3"
OUT_DIR = Path.home() / "Documents/SACC_Data/calibration"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VOCAB = [
    "sneaker", "athletic shoe", "shoe", "shoebox",
    "person", "face", "baby", "child",
    "document", "receipt", "food", "car"
]

SHOE_CLASSES = {"sneaker", "athletic shoe", "shoe", "shoebox"}
PERSON_CLASSES = {"person", "face", "baby", "child"}


def get_stratified_sample(db_path: Path, limit: int = 500):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Sneaker-keyword candidates (up to 100)
    c.execute("""
        SELECT id, original_name, original_path, media_type, mime_type, recovered_path, effective_date, gps_lat, gps_lon
        FROM library_occurrences
        WHERE (original_path LIKE '%Jordan%' OR original_path LIKE '%Shoe%' OR original_name LIKE '%Jordan%' OR original_name LIKE '%Nike%')
          AND file_size_bytes > 0
        ORDER BY RANDOM()
        LIMIT 100;
    """)
    shoe_candidates = [dict(r) for r in c.fetchall()]

    # 2. Known personal candidates (up to 50)
    c.execute("""
        SELECT id, original_name, original_path, media_type, mime_type, recovered_path, effective_date, gps_lat, gps_lon
        FROM library_occurrences
        WHERE (original_path LIKE '%Baby Pic%' OR original_path LIKE '%Isaiah%' OR original_path LIKE '%Family%')
          AND file_size_bytes > 0
        ORDER BY RANDOM()
        LIMIT 50;
    """)
    personal_candidates = [dict(r) for r in c.fetchall()]

    # 3. Stratified general archive across years (fill remainder up to limit)
    existing_ids = {r['id'] for r in shoe_candidates + personal_candidates}
    remainder = limit - len(existing_ids)
    
    c.execute(f"""
        SELECT id, original_name, original_path, media_type, mime_type, recovered_path, effective_date, gps_lat, gps_lon
        FROM library_occurrences
        WHERE file_size_bytes > 0
          AND id NOT IN ({','.join('?' for _ in existing_ids)})
        ORDER BY RANDOM()
        LIMIT {remainder};
    """, list(existing_ids))
    general_sample = [dict(r) for r in c.fetchall()]
    conn.close()

    total = shoe_candidates + personal_candidates + general_sample
    print(f"Selected {len(total)} sample items (Shoe targets: {len(shoe_candidates)}, Personal targets: {len(personal_candidates)}, General: {len(general_sample)})")
    return total


def extract_video_frame(video_path: str, out_path: str) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", "00:00:01",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "3",
            out_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False


def run_calibration():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing YOLO-World v2 on MPS...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLOWorld("yolov8s-worldv2.pt")
    model.set_classes(VOCAB)

    sample = get_stratified_sample(DB_PATH, 500)
    thumbs_dir = OUT_DIR / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    results = []
    counts = {
        "sneaker_only": 0,
        "sneaker_with_person": 0,
        "personal_only": 0,
        "other_unclassified": 0,
        "error": 0
    }

    start_time = time.time()
    for idx, item in enumerate(sample, 1):
        file_path = item["recovered_path"]
        is_video = item["media_type"] == "video"
        thumb_name = f"{item['id'][:16]}.jpg"
        thumb_path = str(thumbs_dir / thumb_name)

        target_img = file_path
        if is_video:
            ok = extract_video_frame(file_path, thumb_path)
            if ok:
                target_img = thumb_path
            else:
                counts["error"] += 1
                results.append({**item, "category": "error", "detections": [], "notes": "Failed video frame extraction"})
                continue
        else:
            # Create a lightweight web preview thumbnail
            try:
                img = cv2.imread(file_path)
                if img is not None:
                    h, w = img.shape[:2]
                    scale = 400.0 / max(h, w)
                    if scale < 1.0:
                        img = cv2.resize(img, (int(w * scale), int(h * scale)))
                    cv2.imwrite(thumb_path, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                else:
                    target_img = file_path
            except Exception:
                pass

        try:
            preds = model.predict(target_img, conf=0.18, device=device, verbose=False)
            boxes = []
            shoe_max_conf = 0.0
            person_max_conf = 0.0

            for p in preds:
                for b in p.boxes:
                    cls_id = int(b.cls[0].item())
                    name = VOCAB[cls_id]
                    conf = float(b.conf[0].item())
                    boxes.append({"class": name, "conf": round(conf, 3)})
                    if name in SHOE_CLASSES:
                        shoe_max_conf = max(shoe_max_conf, conf)
                    elif name in PERSON_CLASSES:
                        person_max_conf = max(person_max_conf, conf)

            # Categorize
            if shoe_max_conf >= 0.20 and person_max_conf < 0.20:
                cat = "sneaker_only"
            elif shoe_max_conf >= 0.20 and person_max_conf >= 0.20:
                cat = "sneaker_with_person"
            elif person_max_conf >= 0.20 and shoe_max_conf < 0.20:
                cat = "personal_only"
            else:
                cat = "other_unclassified"

            counts[cat] += 1
            results.append({
                "id": item["id"],
                "original_name": item["original_name"],
                "original_path": item["original_path"],
                "media_type": item["media_type"],
                "effective_date": item["effective_date"],
                "has_gps": bool(item["gps_lat"]),
                "category": cat,
                "shoe_conf": round(shoe_max_conf, 3),
                "person_conf": round(person_max_conf, 3),
                "detections": boxes,
                "thumb_rel": f"thumbnails/{thumb_name}"
            })

        except Exception as e:
            counts["error"] += 1
            results.append({**item, "category": "error", "detections": [], "notes": str(e)})

        if idx % 50 == 0 or idx == len(sample):
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {idx}/{len(sample)} ({rate:.1f} files/sec) — Shoes: {counts['sneaker_only']}, Shoes+Person: {counts['sneaker_with_person']}, Personal: {counts['personal_only']}, Other: {counts['other_unclassified']}")

    # Save JSON results
    json_path = OUT_DIR / "sample_500_results.json"
    json_path.write_text(json.dumps({"counts": counts, "total": len(sample), "items": results}, indent=2))

    # Generate HTML Calibration Deck
    html_path = OUT_DIR / "sample_500_deck.html"
    generate_html_deck(results, counts, html_path)

    print("\n" + "=" * 60)
    print("CALIBRATION COMPLETE")
    print(f"Total Processed: {len(sample)}")
    print(f"  • Sneaker Only (Pure Shoe Content)  : {counts['sneaker_only']} ({counts['sneaker_only']/len(sample)*100:.1f}%)")
    print(f"  • Sneaker with Person (On-foot/Hold): {counts['sneaker_with_person']} ({counts['sneaker_with_person']/len(sample)*100:.1f}%)")
    print(f"  • Personal Only (Family/Selfies)    : {counts['personal_only']} ({counts['personal_only']/len(sample)*100:.1f}%)")
    print(f"  • Other / Unclassified (Objects/etc): {counts['other_unclassified']} ({counts['other_unclassified']/len(sample)*100:.1f}%)")
    print(f"  • Errors                            : {counts['error']}")
    print(f"JSON Results: file://{json_path}")
    print(f"HTML Visual Deck: file://{html_path}")
    print("=" * 60)


def generate_html_deck(items, counts, out_path: Path):
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SACC 500-File Triage Calibration Deck</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }}
    h1 {{ color: #ffffff; margin-bottom: 8px; }}
    .stats-bar {{ display: flex; gap: 16px; margin: 20px 0; flex-wrap: wrap; }}
    .stat-card {{ background: #1e1e1e; border: 1px solid #333; border-radius: 8px; padding: 12px 18px; min-width: 150px; }}
    .stat-val {{ font-size: 24px; font-weight: bold; margin-top: 4px; }}
    .c-sneaker {{ color: #4ade80; }}
    .c-both {{ color: #fbbf24; }}
    .c-personal {{ color: #f87171; }}
    .c-other {{ color: #94a3b8; }}
    .filter-btn {{ background: #2a2a2a; border: 1px solid #444; color: #fff; padding: 8px 14px; border-radius: 6px; cursor: pointer; margin-right: 8px; }}
    .filter-btn.active {{ background: #2563eb; border-color: #3b82f6; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: #1a1a1a; border: 1px solid #2e2e2e; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }}
    .card img {{ width: 100%; height: 180px; object-fit: cover; background: #000; }}
    .card-body {{ padding: 10px; font-size: 12px; display: flex; flex-direction: column; gap: 4px; flex-grow: 1; }}
    .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; width: fit-content; }}
    .bg-sneaker {{ background: #14532d; color: #86efac; }}
    .bg-both {{ background: #713f12; color: #fde047; }}
    .bg-personal {{ background: #7f1d1d; color: #fca5a5; }}
    .bg-other {{ background: #334155; color: #cbd5e1; }}
    .dets {{ color: #888; font-family: monospace; font-size: 10px; margin-top: 4px; max-height: 40px; overflow-y: auto; }}
  </style>
</head>
<body>
  <h1>SACC Triage Calibration Deck (500 Samples)</h1>
  <p style="color: #888;">Local M4 YOLO-World v2 open-vocabulary inference on recovered Takeout media.</p>

  <div class="stats-bar">
    <div class="stat-card"><div>Total Sampled</div><div class="stat-val">{len(items)}</div></div>
    <div class="stat-card"><div>Sneakers Only</div><div class="stat-val c-sneaker">{counts['sneaker_only']}</div></div>
    <div class="stat-card"><div>Sneakers + Person</div><div class="stat-val c-both">{counts['sneaker_with_person']}</div></div>
    <div class="stat-card"><div>Personal Only</div><div class="stat-val c-personal">{counts['personal_only']}</div></div>
    <div class="stat-card"><div>Other / Unclassified</div><div class="stat-val c-other">{counts['other_unclassified']}</div></div>
  </div>

  <div>
    <button class="filter-btn active" onclick="filterCat('all')">Show All ({len(items)})</button>
    <button class="filter-btn" onclick="filterCat('sneaker_only')">Sneakers Only ({counts['sneaker_only']})</button>
    <button class="filter-btn" onclick="filterCat('sneaker_with_person')">Sneakers + Person ({counts['sneaker_with_person']})</button>
    <button class="filter-btn" onclick="filterCat('personal_only')">Personal Only ({counts['personal_only']})</button>
    <button class="filter-btn" onclick="filterCat('other_unclassified')">Other ({counts['other_unclassified']})</button>
  </div>

  <div class="grid" id="grid">
"""
    for it in items:
        cat = it.get('category', 'other_unclassified')
        badge_cls = {
            'sneaker_only': 'bg-sneaker',
            'sneaker_with_person': 'bg-both',
            'personal_only': 'bg-personal',
            'other_unclassified': 'bg-other'
        }.get(cat, 'bg-other')
        label = cat.replace('_', ' ').title()
        det_str = ", ".join(f"{d['class']} ({d['conf']})" for d in it.get('detections', [])) or "None"
        date_str = it.get('effective_date') or "No date"

        html += f"""
    <div class="card" data-cat="{cat}">
      <img src="{it.get('thumb_rel', '')}" loading="lazy" alt="thumb">
      <div class="card-body">
        <span class="badge {badge_cls}">{label}</span>
        <div style="font-weight: 500; word-break: break-all;">{it.get('original_name')}</div>
        <div style="color: #666;">Date: {date_str} | GPS: {'Yes' if it.get('has_gps') else 'No'}</div>
        <div class="dets">{det_str}</div>
      </div>
    </div>
"""

    html += """
  </div>

  <script>
    function filterCat(cat) {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      event.target.classList.add('active');
      document.querySelectorAll('.card').forEach(c => {
        if (cat === 'all' || c.getAttribute('data-cat') === cat) {
          c.style.display = 'flex';
        } else {
          c.style.display = 'none';
        }
      });
    }
  </script>
</body>
</html>
"""
    out_path.write_text(html)


if __name__ == "__main__":
    run_calibration()
