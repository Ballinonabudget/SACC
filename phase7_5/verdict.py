"""Verdict matrix — converts (path, similarity, ocr_confidence) into a label."""
from __future__ import annotations

VERDICTS = {
    "verified", "verified_low_visual", "mismatch_label_vs_shoe",
    "needs_review", "unverified",
}


def classify(path: str, similarity: float | None,
             ocr_confidence: float | None = None) -> str:
    """
    path:           "ocr" or "visual"
    similarity:     max DINOv2 cosine similarity (0..1)
    ocr_confidence: Gemini's reported OCR confidence (0..1) — Path A only

    Returns one of VERDICTS.
    """
    s = similarity if similarity is not None else 0.0
    # Thresholds calibrated from observed video-frame-vs-studio-shot
    # similarity distribution (max ~0.80 for plausible matches).
    if path == "ocr":
        if s >= 0.65:
            return "verified"
        if s >= 0.45:
            return "verified_low_visual"
        return "mismatch_label_vs_shoe"
    if s >= 0.75:
        return "verified"
    if s >= 0.55:
        return "needs_review"
    return "unverified"
