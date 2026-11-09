"""
SACC Local Photo Recognizer Pipeline
====================================
High-speed, zero-API-cost sneaker image recognition for retail store photos:
1. Local Object Detection (YOLO-World on Apple Silicon MPS): Isolates shoes, shoeboxes, and labels.
2. Local Box Label OCR (Native Apple Vision): Instant extraction of model names, 9-digit Nike/Jordan SKUs, sizes, prices.
3. Temporal Co-occurrence Clustering: Links shelf/shoe photos with nearby box labels photographed in the same aisle/session.
4. Visual Feature Embedding (CLIP on Apple Silicon MPS): Generates visual fingerprints to verify shoe silhouette.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import List, Optional, Dict, Any

from PIL import Image
import torch

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = REPO_ROOT / "yolov8s-worldv2.pt"
OCR_BINARY = REPO_ROOT / "bin" / "apple_vision_ocr"

# Regex for standard Nike / Jordan style codes: 6 digits, space/hyphen, 3 digits
NIKE_SKU_REGEX = re.compile(r'\b(\d{6})[-\s](\d{3})\b')
# Timberland style format: TB0...
TIMBERLAND_REGEX = re.compile(r'\b(TB0[A-Z0-9]{5,6})\b')
# Generic style code
GENERIC_STYLE_REGEX = re.compile(r'\b([A-Z0-9]{6,7}[-\s][A-Z0-9]{3})\b')


@dataclass
class DetectedObject:
    cls_name: str
    confidence: float
    bbox: List[int]  # [x1, y1, x2, y2]


@dataclass
class PhotoRecognitionResult:
    file_path: str
    filename: str
    capture_time: Optional[str]
    has_box_label: bool
    detected_skus: List[str]
    detected_model_text: Optional[str]
    detected_colorway_text: Optional[str]
    detected_retail_price: Optional[float]
    detected_size: Optional[str]
    detected_objects: List[Dict[str, Any]]
    visual_line_prediction: Optional[str]
    visual_confidence: float
    cluster_linked_sku: Optional[str]
    recognition_source: str  # "exact_box_ocr", "session_clustered", "visual_embedding", "pending_review"


class LocalPhotoRecognizer:
    def __init__(self, weights_path: Path = DEFAULT_WEIGHTS):
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        
        # 1. Initialize YOLO-World
        os.environ["YOLO_VERBOSE"] = "false"
        from ultralytics import YOLOWorld
        self.yolo = YOLOWorld(str(weights_path))
        self.yolo_classes = [
            "sneaker", "athletic shoe", "shoebox", "box label",
            "nike logo", "jumpman logo", "barcode label"
        ]
        self.yolo.set_classes(self.yolo_classes)

        # 2. Initialize CLIP for local visual embedding
        import clip
        self.clip_model, self.clip_preprocess = clip.load("ViT-B/32", device=self.device)
        self.candidate_lines = [
            "Nike LeBron basketball shoe",
            "Nike Kobe basketball shoe",
            "Air Jordan sneaker",
            "Nike Free Flyknit running shoe",
            "Nike Air Max athletic sneaker",
            "Timberland boot",
            "shoebox barcode label sticker"
        ]
        self.text_tokens = clip.tokenize(self.candidate_lines).to(self.device)

    def run_ocr(self, file_paths: List[str]) -> Dict[str, List[str]]:
        """Run native Apple Vision OCR on a list of image paths."""
        if not OCR_BINARY.is_file():
            return {p: [] for p in file_paths}
        
        try:
            cmd = [str(OCR_BINARY)] + file_paths
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            data = json.loads(out)
            return {item["file"]: item.get("text", []) for item in data}
        except Exception as e:
            print(f"Warning: OCR extraction failed: {e}")
            return {p: [] for p in file_paths}

    def recognize_batch(self, file_paths: List[str], metadata: Optional[List[Dict[str, Any]]] = None) -> List[PhotoRecognitionResult]:
        """Process a batch of store photos locally without external network API calls."""
        start_time = time.time()
        results: List[PhotoRecognitionResult] = []

        # 1. Run local Apple Vision OCR
        ocr_map = self.run_ocr(file_paths)

        # 2. Run local YOLO-World detection
        yolo_preds = self.yolo.predict(file_paths, conf=0.18, device=self.device, verbose=False)

        # 3. Process each photo
        for i, path in enumerate(file_paths):
            p = Path(path)
            raw_texts = ocr_map.get(path, [])
            pred = yolo_preds[i]

            # Parse detected objects
            det_objs = []
            has_box_label = False
            for box in pred.boxes:
                c_idx = int(box.cls[0].item())
                name = self.yolo_classes[c_idx]
                conf = float(box.conf[0].item())
                xyxy = [int(v) for v in box.xyxy[0].tolist()]
                det_objs.append({"class": name, "confidence": round(conf, 3), "bbox": xyxy})
                if name in ("shoebox", "box label", "barcode label"):
                    has_box_label = True

            # Extract SKUs and shoe names from OCR lines
            skus: List[str] = []
            model_text = None
            colorway_text = None
            price = None
            size = None

            for line in raw_texts:
                # Check Nike SKU
                m = NIKE_SKU_REGEX.search(line)
                if m:
                    formatted = f"{m.group(1)}-{m.group(2)}"
                    if formatted not in skus:
                        skus.append(formatted)

                # Check Timberland SKU
                tb = TIMBERLAND_REGEX.search(line)
                if tb:
                    tb_sku = tb.group(1)
                    if tb_sku not in skus:
                        skus.append(tb_sku)

                # Look for model indicators
                upper = line.upper()
                if "LEBRON" in upper and not model_text:
                    model_text = line
                elif "FREE" in upper and "FLYKNIT" in upper and not model_text:
                    model_text = line
                elif "AIR MAX" in upper and not model_text:
                    model_text = line
                elif "KOBE" in upper and not model_text:
                    model_text = line
                elif "EUROHIKER" in upper and not model_text:
                    model_text = line

                # Colorway text
                if ("PRPL" in upper or "CRMSN" in upper or "BLACK" in upper) and "/" in line and not colorway_text:
                    colorway_text = line

                # MSRP price
                if "$" in line:
                    p_match = re.search(r'\$\s*(\d+(\.\d{2})?)', line)
                    if p_match:
                        try:
                            price = float(p_match.group(1))
                        except ValueError:
                            pass

                # Size
                s_match = re.search(r'\b(Size\s*)?(\d{1,2}(\.5)?)\b', line)
                if s_match and not size and s_match.group(2) in ("8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5", "12"):
                    size = s_match.group(2)

            if skus:
                has_box_label = True

            # 4. Local CLIP Visual Embedding
            visual_pred = None
            visual_conf = 0.0
            try:
                img_pil = Image.open(path).convert("RGB")
                img_tensor = self.clip_preprocess(img_pil).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    logits, _ = self.clip_model(img_tensor, self.text_tokens)
                    probs = logits.softmax(dim=-1).cpu().numpy()[0]
                    top_idx = int(probs.argmax())
                    visual_pred = self.candidate_lines[top_idx]
                    visual_conf = float(probs[top_idx])
            except Exception:
                pass

            # Determination of primary recognition source
            rec_source = "exact_box_ocr" if skus else "visual_embedding"

            results.append(PhotoRecognitionResult(
                file_path=path,
                filename=p.name,
                capture_time=metadata[i].get("capture_utc") if metadata else None,
                has_box_label=has_box_label,
                detected_skus=skus,
                detected_model_text=model_text,
                detected_colorway_text=colorway_text,
                detected_retail_price=price,
                detected_size=size,
                detected_objects=det_objs,
                visual_line_prediction=visual_pred,
                visual_confidence=round(visual_conf, 3),
                cluster_linked_sku=None,
                recognition_source=rec_source
            ))

        # 5. Temporal Cluster Propagation (Propagate box SKU to nearby shelf photos)
        self._propagate_temporal_clusters(results)

        elapsed = time.time() - start_time
        fps = len(file_paths) / elapsed if elapsed > 0 else 0
        print(f"Recognized {len(file_paths)} photos in {elapsed:.2f}s ({fps:.1f} photos/sec)")
        return results

    def _propagate_temporal_clusters(self, results: List[PhotoRecognitionResult]):
        """Link shelf photos to nearby box labels photographed in the same shopping cluster."""
        active_sku = None
        active_model = None

        for res in results:
            if res.detected_skus:
                active_sku = res.detected_skus[0]
                active_model = res.detected_model_text
            elif active_sku:
                # If this photo has no SKU but is an in-store photo without a box, link candidate
                res.cluster_linked_sku = active_sku
                if not res.detected_model_text and active_model:
                    res.detected_model_text = f"Cluster: {active_model}"
                res.recognition_source = "session_clustered"


def format_markdown_report(results: List[PhotoRecognitionResult]) -> str:
    """Format batch results as a clean markdown table."""
    lines = [
        "| Photo | Source | Detected Model | Detected SKU | Retail Price | Visual Top Guess | Confidence |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        model = r.detected_model_text or "—"
        sku = (r.detected_skus[0] if r.detected_skus else (f"🔗 {r.cluster_linked_sku}" if r.cluster_linked_sku else "—"))
        price = f"${r.detected_retail_price:.2f}" if r.detected_retail_price else "—"
        source_badge = (
            "🏷️ Box OCR" if r.recognition_source == "exact_box_ocr" else
            "🔗 Clustered" if r.recognition_source == "session_clustered" else
            "👁️ Visual"
        )
        guess = r.visual_line_prediction or "—"
        conf = f"{r.visual_confidence * 100:.1f}%"
        lines.append(f"| `{r.filename}` | {source_badge} | **{model}** | `{sku}` | {price} | {guess} | {conf} |")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SACC Local Photo Recognizer")
    parser.add_argument("paths", nargs="+", help="Image paths to recognize")
    args = parser.parse_args()

    rec = LocalPhotoRecognizer()
    res = rec.recognize_batch(args.paths)
    print("\n" + format_markdown_report(res))
