"""Narrow readback deferral tests using only temporary synthetic media."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sacc_takeout import full_recovery as recovery
from sacc_takeout import recovery_io
from sacc_takeout.common import file_hash
from sacc_takeout.importer import dry_run
from sacc_takeout.manifest import Manifest
from sacc_takeout.recovery_store import Ledger
from test_takeout_recovery import fixture
import test_takeout_full_recovery as helpers


class ReadbackDeferralTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        discovery,self.archives=fixture(self.root,3)
        self.source=self.root/'milestone'
        report=dry_run(discovery,self.source,'synthetic-account','synthetic-export',as_of='2026-10-30')
        self.batch=report['batch_id'];self.out=self.root/'run'
        self.proofs={p:file_hash(p) for p in [*self.archives,self.source/'recovery.sqlite3']}
        for p in (patch.object(recovery,'tool_version',return_value='synthetic-tool-version'),
                  patch.object(recovery_io,'read_tags',side_effect=helpers.fake_tags)):
            p.start();self.addCleanup(p.stop)

    def tearDown(self):
        for path,sha in self.proofs.items():self.assertEqual(file_hash(path),sha,str(path))

    def plan(self,name='run'):
        self.out=self.root/name
        plan=recovery.create_plan(self.source,self.batch,self.out,mode='pilot',source_kind='sample',max_files=3)
        recovery.approve_plan(self.out,plan['plan_id'],scope='pilot',reviewer='Synthetic reviewer',
                              evidence='Synthetic fixture only; never approval for real library')
        return plan

    def execute(self,plan,**kwargs):
        return recovery.run_recovery(self.out,plan['plan_id'],scope='pilot',**kwargs)

    def rows(self,query='SELECT * FROM items ORDER BY ordinal',params=()):
        con=sqlite3.connect((self.out/'recovery-run.sqlite3').as_uri()+'?mode=ro',uri=True)
        con.row_factory=sqlite3.Row
        try:return [dict(row) for row in con.execute(query,params)]
        finally:con.close()

    def report(self):return json.loads((self.out/'report.json').read_text())

    def bad_writer(self,error,fail_index=0,tamper=None):
        calls=[];candidates=[]
        def write(source,destination,proposal,**kwargs):
            index=len(calls);calls.append(Path(source).name)
            if index==fail_index:
                Path(destination).write_bytes(b'UNVERIFIED CANDIDATE MUST NEVER BE PUBLISHED')
                candidates.append(Path(destination))
                if tamper:tamper(Path(source))
                raise error
            return helpers.fake_restore(source,destination,proposal,**kwargs)
        return write,calls,candidates

    def test_typed_date_gps_description_failures_retain_raw_and_continue(self):
        cases=[('XMP-photoshop:DateCreated','2020-01-01T12:00:00+00:00',None,0),
               ('GPS:GPSLatitude',10.0,11.0,1),
               ('XMP-dc:Description','Synthetic fixture only','Different observed description',1)]
        for number,(field,expected,observed,index) in enumerate(cases):
            with self.subTest(field=field):
                plan=self.plan(f'typed-{number}')
                writer,calls,candidates=self.bad_writer(
                    recovery_io.MetadataReadbackMismatch(field,expected,observed),index)
                with patch.object(recovery_io,'restore_candidate',side_effect=writer):
                    completed=self.execute(plan)
                self.assertEqual(completed['counts'],{'complete':2,'review':1})
                self.assertIsNone(completed['paused_reason']);self.assertEqual(len(calls),3)
                row=self.rows()[index];out=json.loads(row['output_json']);result=json.loads(row['result_json'])
                self.assertEqual(file_hash(self.out/out['path']),row['raw_sha256'])
                self.assertEqual(out['sha256'],row['raw_sha256'])
                self.assertEqual(out['embedding_status'],'unchanged_needs_review')
                self.assertNotIn('verification',out)
                self.assertIn('metadata_write_readback_failed',result['review_reasons'])
                evidence=result['write_readback_review']
                self.assertEqual((evidence['field'],evidence['expected'],evidence['observed']),(field,expected,observed))
                self.assertEqual(evidence['operator'],'runner')
                self.assertEqual(evidence['disposition'],'retained_original_bytes_no_embedding')
                self.assertEqual((row['source_attempts'],row['metadata_attempts']),(1,1))
                side=out['sidecar']
                self.assertEqual(file_hash(self.out/side['path']),side['sha256'])
                self.assertTrue(candidates[0].is_file())
                self.assertNotEqual(file_hash(candidates[0]),out['sha256'])
                pending=self.rows("SELECT * FROM intents WHERE state='cleanup_pending'")
                self.assertEqual(len(pending),1);self.assertEqual(pending[0]['occurrence_id'],row['id'])
                events=self.rows("SELECT * FROM events WHERE event='metadata_readback_deferred'")
                self.assertEqual(len(events),1)
                self.assertEqual(json.loads(events[0]['details_json'])['field'],field)
                report=self.report()
                self.assertEqual(report['metadata_write_readback_passed'],2)
                self.assertEqual(report['readback_failures_retained_for_review'],1)
                self.assertEqual(completed['source_bytes_read_reserved'],plan['source_bytes'])

    def test_cleanup_only_resume_does_not_retry_deferred_file_or_publish_bad_candidate(self):
        plan=self.plan()
        writer,_,candidates=self.bad_writer(recovery_io.MetadataReadbackMismatch('GPS:GPSLongitude',30.,40.))
        with patch.object(recovery_io,'restore_candidate',side_effect=writer):first=self.execute(plan)
        before={r['id']:json.loads(r['output_json']) for r in self.rows()}
        attempts={r['id']:(r['source_attempts'],r['metadata_attempts']) for r in self.rows()}
        with (patch.object(recovery_io,'restore_candidate',side_effect=AssertionError('No metadata rewrite')),
              patch.object(recovery_io,'stream_file',side_effect=AssertionError('No source reread'))):
            resumed=self.execute(plan)
        self.assertEqual(resumed['counts'],first['counts'])
        self.assertEqual(resumed['source_bytes_read_reserved'],first['source_bytes_read_reserved'])
        self.assertFalse(candidates[0].exists())
        self.assertFalse(self.rows("SELECT * FROM intents WHERE state='cleanup_pending'"))
        self.assertEqual(before,{r['id']:json.loads(r['output_json']) for r in self.rows()})
        self.assertEqual(attempts,{r['id']:(r['source_attempts'],r['metadata_attempts']) for r in self.rows()})
        for out in before.values():self.assertEqual(file_hash(self.out/out['path']),out['sha256'])
        self.assertEqual(self.report()['readback_failures_retained_for_review'],1)

    def test_raw_or_sidecar_corruption_and_mtime_changes_are_not_deferrable(self):
        for kind in ('raw_bytes','raw_mtime','sidecar_bytes'):
            with self.subTest(kind=kind):
                plan=self.plan(kind)
                def tamper(source):
                    if kind=='raw_bytes':source.write_bytes(b'corrupted raw working copy')
                    elif kind=='raw_mtime':
                        os.utime(source,ns=(source.stat().st_atime_ns,source.stat().st_mtime_ns+10**9))
                    else:
                        row=next(r for r in self.rows() if Path(json.loads(r['output_json'])['path']).name==source.name)
                        side=json.loads(row['output_json'])['sidecar']
                        (self.out/side['path']).write_bytes(b'corrupted packaged sidecar')
                writer,calls,_=self.bad_writer(recovery_io.MetadataReadbackMismatch('XMP-dc:Description','expected','observed'),tamper=tamper)
                with patch.object(recovery_io,'restore_candidate',side_effect=writer):result=self.execute(plan)
                self.assertEqual(len(calls),1)
                self.assertEqual(result['paused_reason'],'metadata_error')
                self.assertEqual(result['counts'],{'metadata_error':1,'raw':2})
                self.assertFalse(self.rows("SELECT * FROM events WHERE event='metadata_readback_deferred'"))
                self.assertEqual(self.report()['readback_failures_retained_for_review'],0)

    def test_other_failure_types_keep_hard_stop_behavior(self):
        errors=[ValueError('Existing embedded metadata changed: GPSLatitude'),
                ValueError('Metadata readback mismatch: XMP-dc:Description'),
                TimeoutError('Metadata tool timed out'),
                recovery_io.ToolError('exiftool',1,'','Bad tool output'),
                OSError(5,'Synthetic I/O failure'),OSError(28,'No space left')]
        for number,error in enumerate(errors):
            with self.subTest(error=type(error).__name__,number=number):
                plan=self.plan(f'hard-stop-{number}')
                writer,calls,_=self.bad_writer(error)
                with patch.object(recovery_io,'restore_candidate',side_effect=writer):result=self.execute(plan)
                self.assertEqual(len(calls),1)
                self.assertTrue(result['paused_reason'])
                self.assertEqual(result['counts'],{'raw':3} if isinstance(error,OSError) and error.errno==28
                                 else {'metadata_error':1,'raw':2})
                self.assertFalse(self.rows("SELECT * FROM events WHERE event='metadata_readback_deferred'"))
                self.assertEqual(self.report()['readback_failures_retained_for_review'],0)

    def test_deferral_event_failure_rolls_back_review_and_cleanup_state_atomically(self):
        plan=self.plan()
        original_event=Ledger.event
        def event(db,name,*args,**kwargs):
            if name=='metadata_readback_deferred':raise RuntimeError('Synthetic audit-event failure')
            return original_event(db,name,*args,**kwargs)
        writer,_,candidates=self.bad_writer(recovery_io.MetadataReadbackMismatch('XMP-dc:Description','expected',None))
        with (patch.object(Ledger,'event',autospec=True,side_effect=event),
              patch.object(recovery_io,'restore_candidate',side_effect=writer)):
            stopped=self.execute(plan)
        self.assertEqual(stopped['counts'],{'metadata_error':1,'raw':2})
        failed=self.rows()[0];raw=json.loads(failed['result_json']);out=json.loads(failed['output_json'])
        self.assertNotIn('write_readback_review',raw)
        self.assertNotIn('metadata_write_readback_failed',raw['review_reasons'])
        self.assertEqual(out['embedding_status'],'source_verified_only')
        self.assertEqual(file_hash(self.out/out['path']),failed['raw_sha256'])
        self.assertFalse(self.rows("SELECT * FROM intents WHERE state='cleanup_pending'"))
        self.assertTrue(self.rows("SELECT * FROM intents WHERE phase='metadata' AND state='started'"))
        self.assertTrue(candidates[0].is_file())
        self.assertFalse(self.rows("SELECT * FROM events WHERE event='metadata_readback_deferred'"))
        with patch.object(recovery_io,'restore_candidate',side_effect=helpers.fake_restore):
            resumed=self.execute(plan)
        self.assertEqual(resumed['counts'],{'complete':3})
        self.assertEqual(resumed['source_bytes_read_reserved'],stopped['source_bytes_read_reserved'])

    def test_oversized_failure_evidence_is_bounded_and_never_partially_committed(self):
        plan=self.plan()
        writer,_,_=self.bad_writer(recovery_io.MetadataReadbackMismatch('XMP-dc:Description','expected','x'*(1024**2+128)))
        with patch.object(recovery_io,'restore_candidate',side_effect=writer):result=self.execute(plan)
        self.assertEqual(result['paused_reason'],'metadata_error')
        row=self.rows()[0]
        self.assertLess(len(row['result_json'].encode()),1024**2)
        self.assertNotIn('write_readback_review',json.loads(row['result_json']))
        self.assertFalse(self.rows("SELECT * FROM intents WHERE state='cleanup_pending'"))
        self.assertEqual(self.report()['readback_failures_retained_for_review'],0)

    def test_writer_emits_typed_error_only_for_expected_tag_comparisons(self):
        db=Manifest(self.source)
        oid=db.con.execute('SELECT occurrence_id FROM sample_members ORDER BY ordinal LIMIT 1').fetchone()[0]
        proposal=db.result(oid)['result'];db.close()
        source=Path(proposal['paths']['staged']);before=file_hash(source)
        values={'XMP-photoshop:DateCreated':'2020:01:01 12:00:00+00:00',
                'XMP-dc:Description':'Synthetic fixture only','GPS:GPSLatitude':10.,
                'GPS:GPSLatitudeRef':'N','GPS:GPSLongitude':30.,'GPS:GPSLongitudeRef':'W'}
        for number,(field,observed) in enumerate((('XMP-photoshop:DateCreated',None),
                                                 ('GPS:GPSLatitude',20.),('XMP-dc:Description','changed'))):
            with self.subTest(field=field):
                destination=self.root/f'unpublished-{number}.jpg'
                checked={**values,field:observed}
                with patch.object(recovery_io,'read_tags',return_value=checked):
                    with self.assertRaises(recovery_io.MetadataReadbackMismatch) as caught:
                        helpers.REAL_RESTORE(source,destination,proposal)
                self.assertEqual(caught.exception.field,field)
                self.assertEqual(caught.exception.observed,observed)
                self.assertFalse(destination.exists())
        self.assertEqual(file_hash(source),before)

    def test_postcommit_accounting_failure_preserves_review_and_resumes_later_items(self):
        for number,error in enumerate((OSError(13,'Synthetic allocation EACCES'),ValueError('Synthetic allocation failure'))):
            with self.subTest(error=type(error).__name__):
                plan=self.plan(f'postcommit-{number}')
                original_allocated=recovery._allocated;triggered=[]
                def allocated(path):
                    if not triggered and Path(path).parent.name=='transient':
                        reviewed=self.rows("SELECT result_json FROM items WHERE state='review'")
                        if any('write_readback_review' in json.loads(row['result_json']) for row in reviewed):
                            triggered.append(True);raise error
                    return original_allocated(path)
                writer,calls,_=self.bad_writer(recovery_io.MetadataReadbackMismatch('XMP-photoshop:DateCreated','expected',None))
                with (patch.object(recovery,'_allocated',side_effect=allocated),
                      patch.object(recovery_io,'restore_candidate',side_effect=writer)):
                    stopped=self.execute(plan)
                self.assertTrue(triggered)
                self.assertTrue(stopped['paused_reason'])
                self.assertEqual(stopped['counts'],{'raw':2,'review':1})
                row=self.rows()[0];out=json.loads(row['output_json'])
                self.assertEqual(file_hash(self.out/out['path']),row['raw_sha256'])
                before=file_hash(self.out/out['path'])
                with patch.object(recovery_io,'restore_candidate',side_effect=helpers.fake_restore) as restored:
                    resumed=self.execute(plan)
                self.assertEqual(restored.call_count,2)
                self.assertEqual(resumed['counts'],{'complete':2,'review':1})
                self.assertEqual(file_hash(self.out/out['path']),before)
                self.assertEqual(self.rows()[0]['metadata_attempts'],1)
                self.assertEqual(resumed['source_bytes_read_reserved'],stopped['source_bytes_read_reserved'])


if __name__=='__main__':
    unittest.main()
