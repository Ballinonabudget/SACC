"""Read JSON only from Takeout ZIPs; cache outside source, resume per archive.

Never extracts media or changes archives. Run with --dry-run to list work.
Input: discovery archives.json. Output: one JSONL cache and status per ZIP.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import zipfile


def read_archive(row, output):
    source = Path(row['path'])
    stat = source.stat()
    fingerprint = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    if fingerprint != {'size': row['size_bytes'], 'mtime_ns': row['mtime_ns']}:
        raise ValueError(f'Archive changed since inventory: {source}')
    cache = output / (source.name + '.jsonl')
    status = output / (source.name + '.status.json')
    if status.exists() and cache.exists():
        prior = json.loads(status.read_text())
        if prior.get('fingerprint') == fingerprint and prior.get('complete'):
            return prior
    count = 0
    errors = 0
    temporary = cache.with_suffix('.partial')
    with zipfile.ZipFile(source) as archive, temporary.open('w') as stream:
        for entry in archive.infolist():
            if not entry.filename.startswith('Takeout/Google Photos/') or not entry.filename.lower().endswith('.json'):
                continue
            result = {'archive': str(source), 'member': entry.filename}
            try:
                if entry.file_size > 10 * 1024 * 1024:
                    raise ValueError('JSON exceeds 10 MiB read limit')
                result['document'] = json.loads(archive.read(entry))
            except Exception as exc:
                result['error'] = str(exc)
                errors += 1
            stream.write(json.dumps(result) + '\n')
            count += 1
    after = source.stat()
    if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
        raise ValueError(f'Archive changed while reading: {source}')
    temporary.replace(cache)
    result = {'archive': str(source), 'fingerprint': fingerprint, 'json_count': count,
              'errors': errors, 'complete': True}
    status.write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    rows = json.loads(args.inventory.read_text())
    output = args.output.resolve()
    for row in rows:
        if output.is_relative_to(Path(row['path']).resolve().parent):
            raise ValueError('Cache must be outside source directory')
    if args.dry_run:
        print(json.dumps({'archives': len(rows), 'output': str(output), 'action': 'read JSON only'}))
        return
    output.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        futures = [pool.submit(read_archive, row, output) for row in rows]
        for future in as_completed(futures):
            print(json.dumps(future.result()), flush=True)


if __name__ == '__main__':
    main()
