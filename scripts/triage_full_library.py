#!/usr/bin/env python3
"""
scripts/triage_full_library.py
==============================
Full-library on-device vision triage runner using YOLO-World v2 on Apple M1 (MPS).

Separates all 87,982 recovered Takeout media files into:
  - 'non_personal' (Sneaker only or Sneaker with Person) -> SACC candidate pool
  - 'personal' (People/faces/family, zero shoes) -> Private local vault
  - 'unknown' (Neither detected with confidence) -> Operator review queue

Guarantees:
  1. 100% on-device & local (Apple M1 GPU). ZERO tokens, ZERO cloud API calls.
  2. Resumable checkpointing via SQLite.
  3. Never overwrites manual user privacy decisions.
  4. Non-destructive: originals and recovered files are untouched.
"""

import os
import sys
import json
import time
import signal
import sqlite3
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

import cv2
import torch
from ultralytics import YOLOWorld

DB_PATH = Path.home() / "Documents/SACC_Data/library/staging/sacc-library.sqlite3"
LOG_DIR = Path.home() / "Documents/SACC_Data/calibration"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "triage_progress.log"

VOCAB = [
    "sneaker", "athletic shoe", "shoe", "shoebox",
    "person", "face", "baby", "child",
    "document", "receipt", "food", "car"
]

SHOE_CLASSES = {"sneaker", "athletic shoe", "shoe", "shoebox"}
PERSON_CLASSES = {"person", "face", "baby", "child"}

BATCH_SIZE = 16
COMMIT_INTERVAL = 200

# Global shutdown flag
running = True

def handle_signal(sig, frame):
    global running
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Graceful shutdown requested. Finishing current batch...", flush=True)
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def log_msg(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(formatted + "\n")


def ensure_triage_table(con: sqlite3.Connection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS library_triage_detections (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            shoe_conf REAL NOT NULL,
            person_conf REAL NOT NULL,
            detections_json TEXT NOT NULL,
            processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_triage_cat ON library_triage_detections(category);")
    con.commit()


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


def main():
    global running

    if not DB_PATH.is_file():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    log_msg("=== SACC FULL-LIBRARY VISION TRIAGE START ===")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    log_msg(f"Initializing YOLO-World v2 on device: {device} (Apple M1)...")
    
    model = YOLOWorld("yolov8s-worldv2.pt")
    model.set_classes(VOCAB)

    con = sqlite3.connect(DB_PATH, timeout=60.0)
    con.row_factory = sqlite3.Row
    ensure_triage_table(con)

    # Check total already processed vs remaining
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM library_occurrences;")
    total_occurrences = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM library_triage_detections;")
    already_done = cur.fetchone()[0]

    remaining = total_occurrences - already_done
    log_msg(f"Total occurrences: {total_occurrences} | Already processed: {already_done} | Remaining: {remaining}")

    if remaining == 0:
        log_msg("All occurrences have already been classified! Nothing to do.")
        con.close()
        return

    # Query unclassified items
    cur.execute("""
        SELECT o.id, o.recovered_path, o.media_type, o.overrides_json, o.privacy
        FROM library_occurrences o
        LEFT JOIN library_triage_detections d ON o.id = d.id
        WHERE d.id IS NULL
        ORDER BY o.rowid;
    """)

    scratch_dir = Path(tempfile.gettempdir()) / "sacc_triage_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    processed_in_run = 0
    start_time = time.time()
    batch_items = []
    pending_updates = []
    pending_detections = []

    cat_counts = {"non_personal": 0, "personal": 0, "unknown": 0, "error": 0}

    def flush_batch():
        nonlocal pending_updates, pending_detections
        if not pending_detections:
            return
        with con:
            con.executemany("""
                INSERT OR REPLACE INTO library_triage_detections(id, category, shoe_conf, person_conf, detections_json)
                VALUES (?, ?, ?, ?, ?);
            """, pending_detections)

            for item_id, priv_label, needs_att in pending_updates:
                con.execute("""
                    UPDATE library_occurrences
                    SET privacy = ?, needs_attention = ?
                    WHERE id = ? AND json_extract(overrides_json, '$.privacy') IS NULL;
                """, (priv_label, needs_att, item_id))
        pending_updates = []
        pending_detections = []

    try:
        while running:
            row = cur.fetchone()
            if row is None:
                # End of results
                break

            batch_items.append(dict(row))

            if len(batch_items) >= BATCH_SIZE:
                # Process batch
                paths_to_predict = []
                temp_video_files = []

                for item in batch_items:
                    fp = item["recovered_path"]
                    if item["media_type"] == "video":
                        tmp_thumb = str(scratch_dir / f"{item['id'][:16]}.jpg")
                        if extract_video_frame(fp, tmp_thumb):
                            paths_to_predict.append(tmp_thumb)
                            temp_video_files.append(tmp_thumb)
                        else:
                            paths_to_predict.append(None)
                    else:
                        paths_to_predict.append(fp)

                # Filter valid
                valid_indices = [i for i, p in enumerate(paths_to_predict) if p and os.path.exists(p)]
                valid_paths = [paths_to_predict[i] for i in valid_indices]

                preds = []
                if valid_paths:
                    try:
                        preds = model.predict(valid_paths, batch=len(valid_paths), conf=0.18, device=device, verbose=False)
                    except Exception as e:
                        log_msg(f"Batch prediction error: {e}")
                        preds = []

                # Map predictions back
                pred_map = {}
                for idx, p in zip(valid_indices, preds):
                    pred_map[idx] = p

                for idx, item in enumerate(batch_items):
                    if idx in pred_map:
                        p = pred_map[idx]
                        shoe_max = 0.0
                        person_max = 0.0
                        boxes = []
                        for b in p.boxes:
                            cls_id = int(b.cls[0].item())
                            name = VOCAB[cls_id]
                            conf = float(b.conf[0].item())
                            boxes.append({"class": name, "conf": round(conf, 3)})
                            if name in SHOE_CLASSES:
                                shoe_max = max(shoe_max, conf)
                            elif name in PERSON_CLASSES:
                                person_max = max(person_max, conf)

                        # Decision rule
                        if shoe_max >= 0.20:
                            cat = "non_personal"  # Sneaker only or Sneaker with Person
                            needs_att = 0
                        elif person_max >= 0.20 and shoe_max < 0.20:
                            cat = "personal"      # Pure personal / family
                            needs_att = 0
                        else:
                            cat = "unknown"       # Neither detected confidently
                            needs_att = 1

                        cat_counts[cat] += 1
                        pending_detections.append((item["id"], cat, round(shoe_max, 3), round(person_max, 3), json.dumps(boxes)))
                        pending_updates.append((item["id"], cat, needs_att))
                    else:
                        cat_counts["error"] += 1
                        pending_detections.append((item["id"], "error", 0.0, 0.0, "[]"))

                # Clean temporary video keyframes
                for tmp in temp_video_files:
                    try: os.remove(tmp)
                    except OSError: pass

                processed_in_run += len(batch_items)
                batch_items = []

                if len(pending_detections) >= COMMIT_INTERVAL:
                    flush_batch()

                if processed_in_run % 500 == 0:
                    elapsed = time.time() - start_time
                    rate = processed_in_run / elapsed if elapsed > 0 else 0
                    percent = (already_done + processed_in_run) / total_occurrences * 100
                    rem_time = (total_occurrences - (already_done + processed_in_run)) / rate / 60 if rate > 0 else 0
                    log_msg(f"Progress: {already_done + processed_in_run}/{total_occurrences} ({percent:.1f}%) | Speed: {rate:.1f} files/s | ETA: {rem_time:.1f}m | SACC Candidates: {cat_counts['non_personal']} | Personal: {cat_counts['personal']} | Review: {cat_counts['unknown']}")

        # Flush any remaining items in last partial batch
        if batch_items:
            for item in batch_items:
                pending_detections.append((item["id"], "unknown", 0.0, 0.0, "[]"))
                pending_updates.append((item["id"], "unknown", 1))
            processed_in_run += len(batch_items)
            flush_batch()

    finally:
        flush_batch()
        con.close()
        try:
            for f in scratch_dir.glob("*.jpg"):
                f.unlink(missing_ok=True)
        except Exception:
            pass

    elapsed = time.time() - start_time
    rate = processed_in_run / elapsed if elapsed > 0 else 0
    log_msg("=== TRIAGE RUN FINISHED ===")
    log_msg(f"Processed in this run: {processed_in_run} in {elapsed/60:.1f} min ({rate:.1f} files/s)")
    log_msg(f"Counts: SACC/Sneaker: {cat_counts['non_personal']} | Personal: {cat_counts['personal']} | Unknown/Review: {cat_counts['unknown']} | Errors: {cat_counts['error']}")


if __name__ == "__main__":
    main()
