"""Bounded local I/O for full recovery; no ledger or final-publication authority."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import tempfile
import time
import zipfile
import zlib

from .common import file_hash, finite, no_symlinks, safe_member
from .metadata import COPY_FORMATS, TAGS, parse_date

CHUNK_SIZE = 1024 * 1024
MAX_SIDECAR = 10 * 1024 * 1024
MAX_TOOL_OUTPUT = 4 * 1024 * 1024


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Invalid '+name)
    return value


def _signature(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns)


def _fingerprint(path):
    info = no_symlinks(Path(path).absolute()).stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Source must be a regular file')
    return info


def _open_destination(destination):
    destination = no_symlinks(Path(destination).absolute())
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             os.O_NOFOLLOW, 0o600), 'wb')


def _copy_stream(inp, out, expected_size, on_bytes=None, expected_crc=None):
    """Reserve each attempted chunk before reading; never buffer a whole member."""
    _integer(expected_size, 'expected size')
    digest, total, crc = hashlib.sha256(), 0, 0
    while total < expected_size:
        amount = min(CHUNK_SIZE, expected_size-total)
        if on_bytes:
            on_bytes(amount)
        content = inp.read(amount)
        if not content or len(content) > amount:
            raise ValueError('Source size differs from planned size')
        out.write(content)
        total += len(content)
        digest.update(content)
        crc = zlib.crc32(content, crc)
    if inp.read(1):
        raise ValueError('Source exceeds planned size')
    if expected_crc is not None and crc & 0xffffffff != expected_crc:
        raise ValueError('Source CRC differs from planned CRC')
    return digest.hexdigest()


class BoundedZipPool:
    """Small LRU of read-only ZIP handles bound to immutable stat fingerprints."""
    def __init__(self, archives, max_open=2):
        if type(max_open) is not int or not 1 <= max_open <= 4:
            raise ValueError('ZIP handle limit must be 1..4')
        self.max_open, self._open, self._closed = max_open, OrderedDict(), False
        self.archives = {}
        for archive in archives:
            name = str(no_symlinks(Path(archive['path']).absolute()))
            fp = archive['fingerprint']
            expected = {'size': _integer(fp['size'], 'archive size'),
                        'mtime_ns': _integer(fp['mtime_ns'], 'archive mtime')}
            if name in self.archives:
                raise ValueError('Duplicate archive identity')
            self.archives[name] = expected

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        for handle in self._open.values():
            handle.close()
        self._open.clear()
        self._closed = True

    def _checked_stat(self, name):
        if name not in self.archives:
            raise ValueError('Archive is not in the approved source registry')
        info = _fingerprint(name)
        if {'size': info.st_size, 'mtime_ns': info.st_mtime_ns} != self.archives[name]:
            raise ValueError('Archive fingerprint changed')
        return info

    @contextmanager
    def _member(self, entry):
        if self._closed:
            raise RuntimeError('ZIP pool is closed')
        name = str(no_symlinks(Path(entry['archive']).absolute()))
        before = self._checked_stat(name)
        index = _integer(entry['index'], 'member index')
        size = _integer(entry['size'], 'member size')
        crc = _integer(entry['crc'], 'member CRC')
        if crc > 0xffffffff:
            raise ValueError('Invalid member CRC')
        safe_member(entry['member'])
        if name in self._open:
            handle = self._open.pop(name)
        else:
            if len(self._open) >= self.max_open:
                _, expired = self._open.popitem(last=False)
                expired.close()
            handle = zipfile.ZipFile(name, 'r')
        self._open[name] = handle
        if _signature(os.fstat(handle.fp.fileno())) != _signature(before):
            raise ValueError('Open archive no longer matches source path')
        rows = handle.infolist()
        if index >= len(rows):
            raise ValueError('Planned ZIP member index is absent')
        member = rows[index]
        kind = stat.S_IFMT(member.external_attr >> 16)
        if (member.filename, member.file_size, member.CRC) != (entry['member'], size, crc):
            raise ValueError('Indexed ZIP member differs from plan')
        if member.is_dir() or kind not in (0, stat.S_IFREG):
            raise ValueError('ZIP member is not a regular file')
        try:
            with handle.open(member, 'r') as stream:
                yield stream
        finally:
            after = self._checked_stat(name)
            if (_signature(after) != _signature(before) or
                    _signature(os.fstat(handle.fp.fileno())) != _signature(after)):
                raise ValueError('Archive changed during member read')

    def stream(self, entry, destination, on_bytes=None):
        """Write a new caller-owned candidate; a failed candidate is left for audit."""
        with self._member(entry) as inp:
            with _open_destination(destination) as out:
                digest = _copy_stream(inp, out, entry['size'], on_bytes, entry['crc'])
                out.flush()
                os.fsync(out.fileno())
        return digest

    def read_sidecar(self, entry, max_bytes=MAX_SIDECAR, on_bytes=None):
        _integer(max_bytes, 'sidecar byte limit', 1)
        if max_bytes > MAX_SIDECAR or _integer(entry['size'], 'sidecar size') > max_bytes:
            raise ValueError('Sidecar exceeds bounded byte limit')
        content = io.BytesIO()
        with self._member(entry) as inp:
            digest = _copy_stream(inp, content, entry['size'], on_bytes, entry['crc'])
        return content.getvalue(), digest


def stream_file(source, destination, expected_size, on_bytes=None):
    """Copy a verified sample source without changing or following source links."""
    source = no_symlinks(Path(source).absolute())
    destination = no_symlinks(Path(destination).absolute())
    if source == destination:
        raise ValueError('Source and candidate must be separate')
    before = _fingerprint(source)
    if before.st_size != _integer(expected_size, 'expected size'):
        raise ValueError('Sample size differs from plan')
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as inp:
        if _signature(os.fstat(inp.fileno())) != _signature(before):
            raise ValueError('Sample source changed while opening')
        with _open_destination(destination) as out:
            digest = _copy_stream(inp, out, expected_size, on_bytes)
            out.flush()
            os.fsync(out.fileno())
        if (_signature(os.fstat(inp.fileno())) != _signature(before) or
                _signature(_fingerprint(source)) != _signature(before)):
            raise ValueError('Sample source changed during read')
    return digest


class MetadataReadbackMismatch(ValueError):
    """Expected-tag mismatch in an unpublished candidate, never an integrity waiver."""
    def __init__(self,field,expected=None,observed=None):
        self.field,self.expected,self.observed=field,expected,observed
        super().__init__('Metadata readback mismatch: '+field)


class ToolError(RuntimeError):
    def __init__(self, command, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        super().__init__(f'{Path(command).name} exited {returncode}: '+stderr[:8192])


def _kill_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def run_tool(args, timeout=120, max_output=MAX_TOOL_OUTPUT, check_space=None):
    """Run trusted local argv with bounded stdout+stderr and a process deadline."""
    if not args or not all(isinstance(a, str) and '\x00' not in a for a in args):
        raise ValueError('Tool requires a nonempty argv of strings')
    if not finite(timeout) or not 0 < timeout <= 3600:
        raise ValueError('Tool timeout must be positive and at most one hour')
    _integer(max_output, 'tool output bound', 1)
    if max_output > 16*1024*1024:
        raise ValueError('Tool output bound exceeds 16 MiB')
    if check_space:
        check_space()
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    output, errors, total = bytearray(), bytearray(), 0
    deadline = time.monotonic()+timeout
    try:
        for stream, target in ((process.stdout, output), (process.stderr, errors)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, target)
        while selector.get_map() or process.poll() is None:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Local metadata tool timed out')
            if check_space:
                check_space()
            if selector.get_map():
                events = selector.select(min(0.1, remaining))
            else:
                # A tool may close stdout/stderr before finishing a file write.
                # Keep checking disk capacity and timeout until the process exits.
                time.sleep(min(0.1, remaining))
                events = []
            for key, _ in events:
                content = os.read(key.fd, 64*1024)
                if not content:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                total += len(content)
                if total > max_output:
                    raise ValueError('Local metadata tool output exceeds bounded limit')
                key.data.extend(content)
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Local metadata tool timed out')
        code = process.wait(timeout=remaining)
        if check_space:
            check_space()
        stdout, stderr = output.decode('utf-8'), errors.decode('utf-8', 'replace')
        if code:
            raise ToolError(args[0], code, stdout, stderr)
        return stdout
    except BaseException:
        _kill_process_group(process)
        raise
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def read_tags(path, check_space=None):
    path = no_symlinks(Path(path).absolute())
    args = ['exiftool', '-config', '', '-j', '-n', '-G1', '-a', '-s',
            '-api', 'QuickTimeUTC=0', *('-'+tag for tag in TAGS), str(path)]
    tool_error = None
    try:
        content = run_tool(args, timeout=180, check_space=check_space)
    except ToolError as exc:
        content, tool_error = exc.stdout, exc
    try:
        records = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise ValueError('ExifTool returned no readable bounded JSON') from exc
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError('ExifTool returned an unexpected record set')
    record = records[0]
    if record.get('SourceFile') != str(path):
        raise ValueError('ExifTool source identity differs from requested file')
    if tool_error and not any(k.endswith(':Error') for k in record):
        record['ExifTool:Error'] = tool_error.stderr[:8192] or 'Nonzero tool exit'
    return record


def restore_candidate(source, destination, proposal, check_space=None):
    """Create a separate verified JPEG/PNG candidate; never publish a final asset."""
    source = no_symlinks(Path(source).absolute())
    destination = no_symlinks(Path(destination).absolute())
    if source == destination or source.suffix.lower() not in COPY_FORMATS:
        raise ValueError('Metadata candidate requires a separate JPEG/PNG output')
    if destination.exists():
        raise FileExistsError('Metadata candidate already exists')
    blocked = {'gps_conflict', 'gps_invalid', 'gps_conflicting_reference', 'embedded_read_error',
               'detected_media_type_mismatch', 'duplicate_metadata_conflict',
               'ambiguous_sidecar', 'missing_sidecar'}
    if not proposal['capture']['safe_to_embed'] or blocked.intersection(proposal['review_reasons']):
        raise ValueError('Conflicting or uncertain metadata cannot be embedded')
    captured = proposal['capture']['selected']['utc']
    captured_date = parse_date(captured)
    if not captured_date or not captured_date.tzinfo:
        raise ValueError('A validated capture instant is required')
    embedded = proposal['embedded']
    if not isinstance(embedded, dict):
        raise ValueError('Embedded source observations are required')
    expected = {'XMP-photoshop:DateCreated': captured}
    assignments = ['-XMP-photoshop:DateCreated='+captured]
    description = proposal.get('description')
    if description is not None and (not isinstance(description, str) or len(description.encode()) > 65536):
        raise ValueError('Description exceeds bounded metadata policy')
    if description and not any(key.endswith(':Description') for key in embedded):
        expected['XMP-dc:Description'] = description
        assignments.append('-XMP-dc:Description='+description)
    gps = proposal['observed_gps'].get('selected')
    has_gps = any(k.endswith((':GPSLatitude', ':GPSLongitude', ':GPSCoordinates')) for k in embedded)
    if gps and not has_gps:
        lat, lon = gps.get('latitude'), gps.get('longitude')
        if (not proposal['observed_gps'].get('safe_to_embed') or not finite(lat) or not finite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0)):
            raise ValueError('A validated GPS pair is required')
        expected.update({'GPS:GPSLatitude': abs(lat), 'GPS:GPSLatitudeRef': 'N' if lat >= 0 else 'S',
                         'GPS:GPSLongitude': abs(lon), 'GPS:GPSLongitudeRef': 'E' if lon >= 0 else 'W'})
        assignments += ['-EXIF:'+k.split(':')[-1]+'='+str(v) for k, v in expected.items() if k.startswith('GPS:')]
    before = _fingerprint(source)
    source_hash = file_hash(source)
    if proposal.get('source_sha256', source_hash) != source_hash:
        raise ValueError('Metadata proposal source hash is stale')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=destination.parent) as directory:
        candidate = Path(directory)/('candidate'+source.suffix.lower())
        def checked_space():
            if check_space:
                check_space()
            if candidate.exists() and candidate.stat().st_size > before.st_size+16*1024*1024:
                raise ValueError('Metadata candidate exceeds bounded growth allowance')
        run_tool(['exiftool', '-config', '', '-o', str(candidate), *assignments, str(source)],
                 check_space=checked_space)
        checked = read_tags(candidate, check_space=checked_space)
        if any(field.endswith(':Error') for field in checked):
            raise ValueError('Metadata candidate readback reported an embedded error')
        for field, value in expected.items():
            got = checked.get(field)
            if field.endswith(':DateCreated'):
                valid = parse_date(got) == captured_date
            elif finite(value):
                valid = finite(got) and abs(got-value) < 0.000001
            else:
                valid = got == value
            if not valid:
                raise MetadataReadbackMismatch(field,value,got)
        preserve = {'Make', 'Model', 'Orientation', 'DateTimeOriginal', 'OffsetTimeOriginal',
                    'CreateDate', 'GPSLatitude', 'GPSLongitude', 'GPSLatitudeRef', 'GPSLongitudeRef',
                    'GPSAltitude', 'GPSAltitudeRef', 'GPSCoordinates', 'GPSHPositioningError',
                    'GPSHorizontalAccuracy', 'ContentIdentifier', 'Description'}
        for field, value in embedded.items():
            if field.split(':')[-1] in preserve and checked.get(field) != value:
                raise ValueError('Existing embedded metadata changed: '+field)
        delta = captured_date.astimezone(timezone.utc)-datetime(1970, 1, 1, tzinfo=timezone.utc)
        timestamp_ns = (delta.days*86400+delta.seconds)*1_000_000_000+delta.microseconds*1000
        os.utime(candidate, ns=(candidate.stat().st_atime_ns, timestamp_ns))
        if abs(candidate.stat().st_mtime_ns-timestamp_ns) > 1000:
            raise ValueError('Metadata candidate mtime readback mismatch')
        if file_hash(source) != source_hash or _signature(_fingerprint(source)) != _signature(before):
            raise ValueError('Source changed during metadata restoration')
        candidate.chmod(0o600)
        with candidate.open('rb') as stream:
            os.fsync(stream.fileno())
        # link fails rather than overwriting an unexpected caller-owned candidate.
        no_symlinks(destination)
        os.link(candidate, destination, follow_symlinks=False)
        return {'status': 'verified', 'path': str(destination), 'sha256': file_hash(destination),
                'expected_tags': expected, 'readback': checked, 'mtime_ns': destination.stat().st_mtime_ns,
                'source_sha256': source_hash, 'final_size_bytes': destination.stat().st_size}
