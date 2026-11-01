"""Bounded, resumable ZIP recovery; all detailed outputs remain local."""
from collections import Counter, defaultdict
from datetime import date
import hashlib
import csv
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import uuid
import zipfile

from scripts.takeout_match_inventory import PHOTO, VIDEO, match, normalized
from . import MAX_SAMPLE, MAX_VERIFY_COPIES, POLICY_VERSION, SCHEMA_VERSION
from .common import atomic_text, canonical, child, file_hash, private_root, run_lock, safe_member, token
from .manifest import Manifest
from .metadata import COPY_FORMATS, propose, read_tags, verify_copy
from .locations import propose_stops, save_visit
from .review_policy import reviewed_result, REVIEW_POLICY_VERSION


def load_json(text):
    return json.loads(text, parse_constant=lambda s: {'non_json_number': s})


def json_lines(path):
    with Path(path).open() as stream:
        for line in stream:
            yield load_json(line)


def fingerprint(path):
    s = Path(path).stat()
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns}


def assert_archive(row):
    if fingerprint(row['path']) != {'size': row['size_bytes'], 'mtime_ns': row['mtime_ns']}:
        raise ValueError('Source archive changed since discovery')


def conservative_matches(media, documents):
    """Reuse discovery matching, but never let its fallback erase a conflict."""
    proposed = defaultdict(set)
    blocked = set()
    for sidecar, doc in documents.items():
        if not isinstance(doc, dict):
            continue
        p = PurePosixPath(sidecar)
        stem = re.sub(r'(\.supplemental-metadata)?\.json$', '', p.name)
        moved = re.sub(r'(\.[^.()]+)\((\d+)\)$', r'(\2)\1', stem)
        names = {str(p.with_name(n)) for n in (stem, moved)} & media.keys()
        if len(names) > 1:
            blocked |= names
        for name in names:
            proposed[name].add(sidecar)
            title = doc.get('title')
            if title and (not isinstance(title, str) or normalized(title) != normalized(PurePosixPath(name).name)):
                blocked.add(name)
    blocked |= {n for n, v in proposed.items() if len(v) > 1}
    safe_docs = {k: v for k, v in documents.items() if isinstance(v, dict) and
                 (v.get('title') is None or isinstance(v.get('title'), str))}
    matches, _ = match(media, safe_docs)
    return {k: v for k, v in matches.items() if k not in blocked}, blocked


def load_inventory(discovery):
    discovery = Path(discovery).resolve()
    archives = load_json((discovery/'archives.json').read_text())
    if not archives or len({r['path'] for r in archives}) != len(archives):
        raise ValueError('Empty or duplicate archive inventory')
    expected = defaultdict(list)
    for r in json_lines(discovery/'zip_entries.jsonl'):
        if r['member'].startswith('Takeout/Google Photos/'):
            expected[r['archive']].append((r['member'], r['size'], r['crc']))
    if set(expected) - {r['path'] for r in archives}:
        raise ValueError('Entry references an unregistered archive')
    entries, docs, cache_hashes = [], {}, {}
    for archive in archives:
        assert_archive(archive)
        with zipfile.ZipFile(archive['path']) as z:
            actual = []
            for index, info in enumerate(z.infolist()):
                if not info.filename.startswith('Takeout/Google Photos/') or info.is_dir():
                    continue
                safe_member(info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP symlink is not supported')
                actual.append((info.filename, info.file_size, info.CRC))
                entries.append({'archive': archive['path'], 'member': info.filename, 'index': index,
                                'size': info.file_size, 'crc': info.CRC, 'zip_time': info.date_time})
            if sorted(actual) != sorted(expected[archive['path']]):
                raise ValueError('Central directory differs from discovery')
        cache = discovery/'sidecars'/(Path(archive['path']).name+'.jsonl')
        status = load_json(cache.with_name(Path(archive['path']).name+'.status.json').read_text())
        if not status.get('complete') or status.get('errors') or status.get('fingerprint') != fingerprint(archive['path']):
            raise ValueError('Stale or incomplete sidecar cache')
        cache_hashes[str(cache)] = file_hash(cache)
        cached = []
        for item in json_lines(cache):
            if item.get('archive') != archive['path'] or 'document' not in item:
                raise ValueError('Invalid sidecar cache provenance')
            cached.append(item['member'])
            docs.setdefault((archive['path'], item['member']), []).append(item['document'])
        expected_json = [n for n, _, _ in actual if n.lower().endswith('.json')]
        if sorted(cached) != sorted(expected_json):
            raise ValueError('Sidecar cache member inventory mismatch')
        assert_archive(archive)
    groups = defaultdict(list)
    for row in entries:
        groups[row['member']].append(row)
    media = {n: rows[0] for n, rows in groups.items() if len(rows) == 1 and PurePosixPath(n).suffix.lower() in PHOTO | VIDEO}
    documents = {n: docs[(rows[0]['archive'], n)][0] for n, rows in groups.items()
                 if len(rows) == 1 and n.lower().endswith('.json') and len(docs.get((rows[0]['archive'], n), [])) == 1}
    matches, blocked = conservative_matches(media, documents)
    occurrences = []
    for row in entries:
        ext = PurePosixPath(row['member']).suffix.lower()
        if ext not in PHOTO | VIDEO | {'.mp'}:
            continue
        row['media_type'] = 'image' if ext in PHOTO else 'video' if ext in VIDEO else 'unknown'
        pair = matches.get(row['member'])
        status = 'ambiguous_sidecar' if len(groups[row['member']]) > 1 or row['member'] in blocked else 'missing_sidecar'
        row['match'] = {'status': status}
        if pair:
            name, method = pair
            sidecar = groups[name][0]
            row['match'] = {'status': 'matched', 'method': method, 'sidecar': sidecar,
                            'cached_document': documents[name]}
        occurrences.append(row)
    identity = token(archives, entries, cache_hashes)
    summary = {'archives': len(archives), 'media_occurrences': len(occurrences),
               'recognized_media': sum(r['media_type'] != 'unknown' for r in occurrences),
               'matched': sum(r['match']['status'] == 'matched' for r in occurrences),
               'ambiguous': sum(r['match']['status'] == 'ambiguous_sidecar' for r in occurrences),
               'unmatched_sidecars': sum(n.lower().endswith('.json') for n in groups)-len(matches),
               'source_completeness': 'unconfirmed', 'inventory_hash': identity}
    return archives, occurrences, identity, summary


def register(db, account, export_key, archives, rows, identity, summary, config):
    batch = token('batch', account, export_key)
    prior = db.con.execute('SELECT * FROM batches WHERE id=?', (batch,)).fetchone()
    if prior:
        if prior['inventory_hash'] != identity or prior['config_json'] != canonical(config):
            raise ValueError('Batch inventory/configuration is immutable; resume with the original inputs and sample settings')
        return batch
    recognized = sorted((r for r in rows if r['media_type'] != 'unknown'), key=lambda r: (r['member'], r['archive'], r['index']))
    sample = random.Random(config['seed']).sample(recognized, min(config['limit'], len(recognized)))
    with db.con:
        db.con.execute('INSERT OR IGNORE INTO accounts(id,label) VALUES (?,?)', (account, 'Provisional account; identity unconfirmed'))
        db.con.execute('INSERT INTO batches VALUES (?,?,?,?,?,?)', (batch, account, export_key, canonical(config), identity, canonical(summary)))
        for a in archives:
            db.con.execute('INSERT INTO archives VALUES (?,?,?,?)', (token(batch, a['path']), batch, a['path'], canonical(fingerprint(a['path']))))
        for r in rows:
            r['id'] = token(batch, r['archive'], r['index'], r['member'])
            db.con.execute('INSERT INTO occurrences VALUES (?,?,?,?,?,?,?,?,?,?,NULL)',
                           (r['id'], batch, token(batch, r['archive']), r['member'], r['index'],
                            str(PurePosixPath(r['member']).parent), r['media_type'], r['size'], r['crc'], canonical(r['match'])))
        for i, r in enumerate(sample):
            db.con.execute('INSERT INTO sample_members VALUES (?,?,?)', (batch, i, r['id']))
            db.con.execute('INSERT INTO recovery_results(occurrence_id,state) VALUES (?,?)', (r['id'], 'pending'))
        db.event(None, 'batch_registered', {'batch_id': batch, 'sample_count': len(sample), 'config': config})
    return batch


def selected_rows(db, batch):
    if not db.con.execute('SELECT 1 FROM batches WHERE id=?', (batch,)).fetchone():
        raise ValueError('Unknown manifest batch ID')
    return [dict(r) for r in db.con.execute('''SELECT o.*,a.path AS archive FROM sample_members s
        JOIN occurrences o ON o.id=s.occurrence_id JOIN archives a ON a.id=o.archive_id
        WHERE s.batch_id=? ORDER BY s.ordinal''', (batch,))]


def read_member(row, destination=None):
    """Streaming CRC/SHA-256 validation, using the exact indexed ZIP entry."""
    source = row.get('archive')
    before = fingerprint(source)
    size = row.get('size', row.get('size_bytes'))
    if size > 2*1024**3:
        raise ValueError('Member exceeds the 2 GiB milestone bound')
    index = row.get('index', row.get('member_index'))
    partial = destination.with_name(destination.name+'.partial') if destination else None
    stream = None
    try:
        if destination:
            destination = child(destination.parent, destination.name)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            partial = child(destination.parent, destination.name+'.partial')
            stream = os.fdopen(os.open(partial, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600), 'wb')
        digest, total = hashlib.sha256(), 0
        with zipfile.ZipFile(source) as z:
            info = z.infolist()[index]
            if (info.filename, info.file_size, info.CRC) != (row['member'], size, row['crc']):
                raise ValueError('ZIP entry changed')
            with z.open(info) as inp:
                while data := inp.read(1024*1024):
                    total += len(data)
                    if total > size:
                        raise ValueError('ZIP member exceeds declared size')
                    digest.update(data)
                    if stream:
                        stream.write(data)
        if total != size or fingerprint(source) != before:
            raise ValueError('Source changed during member read')
        if stream:
            stream.flush(); os.fsync(stream.fileno()); stream.close(); stream = None
            os.replace(partial, destination)
        return digest.hexdigest()
    finally:
        if stream:
            stream.close()
        if partial and partial.exists():
            partial.unlink()


def read_sidecar(pair):
    row = pair['sidecar']
    if row['size'] > 10*1024**2:
        raise ValueError('Sidecar exceeds 10 MiB')
    before = fingerprint(row['archive'])
    with zipfile.ZipFile(row['archive']) as z:
        info = z.infolist()[row['index']]
        if (info.filename, info.file_size, info.CRC) != (row['member'], row['size'], row['crc']):
            raise ValueError('Sidecar entry changed')
        content = z.read(info)
    doc = load_json(content)
    if fingerprint(row['archive']) != before or doc != pair['cached_document']:
        raise ValueError('Live sidecar differs from cached discovery metadata')
    return doc, hashlib.sha256(content).hexdigest()


def export_report(db, batch, resumed=0):
    rows, records = selected_rows(db, batch), []
    counts, reasons, formats = Counter(), Counter(), Counter()
    for row in rows:
        saved = db.result(row['id'])
        decisions = []
        for decision in db.con.execute("SELECT id,payload_json FROM stage_results WHERE media_id=? AND stage='local_context' ORDER BY rowid DESC",(row['media_id'],)):
            try:
                decisions.append({'id':decision['id'],'payload':json.loads(decision['payload_json'])})
            except (ValueError,TypeError):
                continue
        result = reviewed_result(saved['result'],row['media_type'],decisions)
        exempt = result['gps_requirement']['status'] == 'not_expected_screenshot'
        counts['confirmed_screenshots_gps_exempt'] += exempt
        counts['gps_expected'] += not exempt
        counts['gps_expected_selected'] += not exempt and bool(result.get('observed_gps',{}).get('selected'))
        counts[saved['state']] += 1
        formats[PurePosixPath(row['member']).suffix.lower()] += 1
        reasons.update(result.get('review_reasons', []))
        counts['gps_available'] += bool(result.get('observed_gps', {}).get('available'))
        counts['gps_selected'] += bool(result.get('observed_gps', {}).get('selected'))
        counts['capture_utc'] += bool((result.get('capture', {}).get('selected') or {}).get('utc'))
        counts['unchanged_sources'] += result.get('source_verified') is True
        counts['verified_copies'] += result.get('verification', {}).get('status') == 'verified'
        counts['needs_review'] += bool(result.get('review_reasons'))
        records.append({'schema_version': SCHEMA_VERSION, 'batch_id': batch, 'occurrence_id': row['id'],
                        'media_id': row['media_id'], 'source': {'archive': row['archive'], 'member': row['member'],
                        'album': row['album_path']}, 'state': saved['state'], 'error': saved['error'], **result})
    report = {'schema_version': 1, 'batch_id': batch, 'sample_size': len(rows), 'counts': dict(counts),
              'review_reasons': dict(reasons), 'formats': dict(formats), 'resumed_without_reprocessing': resumed,
              'gps_coverage': {'available': counts['gps_available'], 'selected': counts['gps_selected'], 'denominator': len(rows)},
              'review_policy_version': REVIEW_POLICY_VERSION,
              'gps_expected_coverage': {'selected':counts['gps_expected_selected'],'denominator':counts['gps_expected'],
                                        'excluded_confirmed_screenshots':counts['confirmed_screenshots_gps_exempt'],
                                        'rate':counts['gps_expected_selected']/counts['gps_expected'] if counts['gps_expected'] else None},
              'candidate_coverage': {'numerator': None, 'denominator': len(rows), 'reason': 'No approved real directory imported'},
              'reviewed_store_accuracy': {'correct': None, 'reviewed': 0, 'rate': None},
              'cross_store_errors': {'errors': None, 'reviewed': 0},
              'privacy': 'All media unknown and local; zero remote calls', 'full_recovery_authorized': False,
              'integrity_scope': 'Selected uncompressed ZIP members SHA-256 reread; archive stat/central directories, not whole-ZIP byte hashes'}
    directory = child(db.root, 'reports', batch)
    atomic_text(child(directory, 'recovery.jsonl'), ''.join(canonical(r)+'\n' for r in records))
    csv_buffer = io.StringIO()
    fields = ['occurrence_id','media_id','original_path','state','capture_utc','capture_source','latitude','longitude','gps_source',
              'review_reasons','source_verified','source_sha256','staged_path','proposed_final_path','embedding_status','copy_status',
              'media_subtype','gps_requirement']
    writer = csv.DictWriter(csv_buffer,fieldnames=fields); writer.writeheader()
    for r in records:
        captured = r.get('capture',{}).get('selected') or {}; gps = r.get('observed_gps',{}).get('selected') or {}
        values = dict(occurrence_id=r['occurrence_id'],media_id=r['media_id'],original_path=r['source']['member'],state=r['state'],
            capture_utc=captured.get('utc'),capture_source=captured.get('source'),latitude=gps.get('latitude'),longitude=gps.get('longitude'),
            gps_source=gps.get('source'),review_reasons='; '.join(r.get('review_reasons',[])),source_verified=r.get('source_verified'),
            source_sha256=r.get('source_sha256'),staged_path=r.get('paths',{}).get('staged'),proposed_final_path=r.get('paths',{}).get('proposed_final'),
            embedding_status=r.get('embedding_status'),copy_status=r.get('verification',{}).get('status'),
            media_subtype=r['media_subtype'],gps_requirement=r['gps_requirement']['status'])
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in values.items()})
    atomic_text(child(directory,'review.csv'),csv_buffer.getvalue())
    atomic_text(child(directory, 'summary.json'), json.dumps(report, indent=2)+'\n')
    atomic_text(child(directory, 'summary.md'), '# Takeout metadata/GPS dry run\n\n'+
                f"Sample: {len(rows)}. Complete: {counts['complete']}. Errors: {counts['error']}.\n\n"+
                f"GPS available: {counts['gps_available']}; selected without conflict: {counts['gps_selected']}. "
                f"Unchanged selected sources: {counts['unchanged_sources']}. Verified working copies: {counts['verified_copies']}.\n\n"+
                f"GPS not expected for {counts['confirmed_screenshots_gps_exempt']} confirmed screenshots. "
                f"Expected-GPS coverage: {counts['gps_expected_selected']}/{counts['gps_expected']}.\n\n"+
                'Store accuracy and cross-store errors are not evaluated: no real directory or ground truth. '
                'Full recovery and live import still require approval.\n\n'+
                '\n'.join(f'- {k}: {v}' for k,v in sorted(reasons.items()))+'\n')
    envelopes = []
    for r in records:
        if r['state'] != 'complete':
            continue
        occurrence = next(x for x in rows if x['id'] == r['occurrence_id'])
        envelope = {'schema': 'sacc.takeout.media.v1', 'media_id': r['media_id'], 'occurrence_id': r['occurrence_id'],
                    'media_asset': {'shoe_id': None, 'media_type': occurrence['media_type'], 'file_path': r['paths']['staged'],
                                    'source_path': r['source']['archive']+'#'+r['source']['member'],
                                    'file_size_bytes': occurrence['size_bytes'], 'mime_type': r['mime_type'],
                                    'storage_backend': 'local', 'storage_key': r['media_id'], 'confidence': 0.0,
                                    'needs_review': True, 'review_reason': 'takeout_pending_review_and_shoe_link'},
                    'recovery': r, 'live_import_eligible': False,
                    'stage_extensions': {'video_filter': None, 'classification': None, 'local_context': None}}
        validate_envelope(envelope)
        envelopes.append(envelope)
    atomic_text(child(directory, 'sacc_payloads.jsonl'), ''.join(canonical(r)+'\n' for r in envelopes))
    return report


def validate_envelope(row):
    asset = row.get('media_asset', {})
    if row.get('schema') != 'sacc.takeout.media.v1' or not row.get('media_id') or asset.get('media_type') not in {'image', 'video'}:
        raise ValueError('Invalid SACC recovery envelope')
    if asset.get('shoe_id') is not None or row.get('live_import_eligible') is not False:
        raise ValueError('Milestone envelopes cannot authorize live import')
    for field in ('file_path', 'source_path', 'mime_type', 'review_reason'):
        if not isinstance(asset.get(field), str) or not asset[field]:
            raise ValueError('Missing SACC asset field: '+field)
    if type(asset.get('file_size_bytes')) is not int or asset['file_size_bytes'] < 0:
        raise ValueError('Invalid asset size')


def dry_run(discovery, output, account, export_key, limit=200, seed=20261029, as_of=None, progress=None):
    if type(limit) is not int or not 1 <= limit <= MAX_SAMPLE:
        raise ValueError('Sample limit must be 1..200')
    if not account or not export_key:
        raise ValueError('Account and batch labels required')
    archives, inventory, identity, summary = load_inventory(discovery)
    output = private_root(output, [a['path'] for a in archives])
    with run_lock(output):
        db = Manifest(output)
        try:
            existing = db.con.execute('SELECT config_json FROM batches WHERE id=?',(token('batch',account,export_key),)).fetchone()
            as_of = as_of or (json.loads(existing[0])['as_of'] if existing else date.today().isoformat())
            config = {'limit': limit, 'seed': seed, 'as_of': as_of, 'policy': POLICY_VERSION, 'gps_tolerance_m': 100}
            batch = register(db, account, export_key, archives, inventory, identity, summary, config)
            rows = selected_rows(db, batch)
            if shutil.disk_usage(output).free < sum(r['size_bytes'] for r in rows)*3 + 1024**3:
                raise ValueError('Insufficient free space for sample staging, copies and reserve')
            by_id = {token(batch, r['archive'], r['index'], r['member']): r for r in inventory}
            resumed, pending = 0, []
            for row in rows:
                old = db.result(row['id'])
                result = old['result']
                if old['state'] == 'complete':
                    path = child(output, 'staged', batch, row['id']+PurePosixPath(row['member']).suffix.lower())
                    verification = result.get('verification', {})
                    valid_copy = not verification or (Path(verification['path']).is_file()
                        and file_hash(child(output, *Path(verification['path']).relative_to(output).parts)) == verification['sha256']
                        and Path(verification['path']).stat().st_mtime_ns == verification['mtime_ns'])
                    if path.is_file() and file_hash(path) == result['source_sha256'] and valid_copy:
                        resumed += 1
                        continue
                    # Preserve prior evidence and fail closed; never silently overwrite a changed completed artifact.
                    db.save_result(row['id'], 'error', result, 'Completed output integrity mismatch; inspect before retry')
                    continue
                if old['error'] and 'integrity mismatch' in old['error']:
                    continue
                try:
                    path = child(output, 'staged', batch, row['id']+PurePosixPath(row['member']).suffix.lower())
                    pair = json.loads(row['match_json'])
                    doc, sidecar_hash = read_sidecar(pair) if pair['status'] == 'matched' else ({}, None)
                    digest = read_member(row, path)
                    if file_hash(path) != digest:
                        raise ValueError('Staging hash mismatch')
                    media_id = db.link_media(row['id'], account, digest, row['media_type'], row['size_bytes'])
                    base = {'source_sha256': digest, 'sidecar_sha256': sidecar_hash, 'media_id': media_id,
                            'account_id': account, 'paths': {'staged': str(path), 'proposed_final': None}, 'match_status': pair['status']}
                    db.save_result(row['id'], 'staged', base)
                    pending.append((row, path, doc, base))
                except Exception as exc:
                    db.save_result(row['id'], 'error', result, str(exc))
                if progress:
                    progress({'stage': 'staging', 'prepared': len(pending), 'resumed': resumed, 'total': len(rows)})
            embedded = read_tags([p for _,p,_,_ in pending]) if pending else {}
            for row, path, doc, base in pending:
                try:
                    result = {**base, **propose(doc, embedded[str(path)], by_id[row['id']]['zip_time'], date.fromisoformat(as_of))}
                    if base['match_status'] != 'matched':
                        result['review_reasons'].append(base['match_status'])
                    if read_member(row) != base['source_sha256'] or file_hash(path) != base['source_sha256']:
                        raise ValueError('Source hash changed during metadata read')
                    result['source_verified'] = True
                    result['mime_type'] = embedded[str(path)].get('File:MIMEType') or mimetypes.guess_type(path)[0] or 'application/octet-stream'
                    if not result['mime_type'].startswith('image/' if row['media_type']=='image' else 'video/'):
                        result['review_reasons'].append('detected_media_type_mismatch')
                    expected_type = {'.jpg':'JPEG','.jpeg':'JPEG','.png':'PNG'}.get(path.suffix)
                    if expected_type and embedded[str(path)].get('File:FileType') != expected_type:
                        result['review_reasons'].append('detected_media_type_mismatch')
                    result['review_reasons'] = sorted(set(result['review_reasons']))
                    result['embedding_status'] = 'proposal_only' if path.suffix in COPY_FORMATS else 'manifest_only_format'
                    selected = result['capture']['selected']
                    period = selected['utc'][:7].replace('-', '/') if selected and selected['utc'] else 'undated'
                    result['paths']['proposed_final'] = ('Photos/' if row['media_type']=='image' else 'Videos/')+period+'/'+row['id']+path.suffix
                    db.save_result(row['id'], 'complete', result)
                except Exception as exc:
                    db.save_result(row['id'], 'error', base, str(exc))
            for a in archives:
                assert_archive(a)
            members, observations = {}, defaultdict(list)
            for row in rows:
                saved = db.result(row['id'])
                if saved['state'] != 'complete':
                    continue
                r = saved['result']; selected = r['capture']['selected']
                observations[r['media_id']].append((row['id'], r))
                members.setdefault(r['media_id'], {'media_id': r['media_id'], 'account_id': account,
                    'capture_utc': selected['utc'] if selected else None, 'gps': r['observed_gps']['selected'],
                    'date_uncertain': not r['capture']['safe_to_embed']})
            for mid, copies in observations.items():
                copies = [(row['occurrence_id'], json.loads(row['result_json'])) for row in db.con.execute(
                    "SELECT r.occurrence_id,r.result_json FROM recovery_results r JOIN occurrences o ON o.id=r.occurrence_id WHERE o.media_id=? AND r.state='complete'",(mid,))]
                signatures = {canonical({'capture': (r['capture']['selected'] or {}).get('utc'),
                    'gps': {k:r['observed_gps']['selected'].get(k) for k in ('latitude','longitude')} if r['observed_gps']['selected'] else None}) for _,r in copies}
                if len(signatures) > 1:
                    del members[mid]  # No arbitrary winner across album/export observations.
                    for oid,r in copies:
                        r['review_reasons'] = sorted(set(r['review_reasons']+['duplicate_metadata_conflict']))
                        db.save_result(oid,'complete',r)
                    with db.con:
                        db.con.execute("UPDATE visits SET status='needs_review' WHERE id IN (SELECT visit_id FROM visit_members WHERE media_id=?)",(mid,))
                        db.event(None,'duplicate_metadata_conflict',{'media_id':mid,'occurrences':[oid for oid,_ in copies]})
            for group in propose_stops(list(members.values())):
                save_visit(db, account, group, {'method': 'sample_only_temporal_gps_proposal', 'confirmed': False})
            return export_report(db, batch, resumed)
        finally:
            db.close()


def verify_copies(output, batch):
    output = private_root(output)
    with run_lock(output):
        db = Manifest(output)
        try:
            # Immutable selection is persisted even when a copy attempt fails.
            with db.con:
                db.con.execute('CREATE TABLE IF NOT EXISTS copy_members(batch_id TEXT, occurrence_id TEXT UNIQUE REFERENCES occurrences(id), PRIMARY KEY(batch_id,occurrence_id))')
            chosen = [r[0] for r in db.con.execute('SELECT occurrence_id FROM copy_members WHERE batch_id=?', (batch,))]
            rows = selected_rows(db, batch)
            if not chosen:
                for row in rows:
                    r = db.result(row['id'])
                    value = r['result']
                    if r['state']=='complete' and Path(row['member']).suffix.lower() in COPY_FORMATS and value['capture']['safe_to_embed'] and value['match_status']=='matched' and not any(
                        k in value['review_reasons'] for k in ('gps_conflict','gps_invalid','gps_conflicting_reference','embedded_read_error','detected_media_type_mismatch','duplicate_metadata_conflict')):
                        chosen.append(row['id'])
                    if len(chosen) == MAX_VERIFY_COPIES:
                        break
                with db.con:
                    db.con.executemany('INSERT INTO copy_members VALUES (?,?)', [(batch, x) for x in chosen])
            for row in rows:
                if row['id'] not in chosen:
                    continue
                saved = db.result(row['id']); result = saved['result']
                try:
                    source = child(output, *Path(result['paths']['staged']).relative_to(output).parts)
                    if file_hash(source) != result['source_sha256']:
                        raise ValueError('Staged source integrity mismatch')
                    prior = result.get('verification')
                    if prior and prior.get('status') == 'verified':
                        dest = child(output, *Path(prior['path']).relative_to(output).parts)
                        if file_hash(dest) != prior['sha256'] or dest.stat().st_mtime_ns != prior['mtime_ns']:
                            raise ValueError('Verified copy integrity mismatch')
                        continue
                    dest = child(output, 'verified', batch, row['id']+source.suffix)
                    if shutil.disk_usage(output).free < row['size_bytes']*2+1024**3:
                        raise ValueError('Insufficient space for verification copy')
                    if dest.exists():
                        # Reproduce expected bytes privately and adopt only an exact,
                        # fully read-back match. Never overwrite an unknown destination.
                        check = child(output,'verified',batch,'.resume-'+uuid.uuid4().hex+source.suffix)
                        try:
                            verification = verify_copy(source,check,result)
                            if file_hash(dest) != verification['sha256'] or dest.stat().st_mtime_ns != verification['mtime_ns']:
                                raise ValueError('Uncommitted copy integrity mismatch; preserved for review')
                            verification['path'] = str(dest)
                            result['verification'] = verification
                            with db.con: db.event(row['id'],'orphan_copy_validated_and_adopted',{'sha256':verification['sha256']})
                        finally:
                            if check.exists():check.unlink()
                    else:
                        result['verification'] = verify_copy(source, dest, result)
                    if read_member(row) != result['source_sha256']:
                        raise ValueError('Original source changed after copy verification')
                    db.save_result(row['id'], 'complete', result)
                except Exception as exc:
                    result['verification_error'] = str(exc)
                    db.save_result(row['id'], 'error', result, str(exc))
            return export_report(db, batch)
        finally:
            db.close()
