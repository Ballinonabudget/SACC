"""Audit cached Takeout metadata locally; writes manifests outside the source.

No media is opened. No metadata, source path, or database is changed.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import json
from pathlib import Path, PurePosixPath
import random
import re

PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.gif', '.webp', '.tif', '.tiff', '.dng', '.arw', '.nef'}
VIDEO = {'.mov', '.mp4', '.m4v', '.3gp', '.3g2', '.mpg', '.mpeg', '.avi', '.wmv', '.mkv'}


def date_value(document):
    try:
        return datetime.fromtimestamp(int(document['photoTakenTime']['timestamp']), timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


def normalized(name):
    name = re.sub(r'\(\d+\)(?=\.[^.]+$|$)', '', name)
    # Observed Takeout export substitutions; only used to validate an exact
    # sidecar filename pair, never to search for or choose another media file.
    return re.sub(r"[:&']", '_', name)


def match(media, documents):
    """Unique filename first; then a unique exact JSON title in the same folder.

    Cross-part paths are combined before matching. No cross-album guessing or
    fuzzy/truncated-prefix match. Each sidecar can be assigned only once.
    """
    proposals = defaultdict(list)
    for sidecar, document in documents.items():
        path = PurePosixPath(sidecar)
        stem = re.sub(r'(\.supplemental-metadata)?\.json$', '', path.name)
        candidates = [(str(path.with_name(stem)), 'filename')]
        moved = re.sub(r'(\.[^.()]+)\((\d+)\)$', r'(\2)\1', stem)
        if moved != stem:
            candidates.append((str(path.with_name(moved)), 'duplicate_suffix_position'))
        found = [(name, method) for name, method in candidates if name in media]
        if len(found) == 1:
            name, method = found[0]
            title = document.get('title')
            if title and normalized(title) != normalized(PurePosixPath(name).name):
                continue
            if title and title != PurePosixPath(name).name and re.search(r"[:&']", title):
                method += '_sanitized_title'
            proposals[name].append((sidecar, method))
    matches = {}
    used = set()
    for name, candidates in proposals.items():
        if len(candidates) == 1:
            matches[name] = candidates[0]
            used.add(candidates[0][0])
    title_candidates = defaultdict(list)
    for sidecar, document in documents.items():
        title = document.get('title')
        if sidecar in used or not isinstance(title, str) or not title or '/' in title:
            continue
        name = str(PurePosixPath(sidecar).with_name(title))
        if name in media and name not in matches:
            title_candidates[name].append(sidecar)
    for name, candidates in title_candidates.items():
        if len(candidates) == 1:
            matches[name] = (candidates[0], 'exact_title_same_folder')
            used.add(candidates[0])
    return matches, used


def analyze(rows, documents, output, label, sample_size=200, write=True):
    media = {name: row for name, row in rows.items() if PurePosixPath(name).suffix.lower() in PHOTO | VIDEO}
    photo_documents = {name: doc for name, doc in documents.items() if isinstance(doc, dict) and
                       ('photoTakenTime' in doc or ('creationTime' in doc and PurePosixPath(str(doc.get('title', ''))).suffix.lower() in PHOTO | VIDEO))}
    matches, used = match(media, photo_documents)
    dates = [d for doc in photo_documents.values() if (d := date_value(doc))]
    sample = random.Random(20261029).sample(sorted(media), min(sample_size, len(media)))
    fields = ['media', 'archive', 'status', 'method', 'sidecar', 'sidecar_archive', 'capture_utc', 'json_title']
    records = []
    for name, row in sorted(media.items()):
        sidecar, method = matches.get(name, (None, None))
        doc = photo_documents.get(sidecar, {})
        records.append({'media': name, 'archive': row.get('archive', ''),
                        'status': 'matched' if sidecar else 'unresolved', 'method': method,
                        'sidecar': sidecar, 'sidecar_archive': rows.get(sidecar, {}).get('archive', ''),
                        'capture_utc': date_value(doc), 'json_title': doc.get('title')})
    by_name = {r['media']: r for r in records}
    exports = [(label + '_matches.csv', records), (label + '_sample_200.csv', [by_name[n] for n in sample])] if write else []
    for filename, selected in exports:
        with (output / filename).open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(selected)
    if write:
        with (output / (label + '_unmatched_sidecars.csv')).open('w') as stream:
            writer = csv.writer(stream)
            writer.writerow(['sidecar', 'title', 'capture_utc'])
            for name in sorted(set(photo_documents) - used):
                writer.writerow([name, photo_documents[name].get('title'), date_value(photo_documents[name])])
    year_counts = Counter(d[:4] for d in dates)
    summary = {'label': label, 'file_count': len(rows), 'extensions': dict(Counter(PurePosixPath(n).suffix.lower() for n in rows)),
               'photos': sum(PurePosixPath(n).suffix.lower() in PHOTO for n in media),
               'videos': sum(PurePosixPath(n).suffix.lower() in VIDEO for n in media),
               'media': len(media), 'json_documents': len(documents), 'media_sidecars': len(photo_documents),
               'other_json': len(documents) - len(photo_documents), 'matched_media': len(matches),
               'unresolved_media': len(media) - len(matches), 'unmatched_sidecars': len(photo_documents) - len(used),
               'matching_methods': dict(Counter(method for _, method in matches.values())),
               'capture_dates': len(dates), 'missing_capture_date': len(photo_documents) - len(dates),
               'capture_range_utc': [min(dates), max(dates)] if dates else None,
               'capture_year_counts': dict(sorted(year_counts.items())),
               'sample': {'seed': 20261029, 'size': len(sample), 'matched': sum(n in matches for n in sample),
                          'valid_capture_dates': sum(bool(by_name[n]['capture_utc']) for n in sample),
                          'methods': dict(Counter(by_name[n]['method'] or 'unresolved' for n in sample))},
               'cross_archive_matches': sum(bool(r['archive'] and r['sidecar_archive'] and r['archive'] != r['sidecar_archive']) for r in records),
               'note': 'Matching is structural metadata verification, not visual verification. Unresolved includes missing, ambiguous, and naming conflicts. Counts include album copies; no deduplication performed.'}
    if write:
        (output / (label + '_summary.json')).write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', help='Print summaries without writing manifests')
    args = parser.parse_args()
    work = args.work.resolve()
    rows = {}
    for line in (work / 'zip_entries.jsonl').open():
        row = json.loads(line)
        if row['member'].startswith('Takeout/Google Photos/'):
            if row['member'] in rows:
                raise ValueError('Duplicate archive member path needs explicit handling')
            rows[row['member']] = row
    documents = {}
    for row in json.loads((work / 'archives.json').read_text()):
        source = Path(row['path'])
        status = json.loads((work / 'sidecars' / (source.name + '.status.json')).read_text())
        if not status.get('complete') or status.get('errors'):
            raise ValueError('Incomplete or erroneous JSON cache')
        for line in (work / 'sidecars' / (source.name + '.jsonl')).open():
            item = json.loads(line)
            documents[item['member']] = item['document']
    expected = sum(PurePosixPath(n).suffix.lower() == '.json' for n in rows)
    if len(documents) != expected:
        raise ValueError('Sidecar cache count does not match archive inventory')
    print(json.dumps(analyze(rows, documents, work, 'nas_archives', write=not args.dry_run), indent=2))
    for filename, label in [('extracted_entries.jsonl', 'nas_extracted')]:
        grouped = defaultdict(dict)
        for line in (work / filename).open():
            item = json.loads(line)
            grouped[item.get('root', label)][item['relative']] = item
        for index, (root, items) in enumerate(grouped.items()):
            docs = {n: r['document'] for n, r in items.items() if 'document' in r}
            result = analyze(items, docs, work, label + (str(index) if len(grouped) > 1 else ''), write=not args.dry_run)
            result['root'] = root
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
