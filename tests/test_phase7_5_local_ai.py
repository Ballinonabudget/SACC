"""Unit tests for Phase 7.5 Local AI integration (Apple Vision OCR & DINOv2 MPS)."""
import os
import sys
import unittest
from pathlib import Path
from PIL import Image
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from phase7_5.local_ocr_helper import check_frames_for_label, run_vision_on_image, extract_candidate_skus
from phase7_5.dinov2_similarity import embed_image, cosine, max_similarity, device


class TestPhase75LocalAI(unittest.TestCase):
    def setUp(self):
        self.sample_label = Path("/Users/daplug/local-ai-toolkit/tests/samples/label_00_CT8527-115_clean.png")
        self.sample_bus = Path("/Users/daplug/local-ai-toolkit/venv/lib/python3.13/site-packages/ultralytics/assets/bus.jpg")

    def test_01_apple_vision_extraction(self):
        """Verify native Apple Vision extracts accurate label text."""
        self.assertTrue(self.sample_label.exists(), "Sample label file must exist")
        lines = run_vision_on_image(str(self.sample_label))
        self.assertTrue(len(lines) > 0, "Apple Vision must return text lines")
        cands = extract_candidate_skus(lines)
        self.assertIn("CT8527-115", cands, "Candidate SKUs must include CT8527-115")

    def test_02_local_label_kicksdb_verification(self):
        """Verify local OCR pre-check verifies SKU against KicksDB."""
        frame = {
            "path": str(self.sample_label),
            "index": 3,
            "time_sec": 1.5,
            "sharpness": 250.0,
        }
        hit = check_frames_for_label([frame], source="stockx", verbose=False)
        self.assertIsNotNone(hit, "Must detect and verify label")
        self.assertEqual(hit["sku"], "CT8527-115")
        self.assertEqual(hit["frame"]["index"], 3)
        self.assertEqual(hit["source"], "apple_vision_local")
        self.assertIn("Jordan 4", hit["product"].get("name", ""))

    def test_03_non_label_frame_returns_none(self):
        """Verify non-label frame cleanly returns None (no false positives)."""
        frame = {
            "path": str(self.sample_bus),
            "index": 1,
            "time_sec": 0.5,
            "sharpness": 120.0,
        }
        hit = check_frames_for_label([frame], verbose=False)
        self.assertIsNone(hit, "Non-label frame must return None")

    def test_04_dinov2_mps_embedding(self):
        """Verify DINOv2 embedding runs on MPS and normalizes vector."""
        img = Image.new("RGB", (224, 224), color=(255, 0, 0))
        emb = embed_image(img)
        self.assertEqual(len(emb.shape), 1)
        self.assertEqual(emb.shape[0], 768)
        norm = torch.linalg.norm(emb).item()
        self.assertAlmostEqual(norm, 1.0, places=3)
        self.assertEqual(device(), "mps")

    def test_05_dinov2_cosine_similarity(self):
        """Verify cosine similarity calculation."""
        img_red = Image.new("RGB", (224, 224), color=(255, 0, 0))
        img_blue = Image.new("RGB", (224, 224), color=(0, 0, 255))
        emb_red = embed_image(img_red)
        emb_blue = embed_image(img_blue)

        sim_self = cosine(emb_red, emb_red)
        self.assertAlmostEqual(sim_self, 1.0, places=3)

        sim_diff = cosine(emb_red, emb_blue)
        self.assertLess(sim_diff, 0.99)


if __name__ == "__main__":
    unittest.main()
