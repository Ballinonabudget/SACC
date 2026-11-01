"""
stage0_triage.py — Phase B Stage 0 (cheap triage)
==================================================
Per-clip detection-only pass that decides whether a clip warrants any
downstream identification work. This is the cost gate of the v2 pipeline:
the 90%+ of clips that are B-roll, transitions, talking heads, or
incidental shots are routed to the archive at zero API cost.

Per clip, writes one JSON to `<folder>/stage0/<stem>.json`:

    {
        "schema_version":                 "stage0-1.0",
        "clip_stem":                      "...",
        "clip_path":                      "...",
        "duration_sec":                   12.4,
        "shoe_present":                   true,
        "hand_interaction":               false,
        "audio_present_in_window":        true,
        "duration_with_shoe_visible_sec": 6.2,
        "frame_count":                    5,
        "frames_with_shoe":               3,
        "frames_with_hand":               1,
        "shoe_max_conf":                  0.41,
        "hand_max_conf":                  0.17,
        "analysed_at":                    "2026-06-12T..."
    }

Tier assignment is INTENTIONALLY left out of this module. The Tier 3/4
duration threshold needs operator calibration (per the spec); once
locked, tier classification is a thin layer over these fields.

Detector: YOLO-World v2 small (open-vocab, MPS on M4). Audio: webrtcvad.

Usage:
    python stage0_triage.py --root "/Volumes/Team Bank 12/5 May 2019/" --device mps
    python stage0_triage.py --root <root> --device cpu --limit 30 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import webrtcvad
from ultralytics import YOLOWorld

VIDEO_EXTS    = {".mov", ".mp4", ".m4v"}
SHOE_VOCAB    = ["shoe", "sneaker", "athletic shoe", "footwear"]
HAND_VOCAB    = ["hand", "arm"]
DETECT_VOCAB  = SHOE_VOCAB + HAND_VOCAB

# Class -> bucket the detector vocab maps into
_BUCKET = {**{w: "shoe" for w in SHOE_VOCAB}, **{w: "hand" for w in HAND_VOCAB}}

DEFAULT_N_FRAMES        = 5
DEFAULT_DET_CONF        = 0.10     # detector confidence threshold
DEFAULT_IOU_THRESHOLD   = 0.01     # any overlap counts as hand interaction
DEFAULT_VAD_AGGRESSIVE  = 2        # 0..3, higher = more aggressive speech filter
VAD_FRAME_MS            = 30       # webrtcvad supports 10/20/30 ms
VAD_SAMPLE_RATE         = 16000
_THIS_DIR = Path(__file__).resolve().parent
_FFMPEG   = str(_THIS_DIR / "ffmpeg")  # bundled binary; falls back to PATH


# ── Frame sampling ────────────────────────────────────────────────────────────

def _open_clip(clip_path: str):
    cap = cv2.VideoCapture(clip_path)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps      = float(cap.get(cv2.CAP_PROP_FPS)) or 24.0
    duration = n_frames / fps if fps > 0 else 0.0
    return cap, n_frames, fps, duration


def _sample_frames(clip_path: str, n_samples: int) -> list[tuple[int, np.ndarray, float]]:
    """Sample `n_samples` frames evenly across the clip. Returns
    [(frame_index, frame_bgr_resized_to_long640, timestamp_sec), ...]."""
    cap, n_frames, fps, duration = _open_clip(clip_path)
    if n_frames <= 1 or fps <= 0:
        cap.release()
        return []

    indices = [int(round(i * (n_frames - 1) / max(1, n_samples))) for i in range(1, n_samples + 1)]
    indices = [min(max(0, i), n_frames - 1) for i in indices]

    out: list[tuple[int, np.ndarray, float]] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok or fr is None:
            continue
        h, w = fr.shape[:2]
        scale = 640 / max(h, w)
        fr = cv2.resize(fr, (int(w * scale), int(h * scale)))
        out.append((idx, fr, idx / fps))
    cap.release()
    return out


# ── Detection ────────────────────────────────────────────────────────────────

def _load_model(weights: str | None = None) -> YOLOWorld:
    w = weights or str(_THIS_DIR / "yolov8s-worldv2.pt")
    model = YOLOWorld(w)
    model.set_classes(DETECT_VOCAB)
    return model


def _bbox_iou(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> float:
    """IoU between two (x1, y1, x2, y2) bboxes."""
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    iw = max(0.0, x2 - x1); ih = max(0.0, y2 - y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _detect_frame(model: YOLOWorld, frame: np.ndarray,
                  conf: float, device: str) -> tuple[list, list]:
    """Returns (shoe_dets, hand_dets), each list of (conf, (x1,y1,x2,y2))."""
    res = model.predict(frame, conf=conf, verbose=False, device=device, imgsz=640)[0]
    names = res.names
    shoes, hands = [], []
    for b in res.boxes:
        cls   = names[int(b.cls.item())]
        c     = float(b.conf.item())
        bbox  = tuple(float(x) for x in b.xyxy[0].tolist())
        bucket = _BUCKET.get(cls)
        if bucket == "shoe":
            shoes.append((c, bbox))
        elif bucket == "hand":
            hands.append((c, bbox))
    return shoes, hands


# ── Audio voice activity ──────────────────────────────────────────────────────

def _ffmpeg_exe() -> str:
    return _FFMPEG if os.path.isfile(_FFMPEG) else "ffmpeg"


def _has_audio_track(clip_path: str) -> bool:
    """ffprobe check — avoid wasting an extract on a silent/audio-less clip."""
    try:
        out = subprocess.check_output(
            [_ffmpeg_exe().replace("ffmpeg", "ffprobe"),
             "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             clip_path],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        return b"audio" in out
    except Exception:
        return False


def _extract_audio_wav(clip_path: str, dest_wav: str) -> bool:
    """Extract mono 16kHz PCM WAV via ffmpeg. Returns True on success."""
    try:
        subprocess.run(
            [_ffmpeg_exe(), "-y", "-v", "quiet",
             "-i", clip_path, "-vn",
             "-acodec", "pcm_s16le",
             "-ar", str(VAD_SAMPLE_RATE),
             "-ac", "1",
             dest_wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=120,
        )
        return os.path.isfile(dest_wav) and os.path.getsize(dest_wav) > 0
    except Exception:
        return False


def _voice_present(wav_path: str, vad: webrtcvad.Vad,
                   min_voiced_frames: int = 5) -> bool:
    """True if at least `min_voiced_frames` 30ms windows contain speech."""
    try:
        with wave.open(wav_path, "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 \
               or wf.getframerate() != VAD_SAMPLE_RATE:
                return False
            samples_per_frame = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)
            bytes_per_frame   = samples_per_frame * 2  # int16 mono
            voiced = 0
            while True:
                buf = wf.readframes(samples_per_frame)
                if len(buf) < bytes_per_frame:
                    break
                if vad.is_speech(buf, VAD_SAMPLE_RATE):
                    voiced += 1
                    if voiced >= min_voiced_frames:
                        return True
        return False
    except Exception:
        return False


def _clip_has_voice(clip_path: str, vad: webrtcvad.Vad) -> bool:
    if not _has_audio_track(clip_path):
        return False
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        if not _extract_audio_wav(clip_path, wav):
            return False
        return _voice_present(wav, vad)


# ── Triage per clip ───────────────────────────────────────────────────────────

def triage_clip(clip_path: str, model: YOLOWorld, vad: webrtcvad.Vad,
                device: str = "mps",
                n_frames: int = DEFAULT_N_FRAMES,
                det_conf: float = DEFAULT_DET_CONF,
                iou_thresh: float = DEFAULT_IOU_THRESHOLD) -> dict:
    """Run Stage 0 detection on one clip; return the spec JSON shape."""
    cap, n_frames_total, fps, duration = _open_clip(clip_path)
    cap.release()

    frames = _sample_frames(clip_path, n_frames)

    frames_with_shoe     = 0
    frames_with_hand     = 0
    hand_interaction     = False
    shoe_max_conf        = 0.0
    hand_max_conf        = 0.0

    for _idx, frame, _ts in frames:
        shoes, hands = _detect_frame(model, frame, det_conf, device)
        if shoes:
            frames_with_shoe += 1
            shoe_max_conf = max(shoe_max_conf, max(c for c, _ in shoes))
        if hands:
            frames_with_hand += 1
            hand_max_conf = max(hand_max_conf, max(c for c, _ in hands))
        if shoes and hands:
            for _, sbb in shoes:
                for _, hbb in hands:
                    if _bbox_iou(sbb, hbb) >= iou_thresh:
                        hand_interaction = True
                        break
                if hand_interaction:
                    break

    sampled  = max(1, len(frames))
    duration_with_shoe = duration * (frames_with_shoe / sampled) if frames else 0.0

    shoe_present = frames_with_shoe > 0

    # Audio gate: only check VAD if we already think the clip is shoe-bearing
    # OR if it's a Tier 4 maybe (short clip). For first cut, run unconditionally
    # since audio is cheap; the spec's "audio_present_in_window" is a per-clip
    # bool for triage purposes and we're not yet windowing to the shoe-visible
    # subrange.
    audio_present = _clip_has_voice(clip_path, vad)

    return {
        "schema_version":                 "stage0-1.0",
        "clip_stem":                      Path(clip_path).stem,
        "clip_path":                      clip_path,
        "duration_sec":                   round(duration, 2),
        "shoe_present":                   bool(shoe_present),
        "hand_interaction":               bool(hand_interaction),
        "audio_present_in_window":        bool(audio_present),
        "duration_with_shoe_visible_sec": round(duration_with_shoe, 2),
        "frame_count":                    sampled,
        "frames_with_shoe":               frames_with_shoe,
        "frames_with_hand":               frames_with_hand,
        "shoe_max_conf":                  round(shoe_max_conf, 3),
        "hand_max_conf":                  round(hand_max_conf, 3),
        "analysed_at":                    datetime.now(timezone.utc).isoformat(),
    }


# ── Folder driver ────────────────────────────────────────────────────────────

def _iter_clips(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip junk dirs
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and d not in ("_proxy", "_anchor_proxies", "stage0", "json", "_archive_db")]
        for f in sorted(filenames):
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                out.append(os.path.join(dirpath, f))
    return out


def _already_triaged(clip_path: str) -> bool:
    out_dir = os.path.join(os.path.dirname(clip_path), "stage0")
    out_path = os.path.join(out_dir, f"{Path(clip_path).stem}.json")
    if not os.path.isfile(out_path):
        return False
    try:
        with open(out_path) as f:
            d = json.load(f)
        return bool(d.get("analysed_at"))
    except Exception:
        return False


def run(root: str, device: str = "mps", n_frames: int = DEFAULT_N_FRAMES,
        det_conf: float = DEFAULT_DET_CONF, dry_run: bool = False,
        limit: int = 0, force: bool = False,
        vad_aggressive: int = DEFAULT_VAD_AGGRESSIVE) -> dict:
    if not os.path.isdir(root):
        raise SystemExit(f"root not found: {root}")

    print(f"[stage0] root          : {root}")
    print(f"[stage0] device        : {device}")
    print(f"[stage0] frames/clip   : {n_frames}")
    print(f"[stage0] det conf      : {det_conf}")
    print(f"[stage0] dry_run       : {dry_run}")

    clips = _iter_clips(root)
    if limit:
        clips = clips[:limit]
    print(f"[stage0] clips found   : {len(clips)}")

    if not force:
        new = [c for c in clips if not _already_triaged(c)]
        skipped = len(clips) - len(new)
        if skipped:
            print(f"[stage0] skipping {skipped} already-triaged clip(s)  "
                  f"(use --force to override)")
        clips = new

    if dry_run:
        for c in clips[:10]:
            print(f"  DRY: would triage {c}")
        if len(clips) > 10:
            print(f"  … and {len(clips) - 10} more")
        return {"would_triage": len(clips)}

    print(f"[stage0] loading detector …")
    t0 = time.time()
    model = _load_model()
    vad   = webrtcvad.Vad(vad_aggressive)
    print(f"[stage0] detector ready  ({time.time()-t0:.1f}s)")

    stats = {"processed": 0, "errors": 0, "shoe_present_true": 0,
             "hand_interaction_true": 0, "audio_present_true": 0,
             "elapsed_sec": 0.0}

    start = time.time()
    for i, clip in enumerate(clips, 1):
        out_dir  = os.path.join(os.path.dirname(clip), "stage0")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{Path(clip).stem}.json")
        try:
            result = triage_clip(clip, model, vad, device=device,
                                 n_frames=n_frames, det_conf=det_conf)
        except Exception as e:
            stats["errors"] += 1
            print(f"  [{i:4d}/{len(clips)}] ERROR {Path(clip).name}: {e}")
            continue

        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        stats["processed"] += 1
        if result["shoe_present"]:           stats["shoe_present_true"] += 1
        if result["hand_interaction"]:       stats["hand_interaction_true"] += 1
        if result["audio_present_in_window"]: stats["audio_present_true"] += 1

        flags = []
        if result["shoe_present"]:        flags.append("S")
        if result["hand_interaction"]:    flags.append("H")
        if result["audio_present_in_window"]: flags.append("A")
        flag_str = "".join(flags) or "-"
        print(f"  [{i:4d}/{len(clips)}] {flag_str:3s}  "
              f"d={result['duration_sec']:5.1f}s  "
              f"shoe_d={result['duration_with_shoe_visible_sec']:5.1f}s  "
              f"shoe_conf={result['shoe_max_conf']:.2f}  "
              f"hand_conf={result['hand_max_conf']:.2f}  "
              f"{Path(clip).stem}")

    stats["elapsed_sec"] = round(time.time() - start, 1)
    print()
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k:25s} {v}")
    print("=" * 60)
    return stats


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--root", required=True,
                   help="Folder root to walk for video files")
    p.add_argument("--device", default="mps", choices=["mps", "cpu"],
                   help="Inference backend (default: mps)")
    p.add_argument("--frames", type=int, default=DEFAULT_N_FRAMES,
                   help=f"Frames sampled per clip (default: {DEFAULT_N_FRAMES})")
    p.add_argument("--conf", type=float, default=DEFAULT_DET_CONF,
                   help=f"Detector confidence threshold (default: {DEFAULT_DET_CONF})")
    p.add_argument("--vad-aggressive", type=int, default=DEFAULT_VAD_AGGRESSIVE,
                   choices=[0, 1, 2, 3],
                   help="webrtcvad aggressiveness 0-3 (default: 2)")
    p.add_argument("--limit", type=int, default=0,
                   help="Process at most N clips (0 = all)")
    p.add_argument("--force", action="store_true",
                   help="Re-triage clips that already have a stage0 JSON")
    p.add_argument("--dry-run", action="store_true",
                   help="List clips that would be processed; do nothing")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(root=args.root, device=args.device, n_frames=args.frames,
        det_conf=args.conf, dry_run=args.dry_run, limit=args.limit,
        force=args.force, vad_aggressive=args.vad_aggressive)
