"""Additive local catalogue for recovered media, independent of shoe identification."""
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .common import canonical, child, file_hash, no_symlinks, private_root, run_lock, token
from .full_recovery import _plan, _projection
from .recovery_store import open_ledger, sync_dir
from .locations import validate_directory
from .library_projection import projection, triage_record

DEFAULT_ROOT = Path.home()/'Documents/SACC_Data/library/staging'
DEFAULT_RECOVERY = Path.home()/'Documents/SACC_Data/recovery/denivic'

SCHEMA = '''
CREATE TABLE library_schema(version INTEGER PRIMARY KEY CHECK(version=1));
INSERT INTO library_schema VALUES(1);
CREATE TABLE library_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE library_imports(id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,watermark INTEGER NOT NULL,
 report_sha TEXT NOT NULL,source_root TEXT NOT NULL,summary_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE library_media(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,
 remote_eligible INTEGER NOT NULL DEFAULT 0 CHECK(remote_eligible=0),UNIQUE(account_id,source_sha256));
CREATE TABLE library_occurrences(id TEXT PRIMARY KEY,media_id TEXT NOT NULL REFERENCES library_media(id),
 import_id TEXT NOT NULL REFERENCES library_imports(id),plan_id TEXT NOT NULL,source_root TEXT NOT NULL,
 original_path TEXT NOT NULL,original_name TEXT NOT NULL,media_type TEXT NOT NULL,mime_type TEXT NOT NULL,
 recovered_path TEXT NOT NULL,final_sha256 TEXT NOT NULL,file_size_bytes INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,
 capture_utc TEXT,source_date TEXT,source_date_trusted INTEGER NOT NULL,effective_date TEXT,date_basis TEXT NOT NULL,
 date_trusted INTEGER NOT NULL,gps_lat REAL,gps_lon REAL,screenshot INTEGER NOT NULL DEFAULT 0,
 privacy TEXT NOT NULL DEFAULT 'unknown',store_version_id TEXT,review_revision INTEGER NOT NULL DEFAULT 0,
 needs_attention INTEGER NOT NULL,embedding_status TEXT NOT NULL,raw_json TEXT NOT NULL,
 overrides_json TEXT NOT NULL DEFAULT '{}',search_text TEXT NOT NULL,organized_path TEXT,organization_plan TEXT);
CREATE INDEX library_date ON library_occurrences(effective_date,id);
CREATE INDEX library_capture_time ON library_occurrences(capture_utc,id);
CREATE INDEX library_year ON library_occurrences(substr(effective_date,1,4),media_type);
CREATE INDEX library_type ON library_occurrences(media_type);
CREATE INDEX library_review ON library_occurrences(needs_attention,review_revision);
CREATE INDEX library_media_refs ON library_occurrences(media_id);
CREATE INDEX library_store ON library_occurrences(store_version_id);
CREATE TABLE library_source_history(import_id TEXT NOT NULL,id TEXT NOT NULL,raw_json TEXT NOT NULL,
 PRIMARY KEY(import_id,id));
CREATE TABLE library_review_events(id INTEGER PRIMARY KEY,occurrence_id TEXT NOT NULL REFERENCES library_occurrences(id),
 revision INTEGER NOT NULL,action TEXT NOT NULL,value_json TEXT NOT NULL,reviewer TEXT NOT NULL,
 evidence TEXT NOT NULL,details_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE library_directories(id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,reviewer TEXT NOT NULL,evidence TEXT NOT NULL);
CREATE TABLE library_stores(id TEXT PRIMARY KEY,store_id TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,
 valid_from TEXT,valid_to TEXT,aliases_json TEXT NOT NULL,payload_json TEXT NOT NULL,directory_id TEXT NOT NULL);
CREATE TABLE library_context(import_id TEXT NOT NULL,table_name TEXT NOT NULL,ordinal INTEGER NOT NULL,record_json TEXT NOT NULL,
 PRIMARY KEY(import_id,table_name,ordinal));
CREATE VIRTUAL TABLE library_fts USING fts5(search_text,content='library_occurrences',content_rowid='rowid');
CREATE TRIGGER library_fts_insert AFTER INSERT ON library_occurrences BEGIN
 INSERT INTO library_fts(rowid,search_text) VALUES(new.rowid,new.search_text); END;
CREATE TRIGGER library_fts_delete AFTER DELETE ON library_occurrences BEGIN
 INSERT INTO library_fts(library_fts,rowid,search_text) VALUES('delete',old.rowid,old.search_text); END;
CREATE TRIGGER library_fts_update AFTER UPDATE OF search_text ON library_occurrences BEGIN
 INSERT INTO library_fts(library_fts,rowid,search_text) VALUES('delete',old.rowid,old.search_text);
 INSERT INTO library_fts(rowid,search_text) VALUES(new.rowid,new.search_text); END;
CREATE TABLE IF NOT EXISTS library_shoes(id TEXT PRIMARY KEY,brand TEXT NOT NULL,line TEXT,
 model TEXT NOT NULL,colorway TEXT,sku TEXT,category TEXT,display_name TEXT NOT NULL,
 aliases_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_ls_sku ON library_shoes(sku);
CREATE INDEX IF NOT EXISTS idx_ls_line ON library_shoes(line);
CREATE INDEX IF NOT EXISTS idx_ls_model ON library_shoes(model);
CREATE INDEX IF NOT EXISTS idx_ls_brand ON library_shoes(brand);
CREATE TABLE IF NOT EXISTS library_shoe_associations(id TEXT PRIMARY KEY,
 occurrence_id TEXT NOT NULL REFERENCES library_occurrences(id),
 shoe_id TEXT NOT NULL REFERENCES library_shoes(id),tag_type TEXT NOT NULL DEFAULT 'solo',
 group_descriptor TEXT,confidence REAL NOT NULL DEFAULT 1.0,evidence TEXT,
 price_observed REAL,time_start_sec REAL,time_end_sec REAL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_lsa_occurrence ON library_shoe_associations(occurrence_id);
CREATE INDEX IF NOT EXISTS idx_lsa_shoe ON library_shoe_associations(shoe_id);
'''


class StaleReview(ValueError):
    pass


def default_db():
    return Path(os.getenv('SACC_LIBRARY_DB',str(DEFAULT_ROOT/'sacc-library.sqlite3'))).expanduser()


def _plain(value, maximum=4000):
    if not isinstance(value,str) or len(value)>maximum or '\x00' in value:
        raise ValueError('Invalid text value')
    return value.strip()


class LibraryDB:
    def __init__(self,path=None):
        self.path=no_symlinks(Path(path or default_db()).expanduser()).absolute()

    @contextmanager
    def connection(self,write=False):
        no_symlinks(self.path)
        if not self.path.is_file():
            raise ValueError('Library is not initialized')
        con=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=30)
        con.row_factory=sqlite3.Row
        try:
            con.execute('PRAGMA foreign_keys=ON')
            if [tuple(r) for r in con.execute('SELECT version FROM library_schema')]!=[(1,)]:
                raise ValueError('Unsupported library database')
            if write:
                con.execute('PRAGMA synchronous=FULL')
            else:
                con.execute('PRAGMA query_only=ON');con.execute('BEGIN')
            yield con
            if write:con.commit()
        except BaseException:
            con.rollback();raise
        finally:
            con.close()

    def initialize(self,base_db=None):
        base=no_symlinks(Path(base_db).expanduser()).resolve(strict=True) if base_db else None
        root=private_root(self.path.parent, [base] if base else [])
        with run_lock(root):
            if self.path.exists():
                with self.connection():pass
                return {'created':False,'path':str(self.path)}
            temporary=child(root,'.library-'+uuid.uuid4().hex+'.sqlite3')
            out=sqlite3.connect(temporary)
            try:
                if base:
                    original=sqlite3.connect(base.as_uri()+'?mode=ro',uri=True)
                    try:original.backup(out)
                    finally:original.close()
                existing={r[0] for r in out.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if any(n.startswith('library_') for n in existing):
                    raise ValueError('Base already contains library tables; use existing library explicitly')
                out.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')
                out.execute('INSERT INTO library_meta VALUES(?,?)',('base_db',str(base) if base else 'synthetic_empty'))
                out.commit();out.execute('PRAGMA journal_mode=WAL');out.close();out=None
                temporary.chmod(0o600);os.link(temporary,self.path);temporary.unlink();sync_dir(root)
            finally:
                if out:out.close()
                if temporary.exists():temporary.unlink()
        return {'created':True,'path':str(self.path)}

    def import_recovery(self,recovery_root,progress=None):
        root=no_symlinks(Path(recovery_root).expanduser()).resolve(strict=True)
        with open_ledger(root,readonly=True) as source:
            plan=_plan(source,root)
            if source.get('phase')!='complete':raise ValueError('Completed recovery required')
            report_path=child(root,'report.json');report=json.loads(report_path.read_text())
            watermark=source.con.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE event NOT IN ('invocation_finished','human_approval_recorded')").fetchone()[0]
            counts=dict(source.con.execute('SELECT state,COUNT(*) FROM items GROUP BY state'))
            if (report['plan_id']!=plan['plan_id'] or report['watermark']!=watermark or report['counts']!=counts
                or set(counts)-{'complete','review'} or sum(counts.values())!=plan['files']):
                raise ValueError('Recovery report/ledger snapshot mismatch')
            snapshot=child(root,*Path(report['snapshot']).parts)
            if json.loads(child(snapshot,'summary.json').read_text())!=report:raise ValueError('Report pointer differs from snapshot')
            for name,sha in report['artifact_sha256'].items():
                if file_hash(child(snapshot,name))!=sha:raise ValueError('Recovery report artifact changed')
            report_sha=file_hash(report_path);import_id=token('library-import',plan['plan_id'],watermark,report_sha)
            with self.connection(write=True) as con:
                if con.execute('SELECT 1 FROM library_imports WHERE id=?',(import_id,)).fetchone():
                    return {'imported':0,'reused':plan['files'],'import_id':import_id}
                con.execute('INSERT INTO library_imports(id,plan_id,watermark,report_sha,source_root,summary_json) VALUES(?,?,?,?,?,?)',
                            (import_id,plan['plan_id'],watermark,report_sha,str(root),canonical(report)))
                count=0
                for row in source.con.execute('SELECT * FROM items ORDER BY ordinal'):
                    src=json.loads(row['source_json']);out=json.loads(row['output_json']);result=_projection(source,row)
                    if row['media_id']!=token('media',plan['account_id'],row['raw_sha256']):raise ValueError('Media identity mismatch')
                    path=child(root,*Path(out['path']).parts)
                    if not path.is_relative_to(child(root,'objects')):raise ValueError('Recovery object outside object root')
                    st=path.stat()
                    if st.st_size!=out['file_size_bytes'] or st.st_mtime_ns!=out['mtime_ns']:raise ValueError('Recovered file stat changed')
                    selected=result['capture'].get('selected') or {};instant=selected.get('utc');day=instant[:10] if instant else None
                    trusted=bool(instant and result['capture']['safe_to_embed'])
                    gps=result.get('observed_gps',{}).get('selected') or {}
                    raw={'capture':result['capture'],'observed_gps':result['observed_gps'],
                         'review_reasons':result['review_reasons'],'description':result.get('description'),
                         'write_readback_review':result.get('write_readback_review',result.get('restoration_review')),
                         'source_entry':src['entry'],'output':out,'recovery_state':row['state'],
                         'gps_requirement':result['gps_requirement'],'source_integrity':result.get('integrity_mode'),
                         'media_subtype':result['media_subtype']}
                    previous=con.execute('SELECT * FROM library_occurrences WHERE id=?',(row['id'],)).fetchone()
                    overrides=json.loads(previous['overrides_json']) if previous else {}
                    effective=overrides.get('capture_date',day);date_trusted=bool(overrides.get('capture_date')) or trusted
                    screenshot=overrides.get('screenshot',result['media_subtype']=='screenshot')
                    projected=projection(raw,out['embedding_status'],overrides,triage_record(con,row['id']))
                    privacy=projected['privacy'];store=overrides.get('store')
                    if store and not self._store_compatible(con,store,effective,date_trusted,overrides.get('historical_evidence')):
                        store=None;overrides.pop('store',None)
                    attention=projected['needs_attention']
                    changed=bool(previous and (previous['raw_json']!=canonical(raw) or previous['overrides_json']!=canonical(overrides)))
                    revision=previous['review_revision']+int(changed) if previous else 0
                    values={'id':row['id'],'media_id':row['media_id'],'import_id':import_id,'plan_id':plan['plan_id'],
                        'source_root':str(root),'original_path':src['entry']['member'],'original_name':Path(src['entry']['member']).name,
                        'media_type':row['media_type'],'mime_type':result['mime_type'],'recovered_path':str(path),
                        'final_sha256':out['sha256'],'file_size_bytes':st.st_size,'mtime_ns':st.st_mtime_ns,
                        'capture_utc':instant,'source_date':day,'source_date_trusted':int(trusted),'effective_date':effective,
                        'date_basis':'reviewed_calendar' if overrides.get('capture_date') else 'source_utc' if instant else 'unknown',
                        'date_trusted':int(date_trusted),'gps_lat':gps.get('latitude'),'gps_lon':gps.get('longitude'),
                        'screenshot':int(screenshot),'privacy':privacy,'store_version_id':store,
                        'needs_attention':int(attention),'embedding_status':out['embedding_status'],'raw_json':canonical(raw),
                        'overrides_json':canonical(overrides),'review_revision':revision,
                        'search_text':self._search_text(src['entry']['member'],raw,overrides,con,store)}
                    con.execute('INSERT OR IGNORE INTO library_media(id,account_id,source_sha256) VALUES(?,?,?)',
                                (row['media_id'],plan['account_id'],row['raw_sha256']))
                    keys=list(values);updates=[k for k in keys if k!='id']
                    con.execute('INSERT INTO library_occurrences('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+') '
                                'ON CONFLICT(id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in updates),list(values.values()))
                    con.execute('INSERT INTO library_source_history VALUES(?,?,?)',(import_id,row['id'],canonical(raw)))
                    if changed:
                        con.execute('INSERT INTO library_review_events(occurrence_id,revision,action,value_json,reviewer,evidence,details_json) VALUES(?,?,?,?,?,?,?)',
                            (row['id'],revision,'source_refresh',canonical(import_id),'system','New audited recovery snapshot',
                             canonical({'previous_import':previous['import_id'],'previous_store':previous['store_version_id'],'source_observations_preserved':True})))
                    count+=1
                    if progress and count%500==0:progress(count,plan['files'])
                version=source.get('review_version')
                for r in source.con.execute('SELECT table_name,ordinal,record_json FROM reviews WHERE version=?',(version,)):
                    con.execute('INSERT INTO library_context VALUES(?,?,?,?)',(import_id,r['table_name'],r['ordinal'],r['record_json']))
            return {'imported':count,'reused':0,'import_id':import_id,'integrity_scope':'report hashes and file size/mtime; no new full-media SHA scan'}

    @staticmethod
    def _search_text(name,raw,overrides,con,store=None):
        values=[name,raw.get('description') or '',overrides.get('note','')]
        if store:
            s=con.execute('SELECT code,label,aliases_json FROM library_stores WHERE id=?',(store,)).fetchone()
            if s:values.extend([s['code'],s['label'],s['aliases_json']])
        return ' '.join(values)

    @staticmethod
    def _filters(filters):
        f=filters or {};where=[];args=[]
        q=_plain(f.get('q',''),128);words=re.findall(r'[^\W_]+',q,flags=re.UNICODE)
        if words:
            where.append('o.rowid IN (SELECT rowid FROM library_fts WHERE library_fts MATCH ?)')
            args.append(' AND '.join('"'+w+'"*' for w in words))
        for field,allowed,column in [('media_type',{'image','video','unknown'},'media_type'),
                                     ('privacy',{'unknown','personal','mixed','non_personal'},'privacy')]:
            value=f.get(field,'all')
            if value not in ('all','',None):
                if value not in allowed:raise ValueError('Invalid '+field)
                where.append('o.'+column+'=?');args.append(value)
        year=str(f.get('year','all'))
        if year=='undated':where.append('o.effective_date IS NULL')
        elif year not in ('all','', 'None'):
            if not re.fullmatch(r'\d{4}',year):raise ValueError('Invalid year')
            where.append('substr(o.effective_date,1,4)=?');args.append(year)
        month=str(f.get('month','all'))
        if month not in ('all','','None'):
            if not month.isdigit() or not 1<=int(month)<=12:raise ValueError('Invalid month')
            where.append('substr(o.effective_date,6,2)=?');args.append(f'{int(month):02d}')
        review=f.get('review','all')
        if review=='attention':where.append('o.needs_attention=1')
        elif review=='annotated':where.append("o.overrides_json!='{}'")
        elif review=='unreviewed':where.append("o.overrides_json='{}'")
        elif review not in ('all','',None):raise ValueError('Invalid review filter')
        gps=f.get('gps','all')
        if gps=='present':where.append('o.gps_lat IS NOT NULL')
        elif gps=='missing':where.append('o.gps_lat IS NULL AND o.screenshot=0')
        elif gps=='not_expected':where.append('o.screenshot=1')
        elif gps not in ('all','',None):raise ValueError('Invalid GPS filter')
        store=f.get('store','all')
        if store=='unknown':where.append('o.store_version_id IS NULL')
        elif store not in ('all','',None):where.append('o.store_version_id=?');args.append(_plain(store,200))
        reason=f.get('reason')
        if reason:
            where.append("EXISTS(SELECT 1 FROM json_each(o.raw_json,'$.review_reasons') WHERE value=?)")
            args.append(_plain(reason,100))
        return (' WHERE '+' AND '.join(where) if where else ''),args

    @staticmethod
    def _summary(con,row):
        r=dict(row);raw=json.loads(r['raw_json']);store=None
        overrides=json.loads(r['overrides_json'])
        projected=projection(raw,r['embedding_status'],overrides,triage_record(con,r['id']))
        if r['store_version_id']:
            s=con.execute('SELECT id,code,label FROM library_stores WHERE id=?',(r['store_version_id'],)).fetchone()
            store=dict(s) if s else None
        return {'id':r['id'],'media_id':r['media_id'],'original_name':r['original_name'],'media_type':r['media_type'],
                'mime_type':r['mime_type'],'capture_date':r['effective_date'],'capture_utc':r['capture_utc'],
                'date_basis':r['date_basis'],'date_trusted':bool(r['date_trusted']),'has_gps':r['gps_lat'] is not None,
                'gps_requirement':'not_expected_screenshot' if r['screenshot'] else 'expected','store':store,
                'privacy':r['privacy'],'privacy_source':projected['privacy_source'],
                'screenshot':bool(r['screenshot']),'review_revision':r['review_revision'],
                'review_status':'attention' if r['needs_attention'] else 'annotated' if overrides else 'unreviewed',
                'review_reasons':raw['review_reasons'],'embedding_status':r['embedding_status'],
                'asset_url':'/api/library/assets/'+r['id'],
                'preview_supported':r['mime_type'] in {'image/jpeg','image/png','image/gif','image/webp','video/mp4','video/quicktime'}}

    def items(self,filters=None,limit=30,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000:
            raise ValueError('Invalid pagination')
        where,args=self._filters(filters)
        with self.connection() as con:
            total=con.execute('SELECT COUNT(*) FROM library_occurrences o'+where,args).fetchone()[0]
            rows=con.execute('SELECT o.* FROM library_occurrences o'+where+
                             " ORDER BY COALESCE(o.effective_date,'9999-99-99'),o.id LIMIT ? OFFSET ?",[*args,limit,offset])
            return {'results':[self._summary(con,r) for r in rows],'total':total,'limit':limit,'offset':offset}

    def status(self):
        with self.connection() as con:
            counts=dict(con.execute('SELECT media_type,COUNT(*) FROM library_occurrences GROUP BY media_type'))
            totals={'occurrences':sum(counts.values()),'unique_media':con.execute('SELECT COUNT(*) FROM library_media').fetchone()[0],
                    'images':counts.get('image',0),'videos':counts.get('video',0),'unknown':counts.get('unknown',0)}
            queries={'metadata_written':"embedding_status='metadata_write_readback_passed'",'manifest_only':"embedding_status='manifest_only_format'",
                     'needs_review':'needs_attention=1','observed_gps':'gps_lat IS NOT NULL','confirmed_stores':'store_version_id IS NOT NULL',
                     'readback_exceptions':"EXISTS(SELECT 1 FROM json_each(raw_json,'$.review_reasons') WHERE value='metadata_write_readback_failed')"}
            for key,where in queries.items():totals[key]=con.execute('SELECT COUNT(*) FROM library_occurrences WHERE '+where).fetchone()[0]
            imports=[dict(r) for r in con.execute('SELECT id,plan_id,watermark,created_at FROM library_imports ORDER BY created_at DESC')]
            return {'ready':True,'mode':'isolated_copy','totals':totals,'imports':imports}

    def facets(self):
        with self.connection() as con:
            years=[{'value':r[0],'count':r[1]} for r in con.execute('SELECT substr(effective_date,1,4),COUNT(*) FROM library_occurrences WHERE effective_date IS NOT NULL GROUP BY 1 ORDER BY 1')]
            months=[{'value':str(int(r[0])),'count':r[1]} for r in con.execute('SELECT substr(effective_date,6,2),COUNT(*) FROM library_occurrences WHERE effective_date IS NOT NULL GROUP BY 1 ORDER BY 1')]
            stores=[dict(r) for r in con.execute('SELECT s.id,s.code,s.label,COUNT(o.id) AS count FROM library_stores s LEFT JOIN library_occurrences o ON o.store_version_id=s.id GROUP BY s.id ORDER BY s.label')]
            reasons=[{'value':r[0],'label':r[0].replace('_',' ').capitalize(),'count':r[1]} for r in con.execute("SELECT j.value,COUNT(*) FROM library_occurrences o,json_each(o.raw_json,'$.review_reasons') j GROUP BY j.value ORDER BY COUNT(*) DESC")]
            return {'years':years,'months':months,'stores':stores,'review_reasons':reasons}

    def detail(self,oid):
        with self.connection() as con:
            r=con.execute('SELECT * FROM library_occurrences WHERE id=?',(oid,)).fetchone()
            if not r:raise KeyError('Unknown library item')
            raw=json.loads(r['raw_json']);item=self._summary(con,r)
            item.update({k:raw.get(k) for k in ('capture','observed_gps','write_readback_review')})
            item.update({'original_path':r['original_path'],'notes':json.loads(r['overrides_json']).get('note',''),
                         'recovered_path':r['recovered_path'],'organized_path':r['organized_path'],
                         'review_events':[dict(e) for e in con.execute('SELECT revision,action,value_json,reviewer,evidence,details_json,created_at FROM library_review_events WHERE occurrence_id=? ORDER BY id DESC LIMIT 100',(oid,))]})
            related=[]
            if r['capture_utc']:
                instant=datetime.fromisoformat(r['capture_utc'].replace('Z','+00:00'))
                related=[self._summary(con,e) for e in con.execute('SELECT * FROM library_occurrences WHERE plan_id=? AND id!=? AND capture_utc BETWEEN ? AND ? ORDER BY capture_utc,id LIMIT 12',
                    (r['plan_id'],oid,(instant-timedelta(minutes=5)).isoformat(),(instant+timedelta(minutes=5)).isoformat()))]
            return {'item':item,'related':related}

    @staticmethod
    def _store_compatible(con,version,day,trusted,historical=None):
        s=con.execute('SELECT * FROM library_stores WHERE id=?',(version,)).fetchone()
        return bool(s and day and trusted and (s['valid_from'] or historical)
                    and (not s['valid_from'] or day>=s['valid_from']) and (not s['valid_to'] or day<=s['valid_to']))

    def review(self,items,action,value,reviewer,evidence,historical_evidence=''):
        reviewer=_plain(reviewer,100);evidence=_plain(evidence,4000);historical_evidence=_plain(historical_evidence,4000)
        if not reviewer or not evidence:raise ValueError('Reviewer and evidence are required')
        if not isinstance(items,list) or not 1<=len(items)<=100 or len({x['id'] for x in items})!=len(items):raise ValueError('Explicit unique selected items required')
        if action not in {'note','capture_date','screenshot','privacy','store','clear'}:raise ValueError('Invalid review action')
        if action=='capture_date':
            selected=date.fromisoformat(value)
            if selected>date.today()+timedelta(days=1):raise ValueError('Capture date cannot be in the future')
            value=selected.isoformat()
        if action=='screenshot' and type(value) is not bool:raise ValueError('Screenshot decision must be boolean')
        if action=='privacy' and value not in {'unknown','personal','mixed','non_personal'}:raise ValueError('Invalid privacy label')
        if action=='note':value=_plain(value,4000)
        if action=='store' and value is not None:value=_plain(value,200)
        if action=='clear' and value not in {'note','capture_date','screenshot','privacy','store'}:raise ValueError('Invalid override field')
        updated=[]
        with self.connection(write=True) as con:
            con.execute('BEGIN IMMEDIATE')
            for selected in items:
                row=con.execute('SELECT * FROM library_occurrences WHERE id=?',(selected['id'],)).fetchone()
                if not row:raise KeyError('Unknown library item')
                if type(selected.get('expected_revision')) is not int or row['review_revision']!=selected['expected_revision']:raise StaleReview('This item changed; reload before saving')
                raw=json.loads(row['raw_json']);over=json.loads(row['overrides_json']);details={}
                if action=='clear':over.pop(value,None)
                else:over[action]=value
                if action=='store':over['historical_evidence']=historical_evidence
                day=over.get('capture_date',row['source_date']);trusted=bool(over.get('capture_date')) or bool(row['source_date_trusted'])
                store=over.get('store')
                if store and not self._store_compatible(con,store,day,trusted,over.get('historical_evidence')):
                    if action=='store':raise ValueError('Store/date is incompatible or historical evidence is missing')
                    details['invalidated_store_version']=store;over.pop('store',None);store=None
                shot=over.get('screenshot',raw.get('media_subtype')=='screenshot')
                if shot and row['media_type']!='image':raise ValueError('Only images may be confirmed screenshots')
                revision=row['review_revision']+1
                projected=projection(raw,row['embedding_status'],over,triage_record(con,row['id']))
                con.execute('UPDATE library_occurrences SET overrides_json=?,effective_date=?,date_trusted=?,date_basis=?,screenshot=?,privacy=?,needs_attention=?,store_version_id=?,review_revision=?,search_text=? WHERE id=?',
                    (canonical(over),day,int(trusted),'reviewed_calendar' if over.get('capture_date') else 'source_utc' if row['capture_utc'] else 'unknown',int(shot),projected['privacy'],projected['needs_attention'],store,revision,self._search_text(row['original_path'],raw,over,con,store),row['id']))
                con.execute('INSERT INTO library_review_events(occurrence_id,revision,action,value_json,reviewer,evidence,details_json) VALUES(?,?,?,?,?,?,?)',
                            (row['id'],revision,action,canonical(value),reviewer,evidence,canonical(details)))
                updated.append(self._summary(con,con.execute('SELECT * FROM library_occurrences WHERE id=?',(row['id'],)).fetchone()))
        return {'updated':updated}

    def import_directory(self,payload,reviewer,evidence):
        reviewer=_plain(reviewer,100);evidence=_plain(evidence,4000)
        if not reviewer or not evidence:raise ValueError('Directory reviewer/evidence required')
        validate_directory(payload)
        with self.connection(write=True) as con:
            prior=con.execute('SELECT payload_json FROM library_directories WHERE id=?',(payload['snapshot_id'],)).fetchone()
            if prior:
                if prior[0]!=canonical(payload):raise ValueError('Directory snapshots are immutable')
                return {'stores':len(payload['stores']),'reused':True}
            con.execute('INSERT INTO library_directories VALUES(?,?,?,?)',(payload['snapshot_id'],canonical(payload),reviewer,evidence))
            for s in payload['stores']:
                code=s.get('code') or s['store_id'];code=re.sub('[^A-Za-z0-9-]','-',code)[:32].strip('-') or 'Store'
                if con.execute('SELECT 1 FROM library_stores WHERE id=?',(s['version_id'],)).fetchone():raise ValueError('Store version already belongs to another immutable snapshot')
                con.execute('INSERT INTO library_stores VALUES(?,?,?,?,?,?,?,?,?)',(s['version_id'],s['store_id'],code,
                    s['retailer']+' '+s['branch'],s.get('valid_from'),s.get('valid_to'),canonical(s.get('aliases',[])),canonical(s),payload['snapshot_id']))
        return {'stores':len(payload['stores']),'reused':False}

    def directory(self):
        with self.connection() as con:
            return {'stores':[dict(r) for r in con.execute('SELECT id,code,label,valid_from,valid_to FROM library_stores ORDER BY label')]}

    def asset(self,oid):
        with self.connection() as con:
            r=con.execute('SELECT * FROM library_occurrences WHERE id=?',(oid,)).fetchone()
            if not r:raise KeyError('Unknown asset')
            path=no_symlinks(Path(r['organized_path'] or r['recovered_path']))
            recovered_root=no_symlinks(Path(r['source_root']))
            organized_root=Path(self.path.parent.parent/'organized').resolve()
            if not (path.is_relative_to(child(recovered_root,'objects')) or path.is_relative_to(organized_root)):
                raise ValueError('Registered asset escaped its allowed root')
            st=path.stat()
            if st.st_size!=r['file_size_bytes'] or st.st_mtime_ns!=r['mtime_ns']:raise ValueError('Asset changed on disk; needs review')
            return {'path':path,'mime_type':r['mime_type'],'name':r['original_name'],'media_type':r['media_type']}

    def layout_rows(self,filters=None,ids=None):
        where,args=self._filters(filters)
        if ids is not None:
            if not isinstance(ids,list) or not 1<=len(ids)<=100:raise ValueError('Select 1..100 explicit items')
            where+=(' AND ' if where else ' WHERE ')+'o.id IN ('+','.join('?' for _ in ids)+')';args.extend(ids)
        with self.connection() as con:
            for r in con.execute('SELECT o.*,m.account_id FROM library_occurrences o JOIN library_media m ON m.id=o.media_id'+where+' ORDER BY o.id',args):
                s=self._summary(con,r)
                yield {'id':r['id'],'media_id':r['media_id'],'account_id':r['account_id'],'source_root':r['source_root'],
                    'source_path':r['recovered_path'],'sha256':r['final_sha256'],'file_size_bytes':r['file_size_bytes'],
                    'mtime_ns':r['mtime_ns'],'media_type':r['media_type'],'mime_type':r['mime_type'],
                    'capture_date':r['effective_date'],'date_trusted':bool(r['date_trusted']),'store':s['store'],
                    'subject':'Photo' if r['media_type']=='image' else 'Store-Broll' if s['store'] else 'Subject-Unknown',
                    'review_revision':r['review_revision'],'previous_path':r['organized_path']}

    def revision_matches(self,row):
        with self.connection() as con:
            r=con.execute('SELECT review_revision,final_sha256 FROM library_occurrences WHERE id=?',(row['id'],)).fetchone()
            return bool(r and r['review_revision']==row['review_revision'] and r['final_sha256']==row['sha256'])

    def sync_layout(self,entries,plan_id,rollback=False):
        changed=0
        with self.connection(write=True) as con:
            for e in entries:
                if rollback:
                    cursor=con.execute('UPDATE library_occurrences SET organized_path=?,organization_plan=NULL WHERE id=? AND organization_plan=? AND organized_path=?',
                                       (e.get('previous_path'),e['id'],plan_id,str(e['target'])))
                else:
                    cursor=con.execute('UPDATE library_occurrences SET organized_path=?,organization_plan=? WHERE id=? AND review_revision=? AND final_sha256=?',
                                       (str(e['target']),plan_id,e['id'],e['review_revision'],e['sha256']))
                changed+=cursor.rowcount
        return changed

    def search_footwear(self, q='', years=None, store='all', capture_type='all', limit=30, offset=0):
        from .library_search import search_footwear, ensure_catalog_schema
        with self.connection() as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'library_shoes' not in tables:
            with self.connection(write=True) as con:
                ensure_catalog_schema(con)
        with self.connection() as con:
            return search_footwear(con, q=q, years=years, store=store, capture_type=capture_type, limit=limit, offset=offset)

