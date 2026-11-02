import importlib
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sacc_takeout.library import LibraryDB, StaleReview
from sacc_takeout.library_projection import projection
from sacc_takeout.library_paths import ProtectedLibraryPath, unprotected_path
from sacc_takeout.triage import migrate, repair_catalog, run_triage, save_results


def prediction(category='non_personal'):
    return {'category':category,'shoe_conf':.8 if category=='non_personal' else 0,
            'person_conf':0,'detections':[{'class':'sneaker','conf':.8}] if category=='non_personal' else []}


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.sources=self.root/'recovery'
        (self.sources/'objects').mkdir(parents=True)
        self.db=LibraryDB(self.root/'library/staging/catalog.sqlite3');self.db.initialize()
        with self.db.connection(write=True) as con:
            con.execute("INSERT INTO library_imports(id,plan_id,watermark,report_sha,source_root,summary_json) VALUES('batch','plan',1,'hash',?,'{}')",(str(self.sources),))

    def add_items(self,count,attention=False):
        with self.db.connection(write=True) as con:
            for i in range(count):
                oid=f'fixture-{i:03}';path=self.sources/'objects'/f'{oid}.jpg';path.write_bytes(b'SYNTHETIC ONLY')
                con.execute('INSERT INTO library_media(id,account_id,source_sha256) VALUES(?,?,?)',(oid,'synthetic',oid))
                values={'id':oid,'media_id':oid,'import_id':'batch','plan_id':'plan','source_root':str(self.sources),
                    'original_path':path.name,'original_name':path.name,'media_type':'image','mime_type':'image/jpeg',
                    'recovered_path':str(path),'final_sha256':oid,'file_size_bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns,
                    'source_date_trusted':1,'date_basis':'source_utc','date_trusted':1,'effective_date':'2020-01-01',
                    'needs_attention':int(attention),'embedding_status':'unchanged_needs_review' if attention else 'metadata_write_readback_passed',
                    'raw_json':json.dumps({'review_reasons':['gps_conflict'] if attention else [],'media_subtype':'image'}),
                    'search_text':oid}
                con.execute('INSERT INTO library_occurrences('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',list(values.values()))

    def legacy(self,count,tail=0):
        with self.db.connection(write=True) as con:
            con.execute('''CREATE TABLE library_triage_detections(id TEXT PRIMARY KEY,category TEXT NOT NULL,
                shoe_conf REAL NOT NULL,person_conf REAL NOT NULL,detections_json TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            for i in range(count):
                last=i>=count-tail;cat='unknown' if last else 'non_personal'
                con.execute('INSERT INTO library_triage_detections(id,category,shoe_conf,person_conf,detections_json) VALUES(?,?,?,0,?)',
                            (f'fixture-{i:03}',cat,0 if last else .8,'[]' if last else '[{"class":"sneaker","conf":0.8}]'))
                con.execute('UPDATE library_occurrences SET privacy=?,needs_attention=? WHERE id=?',(cat,int(last),f'fixture-{i:03}'))

    def run_fake(self,predictor,**kwargs):
        return run_triage(self.db,predictor,model_sha256='synthetic-model',
                          prepare=lambda db,row,scratch:row['id'],**kwargs)

    def test_legacy_repair_preview_atomic_apply_and_idempotence(self):
        self.add_items(17,attention=True);self.legacy(17,tail=1)
        preview=repair_catalog(self.db,legacy_tail=1)
        self.assertEqual(preview['restored_metadata_flags'],16)
        with self.db.connection() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='library_triage_schema'").fetchone())
            self.assertEqual(con.execute('SELECT SUM(needs_attention) FROM library_occurrences').fetchone()[0],1)
        applied=repair_catalog(self.db,legacy_tail=1,apply=True)
        self.assertEqual(applied['restored_metadata_flags'],16);self.assertEqual(applied['retryable'],1)
        again=repair_catalog(self.db,legacy_tail=1,apply=True)
        self.assertEqual(again['projection_changes'],0);self.assertEqual(again['tail_pending'],0)
        with self.db.connection() as con:
            self.assertEqual(con.execute('SELECT SUM(needs_attention) FROM library_occurrences').fetchone()[0],17)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM library_review_events').fetchone()[0],16)
            self.assertEqual(con.execute('SELECT SUM(remote_eligible) FROM library_media').fetchone()[0],0)
        self.assertEqual(self.db.items({'review':'annotated'})['total'],0)
        self.assertEqual(self.db.items({'review':'unreviewed'})['total'],17)

    def test_bad_tail_signature_rolls_back_migration(self):
        self.add_items(17);self.legacy(17,tail=0)
        with self.assertRaises(ValueError):repair_catalog(self.db,legacy_tail=1,apply=True)
        with self.db.connection() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='library_triage_schema'").fetchone())

    def test_partial_batch_is_inferred_and_resume_is_noop(self):
        self.add_items(17,attention=True);calls=[]
        def detector(paths):calls.extend(paths);return [prediction() for _ in paths]
        result=self.run_fake(detector)
        self.assertEqual(result['succeeded'],17);self.assertEqual(len(set(calls)),17)
        self.assertEqual(self.run_fake(detector)['attempted'],0)
        self.assertEqual(len(calls),17)
        with self.db.connection() as con:
            self.assertEqual(con.execute('SELECT SUM(needs_attention) FROM library_occurrences').fetchone()[0],17)

    def test_failed_batch_isolated_and_only_failure_retried(self):
        self.add_items(17)
        def detector(paths):
            if 'fixture-005' in paths:raise ValueError('Synthetic decoder failure')
            return [prediction() for _ in paths]
        first=self.run_fake(detector)
        self.assertEqual((first['succeeded'],first['failed'],first['retryable_remaining']),(16,1,1))
        retried=[]
        def fixed(paths):retried.extend(paths);return [prediction() for _ in paths]
        second=self.run_fake(fixed)
        self.assertEqual(retried,['fixture-005']);self.assertEqual(second['retryable_remaining'],0)
        with self.db.connection() as con:
            self.assertEqual(con.execute("SELECT attempts FROM library_triage_detections WHERE id='fixture-005'").fetchone()[0],2)

    def test_interruption_commits_inferred_batch_only(self):
        self.add_items(17);stop=False
        def detector(paths):
            nonlocal stop
            stop=True
            return [prediction() for _ in paths]
        first=self.run_fake(detector,stopping=lambda:stop)
        self.assertEqual(first['succeeded'],16);self.assertEqual(first['retryable_remaining'],1)
        self.assertTrue(first['interrupted'])
        self.assertEqual(self.run_fake(lambda paths:[prediction() for _ in paths])['succeeded'],1)

    def test_unknown_success_is_distinct_from_failure(self):
        self.add_items(1)
        self.run_fake(lambda paths:[prediction('unknown') for _ in paths])
        self.assertEqual(self.run_fake(lambda paths:self.fail('Should not retry a completed unknown'))['attempted'],0)
        self.assertEqual(self.db.items({'review':'attention'})['total'],1)

    def test_note_manual_override_clear_and_unknown_override(self):
        self.add_items(1);self.run_fake(lambda paths:[prediction() for _ in paths]);oid='fixture-000'
        selected=lambda rev:[{'id':oid,'expected_revision':rev}]
        item=self.db.review(selected(1),'note','Keep this note','tester','Synthetic evidence')['updated'][0]
        self.assertEqual(item['privacy'],'non_personal');self.assertEqual(item['privacy_source'],'automatic')
        self.db.review(selected(2),'privacy','personal','tester','Synthetic evidence')
        save_results(self.db,[dict(prediction(),id=oid,input_sha256=oid)],'synthetic-model')
        self.assertEqual(self.db.detail(oid)['item']['privacy'],'personal')
        self.assertEqual(self.db.detail(oid)['item']['privacy_source'],'reviewed')
        item=self.db.review(selected(4),'clear','privacy','tester','Synthetic evidence')['updated'][0]
        self.assertEqual(item['privacy'],'non_personal')
        self.db.review(selected(5),'privacy','unknown','tester','Synthetic uncertainty')
        save_results(self.db,[dict(prediction(),id=oid,input_sha256=oid)],'synthetic-model')
        self.assertEqual(self.db.detail(oid)['item']['privacy'],'unknown')
        with self.assertRaises(StaleReview):self.db.review(selected(6),'note','stale','tester','Synthetic evidence')

    def test_source_refresh_projection_preserves_suggestion_and_metadata_flags(self):
        suggested={'category':'personal','status':'succeeded'}
        self.assertEqual(projection({'review_reasons':['gps_conflict']},'metadata_write_readback_passed',{},suggested)['privacy'],'personal')
        self.assertEqual(projection({'review_reasons':['gps_conflict']},'metadata_write_readback_passed',{},suggested)['needs_attention'],1)

    def test_changed_input_rolls_back_whole_result_batch(self):
        self.add_items(2)
        with self.db.connection(write=True) as con:con.execute('BEGIN IMMEDIATE');migrate(con)
        with self.assertRaises(ValueError):
            save_results(self.db,[dict(prediction(),id='fixture-000',input_sha256='fixture-000'),
                                  dict(prediction(),id='fixture-001',input_sha256='changed')],'synthetic')
        with self.db.connection() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM library_triage_detections').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM library_review_events').fetchone()[0],0)

    def client(self,**extra):
        env={'SACC_LIBRARY_DB':str(self.db.path),'SACC_APP_DB':str(self.root/'app.sqlite3'),
             'SACC_POC_DB':str(self.root/'poc.sqlite3'),'SACC_LIBRARY_PROTECTED_ROOTS':str(self.sources),**extra}
        context=patch.dict(os.environ,env);context.start();self.addCleanup(context.stop)
        import sacc_poc.api
        importlib.reload(sacc_poc.api)
        import main
        app=importlib.reload(main)
        return TestClient(app.app,base_url='http://127.0.0.1:5175'),app,sacc_poc.api

    def test_relative_absolute_symlink_and_safe_media_paths(self):
        self.add_items(1);client,_,_=self.client();folder=self.sources/'objects'
        alias=self.root/'alias';alias.symlink_to(folder,target_is_directory=True)
        for path in [str(folder),os.path.relpath(folder),str(alias)]:
            self.assertEqual(client.get('/api/video',params={'path':path,'file':'fixture-000.jpg'}).status_code,403)
        public=self.root/'public';public.mkdir();(public/'fixture.mp4').write_bytes(b'PUBLIC SYNTHETIC')
        self.assertEqual(client.get('/api/video',params={'path':str(public),'file':'fixture.mp4'}).status_code,200)
        self.assertEqual(client.get('/api/library/items').status_code,401)

    def test_stored_defaults_and_poc_asset_cannot_bypass_guard(self):
        self.add_items(1);client,app,poc=self.client()
        app._app_db.patch_settings({'archive_db_folder':str(self.sources)})
        self.assertEqual(client.get('/api/db/search').status_code,403)
        shoe=poc._db.upsert_shoe('SYNTHETIC','Synthetic','','')
        aid=poc._db.add_media_asset(shoe,'image',str(self.sources/'objects/fixture-000.jpg'),'','image/jpeg')
        self.assertEqual(client.get('/api/v1/assets/'+str(aid)).status_code,403)

    def test_legacy_json_child_symlink_and_stem_cannot_escape(self):
        self.add_items(1);client,_,_=self.client()
        (self.sources/'private.json').write_text('{"synthetic":true}')
        public=self.root/'json-source';(public/'json').mkdir(parents=True)
        (public/'json/alias.json').symlink_to(self.sources/'private.json')
        self.assertEqual(client.get('/api/json-db',params={'path':str(public)}).status_code,403)
        self.assertEqual(client.patch('/api/json-db',json={'path':str(public),'stem':'alias','synthetic':False}).status_code,403)
        self.assertEqual(json.loads((self.sources/'private.json').read_text()),{'synthetic':True})

    def test_ingestion_default_root_blocked_before_job_or_model(self):
        self.add_items(1);client,_,poc=self.client(SACC_LOCAL_STAGING=str(self.sources))
        with patch('sacc_poc.api.IngestionService') as service:
            self.assertEqual(client.post('/api/v1/ingest',json={}).status_code,403)
            service.assert_not_called()
        with poc._db.connection() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM ingest_jobs').fetchone()[0],0)
        from sacc_poc.storage import LocalStorageAdapter
        with self.assertRaises(ProtectedLibraryPath):list(LocalStorageAdapter(str(self.sources)).iter_media())

    def test_local_model_context_blocks_network(self):
        from scripts.triage_full_library import offline
        original=socket.getaddrinfo
        with offline():
            with self.assertRaises(PermissionError):socket.getaddrinfo('example.invalid',443)
            with socket.socket() as connection:
                with self.assertRaises(PermissionError):connection.connect(('192.0.2.1',443))
        self.assertIs(socket.getaddrinfo,original)

    def test_backups_and_private_validation_copies_are_protected(self):
        for name in ('backups','calibration','repair_validation'):
            with self.assertRaises(ProtectedLibraryPath):
                unprotected_path(Path.home()/'Documents/SACC_Data'/name/'private.sqlite3')
