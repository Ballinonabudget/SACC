"""Read-only directory snapshots, conservative stops and auditable confirmations."""
from datetime import date, datetime
import json
import uuid

from .common import canonical, finite, token
from .metadata import distance_m, parse_date


def validate_directory(doc):
    if doc.get('schema_version') != 1 or not all(isinstance(doc.get(k), str) and doc[k] for k in ('snapshot_id', 'source', 'provenance')):
        raise ValueError('Directory requires version 1, snapshot_id, source and provenance')
    versions = doc.get('stores')
    if not isinstance(versions, list):
        raise ValueError('stores must be a list')
    seen, branches = set(), {}
    for row in versions:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in
                ('version_id', 'store_id', 'retailer', 'branch', 'store_type', 'provenance')):
            raise ValueError('Each branch version requires stable identities and provenance')
        if row['version_id'] in seen:
            raise ValueError('Duplicate store version')
        seen.add(row['version_id'])
        for key in ('valid_from', 'valid_to'):
            if row.get(key) is not None:
                date.fromisoformat(row[key])
        start, end = row.get('valid_from'), row.get('valid_to')
        if start and end and start > end:
            raise ValueError('Reversed historical interval')
        lat, lon = row.get('latitude'), row.get('longitude')
        if (lat is None) != (lon is None) or (lat is not None and
                (not finite(lat) or not finite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180)):
            raise ValueError('Invalid store coordinates')
        for a, b in branches.setdefault(row['store_id'], []):
            if (start or '0001-01-01') <= (b or '9999-12-31') and (a or '0001-01-01') <= (end or '9999-12-31'):
                raise ValueError('Overlapping historical versions')
        branches[row['store_id']].append((start, end))
    return doc


def import_directory(db, doc):
    validate_directory(doc)
    payload = canonical(doc)
    old = db.con.execute('SELECT payload_json FROM store_snapshots WHERE id=?', (doc['snapshot_id'],)).fetchone()
    if old:
        if old[0] != payload:
            raise ValueError('Snapshot is immutable; use a new snapshot ID')
        return
    with db.con:
        db.con.execute('INSERT INTO store_snapshots VALUES (?,?,?)', (doc['snapshot_id'], doc['source'], payload))
        for row in doc['stores']:
            # Version IDs identify the source snapshot plus its own version key.
            ident = token(doc['source'], doc['snapshot_id'], row['version_id'])
            db.con.execute('INSERT INTO store_versions VALUES (?,?,?,?,?,?,?)',
                           (ident, doc['snapshot_id'], row['store_id'], row.get('venue_id'),
                            row.get('valid_from'), row.get('valid_to'), canonical(row)))


def candidates(stores, gps, captured, tolerance_m=150):
    if not finite(tolerance_m) or tolerance_m < 0:
        raise ValueError('Invalid candidate tolerance')
    if not gps:
        return []
    if not all(finite(gps.get(k)) for k in ('latitude', 'longitude')):
        return []
    accuracy = gps.get('accuracy_m')
    if accuracy is not None and (not finite(accuracy) or accuracy < 0):
        return []
    when = parse_date(captured)
    day = when.date().isoformat() if when and when.tzinfo else None
    result = []
    for store in stores:
        if store.get('latitude') is None:
            continue
        distance = distance_m(store, gps)
        if distance > tolerance_m + (accuracy or 0):
            continue
        start, end = store.get('valid_from'), store.get('valid_to')
        status = 'compatible' if day and start else 'historical_review'
        if day and ((start and day < start) or (end and day > end)):
            status = 'outside_active_dates'
        result.append({'store_id': store['store_id'], 'version_id': store['version_id'],
                       'venue_id': store.get('venue_id'), 'branch': store['branch'], 'retailer': store['retailer'],
                       'distance_m': distance, 'historical_status': status, 'assignment_status': 'candidate_only'})
    return sorted(result, key=lambda r: (r['distance_m'], r['version_id']))


def propose_stops(records, gap_seconds=1200, movement_m=150):
    """Proposed membership only. No-GPS or uncertain dates stay separate."""
    groups = []
    for row in sorted(records, key=lambda r: (r.get('capture_utc') or '', r['media_id'])):
        dt = parse_date(row.get('capture_utc'))
        good = dt is not None and dt.tzinfo is not None and not row.get('date_uncertain')
        attach = False
        if groups and good:
            previous = groups[-1][-1]
            prior = parse_date(previous.get('capture_utc'))
            attach = bool(prior and prior.tzinfo and not previous.get('date_uncertain')
                          and row['account_id'] == previous['account_id']
                          and 0 <= (dt-prior).total_seconds() <= gap_seconds
                          and row.get('gps') and previous.get('gps')
                          and distance_m(row['gps'], previous['gps']) <= movement_m
                          and row.get('store_context') == previous.get('store_context'))
        if attach:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def save_visit(db, account_id, members, evidence, confirmed_members=False):
    if not members:
        raise ValueError('Empty visit')
    ident = token('visit', account_id, sorted(m['media_id'] for m in members))
    with db.con:
        for m in members:
            asset = db.con.execute('SELECT account_id FROM media WHERE id=?', (m['media_id'],)).fetchone()
            if not asset or asset[0] != account_id:
                raise ValueError('Visit cannot mix accounts')
            if confirmed_members and not m.get('membership_evidence'):
                raise ValueError('Confirmed membership requires explicit local evidence')
        db.con.execute('INSERT OR IGNORE INTO visits VALUES (?,?,?,?)', (ident, account_id, 'proposed', canonical(evidence)))
        for m in members:
            db.con.execute('INSERT OR IGNORE INTO visit_members VALUES (?,?,?,?,?)',
                           (ident, m['media_id'], m.get('capture_utc'), canonical(m.get('membership_evidence', {})), int(confirmed_members)))
            if confirmed_members:
                before = dict(db.con.execute('SELECT * FROM visit_members WHERE visit_id=? AND media_id=?', (ident,m['media_id'])).fetchone())
                db.con.execute('UPDATE visit_members SET confirmed=1,evidence_json=? WHERE visit_id=? AND media_id=?',
                               (canonical(m['membership_evidence']),ident,m['media_id']))
                db.event(None,'membership_confirmed',{'visit_id':ident,'media_id':m['media_id'],'before':before,'evidence':m['membership_evidence']})
    return ident


def confirm_visit(db, visit_id, version_id, reviewer, evidence, parents=()):
    if not reviewer or evidence.get('kind') not in {'signage', 'local_video', 'user_branch_confirmation'} or not evidence.get('source_media_id'):
        raise ValueError('Exact branch confirmation requires reviewer and local contextual evidence; shoe brand is insufficient')
    version = db.con.execute('SELECT * FROM store_versions WHERE id=?', (version_id,)).fetchone()
    visit = db.con.execute('SELECT status FROM visits WHERE id=?',(visit_id,)).fetchone()
    if visit and visit[0]=='needs_review' and not evidence.get('metadata_conflict_resolution'):
        raise ValueError('Conflicting visit evidence requires an explicit reviewed resolution')
    members = db.con.execute('SELECT * FROM visit_members WHERE visit_id=?', (visit_id,)).fetchall()
    if not version or not members or evidence['source_media_id'] not in {r['media_id'] for r in members}:
        raise ValueError('Unknown version/visit or unrelated evidence media')
    for r in members:
        dt = parse_date(r['capture_utc'])
        if not dt or not dt.tzinfo:
            raise ValueError('Uncertain capture date requires review before confirmation')
        day = dt.date().isoformat()
        if (version['valid_from'] and day < version['valid_from']) or (version['valid_to'] and day > version['valid_to']):
            raise ValueError('Store version cannot explain this historical visit')
        if not version['valid_from'] and not evidence.get('historical_evidence'):
            raise ValueError('Unknown opening date requires historical evidence')
    invalid = invalid_confirmations(db)
    for parent in parents:
        active = db.con.execute('SELECT id FROM confirmations WHERE id=? AND id NOT IN (SELECT confirmation_id FROM revocations)', (parent,)).fetchone()
        if not active or parent in invalid:
            raise ValueError('Reused confirmation is missing, revoked, or depends on disputed evidence')
        p = db.con.execute('SELECT store_version_id FROM confirmations WHERE id=?', (parent,)).fetchone()
        if p[0] != version_id or not evidence.get('reuse_context_reviewed'):
            raise ValueError('Reuse requires same historical branch and explicitly reviewed context')
    ident = uuid.uuid4().hex
    with db.con:
        active = db.con.execute('SELECT id FROM confirmations WHERE visit_id=? AND id NOT IN (SELECT confirmation_id FROM revocations)', (visit_id,)).fetchall()
        if active:
            raise ValueError('Revoke the prior confirmation explicitly before correcting it')
        db.con.execute('INSERT INTO confirmations(id,visit_id,store_version_id,reviewer,payload_json) VALUES (?,?,?,?,?)',
                       (ident, visit_id, version_id, reviewer, canonical(evidence)))
        for parent in parents:
            db.con.execute('INSERT INTO confirmation_dependencies VALUES (?,?)', (ident, parent))
        for r in members:
            if not r['confirmed']:
                continue  # Temporal proximity alone cannot inherit a store, especially without GPS.
            db.con.execute('INSERT INTO assignments VALUES (?,?,?,?,?,?,?)',
                           (token(ident, r['media_id']), r['media_id'], visit_id, ident, version_id,
                            'confirmed_visit_inference', canonical({'confirmation': ident, 'membership': json.loads(r['evidence_json'])})))
        db.event(None, 'visit_confirmed', {'confirmation_id': ident})
        db.con.execute("UPDATE visits SET status='confirmed' WHERE id=?",(visit_id,))
    return ident


def revoke(db, confirmation_id, reason):
    if not reason or not db.con.execute('SELECT 1 FROM confirmations WHERE id=?', (confirmation_id,)).fetchone():
        raise ValueError('Known confirmation and reason required')
    affected = {confirmation_id}
    while True:
        children = {r[0] for r in db.con.execute('SELECT child_id,parent_id FROM confirmation_dependencies') if r[1] in affected}
        if children <= affected:
            break
        affected |= children
    with db.con:
        for ident in affected:
            db.con.execute('INSERT OR IGNORE INTO revocations(confirmation_id,reason) VALUES (?,?)', (ident, reason))
        db.event(None, 'confirmation_revoked', {'root': confirmation_id, 'dependents': sorted(affected), 'reason': reason})
    return affected


def visit_timeline(db, visit_id):
    rows = db.con.execute('''SELECT vm.*, m.media_type,
        (SELECT json_extract(r.result_json,'$.paths.staged') FROM occurrences o JOIN recovery_results r ON r.occurrence_id=o.id
         WHERE o.media_id=vm.media_id AND r.state='complete' LIMIT 1) AS working_path
        FROM visit_members vm JOIN media m ON m.id=vm.media_id WHERE visit_id=? ORDER BY capture_utc,media_id''', (visit_id,))
    return [dict(r) for r in rows]


def active_assignments(db, media_id):
    invalid = invalid_confirmations(db)
    return [dict(r) for r in db.con.execute('''SELECT a.*,s.store_id,s.venue_id FROM assignments a
        JOIN store_versions s ON s.id=a.store_version_id WHERE a.media_id=?
        AND a.visit_id IN (SELECT id FROM visits WHERE status!='needs_review')
        AND a.confirmation_id NOT IN (SELECT confirmation_id FROM revocations)''', (media_id,))
        if r['confirmation_id'] not in invalid]


def invalid_confirmations(db):
    """A disputed or revoked parent invalidates every transitive reuse."""
    invalid = {r[0] for r in db.con.execute('''SELECT c.id FROM confirmations c JOIN visits v ON v.id=c.visit_id
        WHERE v.status='needs_review' OR c.id IN (SELECT confirmation_id FROM revocations)''')}
    dependencies = list(db.con.execute('SELECT child_id,parent_id FROM confirmation_dependencies'))
    while True:
        children = {r[0] for r in dependencies if r[1] in invalid}
        if children <= invalid:
            return invalid
        invalid |= children
