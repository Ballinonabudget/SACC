from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sacc_poc.database import MultimodalDB
from sacc_poc.gemini import IdentificationError, ShoeIdentification
from sacc_poc.storage import LocalStorageAdapter
from sacc_poc.transcode import AsyncFFmpegTranscoder, MediaGuardrailError, ProxyConfig, ensure_dispatchable


class StorageAdapterTests(unittest.TestCase):
    def test_local_adapter_lists_supported_media_and_blocks_escape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "nested").mkdir()
            (root / "nested" / "clip.mov").write_bytes(b"video")
            (root / "shoe.jpg").write_bytes(b"image")
            (root / "notes.txt").write_text("ignore")
            adapter = LocalStorageAdapter(td)
            assets = list(adapter.iter_media())
            self.assertEqual([a.logical_key for a in assets], ["nested/clip.mov", "shoe.jpg"])
            self.assertEqual({a.media_type for a in assets}, {"video", "image"})
            with self.assertRaises(ValueError):
                adapter.resolve("../escape.mov")


class DatabaseTests(unittest.TestCase):
    def test_search_groups_assets_and_filters_media_type(self):
        with tempfile.TemporaryDirectory() as td:
            db = MultimodalDB(str(Path(td) / "poc.db"))
            jordan = db.upsert_shoe("DZ5485-400", "Air Jordan 1 Retro High OG", "UNC Toe", "Jordan")
            dunk = db.upsert_shoe("DD1503-101", "Nike Dunk Low", "Panda", "Nike")
            db.add_media_asset(jordan, "video", "/tmp/jordan.mp4", "1280x720", "video/mp4", confidence=1.0, needs_review=False)
            db.add_media_asset(jordan, "image", "/tmp/jordan.jpg", "1200x1200", "image/jpeg", confidence=0.9, needs_review=True)
            db.add_media_asset(dunk, "image", "/tmp/dunk.jpg", "1200x1200", "image/jpeg", confidence=1.0, needs_review=False)

            result = db.search("Jordan 1", ["video", "image"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["results"][0]["sku"], "DZ5485-400")
            self.assertEqual(len(result["results"][0]["media"]["videos"]), 1)
            self.assertEqual(len(result["results"][0]["media"]["images"]), 1)

            video_only = db.search("", ["video"])
            self.assertEqual(video_only["total"], 1)
            self.assertEqual(video_only["results"][0]["media"]["images"], [])

            substring = db.search("5485-4", ["video"])
            self.assertEqual(substring["total"], 1)

            punctuation_only = db.search("---", ["video", "image"])
            self.assertEqual(punctuation_only["total"], 0)

    def test_review_queue_is_confidence_ordered(self):
        with tempfile.TemporaryDirectory() as td:
            db = MultimodalDB(str(Path(td) / "poc.db"))
            shoe = db.upsert_shoe("TEST-001", "Test", "Black", "SACC")
            db.add_media_asset(
                shoe, "image", "/tmp/a.jpg", "", "image/jpeg",
                confidence=0.8, needs_review=True,
                review_reason="sku_confidence_below_1.0",
            )
            self.assertEqual(db.review_queue()[0]["confidence"], 0.8)
            self.assertEqual(
                db.review_queue()[0]["review_reason"], "sku_confidence_below_1.0"
            )

    def test_ingest_job_status_is_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "poc.db")
            db = MultimodalDB(path)
            db.save_ingest_job({
                "id": "job-1", "status": "complete", "request": {"limit": 3},
                "events": [{"status": "indexed"}], "result": {"indexed": 3},
                "error": "",
            })
            restored = MultimodalDB(path).get_ingest_job("job-1")
            self.assertEqual(restored["status"], "complete")
            self.assertEqual(restored["result"]["indexed"], 3)


class GeminiContractTests(unittest.TestCase):
    def test_strict_schema_and_review_barrier(self):
        exact = ShoeIdentification.parse({
            "sku": "dz5485-400", "model": "Air Jordan 1", "colorway": "UNC Toe",
            "brand": "Jordan", "confidence": 1.0,
        })
        self.assertEqual(exact.sku, "DZ5485-400")
        self.assertFalse(exact.needs_review)
        uncertain = ShoeIdentification.parse({
            "sku": "", "model": "Air Jordan 1", "colorway": "", "brand": "Jordan",
            "confidence": 0.99,
        })
        self.assertTrue(uncertain.needs_review)
        self.assertEqual(uncertain.review_reason, "sku_unreadable")
        disagreement = ShoeIdentification(
            "EG8081", "UltraBoost", "White", "adidas", 1.0,
            forced_review_reason="secondary_model_disagreement:FV6051",
        )
        self.assertTrue(disagreement.needs_review)
        with self.assertRaises(IdentificationError):
            ShoeIdentification.parse({
                "sku": "X", "model": "M", "colorway": "C", "brand": "B",
                "confidence": 1.0, "timestamp": 12,
            })


class TranscodeTests(unittest.TestCase):
    def test_ffmpeg_contract_and_size_guardrail(self):
        config = ProxyConfig(target_height=720, crf=23, max_dispatch_bytes=4)
        worker = AsyncFFmpegTranscoder(config)
        command = worker.command(Path("source.mov"), Path("proxy.mp4"))
        self.assertIn("libx264", command)
        self.assertEqual(command[command.index("-crf") + 1], "23")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "asset.mp4"
            path.write_bytes(b"12345")
            with self.assertRaises(MediaGuardrailError):
                ensure_dispatchable(path, 4)


if __name__ == "__main__":
    unittest.main()
