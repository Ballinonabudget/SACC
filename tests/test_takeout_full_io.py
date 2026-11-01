"""Synthetic I/O tests: no real Takeout media, archives, or cloud access."""
from contextlib import contextmanager
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from sacc_takeout.common import file_hash
from sacc_takeout.metadata import propose, parse_date
from sacc_takeout.recovery_io import (BoundedZipPool, CHUNK_SIZE, ToolError,
                                     read_tags, restore_candidate, run_tool, stream_file)


def archive(root, number=0):
    path = root/f'part{number}.zip'
    with zipfile.ZipFile(path, 'w') as handle:
        with handle.open('A/image.jpg', 'w', force_zip64=True) as stream:
            stream.write(b'fixture-media'+bytes([number]))
        handle.writestr('A/image.jpg.json', b'{"title":"image.jpg"}')
    info = path.stat()
    registry = {'path': str(path), 'fingerprint': {'size': info.st_size, 'mtime_ns': info.st_mtime_ns}}
    with zipfile.ZipFile(path) as handle:
        entries = [{'archive': str(path), 'member': r.filename, 'index': i,
                    'size': r.file_size, 'crc': r.CRC} for i, r in enumerate(handle.infolist())]
    return registry, entries


class StreamTests(unittest.TestCase):
    def test_exact_zip64_index_crc_sidecar_and_handle_bound(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve()
            fixtures = [archive(root, i) for i in range(3)]
            original_hashes = [file_hash(x[0]['path']) for x in fixtures]
            with BoundedZipPool([x[0] for x in fixtures], max_open=2) as pool:
                reserved = []
                dest = root/'media'
                digest = pool.stream(fixtures[0][1][0], dest, reserved.append)
                self.assertEqual(digest, hashlib.sha256(dest.read_bytes()).hexdigest())
                self.assertEqual(sum(reserved), fixtures[0][1][0]['size'])
                content, sha = pool.read_sidecar(fixtures[0][1][1])
                self.assertEqual(json.loads(content), {'title': 'image.jpg'})
                self.assertEqual(sha, hashlib.sha256(content).hexdigest())
                first_handle = next(iter(pool._open.values()))
                for i in (1, 2):
                    pool.stream(fixtures[i][1][0], root/f'media{i}')
                    self.assertLessEqual(len(pool._open), 2)
                self.assertIsNone(first_handle.fp)
            self.assertFalse(pool._open)
            self.assertEqual(original_hashes, [file_hash(x[0]['path']) for x in fixtures])

    def test_changed_entry_unsafe_member_crc_and_archive_change_fail(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve(); registry, entries = archive(root)
            with BoundedZipPool([registry]) as pool:
                for change in ({'member': 'wrong.jpg'}, {'size': 99}, {'crc': 0},
                               {'index': 99}, {'member': '../image.jpg'}):
                    with self.assertRaises(ValueError):
                        pool.stream({**entries[0], **change}, root/'candidate')
                with self.assertRaises(ValueError):
                    pool.read_sidecar(entries[1], max_bytes=1)
                self.assertFalse((root/'candidate').exists())
            path = Path(registry['path'])
            with path.open('r+b') as stream:
                header = stream.read(30)
                name_len, extra_len = struct.unpack('<HH', header[26:30])
                position = 30+name_len+extra_len
                stream.seek(position); first = stream.read(1)
                stream.seek(position); stream.write(bytes([first[0] ^ 1]))
            info = path.stat()
            corrupted = {**registry, 'fingerprint': {'size': info.st_size, 'mtime_ns': info.st_mtime_ns}}
            with BoundedZipPool([corrupted]) as pool:
                with self.assertRaises((zipfile.BadZipFile, ValueError)):
                    pool.stream(entries[0], root/'corrupt-candidate')
            with BoundedZipPool([registry]) as pool:
                with self.assertRaises(ValueError):
                    pool.stream(entries[0], root/'changed-candidate')

    def test_quota_precedes_payload_read_and_no_destination_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve(); registry, entries = archive(root)
            def exhausted(_):
                raise OSError('Reserved read budget exhausted')
            with BoundedZipPool([registry]) as pool:
                with self.assertRaises(OSError):
                    pool.stream(entries[0], root/'partial', exhausted)
                self.assertEqual((root/'partial').stat().st_size, 0)
                (root/'present').write_bytes(b'keep')
                with self.assertRaises(FileExistsError):
                    pool.stream(entries[0], root/'present')
                self.assertEqual((root/'present').read_bytes(), b'keep')

    def test_sample_file_stream_identity_safety_and_immutability(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve(); source = root/'source'
            source.write_bytes(b'x'*(CHUNK_SIZE+13)); before = source.stat()
            charged = []
            digest = stream_file(source, root/'copy', before.st_size, charged.append)
            self.assertEqual(digest, file_hash(source)); self.assertEqual(digest, file_hash(root/'copy'))
            self.assertEqual(charged, [CHUNK_SIZE, 13])
            self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)
            (root/'link').symlink_to(source)
            with self.assertRaises(ValueError):stream_file(root/'link', root/'unsafe', before.st_size)
            with self.assertRaises(ValueError):stream_file(source, root/'wrong', before.st_size+1)
            with self.assertRaises(ValueError):stream_file(source, source, before.st_size)
            with self.assertRaises(FileExistsError):stream_file(source, root/'copy', before.st_size)

    def test_more_than_five_gib_streams_with_bounded_memory(self):
        # Exercise the actual public ZIP streaming path without allocating/writing
        # a multi-GiB fixture or spending seconds hashing repeated zeros.
        size = 5*1024**3+17
        block = b'x'*CHUNK_SIZE
        class Reader:
            remaining = size
            largest_request = 0
            def read(self, amount):
                self.largest_request = max(self.largest_request, amount)
                length = min(self.remaining, amount); self.remaining -= length
                return block if length == CHUNK_SIZE else block[:length]
        class Sink:
            total = 0
            def __enter__(self):return self
            def __exit__(self, *_):pass
            def write(self, content):self.total += len(content)
            def flush(self):pass
            def fileno(self):return 0
        class Digest:
            total = 0
            def update(self, content):self.total += len(content)
            def hexdigest(self):return 'a'*64
        reader, sink, digest = Reader(), Sink(), Digest()
        @contextmanager
        def member(_):yield reader
        reserved = []
        with BoundedZipPool([]) as pool:
            with (patch.object(pool, '_member', member),
                  patch('sacc_takeout.recovery_io._open_destination', return_value=sink),
                  patch('sacc_takeout.recovery_io.hashlib.sha256', return_value=digest),
                  patch('sacc_takeout.recovery_io.zlib.crc32', return_value=123),
                  patch('sacc_takeout.recovery_io.os.fsync')):
                result = pool.stream({'size': size, 'crc': 123}, 'unused', reserved.append)
        self.assertEqual(result, 'a'*64)
        self.assertEqual((sink.total, digest.total, sum(reserved)), (size, size, size))
        self.assertLessEqual(reader.largest_request, CHUNK_SIZE)


class ToolTests(unittest.TestCase):
    def test_success_and_bounded_combined_tool_output(self):
        self.assertEqual(run_tool([sys.executable, '-c', "print('ok')"]), 'ok\n')
        with self.assertRaises(ValueError):
            run_tool([sys.executable, '-c', "import os;os.write(1,b'x'*800);os.write(2,b'y'*800)"], max_output=1000)
        with self.assertRaises(ToolError) as caught:
            run_tool([sys.executable, '-c', "import sys;print('bad',file=sys.stderr);sys.exit(2)"])
        self.assertEqual(caught.exception.returncode, 2)
        self.assertIn('bad', caught.exception.stderr)
        with self.assertRaises(UnicodeDecodeError):
            run_tool([sys.executable, '-c', "import os;os.write(1,b'\\xff')"])

    def test_timeout_and_midrun_space_breach_kill_tool(self):
        import sacc_takeout.recovery_io as module
        with patch.object(module, '_kill_process_group', wraps=module._kill_process_group) as killed:
            with self.assertRaises(TimeoutError):
                run_tool([sys.executable, '-c', 'import time;time.sleep(5)'], timeout=0.1)
            killed.assert_called_once()
        calls = []
        def space():
            calls.append(1)
            if len(calls) > 1:raise OSError('No space left')
        with patch.object(module, '_kill_process_group', wraps=module._kill_process_group) as killed:
            with self.assertRaises(OSError):
                run_tool([sys.executable, '-c', 'import time;time.sleep(5)'], check_space=space)
            killed.assert_called_once()

    def test_tag_errors_and_wrong_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t).resolve()/'image.jpg'; path.write_bytes(b'fixture')
            content = json.dumps([{'SourceFile': str(path)}])
            with patch('sacc_takeout.recovery_io.run_tool', side_effect=ToolError('exiftool', 1, content, 'bad metadata')):
                self.assertIn('ExifTool:Error', read_tags(path))
            for output in ('not JSON', '{}', '[{"SourceFile":"wrong"}]'):
                with patch('sacc_takeout.recovery_io.run_tool', return_value=output):
                    with self.assertRaises(ValueError):read_tags(path)

    def test_space_monitor_continues_after_tool_closes_output_pipes(self):
        started = time.monotonic()
        checks = []
        def capacity():
            checks.append(time.monotonic()-started)
            if checks[-1] >= 0.15:
                raise OSError('Disk filled after output pipes closed')
        with self.assertRaises(OSError):
            run_tool([sys.executable, '-c',
                      'import os,time;os.close(1);os.close(2);time.sleep(2)'],
                     timeout=3, check_space=capacity)
        self.assertLess(time.monotonic()-started, 0.8)
        self.assertGreaterEqual(len(checks), 3)


class WriterTests(unittest.TestCase):
    def test_jpeg_and_png_date_gps_description_roundtrip_preserves_original(self):
        for extension in ('.jpg', '.png'):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as t:
                root = Path(t).resolve(); source = root/('source'+extension)
                Image.new('RGB', (16, 16), (22, 33, 44)).save(source)
                run_tool(['exiftool', '-config', '', '-overwrite_original', '-Make=Synthetic Camera',
                          '-Model=FixtureModel', '-Orientation#=1',
                          '-DateTimeOriginal=2020:01:01 12:00:00', str(source)])
                embedded = read_tags(source)
                original = source.read_bytes(); before = source.stat()
                doc = {'photoTakenTime': {'timestamp': '1577880000'},
                       'description': 'Synthetic café\nbox label',
                       'geoDataExif': {'latitude': -10., 'longitude': -30.}}
                proposal = propose(doc, embedded, None, date(2026, 10, 30))
                destination = root/('candidate'+extension)
                result = restore_candidate(source, destination, proposal)
                checked = read_tags(destination)
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['sha256'], file_hash(destination))
                self.assertEqual(result['final_size_bytes'], destination.stat().st_size)
                self.assertEqual(parse_date(checked['XMP-photoshop:DateCreated']), parse_date('2020-01-01T12:00:00+00:00'))
                self.assertEqual(checked['XMP-dc:Description'], doc['description'])
                self.assertAlmostEqual(checked['GPS:GPSLatitude'], 10.)
                self.assertEqual(checked['GPS:GPSLatitudeRef'], 'S')
                self.assertAlmostEqual(checked['GPS:GPSLongitude'], 30.)
                self.assertEqual(checked['GPS:GPSLongitudeRef'], 'W')
                self.assertEqual(destination.stat().st_mtime_ns, 1577880000*10**9)
                for name in ('IFD0:Make', 'IFD0:Model', 'IFD0:Orientation', 'ExifIFD:DateTimeOriginal'):
                    self.assertEqual(checked[name], embedded[name])
                self.assertEqual(Image.open(source).tobytes(), Image.open(destination).tobytes())
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)
                # Existing GPS and description survive later compatible proposals.
                second_doc = {**doc, 'description': 'Do not replace the existing description'}
                second = propose(second_doc, checked, None, date(2026, 10, 30))
                retained = restore_candidate(destination, root/('retained'+extension), second)
                self.assertEqual(retained['expected_tags'].keys(), {'XMP-photoshop:DateCreated'})
                self.assertEqual(retained['readback']['XMP-dc:Description'], doc['description'])
                self.assertEqual(retained['readback']['GPS:GPSLatitudeRef'], 'S')

    def test_conflicts_oversized_description_and_existing_candidate_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve(); source = root/'source.png'
            Image.new('RGB', (8, 8)).save(source)
            proposal = propose({'photoTakenTime': {'timestamp': '1577880000'}}, read_tags(source), None, date(2026, 10, 30))
            out = root/'candidate.png'
            with self.assertRaises(ValueError):
                restore_candidate(source, out, {**proposal, 'review_reasons': ['duplicate_metadata_conflict']})
            with self.assertRaises(ValueError):
                restore_candidate(source, out, {**proposal, 'description': 'x'*65537})
            self.assertFalse(out.exists())
            with patch('sacc_takeout.recovery_io.read_tags', return_value={
                    'ExifTool:Error': 'Bad embedded structure',
                    'XMP-photoshop:DateCreated': '2020:01:01 12:00:00+00:00'}):
                with self.assertRaises(ValueError):restore_candidate(source, out, proposal)
            self.assertFalse(out.exists())
            out.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):restore_candidate(source, out, proposal)
            self.assertEqual(out.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
