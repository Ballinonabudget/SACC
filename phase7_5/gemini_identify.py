"""Gemini visual identification — image → top-N candidate descriptions."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai
from google.genai import types

_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
_REMOTE_API_ENABLED = os.getenv("SACC_REMOTE_API_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on",
}

_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").removeprefix("models/")

_PROMPT_MULTI = """You are given {n_frames} sequential frames from a short video of a sneaker.
Frame indices are 0..{n_frames_minus_1} in the order shown.

YOUR FIRST AND MOST IMPORTANT JOB: pick the BEST-FRAMED frame.

The "best frame" is the ONE frame where:
  ✓ The ENTIRE shoe is fully visible (no parts cut off by the edge of the image)
  ✓ The shoe is roughly CENTERED in the frame
  ✓ The shoe takes up a large portion of the frame (close-up, not far away)
  ✓ Side profile or 3/4 angle preferred (most distinctive view)
  ✓ NOT occluded by hands, fingers, tags, or other shoes
  ✓ In focus, not motion-blurred

REJECT frames where:
  ✗ Only part of the shoe is visible (toe-only, heel-only, partial)
  ✗ The shoe is small / far away
  ✗ Hand or fingers cover the shoe
  ✗ Two or more shoes are visible (you cannot tell which to pick)
  ✗ The shoe is on a shelf surrounded by other items

It is BETTER to pick a slightly-blurry well-framed frame than a sharp partial frame.

Then output a TIGHT bounding box around the shoe in your chosen frame, and
identify the sneaker.

Return STRICT JSON only — no markdown fences.

Schema:
{{
  "best_frame_index": 1,
  "best_frame_reason": "string",   // one short sentence explaining your choice
  "shoe_bbox": [120, 340, 780, 920],
                                   // [ymin, xmin, ymax, xmax] in 0..1000 range,
                                   // TIGHT around the visible shoe — exclude
                                   // hands, background, boxes.
                                   // The example values are illustrative ONLY —
                                   // compute real coordinates from your frame.
  "candidates": [
    {{
      "model":            "Air Jordan 1 Retro High OG",
      "colorway":         "Lost and Found",
      "search_query":     "Air Jordan 1 Lost and Found",
      "model_only_query": "Air Jordan 1 Retro High OG",
      "year":             "2022",
      "confidence":       0.85
    }}
  ],
  "label_visible": false,
  "label_sku":     ""
}}

Other rules:
- best_frame_index MUST be a valid index (0..{n_frames_minus_1}).
- shoe_bbox: integer values 0..1000. ymin < ymax, xmin < xmax.
- Up to 3 candidates ordered by confidence.
- search_query: specific marketplace query (model + colorway).
- model_only_query: broad marketplace query (model name ONLY, NO colorway).
  Colorway guesses are often wrong from limited video — model-broad search
  is critical for catching the right shoe.
- Use marketing names ("Lost and Found", "Chicago", "Bred") in search_query.
- Box-label SKU only if clearly legible. No guessing. Blurry → label_sku="".
- If no shoe is identifiable in any frame, candidates=[], label_visible=false.
"""


def identify(image_paths,
             top_n: int = 3,
             timeout_sec: int = 90) -> dict:
    """
    Run Gemini on one or more candidate frames. Returns:
      {
        "best_frame_index": int,   # which input was chosen
        "shoe_bbox": {x_min,y_min,x_max,y_max} in [0,1],
        "candidates": [...],
        "label_visible": bool,
        "label_sku": str,
      }
    """
    if not _GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    if not _REMOTE_API_ENABLED:
        raise RuntimeError(
            "Remote API access is locked; verify the SACC key and set "
            "SACC_REMOTE_API_ENABLED=true in .env"
        )

    # Accept str or list[str]
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    n = len(image_paths)

    with genai.Client(api_key=_GEMINI_KEY) as client:
        files = [client.files.upload(file=p) for p in image_paths]
        try:
            prompt = _PROMPT_MULTI.format(n_frames=n, n_frames_minus_1=n - 1)
            resp = client.models.generate_content(
                model=_MODEL,
                contents=[*files, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    http_options=types.HttpOptions(timeout=timeout_sec * 1000),
                ),
            )
            text = (resp.text or "").strip()
        finally:
            for f in files:
                try:
                    client.files.delete(name=f.name)
                except Exception:
                    pass

    try:
        data = json.loads(text)
    except Exception:
        return {
            "best_frame_index": 0,
            "shoe_bbox":        None,
            "candidates":       [],
            "label_visible":    False,
            "label_sku":        "",
            "_raw":             text,
        }

    candidates = data.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []

    bfi = data.get("best_frame_index", 0)
    try:
        bfi = int(bfi)
    except Exception:
        bfi = 0
    bfi = max(0, min(n - 1, bfi))

    return {
        "best_frame_index":  bfi,
        "best_frame_reason": str(data.get("best_frame_reason") or "").strip(),
        "shoe_bbox":         data.get("shoe_bbox"),
        "candidates":        candidates[:top_n],
        "label_visible":     bool(data.get("label_visible")),
        "label_sku":         str(data.get("label_sku") or "").strip(),
    }
