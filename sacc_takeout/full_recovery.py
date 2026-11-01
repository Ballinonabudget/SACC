"""Local two-pass recovery with immutable scopes and explicit execution approval."""
from collections import Counter
from contextlib import contextmanager
from datetime import date
import hashlib
import csv
import errno
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
import uuid

from .common import atomic_text, canonical, child, file_hash, no_symlinks, private_root, run_lock, safe_member, token
from .importer import fingerprint, validate_envelope
from .metadata import COPY_FORMATS, propose, raw as raw_value
from .recovery_store import Ledger, bounded_json, open_ledger, sync_dir
from .review_policy import reviewed_result
from .trip_preview import ReadOnlyPreview
from . import recovery_io

VERSION = 'full-recovery-v1'
MAX_PILOT_FILES = 12
MAX_PILOT_BYTES = 128*1024**2
MAX_ATTEMPTS = 3
MAX_RECORD = 16*1024**2
METADATA_PER_ITEM = 162090
REVIEW_TABLES = ('accounts','assignments','batches','confirmation_dependencies','confirmations',
                'media','media_links','revocations','stage_results','store_snapshots','store_versions',
                'visit_members','visits')
TERMINAL = {'complete','review'}


class CapacityPause(RuntimeError):
    pass


def tool_version():
    return recovery_io.run_tool(['exiftool','-ver'], timeout=10, max_output=1024).strip()


def _hash_rows(rows):
    digest = hashlib.sha256()
    for r in rows:
        digest.update((canonical(r)+'\n').encode())
    return digest.hexdigest()


def _review_rows(source):
    for table in sorted((*REVIEW_TABLES,'prior_observations')):
        query=('''SELECT o.id,o.media_id,m.account_id,m.sha256,r.result_json
            FROM recovery_results r JOIN occurrences o ON o.id=r.occurrence_id
            JOIN media m ON m.id=o.media_id WHERE r.state='complete' ORDER BY o.id'''
            if table=='prior_observations' else 'SELECT * FROM '+table+' ORDER BY rowid')
        for i,r in enumerate(source.con.execute(query)):
            yield table,i,dict(r)


def _copy_reviews(source,target,version,check_space=None):
    """Preserve complete context graphs and original row ordering, not a positive subset."""
    digest=hashlib.sha256()
    for count,(table,i,record) in enumerate(_review_rows(source)):
        target.con.execute('INSERT INTO reviews VALUES(?,?,?,?)',(version,table,i,bounded_json(record)))
        digest.update((canonical([table,i,record])+'\n').encode())
        if check_space and count%128==0:
            check_space()
    if check_space:
        check_space()
    return digest.hexdigest()


def _sample_selection(source, batch, max_files, max_bytes):
    rows=list(source.con.execute('''SELECT o.id,o.size_bytes,o.media_type,r.result_json
        FROM sample_members s JOIN occurrences o ON o.id=s.occurrence_id
        JOIN recovery_results r ON r.occurrence_id=o.id WHERE s.batch_id=? AND r.state='complete'
        ORDER BY s.ordinal''',(batch,)))
    verified=[r for r in rows if json.loads(r['result_json']).get('verification',{}).get('status')=='verified']
    videos=sorted((r for r in rows if r['media_type']=='video'),key=lambda r:(r['size_bytes'],r['id']))
    # Include a small retained video when available; this does not enable video embedding.
    preferred=verified[:max(0,max_files-1)] + videos[:1] + verified + rows
    picked=[];used=0
    for r in preferred:
        if r['id'] not in picked and used+r['size_bytes']<=max_bytes:
            picked.append(r['id']);used+=r['size_bytes']
            if len(picked)==max_files:
                break
    return picked


def create_plan(source_root, batch, output, *, mode='full', source_kind='zip', selection=None,
                max_files=MAX_PILOT_FILES, max_bytes=MAX_PILOT_BYTES):
    """Metadata-only planning. No source payload reads, approvals or milestone writes."""
    if mode not in {'full','pilot'} or source_kind not in {'zip','sample'}:
        raise ValueError('Invalid recovery mode/source kind')
    if source_kind=='sample' and mode!='pilot':
        raise ValueError('Existing-sample source is exclusively a bounded pilot')
    if mode=='pilot' and (type(max_files) is not int or not 1<=max_files<=MAX_PILOT_FILES
                         or type(max_bytes) is not int or not 1<=max_bytes<=MAX_PILOT_BYTES):
        raise ValueError('Pilot caps must be 1..12 files and at most 128 MiB')
    source_root=no_symlinks(Path(source_root).expanduser()).resolve(strict=True)
    source_path=child(source_root,'recovery.sqlite3')
    if not source_path.is_file():
        raise ValueError('Existing milestone manifest required')
    source=ReadOnlyPreview(source_path)
    temporary=None
    try:
        b=source.con.execute('SELECT * FROM batches WHERE id=?',(batch,)).fetchone()
        if not b:
            raise ValueError('Unknown export batch')
        if source.con.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Incomplete source review/dependency graph')
        archives=[{'path':r['path'],'fingerprint':json.loads(r['fingerprint_json'])}
                  for r in source.con.execute('SELECT * FROM archives WHERE batch_id=? ORDER BY path',(batch,))]
        proposed_output=no_symlinks(Path(output).expanduser()).resolve()
        if proposed_output==source_root or proposed_output.is_relative_to(source_root) or source_root.is_relative_to(proposed_output):
            raise ValueError('Full-recovery output must be separate from milestone artifacts')
        if proposed_output.exists() and any(p.name!='.recovery.lock' for p in proposed_output.iterdir()):
            raise ValueError('Recovery planning requires a new empty output directory')
        output=private_root(proposed_output,[r['path'] for r in archives])
        with run_lock(output):
            if child(output,'recovery-run.sqlite3').exists() or child(output,'plan.json').exists():
                raise ValueError('Plan already exists; use its immutable scope or a different output root')
            if source_kind=='zip':
                for a in archives:
                    no_symlinks(Path(a['path']))
                    if fingerprint(a['path'])!=a['fingerprint']:
                        raise ValueError('Archive changed since inventory; create new discovery/batch')
            if mode=='pilot':
                selection=selection if selection is not None else _sample_selection(source,batch,max_files,max_bytes)
                if not selection or len(selection)!=len(set(selection)) or len(selection)>max_files:
                    raise ValueError('Invalid or empty bounded pilot selection')
                selected=set(selection)
            elif selection is not None:
                raise ValueError('Full plan must cover the complete immutable batch')
            else:
                selected=None
            temporary=child(output,'.planning-'+uuid.uuid4().hex+'.sqlite3')
            db=Ledger(temporary,create=True)
            try:
                digest=hashlib.sha256();total=count=largest=sidecar_bytes=0;found=set()
                query='''SELECT o.*,a.path AS archive,r.result_json AS prior_result,r.state AS prior_state,m.sha256 AS prior_sha256,
                    m.account_id AS prior_account,m.media_type AS prior_type,m.size_bytes AS prior_size
                    FROM occurrences o JOIN archives a ON a.id=o.archive_id
                    LEFT JOIN recovery_results r ON r.occurrence_id=o.id LEFT JOIN media m ON m.id=o.media_id
                    WHERE o.batch_id=? ORDER BY a.path,o.member_index,o.id'''
                with db.con:
                    for row in source.con.execute(query,(batch,)):
                        if selected is not None and row['id'] not in selected:
                            continue
                        safe_member(row['member'])
                        match=json.loads(row['match_json'])
                        prior=json.loads(row['prior_result']) if row['prior_result'] else None
                        entry={'archive':row['archive'],'member':row['member'],'index':row['member_index'],
                               'size':row['size_bytes'],'crc':row['crc']}
                        sidecar=match.get('sidecar')
                        if sidecar:
                            safe_member(sidecar['member'])
                            sidecar_bytes+=sidecar['size']
                        item={'id':row['id'],'size':row['size_bytes'],'media_type':row['media_type'],
                              'entry':entry,'match':match,'prior':prior,'known_media_id':row['media_id']}
                        if source_kind=='sample':
                            if not prior or not (row['prior_state']=='complete' and prior.get('source_verified') is True and prior.get('account_id')==b['account_id']
                                and prior.get('source_sha256')==row['prior_sha256'] and row['prior_account']==b['account_id']
                                and row['prior_size']==row['size_bytes'] and row['prior_type']==row['media_type']
                                and prior.get('media_id')==row['media_id']==token('media',b['account_id'],row['prior_sha256'])):
                                raise ValueError('Pilot requires consistent recorded source-verification provenance')
                            p=no_symlinks(Path(prior['paths']['staged']))
                            if not p.is_relative_to(source_root) or not p.is_file() or p.stat().st_size!=row['size_bytes']:
                                raise ValueError('Pilot sample path/size mismatch')
                            item['sample_file']=str(p)
                        encoded=bounded_json(item)
                        digest.update((encoded+'\n').encode())
                        db.con.execute('INSERT INTO items(id,ordinal,size_bytes,media_type,source_json) VALUES(?,?,?,?,?)',
                                       (row['id'],count,row['size_bytes'],row['media_type'],encoded))
                        total+=row['size_bytes'];count+=1;largest=max(largest,row['size_bytes']);found.add(row['id'])
                    if not count or (selected is not None and found!=selected):
                        raise ValueError('Selection contains unknown occurrences or is empty')
                    if mode=='pilot' and (count>max_files or total>max_bytes):
                        raise ValueError('Persisted pilot scope exceeds its file/byte cap')
                    review_hash=_copy_reviews(source,db,1)
                    reserve=max((50 if mode=='full' else 0.5)*1024**3,total//10)
                    baseline_bytes=db.con.execute('PRAGMA page_count').fetchone()[0]*db.con.execute('PRAGMA page_size').fetchone()[0]
                    # Full review history is independent of pilot size. Budget its
                    # measured baseline plus journal/refresh headroom explicitly.
                    metadata_budget=2*baseline_bytes+max(1024**2,count*METADATA_PER_ITEM)
                    plan={'schema':'sacc.takeout.recovery-plan.v1','version':VERSION,'mode':mode,'source_kind':source_kind,
                          'source_root':str(source_root),'output_root':str(output),'account_id':b['account_id'],
                          'batch_id':batch,'inventory_hash':b['inventory_hash'],'archives':archives,
                          'selection_sha256':digest.hexdigest(),'review_snapshot_sha256':review_hash,
                          'files':count,'source_bytes':total,'sidecar_bytes':sidecar_bytes,'largest_member_bytes':largest,
                          'max_files':max_files if mode=='pilot' else count,'max_bytes':max_bytes if mode=='pilot' else total,
                          'max_attempts':MAX_ATTEMPTS,'source_read_budget':MAX_ATTEMPTS*(total+(sidecar_bytes if source_kind=='zip' else 0)),
                          'metadata_budget_bytes':metadata_budget,'measured_ledger_baseline_bytes':baseline_bytes,
                          'reserve_bytes':int(reserve),
                          'required_free_bytes':total+2*largest+metadata_budget+int(reserve),
                          'as_of':json.loads(b['config_json'])['as_of'],'tool_versions':{'exiftool':tool_version()},
                          'writer_formats':sorted(COPY_FORMATS),'remote_eligible':False,
                          'integrity_mode':'zip_crc_sha256_single_stream' if source_kind=='zip' else 'existing_sample_sha256_recheck',
                          'sidecar_mode':'original_zip_bytes' if source_kind=='zip' else 'canonical_sample_snapshot_only'}
                    plan['plan_id']=token('full-recovery-plan',plan)
                    db.set('plan',plan);db.set('review_version',1);db.set('review_hash',review_hash)
                    db.set('phase','source');db.event('plan_created',plan_id=plan['plan_id'],payload_reads=0)
                db.verify_selection(plan)
            finally:
                db.close()
            os.rename(temporary,child(output,'recovery-run.sqlite3'));temporary=None
            sync_dir(output)
            atomic_text(child(output,'plan.json'),json.dumps(plan,indent=2)+'\n');sync_dir(output)
            return {**public_plan(plan),'free_bytes_snapshot':shutil.disk_usage(output).free,
                    'capacity_sufficient_at_snapshot':shutil.disk_usage(output).free>=plan['required_free_bytes']}
    finally:
        source.close()
        if temporary and temporary.exists():
            temporary.unlink()


def public_plan(plan):
    fields=('plan_id','mode','source_kind','files','source_bytes','largest_member_bytes','required_free_bytes',
            'output_root','integrity_mode','sidecar_mode','writer_formats','tool_versions','account_id','batch_id',
            'metadata_budget_bytes','measured_ledger_baseline_bytes','reserve_bytes')
    return {k:plan[k] for k in fields}


def _root(output):
    root=no_symlinks(Path(output).expanduser()).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Existing recovery root required')
    return root


def _plan(db,root,expected=None):
    plan=db.get('plan')
    if not plan or plan['version']!=VERSION or plan['output_root']!=str(root):
        raise ValueError('Recovery plan/root mismatch')
    if plan['plan_id']!=token('full-recovery-plan',{k:v for k,v in plan.items() if k!='plan_id'}):
        raise ValueError('Recovery plan digest mismatch')
    if expected is not None and plan['plan_id']!=expected:
        raise ValueError('Exact plan ID required')
    db.verify_selection(plan)
    version=db.get('review_version')
    rows=db.con.execute('SELECT table_name,ordinal,record_json FROM reviews WHERE version=? ORDER BY table_name,ordinal',(version,))
    if _hash_rows([r['table_name'],r['ordinal'],json.loads(r['record_json'])] for r in rows)!=db.get('review_hash'):
        raise ValueError('Current review snapshot digest mismatch')
    return plan


def approve_plan(output,plan_id,*,scope,reviewer,evidence):
    """Record an actual human decision; planning/running never invokes this implicitly."""
    if not all(isinstance(x,str) and x.strip() for x in (plan_id,scope,reviewer,evidence)):
        raise ValueError('Exact scope, reviewer and human-approval evidence required')
    root=_root(output)
    with run_lock(root),open_ledger(root) as db:
        plan=_plan(db,root,plan_id)
        if scope!=plan['mode']:
            raise ValueError('Pilot and full execution approvals are separate')
        with db.con:
            db.con.execute('INSERT INTO approvals(plan_id,scope,reviewer,evidence) VALUES(?,?,?,?)',
                           (plan_id,scope,reviewer,evidence))
            db.event('human_approval_recorded',plan_id=plan_id,scope=scope)
        return {'plan_id':plan_id,'approval_scope':scope,'status':'approval_recorded'}


def status(output,plan_id=None):
    root=_root(output)
    with open_ledger(root,readonly=True) as db:
        plan=_plan(db,root,plan_id)
        counts=dict(db.con.execute('SELECT state,COUNT(*) FROM items GROUP BY state').fetchall())
        reasons=dict(db.con.execute('SELECT reason,COUNT(*) FROM invalidations GROUP BY reason').fetchall())
        approved=bool(db.con.execute('SELECT 1 FROM approvals WHERE plan_id=? AND scope=?',(plan['plan_id'],plan['mode'])).fetchone())
        return {**public_plan(plan),'phase':db.get('phase'),'counts':counts,'approved':approved,
                'source_bytes_read_reserved':db.con.execute("SELECT value FROM counters WHERE key='source_bytes_read'").fetchone()[0],
                'invalidated_media':reasons,'completed':sum(counts.get(s,0) for s in TERMINAL),
                'failed':sum(counts.get(s,0) for s in ('source_error','metadata_error','integrity_error')),
                'remote_calls':0,'live_imports':0}


def _allocated(path):
    if not path.exists():
        return 0
    no_symlinks(path)
    if path.is_file():
        return path.stat().st_blocks*512
    total=0
    for base,dirs,files in os.walk(path,followlinks=False):
        for name in [*dirs,*files]:
            p=no_symlinks(Path(base)/name)
            if p.is_file():
                total+=p.stat().st_blocks*512
    return total


class Budget:
    """One startup scan, then account publication deltas and current transient growth."""
    def __init__(self,root,db,plan):
        self.root,self.db,self.plan=root,db,plan
        self.controls=[child(root,n) for n in ('recovery-run.sqlite3','recovery-run.sqlite3-journal',
                                             'recovery-run.sqlite3-wal','recovery-run.sqlite3-shm','plan.json')]
        self.base=_allocated(root)-sum(_allocated(p) for p in self.controls)
        self.remaining=db.con.execute('SELECT COALESCE(SUM(size_bytes),0) FROM items WHERE raw_sha256 IS NULL').fetchone()[0]
        self.watch=[]
        self.inflight_source=None

    def check(self):
        actual=self.base+sum(_allocated(p) for p in self.controls+self.watch)
        logical_ledger=self.db.con.execute('PRAGMA page_count').fetchone()[0]*self.db.con.execute('PRAGMA page_size').fetchone()[0]
        actual+=max(0,logical_ledger-_allocated(self.db.path))
        ceiling=self.plan['source_bytes']+2*self.plan['largest_member_bytes']+self.plan['metadata_budget_bytes']
        if actual>ceiling:
            raise CapacityPause('Actual allocated output exceeds the approved capacity estimate')
        written=min(self.inflight_source.stat().st_size,self.remaining) if self.inflight_source and self.inflight_source.exists() else 0
        required=self.plan['reserve_bytes']+self.remaining-written+2*self.plan['largest_member_bytes']
        # Keep metadata allowance available until a complete terminal snapshot is produced.
        required+=max(0,self.plan['metadata_budget_bytes']-max(0,actual-self.plan['source_bytes']))
        required+=max(0,logical_ledger-self.db.path.stat().st_size)
        if shutil.disk_usage(self.root).free<required:
            raise CapacityPause('Insufficient free space for remaining work and reserve')

    def changed(self,paths,before):
        self.base+=sum(_allocated(p) for p in paths)-before


def _phase_hook(hook,event,oid=None,phase=None):
    if hook:
        hook(event,oid,phase)


def _artifact(root,relative,sha,size,mtime_ns=None):
    p=child(root,*Path(relative).parts)
    if not p.is_file() or p.stat().st_size!=size or file_hash(p)!=sha:
        raise ValueError('Published artifact hash/size mismatch; preserved for inspection')
    if mtime_ns is not None and p.stat().st_mtime_ns!=mtime_ns:
        raise ValueError('Published artifact mtime mismatch; preserved for inspection')
    return p


def _finish_intent(db,root,ident,payload,budget,hook=None):
    oid=payload['occurrence_id'];phase=payload['phase']
    work=child(root,*Path(payload['workdir']).parts)
    accounted_work=_allocated(work) if work not in budget.watch else 0
    paths=[child(root,*Path(a['final']).parts) for a in payload['artifacts']]
    before=sum(_allocated(p) for p in paths)
    for a in payload['artifacts']:
        dest=child(root,*Path(a['final']).parts);candidate=child(root,*Path(a['candidate']).parts)
        dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if dest.exists():
            matches=(dest.stat().st_size==a['size'] and file_hash(dest)==a['sha256']
                     and (a.get('mtime_ns') is None or dest.stat().st_mtime_ns==a['mtime_ns']))
            if matches:
                continue
            old=a.get('replace_raw')
            if phase!='metadata' or not old:
                raise ValueError('Unexpected published file; no overwrite permitted')
            _artifact(root,a['final'],old['sha256'],old['size'],old['mtime_ns'])
        elif a.get('replace_raw'):
            raise ValueError('Owned raw output is missing; inspect before metadata retry')
        _artifact(root,a['candidate'],a['sha256'],a['size'],a.get('mtime_ns'))
        with candidate.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(candidate,dest)
        sync_dir(dest.parent);sync_dir(candidate.parent)
        _phase_hook(hook,'renamed',oid,phase)
    for a in payload['artifacts']:
        _artifact(root,a['final'],a['sha256'],a['size'],a.get('mtime_ns'))
    with db.con:
        db.update(oid,**payload['update'])
        db.con.execute("UPDATE intents SET state='committed' WHERE id=?",(ident,))
        db.event('publication_committed',oid,phase=phase)
    _phase_hook(hook,'committed',oid,phase)
    budget.changed(paths,before)
    # This exact private directory was registered durably before any candidate I/O.
    try:
        if work.exists():
            for base,dirs,files in os.walk(work,followlinks=False):
                for name in [*dirs,*files]:
                    no_symlinks(Path(base)/name)
            shutil.rmtree(work)
    except (OSError,ValueError):
        # Publication is already committed. Cleanup failure must not downgrade a
        # valid final file into a retry that expects the old raw bytes.
        db.intent(ident,'cleanup_pending')
        with db.con:
            db.event('transient_cleanup_deferred',oid,phase=phase)
    try:
        budget.base+=_allocated(work)-accounted_work
    except (OSError,ValueError) as exc:
        raise CapacityPause('Transient cleanup requires inspection; committed outputs retained') from exc
    budget.watch=[]


def _recover_intents(db,root,budget,hook=None):
    rows=list(db.con.execute("SELECT * FROM intents WHERE state IN ('started','ready','cleanup_pending') ORDER BY id"))
    for r in rows:
        payload=json.loads(r['payload_json']);work=child(root,*Path(payload['workdir']).parts)
        if r['state']=='cleanup_pending':
            previous=_allocated(work)
            if work.exists():
                for base,dirs,files in os.walk(work,followlinks=False):
                    for name in [*dirs,*files]:
                        no_symlinks(Path(base)/name)
                shutil.rmtree(work)
            budget.base-=previous
            db.intent(r['id'],'committed')
        elif r['state']=='ready':
            _finish_intent(db,root,r['id'],payload,budget,hook)
        else:
            # No ready intent means there was no permission to replace/publish final bytes.
            if r['phase']=='source' and any(child(root,*Path(p).parts).exists() for p in payload['destinations']):
                raise ValueError('Unexpected output without a ready publication intent')
            if work.exists():
                previous=_allocated(work)
                for base,dirs,files in os.walk(work,followlinks=False):
                    for name in [*dirs,*files]:
                        no_symlinks(Path(base)/name)
                shutil.rmtree(work);budget.base-=previous
            db.intent(r['id'],'abandoned')
    budget.remaining=db.con.execute('SELECT COALESCE(SUM(size_bytes),0) FROM items WHERE raw_sha256 IS NULL').fetchone()[0]


def _start_intent(db,root,oid,phase,destinations):
    workdir='transient/'+uuid.uuid4().hex
    payload={'occurrence_id':oid,'phase':phase,'workdir':workdir,'destinations':destinations}
    ident=db.add_intent(oid,phase,payload)
    work=child(root,*Path(workdir).parts)
    work.mkdir(parents=True,mode=0o700);sync_dir(work.parent)
    return ident,payload,work


def _ready_intent(db,root,ident,payload,artifacts,update,budget,hook):
    payload={**payload,'artifacts':artifacts,'update':update}
    db.intent(ident,'ready',payload)
    _phase_hook(hook,'intent_ready',payload['occurrence_id'],payload['phase'])
    _finish_intent(db,root,ident,payload,budget,hook)


def _source_item(db,root,plan,row,pool,budget,hook):
    item=json.loads(row['source_json']);oid=item['id'];match=item['match']
    suffix=PurePosixPath(item['entry']['member']).suffix.lower()
    if not suffix or len(suffix)>12 or not all(c.isascii() and (c.isalnum() or c=='.') for c in suffix):
        suffix='.bin'
    final='objects/'+oid+suffix;side_final='metadata/'+oid+'.source.json'
    destinations=[final]+([side_final] if match.get('status')=='matched' else [])
    if any(child(root,*Path(p).parts).exists() for p in destinations):
        raise ValueError('Unowned destination exists; inspect before processing')
    budget.check();db.attempt(oid,'source',plan['max_attempts'])
    reserved=item['size']+(match['sidecar']['size'] if plan['source_kind']=='zip' and match.get('status')=='matched' else 0)
    db.charge_bytes(reserved,plan['source_read_budget'])
    ident,payload,work=_start_intent(db,root,oid,'source',destinations)
    budget.watch=[work]
    attempted=0
    def charge(n):
        nonlocal attempted
        attempted+=n
        if attempted>reserved:
            raise ValueError('Source stream exceeds its reserved attempt quota')
        budget.check()
    candidate=work/('source'+suffix)
    budget.inflight_source=candidate
    if plan['source_kind']=='sample':
        digest=recovery_io.stream_file(item['sample_file'],candidate,item['size'],charge)
        if digest!=item['prior']['source_sha256']:
            raise ValueError('Staged sample no longer matches its verified original source SHA')
    else:
        digest=pool.stream(item['entry'],candidate,charge)
    if file_hash(candidate)!=digest:
        raise ValueError('Staged source hash readback mismatch')
    document={};side_info=None;artifacts=[]
    if match.get('status')=='matched':
        if plan['source_kind']=='zip':
            content,side_sha=pool.read_sidecar(match['sidecar'],on_bytes=charge)
            document=json.loads(content)
            if document!=match['cached_document']:
                raise ValueError('Live sidecar differs from immutable cached matching evidence')
            kind='original_zip_json_bytes'
        else:
            document=match['cached_document']
            content=bounded_json(document).encode()
            side_sha=hashlib.sha256(content).hexdigest();kind='canonical_sample_snapshot_not_original_json'
        side_candidate=work/'source.json'
        with side_candidate.open('xb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        side_candidate.chmod(0o600)
        side_info={'path':side_final,'sha256':side_sha,'kind':kind,
                   'recorded_original_sha256':(item.get('prior') or {}).get('sidecar_sha256')}
        artifacts.append({'final':side_final,'candidate':str(side_candidate.relative_to(root)),
                          'sha256':side_sha,'size':len(content)})
    embedded=recovery_io.read_tags(candidate,check_space=budget.check)
    result=propose(document,embedded,None,date.fromisoformat(plan['as_of']))
    mid=token('media',plan['account_id'],digest)
    result.update({'account_id':plan['account_id'],'media_id':mid,'source_sha256':digest,
                   'source_verified':True,'integrity_mode':plan['integrity_mode'],'sidecar_packaging':side_info,
                   'sidecar_sha256':side_info['sha256'] if side_info and plan['source_kind']=='zip' else None,
                   'match_status':match['status'],'mime_type':embedded.get('File:MIMEType') or 'application/octet-stream'})
    if match['status']!='matched':
        result['review_reasons'].append(match['status'])
    expected={'image':'image/','video':'video/'}.get(item['media_type'])
    expected_format={'.jpg':'JPEG','.jpeg':'JPEG','.png':'PNG'}.get(suffix)
    if (expected and not result['mime_type'].startswith(expected)) or (expected_format and embedded.get('File:FileType')!=expected_format):
        result['review_reasons'].append('detected_media_type_mismatch')
    if item['media_type']=='unknown':
        result['review_reasons'].append('unknown_media_format')
    result['review_reasons']=sorted(set(result['review_reasons']))
    output={'path':final,'sha256':digest,'file_size_bytes':candidate.stat().st_size,
            'mtime_ns':candidate.stat().st_mtime_ns,'embedding_status':'source_verified_only','sidecar':side_info}
    artifacts.append({'final':final,'candidate':str(candidate.relative_to(root)),'sha256':digest,
                      'size':candidate.stat().st_size,'mtime_ns':candidate.stat().st_mtime_ns})
    _ready_intent(db,root,ident,payload,artifacts,
                  {'state':'raw','raw_sha256':digest,'media_id':mid,'result_json':result,'output_json':output,'error':None},budget,hook)
    budget.remaining-=item['size']
    budget.inflight_source=None


def _signature(result):
    gps=result.get('observed_gps',{}).get('selected')
    return token((result.get('capture',{}).get('selected') or {}).get('utc'),
                 {k:gps.get(k) for k in ('latitude','longitude')} if gps else None,result.get('description'))


def _reconcile(db,plan):
    """SQL temporary signatures keep full-library reconciliation bounded in memory."""
    db.con.execute('CREATE TEMP TABLE IF NOT EXISTS signatures(media_id TEXT,signature TEXT,disputed INTEGER)')
    db.con.execute('DELETE FROM signatures')
    for r in db.con.execute('SELECT media_id,result_json FROM items WHERE raw_sha256 IS NOT NULL'):
        result=json.loads(r['result_json'])
        db.con.execute('INSERT INTO signatures VALUES(?,?,?)',(r['media_id'],_signature(result),
                       int('duplicate_metadata_conflict' in result.get('review_reasons',[]))))
    version=db.get('review_version')
    for r in db.con.execute("SELECT record_json FROM reviews WHERE version=? AND table_name='prior_observations' ORDER BY ordinal",(version,)):
        record=json.loads(r[0]);result=json.loads(record['result_json'])
        if record['account_id']!=plan['account_id']:
            continue
        if not (result.get('source_verified') is True and result.get('source_sha256')==record['sha256']
                and result.get('account_id')==record['account_id'] and result.get('media_id')==record['media_id']
                and record['media_id']==token('media',record['account_id'],record['sha256'])):
            if db.con.execute('SELECT 1 FROM items WHERE media_id=?',(record['media_id'],)).fetchone():
                db.con.execute('INSERT OR IGNORE INTO invalidations VALUES(?,?)',(record['media_id'],'prior_provenance_invalid'))
            continue
        db.con.execute('INSERT INTO signatures VALUES(?,?,?)',(record['media_id'],_signature(result),
                       int('duplicate_metadata_conflict' in result.get('review_reasons',[]))))
    for r in db.con.execute('SELECT media_id FROM signatures GROUP BY media_id HAVING COUNT(DISTINCT signature)>1 OR MAX(disputed)>0'):
        db.con.execute('INSERT OR IGNORE INTO invalidations VALUES(?,?)',(r[0],'duplicate_metadata_conflict'))
    # Caller owns the transaction, including publication of the review version.
    db.con.execute('''WITH RECURSIVE snap AS (
            SELECT table_name,record_json AS j FROM reviews WHERE version=?), bad(id) AS (
            SELECT json_extract(c.j,'$.id') FROM snap c WHERE c.table_name='confirmations' AND (
                json_extract(c.j,'$.id') IN (SELECT json_extract(j,'$.confirmation_id') FROM snap WHERE table_name='revocations') OR
                json_extract(c.j,'$.visit_id') IN (SELECT json_extract(j,'$.id') FROM snap WHERE table_name='visits' AND json_extract(j,'$.status')='needs_review') OR
                json_extract(c.j,'$.visit_id') IN (SELECT json_extract(j,'$.visit_id') FROM snap WHERE table_name='visit_members'
                    AND json_extract(j,'$.media_id') IN (SELECT media_id FROM invalidations)))
            UNION
            SELECT json_extract(d.j,'$.child_id') FROM snap d JOIN bad ON json_extract(d.j,'$.parent_id')=bad.id
                WHERE d.table_name='confirmation_dependencies')
            INSERT OR IGNORE INTO context_invalidations SELECT id,'revoked_disputed_or_invalid_parent' FROM bad''',(version,))
    db.event('hash_groups_reconciled',review_version=version)


def _projection(db,row):
    result=json.loads(row['result_json']);decisions=[];version=db.get('review_version')
    for r in db.con.execute("SELECT record_json FROM reviews WHERE version=? AND table_name='stage_results' AND json_extract(record_json,'$.media_id')=? ORDER BY ordinal DESC",(version,row['media_id'])):
        d=json.loads(r[0])
        if d['media_id']==row['media_id'] and d['stage']=='local_context':
            try:
                decisions.append({'id':d['id'],'payload':json.loads(d['payload_json'])})
            except (ValueError,TypeError):
                continue
    result=reviewed_result(result,row['media_type'],decisions)
    invalid=db.con.execute('SELECT reason FROM invalidations WHERE media_id=?',(row['media_id'],)).fetchone()
    if invalid:
        result['review_reasons']=sorted(set(result['review_reasons']+[invalid[0]]))
        result['derived_evidence_status']='stale_needs_review'
    result['review_snapshot_version']=version
    return result


def _retain_readback_review(db,root,row,ident,details,operator='runner'):
    """Keep verified raw bytes; do not publish or claim success for a failed write."""
    if row['state'] not in {'raw','metadata_error'}:
        raise ValueError('Readback deferral requires an unpublished metadata outcome')
    intent=db.con.execute('SELECT * FROM intents WHERE id=? AND occurrence_id=? AND phase=? AND state=?',
                          (ident,row['id'],'metadata','started')).fetchone()
    if not intent:
        raise ValueError('No owned pre-publication metadata intent')
    output=json.loads(row['output_json']);result=json.loads(row['result_json'])
    if output['sha256']!=row['raw_sha256'] or output['embedding_status']!='source_verified_only':
        raise ValueError('Readback deferral cannot replace a published metadata file')
    _artifact(root,output['path'],row['raw_sha256'],row['size_bytes'],output['mtime_ns'])
    side=output.get('sidecar')
    if side:
        p=child(root,*Path(side['path']).parts)
        _artifact(root,side['path'],side['sha256'],p.stat().st_size)
    evidence={'operator':operator,**details,'disposition':'retained_original_bytes_no_embedding'}
    bounded_json(evidence,maximum=1024**2)
    result['review_reasons']=sorted(set(result['review_reasons']+['metadata_write_readback_failed']))
    result['write_readback_review']=evidence
    output['embedding_status']='unchanged_needs_review'
    with db.con:
        db.update(row['id'],state='review',result_json=result,output_json=output,error=None)
        db.con.execute("UPDATE intents SET state='cleanup_pending' WHERE id=?",(ident,))
        db.event('metadata_readback_deferred',row['id'],**evidence)


def _metadata_item(db,root,plan,row,budget,hook):
    oid=row['id'];output=json.loads(row['output_json']);result=_projection(db,row)
    raw=_artifact(root,output['path'],row['raw_sha256'],row['size_bytes'],output['mtime_ns'])
    blocked={'gps_conflict','gps_invalid','gps_conflicting_reference','embedded_read_error','detected_media_type_mismatch',
             'duplicate_metadata_conflict','ambiguous_sidecar','missing_sidecar','prior_provenance_invalid'}
    eligible=(raw.suffix.lower() in plan['writer_formats'] and result['capture']['safe_to_embed']
              and not blocked.intersection(result['review_reasons']))
    if not eligible:
        output['embedding_status']='manifest_only_format' if raw.suffix.lower() not in plan['writer_formats'] else 'unchanged_needs_review'
        with db.con:
            db.update(oid,state='review',output_json=output,error=None)
            db.event('unchanged_copy_retained',oid,embedding_status=output['embedding_status'])
        return
    budget.check();db.attempt(oid,'metadata',plan['max_attempts'])
    ident,payload,work=_start_intent(db,root,oid,'metadata',[output['path']]);budget.watch=[work]
    candidate=work/('metadata'+raw.suffix)
    try:
        verification=recovery_io.restore_candidate(raw,candidate,result,check_space=budget.check)
    except recovery_io.MetadataReadbackMismatch as exc:
        _retain_readback_review(db,root,row,ident,
            {'reason':str(exc),'field':exc.field,'expected':raw_value(exc.expected),
             'observed':raw_value(exc.observed),'evidence_kind':'candidate_expected_tag_readback'})
        try:
            budget.base+=_allocated(work)
        except (OSError,ValueError) as accounting_error:
            raise CapacityPause('Readback review saved; transient inspection requires attention') from accounting_error
        finally:
            budget.watch=[]
        return
    output={**output,'sha256':verification['sha256'],'file_size_bytes':candidate.stat().st_size,
            'mtime_ns':candidate.stat().st_mtime_ns,'embedding_status':'metadata_write_readback_passed',
            'verification':{**verification,'path':str(child(root,*Path(output['path']).parts))}}
    artifact={'final':output['path'],'candidate':str(candidate.relative_to(root)),'sha256':output['sha256'],
              'size':output['file_size_bytes'],'mtime_ns':output['mtime_ns'],
              'replace_raw':{'sha256':row['raw_sha256'],'size':row['size_bytes'],
                             'mtime_ns':json.loads(row['output_json'])['mtime_ns']}}
    _ready_intent(db,root,ident,payload,[artifact],{'state':'complete','output_json':output,'error':None},budget,hook)


def _validate_outputs(db,root):
    for r in db.con.execute("SELECT * FROM items WHERE raw_sha256 IS NOT NULL"):
        output=json.loads(r['output_json'])
        try:
            _artifact(root,output['path'],output['sha256'],output['file_size_bytes'],output['mtime_ns'])
            side=output.get('sidecar')
            if side:
                p=child(root,*Path(side['path']).parts)
                _artifact(root,side['path'],side['sha256'],p.stat().st_size)
        except (ValueError,OSError) as exc:
            with db.con:
                db.update(r['id'],state='integrity_error',error=str(exc))
                db.event('output_integrity_failure',r['id'])
            raise ValueError('Completed/raw output changed; preserved and blocked for inspection') from exc


def run_recovery(output,plan_id,*,scope,max_items=None,progress=None,hook=None):
    """Execute only the exact approved pilot/full plan; never records its own approval."""
    if max_items is not None and (type(max_items) is not int or max_items<1):
        raise ValueError('Invocation limit must be a positive integer')
    root=_root(output);start=time.monotonic();processed=0;paused=None
    with run_lock(root),open_ledger(root) as db:
        plan=_plan(db,root,plan_id)
        if scope!=plan['mode'] or not db.con.execute('SELECT 1 FROM approvals WHERE plan_id=? AND scope=?',(plan_id,scope)).fetchone():
            raise ValueError('Exact plan lacks human approval for this execution scope')
        if plan['tool_versions']!={'exiftool':tool_version()}:
            raise ValueError('Tool version changed; create and approve a new plan')
        if plan['source_kind']=='zip':
            for a in plan['archives']:
                if fingerprint(a['path'])!=a['fingerprint']:
                    raise ValueError('Planned archive changed; no processing started')
        budget=Budget(root,db,plan)
        try:
            _recover_intents(db,root,budget,hook)
            _validate_outputs(db,root)
            if db.con.execute("SELECT 1 FROM items WHERE state='integrity_error'").fetchone():
                raise ValueError('Output integrity issue requires inspection')
            with recovery_io.BoundedZipPool(plan['archives']) as pool:
                source_done=db.con.execute('SELECT COUNT(*) FROM items WHERE raw_sha256 IS NOT NULL').fetchone()[0]
                for row in db.con.execute("SELECT * FROM items WHERE raw_sha256 IS NULL ORDER BY ordinal"):
                    if max_items is not None and processed>=max_items:
                        paused='invocation_limit';break
                    try:
                        _source_item(db,root,plan,dict(row),pool,budget,hook)
                    except CapacityPause:
                        raise
                    except OSError as exc:
                        if exc.errno==errno.ENOSPC:
                            raise CapacityPause('Disk filled during source write; progress retained') from exc
                        with db.con:
                            db.update(row['id'],state='source_error',error=str(exc)[:8192])
                            db.event('source_failure',row['id'],error=str(exc)[:8192])
                        paused='source_error';break
                    except Exception as exc:
                        with db.con:
                            db.update(row['id'],state='source_error',error=str(exc)[:8192])
                            db.event('source_failure',row['id'],error=str(exc)[:8192])
                        # Retain valid published artifacts and stop at a retryable failure.
                        paused='source_error';break
                    processed+=1
                    source_done+=1
                    if progress:
                        progress({'stage':'source','stage_completed':source_done,'processed_this_invocation':processed,'total':plan['files']})
            remaining=db.con.execute('SELECT COUNT(*) FROM items WHERE raw_sha256 IS NULL').fetchone()[0]
            unfinished=db.con.execute("SELECT 1 FROM items WHERE state NOT IN ('complete','review')").fetchone()
            if not remaining and paused is None and unfinished:
                with db.con:
                    _reconcile(db,plan)
                    db.set('phase','metadata')
                metadata_done=db.con.execute("SELECT COUNT(*) FROM items WHERE state IN ('complete','review')").fetchone()[0]
                for row in db.con.execute("SELECT * FROM items WHERE state IN ('raw','metadata_error') ORDER BY ordinal"):
                    if max_items is not None and processed>=max_items:
                        paused='invocation_limit';break
                    try:
                        _metadata_item(db,root,plan,dict(row),budget,hook)
                    except CapacityPause:
                        raise
                    except OSError as exc:
                        if exc.errno==errno.ENOSPC:
                            raise CapacityPause('Disk filled during metadata write; raw output retained') from exc
                        with db.con:
                            db.update(row['id'],state='metadata_error',error=str(exc)[:8192])
                            db.event('metadata_failure',row['id'],error=str(exc)[:8192])
                        paused='metadata_error';break
                    except Exception as exc:
                        with db.con:
                            db.update(row['id'],state='metadata_error',error=str(exc)[:8192])
                            db.event('metadata_failure',row['id'],error=str(exc)[:8192])
                        paused='metadata_error';break
                    processed+=1
                    metadata_done+=1
                    if progress:
                        progress({'stage':'metadata','stage_completed':metadata_done,'processed_this_invocation':processed,'total':plan['files']})
        except CapacityPause as exc:
            paused=str(exc)
        except KeyboardInterrupt:
            paused='interrupted'
        with db.con:
            if not db.con.execute("SELECT 1 FROM items WHERE state NOT IN ('complete','review')").fetchone():
                db.set('phase','complete')
            db.event('invocation_finished',processed=processed,paused=paused,elapsed_seconds=round(time.monotonic()-start,3))
    result=status(root,plan_id)
    result.update({'paused_reason':paused,'elapsed_seconds':round(time.monotonic()-start,3)})
    try:
        export_reports(root,plan_id)
        result['report_status']='published'
    except (CapacityPause,OSError) as exc:
        if isinstance(exc,OSError) and exc.errno!=errno.ENOSPC:
            raise
        result['report_status']='deferred_low_space; ledger and status remain available'
    return result


def refresh_reviews(source_root,output,plan_id):
    """Append a complete review projection; never expands processing or rewrites media."""
    root=_root(output)
    with run_lock(root),open_ledger(root) as db:
        plan=_plan(db,root,plan_id)
        source_root=no_symlinks(Path(source_root).expanduser()).resolve(strict=True)
        if str(source_root)!=plan['source_root']:
            raise ValueError('Review refresh must use the same source manifest')
        source=ReadOnlyPreview(child(source_root,'recovery.sqlite3'))
        try:
            b=source.con.execute('SELECT * FROM batches WHERE id=?',(plan['batch_id'],)).fetchone()
            if not b or (b['account_id'],b['inventory_hash'])!=(plan['account_id'],plan['inventory_hash']):
                raise ValueError('Review source identity differs from approved batch')
            if source.con.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Incomplete source review/dependency graph')
            digest=_hash_rows([table,i,record] for table,i,record in _review_rows(source))
            if digest==db.get('review_hash'):
                return {'plan_id':plan_id,'review_snapshot_version':db.get('review_version'),
                        'review_snapshot_sha256':digest,'processing_scope_unchanged':True,
                        'media_rewritten':0,'unchanged':True}
            version=db.get('review_version')+1;budget=Budget(root,db,plan)
            budget.check()
            with db.con:
                copied=_copy_reviews(source,db,version,check_space=budget.check)
                if copied!=digest:
                    raise ValueError('Review snapshot identity changed during refresh')
                db.set('review_version',version);db.set('review_hash',digest)
                db.event('review_snapshot_refreshed',version=version,sha256=digest,scope_unchanged=True)
                _reconcile(db,plan)
                budget.check()
            return {'plan_id':plan_id,'review_snapshot_version':version,'review_snapshot_sha256':digest,
                    'processing_scope_unchanged':True,'media_rewritten':0,'unchanged':False}
        finally:
            source.close()


def _envelope(plan,row,result,out,root):
    if row['media_type'] not in {'image','video'}:
        return None,'unknown_media_format'
    if not result.get('mime_type','').startswith('image/' if row['media_type']=='image' else 'video/'):
        return None,'detected_media_type_mismatch'
    path=child(root,*Path(out['path']).parts)
    if not path.is_file() or path.stat().st_size!=out['file_size_bytes'] or path.stat().st_mtime_ns!=out['mtime_ns']:
        raise ValueError('Exported final path/size/mtime differs from published ledger')
    source=json.loads(row['source_json'])
    envelope={'schema':'sacc.takeout.media.v1','media_id':row['media_id'],'occurrence_id':row['id'],
              'media_asset':{'shoe_id':None,'media_type':row['media_type'],'file_path':str(path),
                  'source_path':source['entry']['archive']+'#'+source['entry']['member'],
                  'file_size_bytes':path.stat().st_size,'mime_type':result['mime_type'],
                  'storage_backend':'local','storage_key':row['media_id'],'confidence':0.0,
                  'needs_review':True,'review_reason':'takeout_pending_review_and_shoe_link'},
              'recovery':result,'live_import_eligible':False,
              'stage_extensions':{'video_filter':None,'classification':None,'local_context':None}}
    validate_envelope(envelope)
    return envelope,None


def export_reports(output,plan_id):
    """Stream deterministic committed snapshots; a pointer is published last."""
    root=_root(output)
    with run_lock(root),open_ledger(root,readonly=True) as db:
        plan=_plan(db,root,plan_id)
        watermark=db.con.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE event NOT IN ('invocation_finished','human_approval_recorded')").fetchone()[0]
        version=db.get('review_version')
        relative=f'reports/snapshot-{watermark}-v{version}'
        final=child(root,*Path(relative).parts)
        if final.exists():
            manifest=json.loads(child(final,'summary.json').read_text())
            for name,sha in manifest['artifact_sha256'].items():
                if file_hash(child(final,name))!=sha:
                    raise ValueError('Existing report snapshot changed; preserved for inspection')
            atomic_text(child(root,'report.json'),json.dumps(manifest,indent=2)+'\n');sync_dir(root)
            return manifest
        temporary=child(root,'reports','.export-'+uuid.uuid4().hex)
        temporary.mkdir(parents=True,mode=0o700)
        budget=Budget(root,db,plan)
        # The freshly created empty export directory contributes no file blocks yet.
        budget.watch=[temporary]
        counts=Counter();embeds=Counter();reasons=Counter();unsupported=Counter();envelopes=0;gps=expected_gps=selected_expected=0
        streams={}
        try:
            for name in ('recovery.jsonl','review.csv','sacc_payloads.jsonl','unsupported.jsonl'):
                p=child(temporary,name)
                streams[name]=p.open('x',encoding='utf-8',newline='')
                p.chmod(0o600)
            fields=['occurrence_id','original_path','state','capture_utc','latitude','longitude',
                    'source_integrity','embedding_status','final_path','review_reasons','error']
            writer=csv.DictWriter(streams['review.csv'],fieldnames=fields);writer.writeheader()
            for r in db.con.execute('SELECT * FROM items ORDER BY ordinal'):
                counts[r['state']]+=1;source=json.loads(r['source_json'])
                result=_projection(db,r) if r['result_json'] else None
                out=json.loads(r['output_json']) if r['output_json'] else None
                if result:
                    result={**result,'occurrence_id':r['id'],'batch_id':plan['batch_id'],
                            'source':source['entry'],'state':r['state'],'output':out,
                            'review_snapshot_sha256':db.get('review_hash')}
                    reasons.update(result['review_reasons'])
                    gps+=bool(result['observed_gps']['selected'])
                    required=result['gps_requirement']['status']!='not_expected_screenshot'
                    expected_gps+=required;selected_expected+=required and bool(result['observed_gps']['selected'])
                record={'occurrence_id':r['id'],'state':r['state'],'error':r['error'],
                        'original_path':source['entry']['member'],'recovery':result}
                streams['recovery.jsonl'].write(bounded_json(record)+'\n')
                if out:
                    embeds[out['embedding_status']]+=1
                captured=(result['capture'].get('selected') or {}) if result else {}
                geo=(result['observed_gps'].get('selected') or {}) if result else {}
                values=dict(occurrence_id=r['id'],original_path=source['entry']['member'],state=r['state'],
                    capture_utc=captured.get('utc'),latitude=geo.get('latitude'),longitude=geo.get('longitude'),
                    source_integrity=plan['integrity_mode'] if r['raw_sha256'] else 'not_processed',
                    embedding_status=out['embedding_status'] if out else None,
                    final_path=str(child(root,*Path(out['path']).parts)) if out else None,
                    review_reasons='; '.join(result['review_reasons']) if result else '',error=r['error'])
                writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in values.items()})
                if r['state'] in TERMINAL and out:
                    envelope,why=_envelope(plan,r,result,out,root)
                    if envelope:
                        streams['sacc_payloads.jsonl'].write(bounded_json(envelope)+'\n');envelopes+=1
                    else:
                        unsupported[why]+=1
                        streams['unsupported.jsonl'].write(bounded_json({'occurrence_id':r['id'],'reason':why,
                            'final_path':str(child(root,*Path(out['path']).parts))})+'\n')
                budget.check()
            for stream in streams.values():
                stream.flush();os.fsync(stream.fileno());stream.close()
            streams={}
            hashes={name:file_hash(child(temporary,name)) for name in ('recovery.jsonl','review.csv','sacc_payloads.jsonl','unsupported.jsonl')}
            report={**public_plan(plan),'snapshot':relative,'watermark':watermark,'review_snapshot_version':version,
                    'review_snapshot_sha256':db.get('review_hash'),'phase':db.get('phase'),'counts':dict(counts),
                    'embedding_outcomes':dict(embeds),'metadata_write_readback_passed':embeds['metadata_write_readback_passed'],
                    'envelopes':envelopes,'unsupported':dict(unsupported),'review_reasons':dict(reasons),
                    'gps_selected':gps,'gps_expected_coverage':{'selected':selected_expected,'denominator':expected_gps},
                    'readback_failures_retained_for_review':reasons['metadata_write_readback_failed'],
                    'source_bytes_read_reserved':db.con.execute("SELECT value FROM counters WHERE key='source_bytes_read'").fetchone()[0],
                    'invalidated_confirmations':db.con.execute('SELECT COUNT(*) FROM context_invalidations').fetchone()[0],
                    'artifact_sha256':hashes,'remote_calls':0,'live_imports':0,'store_assignments_created':0,
                    'real_branch_accuracy':None,'whole_archive_byte_hashes_verified':False}
            atomic_text(child(temporary,'summary.json'),json.dumps(report,indent=2)+'\n')
            sync_dir(temporary);budget.check()
            os.rename(temporary,final);sync_dir(final.parent)
            atomic_text(child(root,'report.json'),json.dumps(report,indent=2)+'\n')
            atomic_text(child(root,'report.md'),'# Local recovery status\n\n'+
                f"Scope: {plan['mode']}, {plan['files']} planned files. Phase: {report['phase']}.\n\n"+
                f"Metadata write/readback passed: {report['metadata_write_readback_passed']}. "
                f"Unchanged/unsupported outcomes: {dict(embeds)}.\n\n"+
                'Source integrity, metadata readback and actual store correctness are separate checks. '
                'No cloud analysis or live SACC import.\n')
            sync_dir(root)
            return report
        except BaseException:
            for stream in streams.values():
                stream.close()
            # Keep only this exporter-owned partial snapshot for audit/retry budget accounting.
            raise
