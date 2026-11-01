"""Audit Takeout sidecars and restore metadata into separate image copies.

No writes to the Takeout source tree. Ambiguous matches are never guessed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import zipfile

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.tif', '.tiff'}
RESTORE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
TAGS = ('Make', 'Model', 'DateTimeOriginal', 'OffsetTimeOriginal', 'CreateDate',
        'GPSLatitude', 'GPSLongitude', 'ImageWidth', 'ImageHeight')


def read_tags(paths: list[Path]) -> dict[str, dict]:
    result = {}
    for start in range(0, len(paths), 100):
        batch = paths[start:start + 100]
        output = subprocess.run(
            ['exiftool', '-j', '-n', *('-' + tag for tag in TAGS), *(str(p) for p in batch)],
            check=True, capture_output=True, text=True, timeout=180,
        )
        result.update({row['SourceFile']: row for row in json.loads(output.stdout)})
    return result


def match_sidecar(image: Path, documents: dict[Path, dict], titles: dict) -> tuple[Path | None, str]:
    candidates = set()
    for name in (image.name + '.json', image.name + '.supplemental-metadata.json'):
        p = image.with_name(name)
        if p in documents and documents[p].get('title') in (None, '', image.name):
            candidates.add(p)
    candidates.update(titles.get((image.parent, image.name), []))
    if len(candidates) == 1:
        return next(iter(candidates)), 'matched'
    return None, 'ambiguous' if candidates else 'missing_sidecar'


def capture_time(sidecar: dict) -> str | None:
    raw = sidecar.get('photoTakenTime', {}).get('timestamp')
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).isoformat()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def location(sidecar: dict) -> dict | None:
    for source in ('geoDataExif', 'geoData'):
        geo = sidecar.get(source) or {}
        lat, lon = geo.get('latitude'), geo.get('longitude')
        if (isinstance(lat, (float, int)) and isinstance(lon, (float, int))
                and math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0)):
            return {'latitude': lat, 'longitude': lon, 'source': source}
    return None


def audit(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root):
        raise ValueError('Audit output must be outside the source tree')
    output.mkdir(parents=True, exist_ok=True)
    documents, titles, images, archives, incomplete, errors = {}, defaultdict(list), [], [], [], []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not d.endswith('.fcpbundle'))
        for name in sorted(files):
            if name.startswith('.'):
                continue
            path = Path(directory) / name
            ext = path.suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                images.append(path)
            elif ext == '.json':
                try:
                    doc = json.loads(path.read_text())
                    if isinstance(doc, dict) and ('photoTakenTime' in doc or 'title' in doc):
                        documents[path] = doc
                        if doc.get('title'):
                            titles[(path.parent, doc['title'])].append(path)
                except (ValueError, OSError) as exc:
                    errors.append({'path': str(path), 'error': str(exc)})
            elif ext == '.zip':
                archives.append({'path': str(path), 'size_bytes': path.stat().st_size})
            elif ext == '.crdownload':
                incomplete.append(str(path))
    metadata = read_tags(images)
    counts = Counter()
    with (output / 'images.jsonl').open('w') as stream:
        for image in images:
            sidecar, status = match_sidecar(image, documents, titles)
            doc = documents.get(sidecar, {})
            embedded = metadata.get(str(image), {})
            captured = capture_time(doc)
            geo = location(doc)
            row = {
                'source': str(image), 'relative_path': str(image.relative_to(root)),
                'sidecar': str(sidecar) if sidecar else None, 'match_status': status,
                'capture_utc': captured, 'location': geo, 'embedded': embedded,
                'source_size': image.stat().st_size,
                'source_mtime_ns': image.stat().st_mtime_ns,
            }
            stream.write(json.dumps(row) + '\n')
            counts['images'] += 1
            counts[status] += 1
            counts['embedded_camera'] += bool(embedded.get('Make') or embedded.get('Model'))
            counts['embedded_capture_time'] += bool(embedded.get('DateTimeOriginal'))
            counts['sidecar_capture_time'] += bool(captured)
            counts['sidecar_location'] += bool(geo)
            counts['missing_camera'] += not bool(embedded.get('Make') or embedded.get('Model'))
    summary = {'root': str(root), 'counts': dict(counts), 'zip_archives': archives,
               'incomplete_downloads': incomplete, 'errors': errors,
               'scope': 'Extracted images only; ZIP payloads have not been extracted or counted.'}
    (output / 'audit.json').write_text(json.dumps(summary, indent=2))
    return summary


def restore(row: dict, output: Path) -> dict:
    if row['match_status'] != 'matched':
        return {'source': row['source'], 'status': row['match_status']}
    source = Path(row['source']).resolve()
    if source.suffix.lower() not in RESTORE_EXTENSIONS:
        return {'source': str(source), 'status': 'unsupported_restore_format'}
    if (source.stat().st_size != row['source_size']
            or source.stat().st_mtime_ns != row['source_mtime_ns']):
        raise ValueError('Source changed since audit; rerun audit')
    relative = Path(row['relative_path'])
    destination = (output / 'restored' / relative).resolve()
    if not destination.is_relative_to(output.resolve()):
        raise ValueError('Invalid output path')
    if destination == source:
        raise ValueError('Refusing to overwrite source')
    if destination.exists():
        return {'source': str(source), 'output': str(destination), 'status': 'already_restored'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    embedded = row['embedded']
    args = ['exiftool', '-P', '-o', str(destination)]
    # Google photoTakenTime is UTC. Existing EXIF time may be local: retain it.
    if row.get('capture_utc'):
        captured = datetime.fromisoformat(row['capture_utc'])
        args.append('-XMP-photoshop:DateCreated=' + row['capture_utc'])
        if not embedded.get('DateTimeOriginal'):
            args += ['-EXIF:DateTimeOriginal=' + captured.strftime('%Y:%m:%d %H:%M:%S'),
                     '-EXIF:OffsetTimeOriginal=+00:00']
    geo = row.get('location')
    if geo and embedded.get('GPSLatitude') is None and embedded.get('GPSLongitude') is None:
        lat, lon = geo['latitude'], geo['longitude']
        args += [f'-EXIF:GPSLatitude={abs(lat)}', '-EXIF:GPSLatitudeRef=' + ('N' if lat >= 0 else 'S'),
                 f'-EXIF:GPSLongitude={abs(lon)}', '-EXIF:GPSLongitudeRef=' + ('E' if lon >= 0 else 'W')]
    # ExifTool copies the entire image; do not fabricate Make/Model from deviceType.
    args += ['-XMP-dc:Source=Google Takeout metadata restoration', str(source)]
    before_hash = hashlib.file_digest(source.open('rb'), 'sha256').hexdigest()
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=120)
    checked = read_tags([destination])[str(destination)]
    for field in ('Make', 'Model', 'DateTimeOriginal', 'GPSLatitude', 'GPSLongitude'):
        if field in embedded and checked.get(field) != embedded[field]:
            raise ValueError(f'Restored copy changed existing {field}')
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != before_hash:
            raise ValueError('Source integrity changed')
    return {'source': str(source), 'output': str(destination), 'status': 'restored',
            'sidecar': row['sidecar'], 'capture_utc': row.get('capture_utc'),
            'source_sha256': before_hash, 'verified': checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audit', 'restore'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('var/takeout'))
    parser.add_argument('--limit', type=int, default=12)
    args = parser.parse_args()
    if args.command == 'audit':
        result = audit(args.root, args.output)
        print(json.dumps({'counts': result['counts'], 'zip_archives': len(result['zip_archives']),
                          'incomplete_downloads': len(result['incomplete_downloads']),
                          'errors': len(result['errors'])}))
    else:
        root, output = args.root.resolve(), args.output.resolve()
        if output.is_relative_to(root):
            raise ValueError('Restoration output must be outside the source tree')
        count, stats = 0, Counter()
        with (output / 'images.jsonl').open() as manifest, (output / 'restoration.jsonl').open('a') as log:
            for line in manifest:
                row = json.loads(line)
                if not Path(row['source']).resolve().is_relative_to(root):
                    raise ValueError('Manifest source outside configured Takeout root')
                if row['match_status'] != 'matched':
                    continue
                try:
                    result = restore(row, output)
                except Exception as exc:
                    result = {'source': row['source'], 'status': 'error', 'error': str(exc)}
                stats[result['status']] += 1
                log.write(json.dumps(result) + '\n'); log.flush()
                count += 1
                if args.limit and count >= args.limit:
                    break
        print(json.dumps(dict(stats)))


if __name__ == '__main__':
    main()
