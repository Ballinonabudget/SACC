"""Extract candidate frames from a video using imageio-ffmpeg + sharpness scoring."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageFilter

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def sharpness(img: Image.Image) -> float:
    """Edge-variance sharpness score. Higher = sharper. Cheap, ~5ms per image."""
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(np.array(edges).var())


def _probe_duration(video_path: str) -> float:
    """Return duration in seconds via ffmpeg stderr parsing. Falls back to 5.0."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-i", str(video_path), "-hide_banner"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return 5.0
    for line in proc.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            try:
                hms = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = hms.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
            except Exception:
                return 5.0
    return 5.0


def extract_keyframes(video_path: str, n: int = 12,
                       output_dir: str | None = None) -> list[dict]:
    """
    Extract `n` evenly-spaced frames from a video. Returns a list of dicts:
      [{path, time_sec, sharpness, index}, ...]
    sorted by frame index ASCENDING (chronological order — Gemini sees frames
    in time order so its index references stay coherent).
    """
    duration = _probe_duration(video_path)
    # Sample slightly inside the boundaries to skip fade-ins / fade-outs.
    start = duration * 0.08
    end   = duration * 0.92
    if end <= start:
        times = [duration / 2.0]
    else:
        times = list(np.linspace(start, end, max(2, n)))

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="kf_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for i, t in enumerate(times):
        out_path = out_dir / f"kf_{i:02d}_t{t:.2f}.jpg"
        try:
            extract_keyframe(str(video_path), str(out_path), time_sec=float(t))
            with Image.open(out_path) as img:
                s = sharpness(img)
            results.append({
                "path":      str(out_path),
                "time_sec":  float(t),
                "sharpness": s,
                "index":     i,
            })
        except Exception as e:
            results.append({
                "path":      str(out_path),
                "time_sec":  float(t),
                "sharpness": 0.0,
                "index":     i,
                "error":     str(e),
            })

    # Keep chronological order — Gemini's frame_index references the order
    # we send, and chronological order is intuitive for the model.
    results.sort(key=lambda r: r["index"])
    return results


def extract_keyframe(video_path: str, output_path: str,
                     time_sec: float | None = None) -> str:
    """
    Extract one frame from `video_path` at `time_sec` (default: midpoint).
    Writes a JPEG to `output_path` and returns the path.
    """
    if time_sec is None:
        duration = _probe_duration(video_path)
        time_sec = max(0.5, duration / 2.0)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", f"{time_sec:.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return str(output_path)
