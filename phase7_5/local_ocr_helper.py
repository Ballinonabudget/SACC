"""Local OCR keyframe label detector using native Apple Vision + KicksDB verification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional

from .kicksdb_search import search_by_description

# Style code regexes
NIKE_SKU_REGEX = re.compile(r'\b([A-Z0-9]{6})[-\s]?([A-Z0-9]{3})\b', re.IGNORECASE)
TIMBERLAND_REGEX = re.compile(r'\b(TB0[A-Z0-9]{5,6})\b', re.IGNORECASE)
GENERIC_STYLE_REGEX = re.compile(r'\b([A-Z0-9]{6,7}[-\s][A-Z0-9]{3})\b', re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLKIT_VISION_BIN = Path.home() / "local-ai-toolkit" / "bin" / "apple_vision"
SACC_VISION_BIN = REPO_ROOT / "bin" / "apple_vision_ocr"
TOOLKIT_DIR = Path.home() / "local-ai-toolkit"


def _clean_style_text(text: str) -> str:
    """Normalize OCR text lines removing artificial spaces inside style codes (e.g., 'C T8527-115' -> 'CT8527-115')."""
    # Fix single letter split before 5-6 digits: C T8527 -> CT8527
    t = re.sub(r'\b([A-Z])\s+([A-Z0-9]{5,6})\b', r'\1\2', text)
    # Fix split before suffix: 8527 - 115 -> 8527-115
    t = re.sub(r'(\d{6})\s*-\s*(\d{3})', r'\1-\2', t)
    return t


def extract_candidate_skus(text_lines: List[str]) -> List[str]:
    """Extract candidate sneaker SKUs from raw OCR text lines."""
    candidates: List[str] = []
    seen: set[str] = set()

    for raw_line in text_lines:
        line = _clean_style_text(raw_line)

        # Nike / Jordan
        for m in NIKE_SKU_REGEX.finditer(line):
            sku = f"{m.group(1).upper()}-{m.group(2).upper()}"
            if sku not in seen:
                seen.add(sku)
                candidates.append(sku)

        # Timberland
        for tb in TIMBERLAND_REGEX.finditer(line):
            sku = tb.group(1).upper()
            if sku not in seen:
                seen.add(sku)
                candidates.append(sku)

        # Generic style
        for gen in GENERIC_STYLE_REGEX.finditer(line):
            sku = gen.group(1).upper().replace(" ", "-")
            if sku not in seen:
                seen.add(sku)
                candidates.append(sku)

    return candidates


def run_vision_on_image(image_path: str) -> List[str]:
    """Run Apple Vision OCR on an image and return text lines."""
    img_path = str(image_path)

    # 1. Try SACC binary first if it supports multiple/single paths
    if SACC_VISION_BIN.is_file() and os.access(SACC_VISION_BIN, os.X_OK):
        try:
            cmd = [str(SACC_VISION_BIN), img_path]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5)
            data = json.loads(out)
            if isinstance(data, list) and len(data) > 0:
                lines = data[0].get("text", [])
                if lines:
                    return lines
        except Exception:
            pass

    # 2. Try Local AI Toolkit binary
    if TOOLKIT_VISION_BIN.is_file() and os.access(TOOLKIT_VISION_BIN, os.X_OK):
        try:
            cmd = [str(TOOLKIT_VISION_BIN), img_path]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=5)
            data = json.loads(out)
            lines = [t.get("text", "") for t in data.get("text_lines", []) if t.get("text")]
            if lines:
                return lines
        except Exception:
            pass

    return []


def verify_sku_kicksdb(sku: str, source: str = "stockx") -> Optional[Dict[str, Any]]:
    """Verify SKU against KicksDB via local_ocr or kicksdb_search."""
    # 1. Try local_ocr helper
    try:
        import sys
        if str(TOOLKIT_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLKIT_DIR))
        from local_ocr import lookup_kicksdb
        prod = lookup_kicksdb(sku)
        if prod:
            return {
                "sku": prod.sku,
                "name": prod.name,
                "shoe_name": prod.name,
                "brand": prod.brand,
                "model": prod.model,
                "colorway": prod.colorway,
                "retail_price": prod.retail_price,
                "image_url": prod.image_url,
                "source": prod.source,
            }
    except Exception:
        pass

    # 2. Try kicksdb_search
    for test_source in (source, "stockx" if source != "stockx" else "goat"):
        products = search_by_description(sku, max_results=2, source=test_source)
        for p in products:
            prod_sku = (p.get("sku") or p.get("style_id") or "").upper().replace(" ", "").replace("-", "")
            cand_norm = sku.upper().replace(" ", "").replace("-", "")
            if prod_sku and cand_norm and (prod_sku == cand_norm or cand_norm in prod_sku):
                return p

    return None


def check_frames_for_label(frames: List[Dict[str, Any]],
                           source: str = "stockx",
                           verbose: bool = False) -> Optional[Dict[str, Any]]:
    """
    Inspect candidate keyframes for a shoebox label using local Apple Vision OCR.
    If a valid style code is detected and confirmed against KicksDB, return the
    verified label hit. Otherwise return None.
    """
    if not frames:
        return None

    for fr in frames:
        frame_path = fr.get("path")
        if not frame_path or not os.path.exists(frame_path):
            continue

        lines = run_vision_on_image(frame_path)
        if not lines:
            continue

        cands = extract_candidate_skus(lines)
        if verbose and cands:
            print(f"    [local_ocr] Frame {fr.get('index')} candidate SKUs: {cands}")

        for cand in cands:
            verified = verify_sku_kicksdb(cand, source=source)
            if verified:
                if verbose:
                    print(f"    [local_ocr] VERIFIED {cand} against KicksDB ({verified.get('shoe_name') or verified.get('name')})")
                return {
                    "frame": fr,
                    "sku": cand,
                    "product": verified,
                    "confidence": 1.0,
                    "source": "apple_vision_local",
                    "raw_text": lines,
                }

    return None
