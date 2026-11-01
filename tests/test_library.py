"""Synthetic catalogue and real FastAPI-boundary checks; never inspect private media."""
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sacc_takeout.common import file_hash
from sacc_takeout.library import LibraryDB,StaleReview
import test_takeout_full_recovery as worker
from test_takeout_recovery import directory


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.worker=worker.WorkerTests(methodName='test_plan_and_status_are_metadata_only_and_do_not_approve');self.worker.setUp()
        self.addCleanup(self.worker.doCleanups);self.addCleanup(self.worker.tearDown)
        w=self.worker;p=w.plan();w.approve(p);w.execute(p)
        self.db=LibraryDB(w.root/'library/staging/catalog.sqlite3')
        self.base_dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.base_dir.cleanup)
        self.base=Path(self.base_dir.name).resolve()/'base.sqlite3';c=sqlite3.connect(self.base);c.executescript('CREATE TABLE shoes(id PRIMARY KEY,name);INSERT INTO shoes VALUES(1,"Synthetic shoe");');c.close()
        self.base_hash=file_hash(self.base)
        self.db.initialize(self.base);self.result=self.db.import_recovery(w.out)
        self.items=self.db.items()['results']

    def test_import_idempotent_scope_and_legacy_preservation(self):
        self.assertEqual(self.result['imported'],2);self.assertEqual(self.db.status()['totals']['unique_media'],1)
        self.assertEqual(self.db.import_recovery(self.worker.out)['reused'],2)
        self.assertEqual(file_hash(self.base),self.base_hash)
        with self.db.connection() as c:
            self.assertEqual(c.execute('SELECT name FROM shoes').fetchone()[0],'Synthetic shoe')
            self.assertEqual(c.execute('SELECT SUM(remote_eligible) FROM library_media').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM library_source_history').fetchone()[0],2)
        self.assertEqual(self.db.items({'q':'" OR * NOT'})['total'],0)
        self.assertEqual(self.db.items({'year':'2020','gps':'present'})['total'],2)
        self.assertEqual(len(self.db.detail(self.items[0]['id'])['related']),1)
        self.assertEqual(self.db.items(limit=1,offset=1)['results'][0]['id'],self.items[1]['id'])

    def test_explicit_occurrence_review_and_stale_atomicity(self):
        a,b=self.items
        result=self.db.review([{'id':a['id'],'expected_revision':0}],'note','Synthetic note','tester','fixture evidence')
        self.assertEqual(result['updated'][0]['review_revision'],1)
        self.assertEqual(self.db.detail(b['id'])['item']['review_revision'],0)
        self.assertEqual(self.db.items({'q':'Synthetic note'})['total'],1)
        with self.assertRaises(StaleReview):
            self.db.review([{'id':b['id'],'expected_revision':0},{'id':a['id'],'expected_revision':0}],'privacy','personal','tester','fixture')
        self.assertEqual(self.db.detail(b['id'])['item']['review_revision'],0)
        self.db.import_recovery(self.worker.out)
        self.assertEqual(self.db.detail(a['id'])['item']['notes'],'Synthetic note')

    def test_screenshot_store_and_calendar_invalidation(self):
        a=self.items[0];selected=lambda rev:[{'id':a['id'],'expected_revision':rev}]
        self.db.import_directory(directory(),'tester','Synthetic fixture only')
        self.db.review(selected(0),'store','nike-near-v1','tester','Synthetic branch observation')
        self.db.review(selected(1),'capture_date','2001-01-01','tester','Synthetic historical correction')
        detail=self.db.detail(a['id'])['item'];self.assertIsNone(detail['store']);self.assertEqual(detail['date_basis'],'reviewed_calendar')
        self.assertIn('invalidated_store_version',detail['review_events'][0]['details_json'])
        self.db.review(selected(2),'screenshot',True,'tester','Screen capture')
        self.assertEqual(self.db.items({'gps':'not_expected'})['total'],1)
        self.db.review(selected(3),'clear','screenshot','tester','Mistaken label')
        self.assertEqual(self.db.items({'gps':'not_expected'})['total'],0)
        with self.assertRaises(ValueError):self.db.review(selected(4),'capture_date','2099-01-01','tester','future')

    def test_source_binding_and_changed_asset_refusal(self):
        report=self.worker.out/'report.json';p=json.loads(report.read_text());p['watermark']+=1;report.write_text(json.dumps(p))
        with self.assertRaises(ValueError):self.db.import_recovery(self.worker.out)
        a=self.items[0];asset=self.db.asset(a['id']);asset['path'].write_bytes(b'edited')
        with self.assertRaises(ValueError):self.db.asset(a['id'])

    def test_actual_main_security_session_range_and_attachment(self):
        env={'SACC_LIBRARY_DB':str(self.db.path),'SACC_APP_DB':str(self.worker.root/'app-state.sqlite3'),
             'SACC_POC_DB':str(self.worker.root/'poc.sqlite3'),'SACC_LIBRARY_PROTECTED_ROOTS':str(self.worker.out)}
        with patch.dict(os.environ,env):
            import main
            client=TestClient(main.app,base_url='http://127.0.0.1:5175')
            self.assertEqual(client.get('/api/library/items').status_code,401)
            self.assertEqual(client.get('/api/library/session',headers={'Origin':'https://evil.example'}).status_code,403)
            self.assertEqual(client.get('/api/library/session',headers={'Host':'evil.example'}).status_code,403)
            self.assertEqual(client.get('/api/library/session',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
            session=client.get('/api/library/session');self.assertEqual(session.status_code,200)
            self.assertIn('HttpOnly',session.headers['set-cookie']);token=session.json()['csrf_token']
            self.assertEqual(client.get('/api/library/items').json()['total'],2)
            a=self.items[0]
            range_result=client.get(a['asset_url'],headers={'Range':'bytes=0-9'})
            self.assertEqual(range_result.status_code,206);self.assertEqual(len(range_result.content),10)
            self.assertEqual(range_result.headers['x-content-type-options'],'nosniff')
            body={'items':[{'id':a['id'],'expected_revision':0}],'action':'note','value':'API note','reviewer':'tester','evidence':'Fixture'}
            self.assertEqual(client.post('/api/library/reviews',json=body).status_code,403)
            headers={'X-SACC-Library-Token':token}
            self.assertEqual(client.post('/api/library/reviews',json=body,headers=headers).status_code,200)
            self.assertEqual(client.post('/api/library/reviews',json=body,headers=headers).status_code,409)
            for path in (str(self.worker.out),str(self.worker.root),str(self.db.path.parent)):
                self.assertEqual(client.get('/api/video',params={'path':path,'file':'fixture.jpg'}).status_code,403)
                self.assertEqual(client.post('/api/does-not-exist',json={'nested':{'folder':path}}).status_code,403)
            with self.db.connection(write=True) as c:c.execute("UPDATE library_occurrences SET mime_type='image/svg+xml' WHERE id=?",(a['id'],))
            response=client.get(a['asset_url']);self.assertIn('attachment',response.headers['content-disposition'])
            self.assertEqual(client.get('/api/health').status_code,200)
            self.assertEqual(client.get('/SACC.html').status_code,200)
