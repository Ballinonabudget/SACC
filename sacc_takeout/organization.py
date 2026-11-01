"""Immutable organization previews and independent, reversible working outputs.

clonefile(2) is used directly on macOS: unsupported cloning never falls back to
copying. Only an explicit copy strategy allocates full new data. Source recovery
objects, their ledgers and the caller's catalogue are never modified here.
"""
from contextlib import contextmanager
import ctypes
from datetime import date
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
import uuid

from .common import atomic_text, canonical, child, file_hash, no_symlinks, private_root, run_lock, token
from .recovery_io import stream_file
from .recovery_store import sync_dir

POLICY = 'date-store-subject-v1'
RESERVE_BYTES = 1024**3
SCHEMA = '''
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE entries(id TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,
 row_json TEXT NOT NULL,target_key TEXT UNIQUE,held_reason TEXT,
 state TEXT NOT NULL,error TEXT,intent_json TEXT,publication_json TEXT,
 attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX entries_state ON entries(state);
CREATE TABLE directories(key TEXT PRIMARY KEY,path TEXT NOT NULL);
CREATE TABLE branch_codes(code TEXT PRIMARY KEY,store_id TEXT NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY,event TEXT NOT NULL,
 occurrence_id TEXT,details_json TEXT NOT NULL);
CREATE TRIGGER sealed_entry_update BEFORE UPDATE OF id,ordinal,row_json,target_key,held_reason ON entries
 BEGIN SELECT RAISE(ABORT,'Immutable organization selection'); END;
CREATE TRIGGER sealed_entry_insert BEFORE INSERT ON entries WHEN EXISTS(SELECT 1 FROM meta WHERE key='plan')
 BEGIN SELECT RAISE(ABORT,'Sealed organization plan'); END;
CREATE TRIGGER sealed_entry_delete BEFORE DELETE ON entries WHEN EXISTS(SELECT 1 FROM meta WHERE key='plan')
 BEGIN SELECT RAISE(ABORT,'Sealed organization plan'); END;
'''


def _normal(value):
    return unicodedata.normalize('NFC', value).casefold()


def _text(value, name, limit=4096):
    if not isinstance(value, str) or not value or len(value.encode()) > limit or any(ord(c)<32 for c in value):
        raise ValueError('Invalid '+name)
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value<minimum:
        raise ValueError('Invalid '+name)
    return value


def _json(value):
    content=canonical(value)
    if len(content.encode())>128*1024:
        raise ValueError('Organization record exceeds bounded size')
    return content


def _slug(value, maximum):
    value=unicodedata.normalize('NFC',_text(value,'name component'))
    result=re.sub(r'[^\w-]+','-',value,flags=re.UNICODE).replace('_','-').strip('-')
    if not result:
        raise ValueError('Empty sanitized name component')
    if len(result.encode())>maximum:
        suffix='-'+hashlib.sha256(result.encode()).hexdigest()[:8]
        result=result.encode()[:maximum-len(suffix)].decode('utf-8','ignore').rstrip('-')+suffix
    return result


def _separate(a,b):
    if a==b or a.is_relative_to(b) or b.is_relative_to(a):
        raise ValueError('Organization, recovery and plan roots must be separate')


def _root(path, *, create=False):
    p=no_symlinks(Path(path).expanduser().absolute()).resolve()
    home=Path.home()
    if p in {home,home/'Documents',home/'Desktop',home/'Downloads',*home.parents}:
        raise ValueError('A dedicated private directory is required')
    if create:
        return private_root(p)
    if not p.is_dir():
        raise ValueError('Existing private plan directory required')
    return p


def _version(path):
    info=no_symlinks(path).stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Regular files are required')
    return info


def _same_version(a,b):
    return (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)


def _source(row, *, hash_content=False):
    root=no_symlinks(Path(row['source_root']).absolute()).resolve(strict=True)
    source=no_symlinks(Path(row['source_path']).absolute())
    if not source.is_relative_to(root/'objects'):
        raise ValueError('Source must be a recovered object below source_root/objects')
    before=_version(source)
    if (before.st_size,before.st_mtime_ns)!=(row['file_size_bytes'],row['mtime_ns']):
        raise ValueError('Recovered source size/mtime changed')
    if hash_content and (file_hash(source)!=row['sha256'] or not _same_version(before,_version(source))):
        raise ValueError('Recovered source final-file hash/identity changed')
    return source,before


def _validated_row(value):
    row={k:_text(value[k],k,256) for k in ('id','media_id','account_id')}
    for key in ('source_root','source_path'):
        p=Path(_text(value[key],key)).expanduser()
        if not p.is_absolute():
            raise ValueError('Source paths must be absolute')
        row[key]=str(no_symlinks(p).absolute())
    sha=_text(value['sha256'],'final published hash',64)
    if not re.fullmatch('[0-9a-fA-F]{64}',sha):
        raise ValueError('Final published SHA-256 required')
    row['sha256']=sha.lower()
    row['file_size_bytes']=_integer(value['file_size_bytes'],'source bytes')
    if type(value['mtime_ns']) is not int:
        raise ValueError('Invalid source mtime')
    row['mtime_ns']=value['mtime_ns']
    row['media_type']=value['media_type']
    if row['media_type'] not in {'image','video','unknown'}:
        raise ValueError('Unknown media type')
    row['mime_type']=_text(value['mime_type'],'MIME type',256)
    if type(value.get('date_trusted')) is not bool:
        raise ValueError('Date trust must be explicit')
    row['date_trusted']=value['date_trusted'];row['capture_date']=value.get('capture_date')
    if row['capture_date'] is not None:
        _text(row['capture_date'],'capture date',10)
        if date.fromisoformat(row['capture_date']).isoformat()!=row['capture_date']:
            raise ValueError('Capture date must be canonical ISO date')
    if row['date_trusted'] and row['capture_date'] is None:
        raise ValueError('Trusted date is missing')
    row['review_revision']=_integer(value['review_revision'],'review revision')
    store=value.get('store')
    row['store']={k:_text(store[k],'store '+k,1024) for k in ('id','code','label')} if isinstance(store,dict) else None
    if store is not None and not isinstance(store,dict):
        raise ValueError('Confirmed store must be an object')
    subject=value.get('subject')
    if subject not in {None,'Photo','Store-Broll','Subject-Unknown'}:
        raise ValueError('Shoe names are not enabled in this naming policy')
    if subject=='Store-Broll' and (row['media_type']!='video' or row['store'] is None):
        raise ValueError('Store B-roll requires confirmed video store context')
    row['subject']=subject or ('Photo' if row['media_type']=='image' else 'Store-Broll' if row['store'] else 'Subject-Unknown')
    for key in ('previous_path','previous_plan'):
        row[key]=value.get(key)
        if row[key] is not None:_text(row[key],key)
    _source(row)
    return row


def _set(con,key,value):
    con.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,_json(value)))


def _get(con,key,default=None):
    result=con.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(result[0]) if result else default


def _event(con,event,oid=None,**details):
    con.execute('INSERT INTO events(event,occurrence_id,details_json) VALUES(?,?,?)',(event,oid,_json(details)))


def _connection(path, *, create=False, readonly=False):
    path=no_symlinks(path)
    if not create and not path.is_file():
        raise ValueError('Organization journal is missing')
    con=sqlite3.connect(path.as_uri()+('?mode=rwc' if create else '?mode=ro' if readonly else '?mode=rw'),uri=True)
    con.row_factory=sqlite3.Row
    try:
        if create:
            con.executescript('BEGIN IMMEDIATE;'+SCHEMA+'COMMIT;')
            path.chmod(0o600)
        if readonly:con.execute('PRAGMA query_only=ON')
        else:con.execute('PRAGMA synchronous=FULL')
        if {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}!={'meta','entries','directories','branch_codes','events'}:
            raise ValueError('Unexpected organization journal schema')
        return con
    except BaseException:
        con.close();raise


def _selection_digest(con):
    digest=hashlib.sha256()
    for row in con.execute('SELECT id,row_json FROM entries ORDER BY ordinal'):
        value=json.loads(row['row_json'])
        if value['id']!=row['id']:
            raise ValueError('Organization occurrence identity changed')
        digest.update((_json(value)+'\n').encode())
    return digest.hexdigest()


def _path_limits(path,root):
    if len(os.fsencode(str(path)))>=min(1024,os.pathconf(root,'PC_PATH_MAX')):
        raise ValueError('Organization path exceeds filesystem byte limit')
    maximum=min(255,os.pathconf(root,'PC_NAME_MAX'))
    if any(len(os.fsencode(part))>maximum for part in path.relative_to(root).parts):
        raise ValueError('Organization component exceeds filesystem byte limit')


def _target(con,row,root):
    kind=row['media_type']
    if kind=='unknown':return None,'unknown_media_type'
    if not row['mime_type'].startswith('image/' if kind=='image' else 'video/'):
        return None,'mime_type_mismatch'
    extension=Path(row['source_path']).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,10}',extension):return None,'unsupported_extension'
    when=row['capture_date'] if row['date_trusted'] else None
    code=_slug(row['store']['code'],32).upper() if row['store'] else 'Store-Unknown'
    branch=code+'_'+_slug(row['store']['label'],80) if row['store'] else code
    if row['store']:
        old=con.execute('SELECT store_id FROM branch_codes WHERE code=?',(_normal(code),)).fetchone()
        if old and old[0]!=row['store']['id']:
            raise ValueError('Store code collides between distinct branches')
        con.execute('INSERT OR IGNORE INTO branch_codes VALUES(?,?)',(_normal(code),row['store']['id']))
    components=['Photos' if kind=='image' else 'Videos',when[:4] if when else 'undated',branch]
    if when:components.append(when[5:7])
    parent=Path()
    for component in components:
        proposed=parent/component;normal=_normal(proposed.as_posix())
        old=con.execute('SELECT path FROM directories WHERE key=?',(normal,)).fetchone()
        if old:parent=Path(old[0])
        else:
            parent=proposed;con.execute('INSERT INTO directories VALUES(?,?)',(normal,parent.as_posix()))
    suffix=row['id'].lower() if re.fullmatch('[0-9a-fA-F]{32,128}',row['id']) else hashlib.sha256(row['id'].encode()).hexdigest()
    for length in range(12,len(suffix)+1):
        name=f"{when or 'Undated'}_{code}_{row['subject']}_{suffix[:length]}{extension}"
        path=child(root,*parent.parts,name);_path_limits(path,root)
        key=_normal(str(path))
        if not con.execute('SELECT 1 FROM entries WHERE target_key=?',(key,)).fetchone():
            return str(path),None
    raise ValueError('Unable to allocate a unique organization filename')


def create_plan(rows,target_root,plans_root,*,binding=None,strategy='clone'):
    if strategy not in {'clone','copy'}:raise ValueError('Explicit clone or copy strategy required')
    target=_root(target_root,create=True);plans=_root(plans_root,create=True);_separate(target,plans)
    _json(binding)
    with run_lock(plans):
        temporary=Path(tempfile.mkdtemp(prefix='.planning-',dir=plans));con=None
        try:
            con=_connection(temporary/'journal.sqlite3',create=True)
            count=files=held=total=largest=0;source_root=None
            with con:
                for value in rows:
                    row=_validated_row(value);source=Path(row['source_root']).resolve()
                    _separate(source,target);_separate(source,plans)
                    if source_root is not None and source_root!=str(source):
                        raise ValueError('One registered recovered source root is required per plan')
                    source_root=str(source)
                    target_path,reason=_target(con,row,target)
                    row.update(target=target_path,held_reason=reason)
                    content=_json(row)
                    con.execute('INSERT INTO entries(id,ordinal,row_json,target_key,held_reason,state) VALUES(?,?,?,?,?,?)',
                                (row['id'],count,content,_normal(target_path) if target_path else None,reason,'held' if reason else 'planned'))
                    count+=1;held+=bool(reason)
                    if not reason:
                        files+=1;total+=row['file_size_bytes'];largest=max(largest,row['file_size_bytes'])
                if not count:raise ValueError('Organization selection is empty')
                header={'schema':'sacc.organization-plan.v1','policy':POLICY,'strategy':strategy,
                        'target_root':str(target),'plans_root':str(plans),'source_root':source_root,
                        'binding':binding,'total':count,'files':files,'held':held,'bytes':total,
                        'largest_file_bytes':largest,'selection_sha256':_selection_digest(con),
                        'reserve_bytes':RESERVE_BYTES,'metadata_allowance_bytes':max(1024**2,count*65536)}
                header['plan_id']=token('organization-plan',header)
                _set(con,'plan',header);_event(con,'plan_created',files=files,held=held)
            atomic_text(temporary/'plan.json',json.dumps(header,indent=2)+'\n');sync_dir(temporary)
            con.close();con=None
            final=child(plans,header['plan_id'])
            if final.exists():
                shutil.rmtree(temporary)
                return inspect_plan(final)
            os.rename(temporary,final);sync_dir(plans)
            return inspect_plan(final)
        except sqlite3.IntegrityError as exc:
            raise ValueError('Duplicate organization occurrence or target identity') from exc
        finally:
            if con:con.close()
            if temporary.exists():shutil.rmtree(temporary)


@contextmanager
def _opened(plan_dir, *, readonly=False):
    root=_root(plan_dir);con=_connection(root/'journal.sqlite3',readonly=readonly)
    try:
        header=_get(con,'plan')
        if not header or header.get('schema')!='sacc.organization-plan.v1' or header.get('policy')!=POLICY:
            raise ValueError('Unsupported organization plan')
        ident=token('organization-plan',{k:v for k,v in header.items() if k!='plan_id'})
        if ident!=header['plan_id'] or root!=Path(header['plans_root'])/ident:
            raise ValueError('Organization plan digest/root mismatch')
        if json.loads((root/'plan.json').read_text())!=header or _selection_digest(con)!=header['selection_sha256']:
            raise ValueError('Immutable organization plan changed')
        yield root,con,header
    finally:con.close()


def _summary(root,con,header):
    counts=dict(con.execute('SELECT state,COUNT(*) FROM entries GROUP BY state'))
    if counts.get('rollback_blocked'):state='rollback_blocked'
    elif _get(con,'rollback_requested',False):
        state='rolled_back' if sum(counts.get(k,0) for k in ('rolled_back','cancelled'))==header['files'] else 'rolling_back'
    elif counts.get('published',0)==header['files']:state='applied' if header['files'] else 'held'
    elif con.execute('SELECT 1 FROM entries WHERE error IS NOT NULL').fetchone():state='blocked'
    elif any(counts.get(k,0) for k in ('intent','ready','published')):state='partial'
    else:state='planned'
    sample=[]
    for entry in con.execute('SELECT row_json,state,error FROM entries ORDER BY ordinal LIMIT 12'):
        row=json.loads(entry['row_json'])
        sample.append({'id':row['id'],'source':row['source_path'],'target':row['target'],
                       'held_reason':row['held_reason'],'state':entry['state'],'error':entry['error']})
    return {k:header[k] for k in ('plan_id','files','bytes','held','total','strategy')}|{
        'state':state,'counts':counts,'sample':sample,'plan_path':str(root),
        'binding':header['binding'],'target_root':header['target_root'],
        'required_free_bytes_estimate':header['reserve_bytes']+header['metadata_allowance_bytes']+
            (header['bytes'] if header['strategy']=='copy' else 0),
        'allocation_note':'COW shared block counts are not exclusive allocation; later edits can require additional space'}


def inspect_plan(plan_dir):
    with _opened(plan_dir,readonly=True) as (root,con,header):return _summary(root,con,header)


def _clone_file(source,destination):
    """Direct clonefile(2); flags from the locally installed sys/clonefile.h."""
    libc=ctypes.CDLL(None,use_errno=True)
    try:function=libc.clonefile
    except AttributeError as exc:raise OSError(errno.ENOTSUP,'clonefile is unavailable; no copy fallback') from exc
    function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];function.restype=ctypes.c_int
    if function(os.fsencode(source),os.fsencode(destination),0x0001|0x0008):
        code=ctypes.get_errno()
        raise OSError(code,os.strerror(code),str(destination))


class _PathGuard:
    """Reject case/Unicode aliases even on case-sensitive target filesystems."""
    def __init__(self,root):self.root=root;self.cache={}

    def check(self,path,*,leaf_exists=False):
        parent=self.root
        for position,part in enumerate(path.relative_to(self.root).parts):
            if parent.exists():
                no_symlinks(parent)
                if not parent.is_dir():raise ValueError('Organization parent is not a directory')
                stamp=(parent.stat().st_mtime_ns,parent.stat().st_ctime_ns)
                cached=self.cache.get(str(parent))
                if not cached or cached[0]!=stamp:
                    if len(self.cache)>=64:self.cache.clear()
                    names={}
                    with os.scandir(parent) as entries:
                        for entry in entries:names.setdefault(_normal(entry.name),[]).append(entry.name)
                    self.cache[str(parent)]=(stamp,names)
                names=self.cache[str(parent)][1].get(_normal(part),[])
                if any(name!=part for name in names):raise ValueError('Case/Unicode target collision')
                if names and position==len(path.relative_to(self.root).parts)-1 and not leaf_exists:
                    raise FileExistsError('Unexpected organization destination exists')
            parent=parent/part
            no_symlinks(parent)

    def remember(self,path):
        parent=path.parent;cached=self.cache.get(str(parent))
        if cached:
            cached[1].setdefault(_normal(path.name),[])
            if path.name not in cached[1][_normal(path.name)]:cached[1][_normal(path.name)].append(path.name)
            self.cache[str(parent)]=((parent.stat().st_mtime_ns,parent.stat().st_ctime_ns),cached[1])


def _capacity(con,header):
    remaining=count=0
    for entry in con.execute("SELECT row_json,intent_json FROM entries WHERE state IN ('planned','intent','ready')"):
        row=json.loads(entry['row_json']);remaining+=row['file_size_bytes'];count+=1
        if header['strategy']=='copy' and entry['intent_json']:
            candidate=Path(json.loads(entry['intent_json'])['candidate'])
            if candidate.exists():remaining-=min(row['file_size_bytes'],_version(candidate).st_size)
    required=header['reserve_bytes']+max(1024**2,count*65536)
    if header['strategy']=='copy':required+=remaining
    if shutil.disk_usage(header['target_root']).free<required:
        raise OSError(errno.ENOSPC,'Insufficient free space for approved organization strategy')


def _checked_file(path,row,identity=None):
    info=_version(path)
    if (info.st_size,info.st_mtime_ns)!=(row['file_size_bytes'],row['mtime_ns']) or file_hash(path)!=row['sha256']:
        raise ValueError('Organization output hash/size/mtime changed')
    if not _same_version(info,_version(path)):
        raise ValueError('Organization output changed during validation')
    if identity and (info.st_dev,info.st_ino)!=(identity['device'],identity['inode']):
        raise ValueError('Organization path no longer identifies the owned output')
    return info


def _callback(hook,event,row):
    if hook:hook(event,dict(row))


def _work_directory(header):
    root=Path(header['target_root']);work=child(root,'.sacc-organize-'+header['plan_id'])
    marker=work/'owner.json';expected={'plan_id':header['plan_id'],'plans_root':header['plans_root']}
    if not work.exists():
        work.mkdir(mode=0o700);sync_dir(root)
        with marker.open('x') as stream:
            stream.write(_json(expected));stream.flush();os.fsync(stream.fileno())
        marker.chmod(0o600);sync_dir(work)
    if no_symlinks(marker).is_file() and json.loads(marker.read_text())==expected:return work
    raise ValueError('Organization transient directory ownership is unproven')


def _apply_item(con,header,entry,revision_check,guard,hook):
    row=json.loads(entry['row_json']);target=Path(row['target'])
    if revision_check(dict(row)) is not True:raise ValueError('Organization plan has stale review revisions')
    source,source_info=_source(row,hash_content=True)
    if entry['state']=='published':
        _checked_file(target,row,json.loads(entry['publication_json']));return
    if entry['state'] not in {'planned','intent','ready'}:
        raise ValueError('Organization item is not applicable')
    _capacity(con,header)
    if entry['state']=='planned':
        guard.check(target)
        work=_work_directory(header)
        candidate=child(work,uuid.uuid4().hex+'.candidate')
        intent={'candidate':str(candidate),'source_sha256':row['sha256'],'target':str(target)}
        with con:
            con.execute("UPDATE entries SET state='intent',intent_json=?,error=NULL,attempts=attempts+1 WHERE id=?",(_json(intent),row['id']))
            _event(con,'candidate_intent',row['id'])
        entry=dict(entry);entry.update(state='intent',intent_json=_json(intent))
        _callback(hook,'intent',row)
    intent=json.loads(entry['intent_json']);candidate=no_symlinks(Path(intent['candidate']))
    work=_work_directory(header)
    if candidate.parent!=work or intent['target']!=str(target) or intent['source_sha256']!=row['sha256']:
        raise ValueError('Candidate intent identity mismatch')
    if entry['state']=='intent':
        guard.check(target)
        if candidate.exists():
            try:_checked_file(candidate,row)
            except ValueError:
                # This is an unverified, registered transient, never a published file.
                if _version(candidate).st_ino==source_info.st_ino and _version(candidate).st_dev==source_info.st_dev:
                    raise ValueError('Candidate illegally shares source inode')
                candidate.unlink();sync_dir(work)
        if not candidate.exists():
            if header['strategy']=='clone':_clone_file(source,candidate)
            else:stream_file(source,candidate,row['file_size_bytes'],lambda _: _capacity(con,header))
            os.utime(candidate,ns=(candidate.stat().st_atime_ns,row['mtime_ns']))
            candidate.chmod(0o600)
        _source(row,hash_content=True)
        info=_checked_file(candidate,row)
        if (info.st_dev,info.st_ino)==(source_info.st_dev,source_info.st_ino):
            raise ValueError('Organization must not hardlink the recovered source')
        with candidate.open('rb') as stream:os.fsync(stream.fileno())
        intent.update(device=info.st_dev,inode=info.st_ino)
        with con:
            con.execute("UPDATE entries SET state='ready',intent_json=?,error=NULL WHERE id=?",(_json(intent),row['id']))
            _event(con,'candidate_verified',row['id'])
        _callback(hook,'intent_ready',row)
    guard.check(target,leaf_exists=target.exists())
    if target.exists():_checked_file(target,row,intent)
    else:
        _checked_file(candidate,row,intent)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        guard.check(target)
        if revision_check(dict(row)) is not True:raise ValueError('Review revision changed before publication')
        os.link(candidate,target,follow_symlinks=False)
        sync_dir(target.parent);guard.remember(target)
        _callback(hook,'published',row)
    info=_checked_file(target,row,intent)
    publication={'device':info.st_dev,'inode':info.st_ino,'sha256':row['sha256'],
                 'file_size_bytes':info.st_size,'mtime_ns':info.st_mtime_ns}
    with con:
        con.execute("UPDATE entries SET state='published',publication_json=?,error=NULL WHERE id=?",(_json(publication),row['id']))
        _event(con,'output_published',row['id'])
    _callback(hook,'committed',row)
    if candidate.exists():
        _checked_file(candidate,row,publication);candidate.unlink();sync_dir(candidate.parent)


def apply_plan(plan_dir,*,approve=False,revision_check=None,progress=None,hook=None):
    if approve is not True:raise PermissionError('Explicit approval of this exact organization plan is required')
    if not callable(revision_check):raise ValueError('A current review-revision checker is required')
    path=_root(plan_dir)
    with run_lock(path),_opened(path) as (root,con,header):
        if _get(con,'rollback_requested',False):raise ValueError('A rolled-back plan cannot be reapplied')
        guard=_PathGuard(Path(header['target_root']))
        for item in con.execute("SELECT * FROM entries WHERE held_reason IS NULL ORDER BY target_key"):
            try:_apply_item(con,header,dict(item),revision_check,guard,hook)
            except Exception as exc:
                with con:
                    con.execute('UPDATE entries SET error=? WHERE id=?',(str(exc)[:8192],item['id']))
                    _event(con,'apply_blocked',item['id'],reason=str(exc)[:8192])
                raise
            if progress:progress({'stage':'organization','id':item['id'],'total':header['files'],
                'completed':con.execute("SELECT COUNT(*) FROM entries WHERE state='published'").fetchone()[0]})
        return _summary(root,con,header)


def _output(row,entry,header):
    return {**row,'plan_id':header['plan_id'],'occurrence_id':row['id'],
            'revision':row['review_revision'],'source':row['source_path'],
            'target_path':row['target'],'state':entry['state'],'error':entry['error']}


def iter_outputs(plan_dir):
    """Journal-owned locators for caller-managed forward/rollback compare-and-swap."""
    with _opened(plan_dir,readonly=True) as (_,con,header):
        for entry in con.execute("SELECT * FROM entries WHERE publication_json IS NOT NULL AND state IN ('published','rolled_back','rollback_blocked') ORDER BY ordinal"):
            yield _output(json.loads(entry['row_json']),entry,header)


def rollback_plan(plan_dir,*,ownership_check=None,progress=None,hook=None):
    if not callable(ownership_check):raise ValueError('A current catalogue output-ownership checker is required')
    path=_root(plan_dir)
    with run_lock(path),_opened(path) as (root,con,header):
        with con:_set(con,'rollback_requested',True)
        for item in con.execute('SELECT * FROM entries WHERE held_reason IS NULL ORDER BY ordinal DESC'):
            entry=dict(item);row=json.loads(entry['row_json']);target=Path(row['target'])
            if entry['state'] in {'rolled_back','cancelled'}:continue
            try:
                publication=json.loads(entry['publication_json']) if entry['publication_json'] else None
                if publication is None:
                    if entry['state']=='ready' and target.exists():
                        publication=json.loads(entry['intent_json']);_checked_file(target,row,publication)
                        with con:con.execute('UPDATE entries SET publication_json=? WHERE id=?',(_json(publication),row['id']))
                    elif target.exists():raise ValueError('Unowned destination is preserved')
                    else:
                        with con:con.execute("UPDATE entries SET state='cancelled',error=NULL WHERE id=?",(row['id'],))
                        continue
                projected=_output(row,entry,header)
                if ownership_check(projected) is not True:raise ValueError('A newer catalogue locator owns this output')
                if target.exists():_checked_file(target,row,publication)
                elif entry['state']!='rollback_intent':raise ValueError('Published output is missing without a rollback intent')
                with con:
                    con.execute("UPDATE entries SET state='rollback_intent',error=NULL WHERE id=?",(row['id'],))
                    _event(con,'rollback_intent',row['id'])
                _callback(hook,'rollback_intent',row)
                if target.exists():
                    if ownership_check(projected) is not True:raise ValueError('Catalogue ownership changed before rollback')
                    _checked_file(target,row,publication);target.unlink();sync_dir(target.parent)
                _callback(hook,'removed',row)
                with con:
                    con.execute("UPDATE entries SET state='rolled_back',error=NULL WHERE id=?",(row['id'],))
                    _event(con,'output_rolled_back',row['id'])
                _callback(hook,'rolled_back',row)
            except Exception as exc:
                with con:
                    con.execute("UPDATE entries SET state='rollback_blocked',error=? WHERE id=?",(str(exc)[:8192],row['id']))
                    _event(con,'rollback_blocked',row['id'],reason=str(exc)[:8192])
            if progress:progress({'stage':'organization_rollback','id':row['id'],'total':header['files']})
        return _summary(root,con,header)
