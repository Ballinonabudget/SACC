import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sacc_poc.catalog import exact_product
from sacc_poc.database import MultimodalDB
from sacc_poc.gemini import ShoeIdentification
from sacc_poc.ingestion import IngestionService, StaticDispatcher, _asset_token
from sacc_poc.storage import LocalStorageAdapter
from sacc_poc.takeout import capture_time, location, match_sidecar


class PreparedVideoTests(unittest.TestCase):
    def test_prepared_video_bypasses_transcode_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'Compressed_Files'
            folder.mkdir()
            clip = folder / 'shoe.mp4'
            clip.write_bytes(b'prepared proxy')
            db = MultimodalDB(str(root / 'test.db'))
            service = IngestionService(LocalStorageAdapter(str(root)), db,
                                       dispatcher=StaticDispatcher(ShoeIdentification('TEST-1', 'M', 'C', 'B', .8)))
            service.transcoder.transcode = AsyncMock(side_effect=AssertionError('must not transcode'))
            service.transcoder.resolution = AsyncMock(return_value='1280x720')
            with patch('sacc_poc.ingestion.enrich_catalog', return_value={'status': 'no_exact_match'}):
                result = asyncio.run(service.ingest(prefix='Compressed_Files/shoe.mp4'))
                again = asyncio.run(service.ingest(prefix='Compressed_Files/shoe.mp4'))
            self.assertEqual(result['indexed'], 1)
            self.assertEqual(again['skipped'], 1)
            self.assertEqual(db.get_asset(1)['file_path'], str(clip.resolve()))
            service.transcoder.transcode.assert_not_called()

    def test_same_filename_on_different_roots_has_distinct_proxy_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens = []
            for directory in ('a', 'b'):
                root = Path(tmp) / directory
                root.mkdir()
                (root / 'C0001.mp4').write_bytes(b'video')
                tokens.append(_asset_token(next(LocalStorageAdapter(str(root)).iter_media())))
            self.assertNotEqual(*tokens)


class TakeoutTests(unittest.TestCase):
    def test_ambiguous_sidecars_are_not_guessed(self):
        image = Path('/photos/A.jpg')
        one, two = Path('/photos/A.jpg.json'), Path('/photos/A.jpg.supplemental-metadata.json')
        docs = {one: {'title': 'A.jpg'}, two: {'title': 'A.jpg'}}
        self.assertEqual(match_sidecar(image, docs, {}), (None, 'ambiguous'))
        self.assertEqual(match_sidecar(image, {one: docs[one]}, {}), (one, 'matched'))

    def test_sidecar_title_recovers_nonstandard_name(self):
        image, sidecar = Path('/photos/long-name.jpg'), Path('/photos/truncated.json')
        docs = {sidecar: {'title': image.name}}
        titles = {(image.parent, image.name): [sidecar]}
        self.assertEqual(match_sidecar(image, docs, titles), (sidecar, 'matched'))

    def test_capture_not_upload_time_and_zero_gps_is_missing(self):
        self.assertEqual(capture_time({'photoTakenTime': {'timestamp': '0'}}), '1970-01-01T00:00:00+00:00')
        self.assertIsNone(capture_time({'creationTime': {'timestamp': '100'}}))
        self.assertIsNone(location({'geoData': {'latitude': 0, 'longitude': 0}}))
        geo = location({'geoDataExif': {'latitude': 10, 'longitude': -30},
                        'geoData': {'latitude': 40, 'longitude': 50}})
        self.assertEqual(geo['latitude'], 10)


class CatalogTests(unittest.TestCase):
    def test_only_exact_sku_is_used(self):
        wrong, right = {'sku': 'CD6578-006'}, {'sku': 'CD6578 507'}
        self.assertEqual(exact_product({'data': [wrong, right]}, 'CD6578-507'), right)
        self.assertIsNone(exact_product({'data': [wrong]}, 'CD6578-507'))
        self.assertIsNone(exact_product({'data': [right, dict(right)]}, 'CD6578-507'))


if __name__ == '__main__':
    unittest.main()
