"""Local triage persistence and bounded retries; model imports live in the CLI."""
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from .common import canonical, run_lock
from .library_projection import projection, triage_record

POLICY = 'sacc.local-triage.v2'
SUCCESS_CATEGORIES = {'non_personal', 'personal', 'mixed', 'unknown'}


def migrate(con):
    """Explicit additive extension migration; caller owns the transaction."""
    con.execute('CREATE TABLE IF NOT EXISTS library_triage_schema(version INTEGER PRIMARY KEY CHECK(version=1))')
    versions = [r[0] for r in con.execute('SELECT version FROM library_triage_schema')]
    if versions not in ([], [1]):
        raise ValueError('Unsupported triage extension')
    con.execute('''CREATE TABLE IF NOT EXISTS library_triage_detections(
        id TEXT PRIMARY KEY REFERENCES library_occurrences(id), category TEXT NOT NULL,
        shoe_conf REAL NOT NULL, person_conf REAL NOT NULL, detections_json TEXT NOT NULL,
        processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    columns = {r['name'] for r in con.execute('PRAGMA table_info(library_triage_detections)')}
    additions = {
        'status': "TEXT NOT NULL DEFAULT 'succeeded'",
        'policy_version': "TEXT NOT NULL DEFAULT 'legacy-v1'",
        'model_sha256': 'TEXT', 'input_sha256': 'TEXT',
        'attempts': 'INTEGER NOT NULL DEFAULT 1', 'error': 'TEXT',
    }
    for name, kind in additions.items():
        if name not in columns:
            con.execute(f'ALTER TABLE library_triage_detections ADD COLUMN {name} {kind}')
    if not versions:
        con.execute("UPDATE library_triage_detections SET status='failed',error='legacy_processing_error' WHERE category='error'")
        con.execute('INSERT INTO library_triage_schema VALUES(1)')
    con.execute('CREATE INDEX IF NOT EXISTS library_triage_status ON library_triage_detections(status,id)')
    con.execute('CREATE INDEX IF NOT EXISTS library_review_occurrence ON library_review_events(occurrence_id,id)')


def _event(con, row, action, value, details):
    revision = row['review_revision'] + 1
    con.execute('UPDATE library_occurrences SET review_revision=? WHERE id=?', (revision, row['id']))
    con.execute('''INSERT INTO library_review_events
        (occurrence_id,revision,action,value_json,reviewer,evidence,details_json)
        VALUES(?,?,?,?,?,?,?)''', (row['id'], revision, action, canonical(value), 'local-triage',
        'Local automatic processing; preserves human overrides and is not privacy approval', canonical(details)))


def repair_catalog(db, legacy_tail=0, apply=False):
    """Repair a single transaction; dry runs roll back schema and data changes."""
    if type(legacy_tail) is not int or not 0 <= legacy_tail < 16:
        raise ValueError('Legacy tail must be between 0 and 15')
    result = {'projection_changes': 0, 'restored_metadata_flags': 0, 'privacy_changes': 0, 'tail_pending': 0}
    with run_lock(db.path.parent), db.connection(write=True) as con:
        con.execute('BEGIN IMMEDIATE')
        migrate(con)
        if legacy_tail and not con.execute("SELECT 1 FROM library_meta WHERE key='triage_legacy_tail_repair'").fetchone():
            count = con.execute('SELECT COUNT(*) FROM library_occurrences').fetchone()[0]
            rows = con.execute('''SELECT d.* FROM library_occurrences o
                JOIN library_triage_detections d ON d.id=o.id ORDER BY o.rowid DESC LIMIT ?''', (legacy_tail,)).fetchall()
            if count % 16 != legacy_tail or len(rows) != legacy_tail or any(
                r['category'] != 'unknown' or r['shoe_conf'] != 0 or r['person_conf'] != 0
                or json.loads(r['detections_json']) != [] or r['policy_version'] != 'legacy-v1'
                for r in rows):
                raise ValueError('Legacy tail does not match the verified unprocessed signature')
            for row in rows:
                con.execute("UPDATE library_triage_detections SET status='pending',attempts=0,error='legacy_tail_not_inferred' WHERE id=?", (row['id'],))
            con.execute('INSERT INTO library_meta VALUES(?,?)', ('triage_legacy_tail_repair', canonical({'ids':[r['id'] for r in rows], 'policy':POLICY})))
            result['tail_pending'] = len(rows)
        for row in con.execute('SELECT * FROM library_occurrences ORDER BY rowid'):
            effective = projection(row['raw_json'], row['embedding_status'], row['overrides_json'], triage_record(con, row['id']))
            if effective['privacy'] == row['privacy'] and effective['needs_attention'] == row['needs_attention']:
                continue
            result['projection_changes'] += 1
            result['privacy_changes'] += int(effective['privacy'] != row['privacy'])
            result['restored_metadata_flags'] += int(effective['metadata_attention'] and not row['needs_attention'])
            con.execute('UPDATE library_occurrences SET privacy=?,needs_attention=? WHERE id=?',
                        (effective['privacy'], effective['needs_attention'], row['id']))
            _event(con, row, 'triage_repair', POLICY,
                   {'previous_privacy':row['privacy'], 'previous_attention':row['needs_attention'],
                    'privacy':effective['privacy'], 'needs_attention':effective['needs_attention']})
        result['retryable'] = con.execute("SELECT COUNT(*) FROM library_triage_detections WHERE status IN ('failed','pending')").fetchone()[0]
        if not apply:
            con.rollback()
    return result | {'applied':apply}


def save_results(db, results, model_sha256):
    with db.connection(write=True) as con:
        con.execute('BEGIN IMMEDIATE')
        for result in results:
            row = con.execute('SELECT * FROM library_occurrences WHERE id=?', (result['id'],)).fetchone()
            if row is None:
                raise ValueError('Triage occurrence no longer exists')
            if row['final_sha256'] != result['input_sha256']:
                raise ValueError('Triage source identity changed; retry after reloading')
            category = result['category']
            if category not in SUCCESS_CATEGORIES | {'error'}:
                raise ValueError('Invalid triage category')
            previous = triage_record(con, row['id'])
            status = 'failed' if category == 'error' else 'succeeded'
            detection = result | {'status':status}
            effective = projection(row['raw_json'], row['embedding_status'], row['overrides_json'], detection)
            con.execute('''INSERT INTO library_triage_detections
                (id,category,shoe_conf,person_conf,detections_json,status,policy_version,model_sha256,input_sha256,attempts,error)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                category=excluded.category,shoe_conf=excluded.shoe_conf,person_conf=excluded.person_conf,
                detections_json=excluded.detections_json,status=excluded.status,policy_version=excluded.policy_version,
                model_sha256=excluded.model_sha256,input_sha256=excluded.input_sha256,attempts=excluded.attempts,
                error=excluded.error,processed_at=CURRENT_TIMESTAMP''',
                (row['id'],category,result.get('shoe_conf',0),result.get('person_conf',0),canonical(result.get('detections',[])),
                 status,POLICY,model_sha256,result['input_sha256'],(previous or {}).get('attempts',0)+1,result.get('error')))
            con.execute('UPDATE library_occurrences SET privacy=?,needs_attention=? WHERE id=?',
                        (effective['privacy'],effective['needs_attention'],row['id']))
            _event(con,row,'triage_result',{'category':category,'status':status},
                   {'policy':POLICY,'model_sha256':model_sha256,'input_sha256':result['input_sha256'],
                    'previous_category':(previous or {}).get('category'),'manual_override_preserved':'privacy' in json.loads(row['overrides_json'])})


def prepare_input(db, row, scratch):
    asset = db.asset(row['id'])
    if row['media_type'] == 'image':
        return str(asset['path'])
    if row['media_type'] != 'video':
        raise ValueError('unsupported_media_type')
    output = Path(scratch)/(row['id']+'.jpg')
    for second in (1, 0):
        output.unlink(missing_ok=True)
        result = subprocess.run(['ffmpeg','-nostdin','-y','-ss',str(second),'-i',str(asset['path']),
                                 '-vframes','1','-q:v','3',str(output)],
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        if result.returncode == 0 and output.is_file() and output.stat().st_size:
            return str(output)
    raise ValueError('video_frame_unavailable')


def run_triage(db, predictor, *, model_sha256, batch_size=16, limit=0,
               stopping=lambda:False, progress=None, prepare=prepare_input):
    if not 1 <= batch_size <= 64 or limit < 0:
        raise ValueError('Invalid triage bounds')
    counts = {'attempted':0,'succeeded':0,'failed':0}
    with run_lock(db.path.parent), tempfile.TemporaryDirectory(prefix='sacc-triage-') as scratch:
        with db.connection(write=True) as con:
            con.execute('BEGIN IMMEDIATE');migrate(con)
        after = 0
        while not stopping() and (not limit or counts['attempted'] < limit):
            size = min(batch_size, limit-counts['attempted']) if limit else batch_size
            with db.connection() as con:
                rows = [dict(r) for r in con.execute('''SELECT o.rowid AS sequence,o.* FROM library_occurrences o
                    LEFT JOIN library_triage_detections d ON d.id=o.id
                    WHERE o.rowid>? AND (d.id IS NULL OR d.status IN ('failed','pending'))
                    ORDER BY o.rowid LIMIT ?''',(after,size))]
            if not rows:
                break
            ready=[];results=[]
            def failed(row, reason):
                return {'id':row['id'],'input_sha256':row['final_sha256'],'category':'error','error':reason}
            for row in rows:
                try:ready.append((row,prepare(db,row,scratch)))
                except Exception as exc:results.append(failed(row,'prepare_failed:'+type(exc).__name__))
            if stopping():
                break  # No checkpoint claims that unprocessed rows were inferred.
            if ready:
                try:
                    predictions=list(predictor([p for _,p in ready]))
                    if len(predictions)!=len(ready):raise ValueError('prediction_count_mismatch')
                    results.extend(dict(pred,id=row['id'],input_sha256=row['final_sha256']) for (row,_),pred in zip(ready,predictions))
                except Exception:
                    for row,path in ready:
                        try:
                            predictions=list(predictor([path]))
                            if len(predictions)!=1:raise ValueError('prediction_count_mismatch')
                            results.append(dict(predictions[0],id=row['id'],input_sha256=row['final_sha256']))
                        except Exception as exc:results.append(failed(row,'inference_failed:'+type(exc).__name__))
            save_results(db,results,model_sha256)
            after=rows[-1]['sequence'];counts['attempted']+=len(results)
            counts['failed']+=sum(r['category']=='error' for r in results)
            counts['succeeded']=counts['attempted']-counts['failed']
            for path in Path(scratch).iterdir():path.unlink()
            if progress:progress(dict(counts))
        with db.connection() as con:
            counts['retryable_remaining']=con.execute('''SELECT COUNT(*) FROM library_occurrences o
                LEFT JOIN library_triage_detections d ON d.id=o.id
                WHERE d.id IS NULL OR d.status IN ('failed','pending')''').fetchone()[0]
    return counts | {'interrupted':bool(stopping())}
