"""Synthetic black-box plan/worker tests; never approve or read a real library."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from sacc_takeout import full_recovery as recovery
from sacc_takeout.common import canonical, file_hash
from sacc_takeout.importer import dry_run, fingerprint, validate_envelope
from sacc_takeout.locations import import_directory, save_visit, confirm_visit, revoke
from sacc_takeout.manifest import Manifest
from test_takeout_recovery import fixture, directory


REAL_TAGS = recovery.recovery_io.read_tags
REAL_RESTORE = recovery.recovery_io.restore_candidate


def fake_tags(path, check_space=None):
    if check_space:check_space()
    kind = 'JPEG' if Path(path).suffix.lower() in {'.jpg', '.jpeg'} else 'BIN'
    return {'SourceFile':str(Path(path).absolute()), 'File:FileType':kind,
            'File:MIMEType':'image/jpeg' if kind == 'JPEG' else 'application/octet-stream'}


def fake_restore(source, destination, proposal, check_space=None):
    """Deterministic external-tool boundary; actual writers have separate roundtrips."""
    if check_space:check_space()
    destination = Path(destination)
    with destination.open('xb') as stream:
        stream.write(Path(source).read_bytes()+b'|synthetic metadata candidate|')
    stamp = int(datetime.fromisoformat(proposal['capture']['selected']['utc']).timestamp()*10**9)
    os.utime(destination, ns=(destination.stat().st_atime_ns, stamp))
    return {'status':'verified','path':str(destination),'sha256':file_hash(destination),
            'source_sha256':file_hash(source),'mtime_ns':stamp,
            'expected_tags':{'XMP-photoshop:DateCreated':proposal['capture']['selected']['utc']},
            'readback':{'File:MIMEType':'image/jpeg'},'final_size_bytes':destination.stat().st_size}


def recache(discovery, archives):
    """Regenerate discovery only for deliberately constructed synthetic source data."""
    registered, entries = [], []
    for path in archives:
        fp = fingerprint(path)
        registered.append({'path':str(path),'size_bytes':fp['size'],'mtime_ns':fp['mtime_ns']})
        docs=[]
        with zipfile.ZipFile(path) as handle:
            for info in handle.infolist():
                entries.append({'archive':str(path),'member':info.filename,
                                'size':info.file_size,'crc':info.CRC})
                if info.filename.endswith('.json'):
                    docs.append({'archive':str(path),'member':info.filename,
                                 'document':json.loads(handle.read(info))})
        (discovery/'sidecars'/(path.name+'.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in docs))
        (discovery/'sidecars'/(path.name+'.status.json')).write_text(json.dumps(
            {'complete':True,'errors':0,'fingerprint':fp}))
    (discovery/'archives.json').write_text(json.dumps(registered))
    (discovery/'zip_entries.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in entries))


def rewrite_documents(discovery, archives, update):
    path=archives[1]
    with zipfile.ZipFile(path) as handle:
        rows=[(i.filename,handle.read(i)) for i in handle.infolist()]
    with zipfile.ZipFile(path,'w') as handle:
        for name,content in rows:
            doc=json.loads(content);update(doc)
            handle.writestr(name,json.dumps(doc))
    recache(discovery,archives)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.proofs={};self.preparations=0
        self.prepare()
        self.version=patch.object(recovery,'tool_version',return_value='synthetic-tool-version')
        self.tags=patch.object(recovery.recovery_io,'read_tags',side_effect=fake_tags)
        self.writer=patch.object(recovery.recovery_io,'restore_candidate',side_effect=fake_restore)
        for item in (self.version,self.tags,self.writer):
            item.start();self.addCleanup(item.stop)

    def tearDown(self):
        for path,digest in self.proofs.items():
            self.assertEqual(file_hash(path),digest,str(path))

    def prepare(self, *, conflicting=False, unknown=False, gps=True, count=2, description=None):
        self.preparations+=1
        base=self.root/f'fixture-{self.preparations}';base.mkdir()
        discovery,archives=fixture(base,count,conflicting_dates=conflicting)
        if not gps or description is not None:
            def update(doc):
                if not gps:doc.pop('geoDataExif',None)
                if description is not None:doc['description']=description
            rewrite_documents(discovery,archives,update)
        if unknown:
            with zipfile.ZipFile(archives[0],'a') as handle:
                handle.writestr('Takeout/Google Photos/Album/unknown.MP',b'unknown fixture bytes')
            recache(discovery,archives)
        self.source=base/'milestone'
        report=dry_run(discovery,self.source,'synthetic-account','synthetic-export',as_of='2026-10-30')
        self.batch=report['batch_id'];self.archives=archives;self.discovery=discovery
        self.out=base/'run'
        self.source_db=self.source/'recovery.sqlite3'
        self.track(*archives,self.source_db)

    def track(self,*paths):
        self.proofs.update({Path(p):file_hash(p) for p in paths})

    def plan(self, **kwargs):
        return recovery.create_plan(self.source,self.batch,self.out,**kwargs)

    def approve(self,plan,scope=None):
        return recovery.approve_plan(self.out,plan['plan_id'],scope=scope or plan['mode'],
            reviewer='Synthetic test reviewer',evidence='Unit fixture approval only; no real-media authorization')

    def execute(self,plan,**kwargs):
        return recovery.run_recovery(self.out,plan['plan_id'],scope=plan['mode'],**kwargs)

    def rows(self, query='SELECT * FROM items ORDER BY ordinal', params=()):
        db=sqlite3.connect((self.out/'recovery-run.sqlite3').as_uri()+'?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        try:return [dict(r) for r in db.execute(query,params)]
        finally:db.close()

    def records(self,name='recovery.jsonl'):
        report=json.loads((self.out/'report.json').read_text())
        return [json.loads(line) for line in (self.out/report['snapshot']/name).read_text().splitlines()]

    def test_plan_and_status_are_metadata_only_and_do_not_approve(self):
        with (patch.object(recovery.recovery_io.BoundedZipPool,'stream',side_effect=AssertionError('No payload reads')),
              patch.object(recovery.recovery_io,'stream_file',side_effect=AssertionError('No sample reads'))):
            plan=self.plan()
            before=file_hash(self.out/'recovery-run.sqlite3')
            current=recovery.status(self.out,plan['plan_id'])
            self.assertEqual(file_hash(self.out/'recovery-run.sqlite3'),before)
        self.assertEqual(plan['files'],2)
        self.assertFalse(current['approved'])
        self.assertEqual(current['counts'],{'pending':2})
        self.assertEqual(current['source_bytes_read_reserved'],0)
        self.assertFalse((self.out/'objects').exists())

    def test_exact_approval_scope_and_digest_required_without_escalation(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        for scope,pid in (('pilot',plan['plan_id']),('full',plan['plan_id']),('pilot','wrong')):
            with self.assertRaises(ValueError):
                recovery.run_recovery(self.out,pid,scope=scope)
        with self.assertRaises(ValueError):self.approve(plan,'full')
        self.approve(plan)
        with self.assertRaises(ValueError):recovery.run_recovery(self.out,plan['plan_id'],scope='full')
        self.assertEqual(recovery.status(self.out)['source_bytes_read_reserved'],0)

    def test_pilot_selection_caps_and_ledger_selection_are_sealed(self):
        for options in ({'max_files':13},{'max_bytes':128*1024**2+1},{'selection':['missing']},
                        {'source_kind':'sample','mode':'full'}):
            with self.assertRaises(ValueError):
                self.plan(mode=options.pop('mode','pilot'),**options)
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        db=sqlite3.connect(self.out/'recovery-run.sqlite3')
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE items SET size_bytes=size_bytes+1")
        db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute('DELETE FROM items')
        db.rollback();db.close()
        with self.assertRaises(ValueError):self.plan(mode='pilot',source_kind='sample',max_files=2)
        self.approve(plan);self.execute(plan);self.execute(plan)
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(recovery.status(self.out)['source_bytes_read_reserved'],plan['source_bytes'])

    def test_real_zip_roundtrip_has_final_paths_sizes_and_idempotent_reports(self):
        self.tags.stop();self.writer.stop()
        plan=self.plan();self.approve(plan)
        result=self.execute(plan)
        self.assertEqual(result['counts'],{'complete':2})
        self.assertEqual(result['phase'],'complete')
        report=json.loads((self.out/'report.json').read_text())
        self.assertEqual(report['metadata_write_readback_passed'],2)
        self.assertEqual(report['integrity_mode'],'zip_crc_sha256_single_stream')
        self.assertFalse(report['whole_archive_byte_hashes_verified'])
        for item in self.records('sacc_payloads.jsonl'):
            validate_envelope(item)
            asset=item['media_asset'];path=Path(asset['file_path'])
            self.assertTrue(path.is_file())
            self.assertEqual(asset['file_size_bytes'],path.stat().st_size)
            self.assertIsNone(asset['shoe_id']);self.assertFalse(item['live_import_eligible'])
        bytes_read=result['source_bytes_read_reserved']
        outputs={r['id']:json.loads(r['output_json']) for r in self.rows()}
        self.execute(plan)
        self.assertEqual(recovery.status(self.out)['source_bytes_read_reserved'],bytes_read)
        self.assertEqual(outputs,{r['id']:json.loads(r['output_json']) for r in self.rows()})
        first=recovery.export_reports(self.out,plan['plan_id'])
        second=recovery.export_reports(self.out,plan['plan_id'])
        self.assertEqual(first,second)
        self.assertEqual(len(self.records()),2)

    def test_sample_pilot_never_reads_zip_and_labels_canonical_sidecar(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1);self.approve(plan)
        with patch.object(recovery.recovery_io.BoundedZipPool,'stream',side_effect=AssertionError('No ZIP media reads')):
            result=self.execute(plan)
        self.assertEqual(result['completed'],1)
        row=self.rows()[0];out=json.loads(row['output_json'])
        self.assertEqual(out['sidecar']['kind'],'canonical_sample_snapshot_not_original_json')
        canonical_doc=json.loads((self.out/out['sidecar']['path']).read_text())
        self.assertEqual(canonical_doc['title'],Path(json.loads(row['source_json'])['entry']['member']).name)
        self.assertIsNone(json.loads(row['result_json'])['sidecar_sha256'])
        self.assertEqual(result['integrity_mode'],'existing_sample_sha256_recheck')

    def test_every_raw_source_precedes_metadata_and_duplicate_conflicts_hold_all(self):
        self.prepare(conflicting=True)
        plan=self.plan();self.approve(plan)
        first=self.execute(plan,max_items=1)
        self.assertEqual(first['counts'],{'pending':1,'raw':1})
        recovery.recovery_io.restore_candidate.assert_not_called()
        result=self.execute(plan)
        self.assertEqual(result['counts'],{'review':2})
        recovery.recovery_io.restore_candidate.assert_not_called()
        self.assertEqual(len({r['media_id'] for r in self.rows()}),1)
        for row in self.records():
            self.assertIn('duplicate_metadata_conflict',row['recovery']['review_reasons'])
            out=row['recovery']['output']
            self.assertEqual(file_hash(self.out/out['path']),row['recovery']['source_sha256'])

    def test_unknown_format_retained_in_canonical_and_unsupported_reports(self):
        self.prepare(unknown=True)
        plan=self.plan();self.approve(plan);result=self.execute(plan)
        self.assertEqual(result['completed'],3)
        unknown=next(r for r in self.records() if r['original_path'].endswith('.MP'))
        self.assertEqual(unknown['state'],'review')
        self.assertIn('unknown_media_format',unknown['recovery']['review_reasons'])
        self.assertTrue((self.out/unknown['recovery']['output']['path']).is_file())
        self.assertEqual(len(self.records('sacc_payloads.jsonl')),2)
        self.assertEqual(self.records('unsupported.jsonl')[0]['reason'],'unknown_media_format')

    def test_changed_output_and_symlink_are_blocked_without_overwrite(self):
        plan=self.plan();self.approve(plan);self.execute(plan)
        out=json.loads(self.rows()[0]['output_json']);path=self.out/out['path']
        path.write_bytes(b'user changed working file')
        with self.assertRaises(ValueError):self.execute(plan)
        self.assertEqual(path.read_bytes(),b'user changed working file')
        self.assertEqual(self.rows()[0]['state'],'integrity_error')
        path.unlink();target=self.root/'outside';target.write_bytes(b'private')
        path.symlink_to(target)
        with self.assertRaises(ValueError):self.execute(plan)
        self.assertEqual(target.read_bytes(),b'private')

    def test_changed_archive_tool_or_plan_rejected_before_payload_reads(self):
        plan=self.plan();self.approve(plan)
        with patch.object(recovery,'tool_version',return_value='changed-version'):
            with self.assertRaises(ValueError):self.execute(plan)
        self.archives[0].write_bytes(self.archives[0].read_bytes()+b'changed')
        self.track(self.archives[0])
        with self.assertRaises(ValueError):self.execute(plan)
        self.assertEqual(recovery.status(self.out)['source_bytes_read_reserved'],0)
        db=sqlite3.connect(self.out/'recovery-run.sqlite3')
        value=json.loads(db.execute("SELECT value FROM meta WHERE key='plan'").fetchone()[0])
        value['max_attempts']+=1
        db.execute("UPDATE meta SET value=? WHERE key='plan'",(json.dumps(value),));db.commit();db.close()
        with self.assertRaises(ValueError):recovery.status(self.out)

    def test_low_space_pauses_before_reads_and_status_remains_available(self):
        plan=self.plan();self.approve(plan)
        empty=shutil._ntuple_diskusage(100,100,0)
        with patch.object(recovery.shutil,'disk_usage',return_value=empty):
            result=self.execute(plan)
        self.assertTrue(result['paused_reason'])
        self.assertEqual(result['source_bytes_read_reserved'],0)
        self.assertEqual(recovery.status(self.out)['counts'],{'pending':2})
        self.assertEqual(self.execute(plan)['completed'],2)

    def test_enospc_retains_raw_and_retry_budget_stays_cumulative(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1);self.approve(plan)
        def no_space(source,candidate,*args,**kwargs):
            Path(candidate).write_bytes(b'partial owned candidate')
            raise OSError(28,'No space left on device')
        with patch.object(recovery.recovery_io,'stream_file',side_effect=no_space):
            first=self.execute(plan)
        self.assertEqual(first['counts'],{'pending':1})
        self.assertIn('Disk filled',first['paused_reason'])
        self.assertFalse((self.out/'objects').exists())
        completed=self.execute(plan)
        self.assertEqual(completed['completed'],1)
        self.assertEqual(completed['source_bytes_read_reserved'],2*plan['source_bytes'])
        self.assertEqual(self.rows()[0]['source_attempts'],2)

    def test_crash_adoption_all_publication_boundaries_and_both_phases(self):
        class Crash(BaseException):pass
        for phase in ('source','metadata'):
            for event in ('intent_ready','renamed','committed'):
                with self.subTest(phase=phase,event=event):
                    self.out=self.out.parent/f'crash-{phase}-{event}'
                    plan=self.plan(mode='pilot',source_kind='sample',max_files=1);self.approve(plan)
                    def crash(when,oid,which):
                        if when==event and which==phase:raise Crash()
                    with self.assertRaises(Crash):self.execute(plan,hook=crash)
                    result=self.execute(plan)
                    self.assertEqual(result['completed'],1)
                    self.assertEqual(result['source_bytes_read_reserved'],plan['source_bytes'])
                    self.assertEqual(len(self.records()),1)
                    self.assertFalse(self.rows("SELECT * FROM intents WHERE state='ready'"))

    def test_metadata_enospc_preserves_all_verified_raw_files_for_retry(self):
        plan=self.plan();self.approve(plan)
        def no_space(source,candidate,*args,**kwargs):
            Path(candidate).write_bytes(b'partial metadata candidate')
            raise OSError(28,'No space left on device')
        with patch.object(recovery.recovery_io,'restore_candidate',side_effect=no_space):
            first=self.execute(plan)
        self.assertEqual(first['counts'],{'raw':2})
        self.assertIn('Disk filled',first['paused_reason'])
        for row in self.rows():
            output=json.loads(row['output_json'])
            self.assertEqual(file_hash(self.out/output['path']),row['raw_sha256'])
            self.assertEqual(output['embedding_status'],'source_verified_only')
        reserved=first['source_bytes_read_reserved']
        result=self.execute(plan)
        self.assertEqual(result['completed'],2)
        self.assertEqual(result['source_bytes_read_reserved'],reserved)

    def test_postpublication_cleanup_failure_does_not_downgrade_or_republish(self):
        original_cleanup=shutil.rmtree
        for cleanup_phase in ('source','metadata'):
            with self.subTest(cleanup_phase=cleanup_phase):
                self.out=self.out.parent/f'cleanup-{cleanup_phase}'
                plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
                self.approve(plan)
                fault={'armed':False,'failed':False}
                def committed(event,oid,phase):
                    if event=='committed' and phase==cleanup_phase:
                        fault['armed']=True
                def cleanup(path,*args,**kwargs):
                    # The shutil module is shared with TemporaryDirectory; only
                    # fail cleanup of the ledger's registered transient directory.
                    if Path(path).parent.name=='transient' and fault['armed'] and not fault['failed']:
                        fault['failed']=True
                        raise OSError(5,'Synthetic post-publication cleanup failure')
                    return original_cleanup(path,*args,**kwargs)
                with patch.object(recovery.recovery_io,'stream_file',wraps=recovery.recovery_io.stream_file) as reader:
                    with patch.object(recovery.shutil,'rmtree',side_effect=cleanup):
                        completed=self.execute(plan,hook=committed)
                    self.assertTrue(fault['failed'])
                    self.assertEqual(completed['counts'],{'complete':1})
                    pending=self.rows("SELECT * FROM intents WHERE state='cleanup_pending'")
                    self.assertEqual(len(pending),1)
                    self.assertEqual(pending[0]['phase'],cleanup_phase)
                    row=self.rows()[0];output=json.loads(row['output_json'])
                    self.assertNotEqual(output['sha256'],row['raw_sha256'])
                    before=file_hash(self.out/output['path'])
                    attempts=(row['source_attempts'],row['metadata_attempts'])
                    reads,writes=reader.call_count,recovery.recovery_io.restore_candidate.call_count
                    resumed=self.execute(plan)
                    self.assertEqual(resumed['counts'],{'complete':1})
                    self.assertEqual(resumed['source_bytes_read_reserved'],completed['source_bytes_read_reserved'])
                    self.assertEqual(reader.call_count,reads)
                    self.assertEqual(recovery.recovery_io.restore_candidate.call_count,writes)
                self.assertFalse(self.rows("SELECT * FROM intents WHERE state='cleanup_pending'"))
                self.assertEqual(self.rows('SELECT state FROM intents WHERE id=?',(pending[0]['id'],))[0]['state'],'committed')
                current=self.rows()[0]
                self.assertEqual((current['source_attempts'],current['metadata_attempts']),attempts)
                self.assertEqual(file_hash(self.out/output['path']),before)

    def test_source_retry_and_byte_caps_cannot_reset_across_invocations(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1);self.approve(plan)
        with patch.object(recovery.recovery_io,'stream_file',side_effect=RuntimeError('Synthetic source failure')) as reader:
            for _ in range(4):
                result=self.execute(plan)
            self.assertEqual(reader.call_count,3)
        self.assertEqual(result['counts'],{'source_error':1})
        self.assertEqual(result['source_bytes_read_reserved'],3*plan['source_bytes'])
        self.assertEqual(self.rows()[0]['source_attempts'],3)
        again=self.execute(plan)
        self.assertEqual(again['completed'],0)
        self.assertEqual(again['source_bytes_read_reserved'],result['source_bytes_read_reserved'])

    def test_screenshot_review_refresh_changes_projection_without_media_writes(self):
        self.prepare(gps=False)
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1);self.approve(plan);self.execute(plan)
        original=self.records()[0]['recovery']
        self.assertIn('gps_missing',original['review_reasons'])
        row=self.rows()[0];out=json.loads(row['output_json']);before=file_hash(self.out/out['path'])
        db=Manifest(self.source)
        db.add_stage_result(row['media_id'],'local_context','synthetic-screenshot-review',{
            'context_type':'screenshot_review','is_screenshot':True,
            'reviewer':'Synthetic reviewer','evidence':'Synthetic screenshot fixture'})
        db.close();self.track(self.source_db)
        refresh=recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        self.assertTrue(refresh['processing_scope_unchanged'])
        self.assertEqual(refresh['media_rewritten'],0)
        report=recovery.export_reports(self.out,plan['plan_id'])
        current=self.records()[0]['recovery']
        self.assertEqual(current['gps_requirement']['status'],'not_expected_screenshot')
        self.assertNotIn('gps_missing',current['review_reasons'])
        self.assertEqual(report['gps_expected_coverage']['denominator'],0)
        self.assertEqual(file_hash(self.out/out['path']),before)

    def test_later_export_conflict_invalidates_projection_preserving_published_bytes(self):
        plan=self.plan();self.approve(plan);self.execute(plan)
        before={r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()}
        later=self.root/'later-export';later.mkdir()
        discovery,archives=fixture(later,1)
        rewrite_documents(discovery,archives,lambda doc:doc['photoTakenTime'].update(timestamp='1609502400'))
        dry_run(discovery,self.source,'synthetic-account','later-export',as_of='2026-10-30')
        self.track(*archives,self.source_db)
        recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        recovery.export_reports(self.out,plan['plan_id'])
        for row in self.records():
            self.assertIn('duplicate_metadata_conflict',row['recovery']['review_reasons'])
            self.assertEqual(row['recovery']['derived_evidence_status'],'stale_needs_review')
        self.assertEqual(before,{r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()})

    def test_failed_review_refresh_rolls_back_active_snapshot_then_retries(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        self.approve(plan);self.execute(plan)
        active=self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key")
        before_events=self.rows('SELECT MAX(id) AS watermark FROM events')[0]['watermark']
        before_output={r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()}
        before_counter=recovery.status(self.out)['source_bytes_read_reserved']
        later=self.root/'later-conflicting-refresh';later.mkdir()
        discovery,archives=fixture(later,1)
        rewrite_documents(discovery,archives,lambda doc:doc['photoTakenTime'].update(timestamp='1609502400'))
        dry_run(discovery,self.source,'synthetic-account','later-conflicting-refresh',as_of='2026-10-30')
        self.track(*archives,self.source_db)
        with patch.object(recovery,'_reconcile',side_effect=RuntimeError('Synthetic refresh reconciliation failure')):
            with self.assertRaises(RuntimeError):
                recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        self.assertEqual(self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key"),active)
        self.assertFalse(self.rows('SELECT * FROM reviews WHERE version=2'))
        self.assertFalse(self.rows('SELECT * FROM invalidations'))
        self.assertEqual(self.rows('SELECT MAX(id) AS watermark FROM events')[0]['watermark'],before_events)
        unchanged=recovery.export_reports(self.out,plan['plan_id'])
        self.assertEqual(unchanged['review_snapshot_version'],1)
        self.assertNotIn('duplicate_metadata_conflict',self.records()[0]['recovery']['review_reasons'])
        refresh=recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        self.assertEqual(refresh['review_snapshot_version'],2)
        self.assertTrue(refresh['processing_scope_unchanged'])
        recovery.export_reports(self.out,plan['plan_id'])
        self.assertIn('duplicate_metadata_conflict',self.records()[0]['recovery']['review_reasons'])
        self.assertEqual(before_counter,recovery.status(self.out)['source_bytes_read_reserved'])
        self.assertEqual(before_output,{r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()})

    def test_revoked_parent_invalidates_complete_dependency_snapshot(self):
        db=Manifest(self.source);media=db.con.execute('SELECT id FROM media').fetchone()[0]
        import_directory(db,directory())
        version=db.con.execute("SELECT id FROM store_versions WHERE store_id='nike-near'").fetchone()[0]
        member={'media_id':media,'capture_utc':'2020-01-01T12:00:00+00:00',
                'membership_evidence':{'kind':'synthetic explicit context'}}
        visit=save_visit(db,'synthetic-account',[member],{'kind':'synthetic'},confirmed_members=True)
        evidence={'kind':'user_branch_confirmation','source_media_id':media}
        parent=confirm_visit(db,visit,version,'Synthetic reviewer',evidence)
        with db.con:
            db.con.execute('INSERT INTO visits VALUES(?,?,?,?)',('child-visit','synthetic-account','proposed','{}'))
            db.con.execute('INSERT INTO visit_members VALUES(?,?,?,?,?)',
                ('child-visit',media,member['capture_utc'],'{"kind":"synthetic reviewed reuse"}',1))
        child=confirm_visit(db,'child-visit',version,'Synthetic reviewer',
                            {**evidence,'reuse_context_reviewed':True},parents=[parent])
        db.close();self.track(self.source_db)
        plan=self.plan();self.approve(plan);self.execute(plan)
        initial=recovery.export_reports(self.out,plan['plan_id'])
        self.assertEqual(initial['invalidated_confirmations'],0)
        before={r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()}
        db=Manifest(self.source);revoke(db,parent,'Synthetic correction');db.close();self.track(self.source_db)
        recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        report=recovery.export_reports(self.out,plan['plan_id'])
        self.assertEqual(report['invalidated_confirmations'],2)
        self.assertEqual({r['confirmation_id'] for r in self.rows(
            'SELECT json_extract(record_json,\'$.confirmation_id\') AS confirmation_id FROM reviews WHERE version=2 AND table_name=\'revocations\'')},{parent,child})
        self.assertEqual(before,{r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()})

    def test_incomplete_review_graph_is_rejected_during_planning(self):
        db=sqlite3.connect(self.source_db)
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('INSERT INTO confirmation_dependencies VALUES(?,?)',('absent-child','absent-parent'))
        db.commit();db.close();self.track(self.source_db)
        with self.assertRaises(ValueError):self.plan()

    def test_one_item_pilot_accounts_for_large_copied_review_history(self):
        self.prepare(count=20,description='Synthetic long description. '*1200)
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        sealed=json.loads((self.out/'plan.json').read_text())
        self.assertEqual(plan['files'],1)
        self.assertGreater(sealed['measured_ledger_baseline_bytes'],1024**2)
        self.assertEqual(len(self.rows(
            "SELECT * FROM reviews WHERE version=1 AND table_name='prior_observations'")),20)
        self.approve(plan)
        result=self.execute(plan)
        self.assertEqual(result['phase'],'complete')
        self.assertEqual(result['counts'],{'complete':1})
        self.assertIsNone(result['paused_reason'])

    def test_unchanged_review_refresh_is_a_repeatable_noop(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        self.approve(plan);self.execute(plan)
        before=file_hash(self.out/'recovery-run.sqlite3')
        active=self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key")
        counts=self.rows('SELECT COUNT(*) AS count FROM reviews')
        events=self.rows('SELECT COUNT(*) AS count FROM events')
        for _ in range(2):
            refreshed=recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
            self.assertTrue(refreshed['unchanged'])
            self.assertEqual(refreshed['review_snapshot_version'],1)
            self.assertEqual(refreshed['media_rewritten'],0)
        self.assertEqual(self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key"),active)
        self.assertEqual(self.rows('SELECT COUNT(*) AS count FROM reviews'),counts)
        self.assertEqual(self.rows('SELECT COUNT(*) AS count FROM events'),events)
        self.assertEqual(file_hash(self.out/'recovery-run.sqlite3'),before)

    def test_capacity_failure_during_review_copy_rolls_back_partial_snapshot(self):
        plan=self.plan(mode='pilot',source_kind='sample',max_files=1)
        self.approve(plan);self.execute(plan)
        active=self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key")
        before_events=self.rows('SELECT MAX(id) AS watermark FROM events')[0]['watermark']
        outputs={r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()}
        db=Manifest(self.source)
        media=db.con.execute('SELECT id FROM media').fetchone()[0]
        for number in range(130):
            db.add_stage_result(media,'local_context','synthetic-audit',
                {'context_type':'synthetic_audit','ordinal':number})
        db.close();self.track(self.source_db)
        observed=[]
        def capacity(budget):
            count=budget.db.con.execute('SELECT COUNT(*) FROM reviews WHERE version=2').fetchone()[0]
            observed.append(count)
            if count>=128:
                raise recovery.CapacityPause('Synthetic budget breach during copied review rows')
        with patch.object(recovery.Budget,'check',autospec=True,side_effect=capacity):
            with self.assertRaises(recovery.CapacityPause):
                recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        self.assertTrue(any(count>=128 for count in observed))
        self.assertFalse(self.rows('SELECT * FROM reviews WHERE version=2'))
        self.assertEqual(self.rows("SELECT key,value FROM meta WHERE key IN ('review_version','review_hash') ORDER BY key"),active)
        self.assertEqual(self.rows('SELECT MAX(id) AS watermark FROM events')[0]['watermark'],before_events)
        self.assertEqual(outputs,{r['id']:file_hash(self.out/json.loads(r['output_json'])['path']) for r in self.rows()})
        refreshed=recovery.refresh_reviews(self.source,self.out,plan['plan_id'])
        self.assertEqual(refreshed['review_snapshot_version'],2)
        self.assertFalse(refreshed['unchanged'])
        self.assertEqual(len(self.rows(
            "SELECT * FROM reviews WHERE version=2 AND table_name='stage_results'")),130)
        self.assertEqual(recovery.status(self.out)['files'],1)


if __name__=='__main__':
    unittest.main()
