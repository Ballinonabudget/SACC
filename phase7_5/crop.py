"""Crop an image to a normalized bbox (returned by Gemini)."""
from __future__ import annotations

import io
from PIL import Image


def crop_to_bbox(image_path: str, bbox: dict, padding: float = 0.05) -> bytes:
    """
    bbox: {"x_min": 0.0..1.0, "y_min": 0.0..1.0, "x_max": 0.0..1.0, "y_max": 0.0..1.0}
    padding: fraction of image dims to expand the box by (each side).
    Returns JPEG bytes of the crop.
    """
    img = Image.open(image_path).convert("RGB")
    W, H = img.size

    x0 = max(0,    int((float(bbox["x_min"]) - padding) * W))
    y0 = max(0,    int((float(bbox["y_min"]) - padding) * H))
    x1 = min(W,    int((float(bbox["x_max"]) + padding) * W))
    y1 = min(H,    int((float(bbox["y_max"]) + padding) * H))
    if x1 <= x0 or y1 <= y0:
        # Bad bbox — return uncropped image
        x0, y0, x1, y1 = 0, 0, W, H

    crop = img.crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def normalize_bbox(bbox) -> dict | None:
    """
    Accepts a bbox in any of these shapes and returns dict
    {x_min, y_min, x_max, y_max} in [0,1], or None if invalid.

      {"x_min":..., "y_min":..., "x_max":..., "y_max":...}     — preferred
      [x_min, y_min, x_max, y_max]                              — list
      {"ymin":..., "xmin":..., "ymax":..., "xmax":...}          — Gemini default
      [ymin, xmin, ymax, xmax]                                  — Gemini default order
    """
    if not bbox:
        return None
    try:
        if isinstance(bbox, dict):
            if "x_min" in bbox and "x_max" in bbox:
                d = {k: float(bbox[k]) for k in ("x_min", "y_min", "x_max", "y_max")}
            elif "xmin" in bbox or "ymin" in bbox:
                d = {
                    "x_min": float(bbox.get("xmin", bbox.get("x_min", 0))),
                    "y_min": float(bbox.get("ymin", bbox.get("y_min", 0))),
                    "x_max": float(bbox.get("xmax", bbox.get("x_max", 1))),
                    "y_max": float(bbox.get("ymax", bbox.get("y_max", 1))),
                }
            else:
                return None
        elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            # Could be [x_min,y_min,x_max,y_max] or [y_min,x_min,y_max,x_max].
            # We default to Gemini's [y,x,y,x] but try to detect.
            a, b, c, d_ = [float(v) for v in bbox]
            # Gemini sometimes returns ints in 0..1000 space; normalize.
            if max(a, b, c, d_) > 1.5:
                a, b, c, d_ = a / 1000.0, b / 1000.0, c / 1000.0, d_ / 1000.0
            d = {"y_min": a, "x_min": b, "y_max": c, "x_max": d_}
        else:
            return None

        # If any value > 1, assume 0..1000 scale and normalize
        if max(d.values()) > 1.5:
            d = {k: v / 1000.0 for k, v in d.items()}
        # Clamp to [0,1]
        d = {k: max(0.0, min(1.0, v)) for k, v in d.items()}
        if d["x_max"] <= d["x_min"] or d["y_max"] <= d["y_min"]:
            return None
        return d
    except Exception:
        return None
