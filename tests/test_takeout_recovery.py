import hashlib
import json
from datetime import date
from pathlib import Path
import tempfile
import sqlite3
import warnings
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
from sacc_takeout.common import canonical, file_hash, private_root, token
from sacc_takeout.importer import conservative_matches, dry_run, fingerprint, load_inventory, verify_copies, validate_envelope
from sacc_takeout.manifest import Manifest
from sacc_takeout.metadata import propose, gps_proposal, capture_proposal, read_tags
from sacc_takeout.locations import (validate_directory, import_directory, candidates, propose_stops,
    save_visit, confirm_visit, revoke, active_assignments, visit_timeline)


def fixture(root, count=3, export='export', conflicting_dates=False, duplicate_names=False):
    source = root/export; source.mkdir()
    discovery = root/(export+'-discovery'); discovery.mkdir(); (discovery/'sidecars').mkdir()
    photo = root/'fixture.jpg'; Image.new('RGB', (16, 16), (22, 33, 44)).save(photo)
    content = photo.read_bytes()
    a, b = source/'part1.zip', source/'part2.zip'
    with zipfile.ZipFile(a, 'w') as z:
        for i in range(count):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                z.writestr(f'Takeout/Google Photos/Album/p{0 if duplicate_names else i}.jpg', content)
    with zipfile.ZipFile(b, 'w') as z:
        for i in range(count):
            doc = {'title': f'p{i}.jpg', 'photoTakenTime': {'timestamp': '1577880000'},
                   'description': 'Synthetic fixture only', 'geoDataExif': {'latitude': 10.0, 'longitude': -30.0}}
            if conflicting_dates and i: doc['photoTakenTime']['timestamp']='1609502400'
            z.writestr(f'Takeout/Google Photos/Album/p{i}.jpg.json', json.dumps(doc))
    archives, entries = [], []
    for p in (a,b):
        fp = fingerprint(p); archives.append({'path': str(p), 'size_bytes': fp['size'], 'mtime_ns': fp['mtime_ns']})
        docs = []
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                entries.append({'archive': str(p), 'member': info.filename, 'size': info.file_size, 'crc': info.CRC})
                if info.filename.endswith('.json'):
                    docs.append({'archive': str(p), 'member': info.filename, 'document': json.loads(z.read(info))})
        (discovery/'sidecars'/(p.name+'.jsonl')).write_text(''.join(json.dumps(x)+'\n' for x in docs))
        (discovery/'sidecars'/(p.name+'.status.json')).write_text(json.dumps({'complete': True, 'errors': 0, 'fingerprint': fp}))
    (discovery/'archives.json').write_text(json.dumps(archives))
    (discovery/'zip_entries.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in entries))
    return discovery, [a,b]


def directory():
    def store(key, retailer, lat, lon, **kw):
        return dict(version_id=key+'-v1', store_id=key, retailer=retailer, branch='SYNTHETIC '+key,
                    store_type='fixture', venue_id='test-mall' if key!='nike-far' else 'test-outlet',
                    latitude=lat, longitude=lon, valid_from='2010-01-01', valid_to=None,
                    provenance='Synthetic test coordinates; no actual stores', **kw)
    return {'schema_version':1, 'snapshot_id':'fixture-v1', 'source':'synthetic', 'provenance':'Tests only',
            'stores':[store('nike-near','Nike',10,-30),store('adidas','adidas',10.0001,-30),
                      store('footaction','Footaction',10.0002,-30),store('finish-line','Finish Line',10.0003,-30),
                      store('nike-far','Nike',11,-31)]}


class MetadataTests(unittest.TestCase):
    def test_conflicts_invalid_booleans_and_missing(self):
        r, issues = gps_proposal({'geoDataExif':{'latitude':10,'longitude':-30}, 'geoData':{'latitude':20,'longitude':-30}}, {}, 100)
        self.assertIsNone(r['selected']); self.assertIn('gps_conflict',issues)
        for value in (True, float('nan'), 91, None):
            r, issues = gps_proposal({'geoData':{'latitude':value,'longitude':10}}, {},100)
            self.assertIsNone(r['selected']); self.assertIn('gps_invalid',issues)
        r,_ = gps_proposal({'geoData':{'latitude':0,'longitude':0}}, {},100)
        self.assertFalse(r['available'])
        r,_ = gps_proposal({'geoDataExif':False}, {},100)
        self.assertIsNone(r['selected'])

    def test_date_policy_and_timezone(self):
        doc={'photoTakenTime':{'timestamp':'1577880000'}}
        r,issues=capture_proposal(doc, {'ExifIFD:DateTimeOriginal':'2020:01:01 07:00:00','ExifIFD:OffsetTimeOriginal':'-05:00'}, None,date(2026,10,29))
        self.assertTrue(r['safe_to_embed']); self.assertNotIn('date_conflict',issues)
        r,issues=capture_proposal(doc, {'ExifIFD:DateTimeOriginal':'2021:01:01 07:00:00'}, None,date(2026,10,29))
        self.assertIn('date_conflict',issues); self.assertFalse(r['safe_to_embed'])
        for value in (False,{'timestamp':True},{'timestamp':'NaN'}):
            r,issues=capture_proposal({'photoTakenTime':value}, {},None,date(2026,10,29))
            self.assertIn('invalid_photo_taken_time',issues); self.assertIsNone(r['selected'])
        r,issues=capture_proposal({'creationTime':{'timestamp':'1577880000'}},{},None,date(2026,10,29))
        self.assertIsNone(r['selected'])
        r,issues=capture_proposal({'photoTakenTime':{'timestamp':'-228448961'}},{},None,date(2026,10,29))
        self.assertIn('suspicious_capture_date',issues)

    def test_signed_gps_and_accuracy_evidence(self):
        r,_=gps_proposal({}, {'GPS:GPSLatitude':10,'GPS:GPSLongitude':30,'GPS:GPSLatitudeRef':'S','GPS:GPSLongitudeRef':'W'},100)
        self.assertEqual(r['selected']['latitude'],-10); self.assertEqual(r['selected']['longitude'],-30)
        r,_=gps_proposal({'geoDataExif':{'latitude':10,'longitude':30,'latitudeSpan':0.1}}, {},100)
        self.assertIsNone(r['selected']['accuracy_m'])

    def test_nonmedia_detected_type_and_manifest_only_video(self):
        r=propose({'photoTakenTime':{'timestamp':'1577880000'}},{'File:MIMEType':'text/plain','File:FileType':'TXT'},None,date(2026,10,29))
        self.assertIn('detected_media_type_mismatch',r['review_reasons'])


class ImporterTests(unittest.TestCase):
    def test_conflicting_suffix_match_cannot_be_erased(self):
        m={'A/a(1).jpg':{}}; d={'A/a.jpg(1).json':{'title':'a.jpg'},'A/a(1).jpg.json':{'title':'a(1).jpg'}}
        found,blocked=conservative_matches(m,d)
        self.assertEqual(found,{}); self.assertIn('A/a(1).jpg',blocked)
        found,_=conservative_matches({'B/a.jpg':{}},{'A/a.jpg.json':{'title':'a.jpg'}})
        self.assertEqual(found,{})

    def test_split_zip_roundtrip_resume_provenance_and_copy(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); discovery,archives=fixture(root); out=root/'out'
            hashes=[file_hash(p) for p in archives]
            first=dry_run(discovery,out,'account1','export',as_of='2026-10-29')
            self.assertEqual(first['counts']['complete'],3); self.assertEqual(first['counts']['unchanged_sources'],3)
            copied=verify_copies(out,first['batch_id'])
            self.assertEqual(copied['counts']['verified_copies'],3)
            again=dry_run(discovery,out,'account1','export',as_of='2026-10-29')
            self.assertEqual(again['resumed_without_reprocessing'],3)
            self.assertEqual(hashes,[file_hash(p) for p in archives])
            db=Manifest(out)
            self.assertEqual(db.con.execute('SELECT COUNT(*) FROM media').fetchone()[0],1)
            self.assertEqual(db.con.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0],3)
            envelope=json.loads((out/'reports'/first['batch_id']/'sacc_payloads.jsonl').read_text().splitlines()[0])
            validate_envelope(envelope); self.assertFalse(envelope['live_import_eligible'])
            db.close()
            with self.assertRaises(ValueError): dry_run(discovery,out,'account1','export',limit=2,as_of='2026-10-29')
            with self.assertRaises(ValueError): dry_run(discovery,out,'account1','export',seed=99,as_of='2026-10-29')
            second,_=fixture(root,export='later')
            r=dry_run(second,out,'account1','later',as_of='2026-10-29')
            db=Manifest(out)
            self.assertEqual(db.con.execute('SELECT COUNT(*) FROM media').fetchone()[0],1)
            self.assertEqual(len(db.compare_batches(first['batch_id'],r['batch_id'])['hash_proven_common_media']),1)
            db.close()

    def test_cache_mutation_and_source_change(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); d,archives=fixture(root,1)
            cache=d/'sidecars'/'part2.zip.jsonl'
            item=json.loads(cache.read_text());item['document']['description']='tampered';cache.write_text(json.dumps(item)+'\n')
            result=dry_run(d,root/'out','a','e',as_of='2026-10-29')
            self.assertEqual(result['counts']['error'],1)
            archives[0].write_bytes(archives[0].read_bytes()+b'changed')
            with self.assertRaises(ValueError):load_inventory(d)

    def test_failure_retry_and_output_corruption(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); d,_=fixture(root,1); out=root/'out'
            with patch('sacc_takeout.importer.read_tags',side_effect=RuntimeError('interruption')):
                with self.assertRaises(RuntimeError): dry_run(d,out,'a','e',as_of='2026-10-29')
            r=dry_run(d,out,'a','e',as_of='2026-10-29');self.assertEqual(r['counts']['complete'],1)
            next((out/'staged').rglob('*.jpg')).write_bytes(b'corrupt')
            r=dry_run(d,out,'a','e',as_of='2026-10-29');self.assertEqual(r['counts']['error'],1)
            r=dry_run(d,out,'a','e',as_of='2026-10-29');self.assertEqual(r['counts']['error'],1)

    def test_limits_and_output_guards(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); d,archives=fixture(root,1)
            with self.assertRaises(ValueError): dry_run(d,root/'out','a','e',limit=201)
            with self.assertRaises(ValueError): private_root(archives[0].parent/'output',archives)
            (root/'link').symlink_to(root/'target')
            with self.assertRaises(ValueError):private_root(root/'link'/'out')
            with self.assertRaises(ValueError):private_root(root/'Inbox'/'out')

    def test_duplicate_observation_conflict_excludes_visits(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();d,_=fixture(root,2,conflicting_dates=True)
            r=dry_run(d,root/'out','a','e')
            self.assertEqual(r['review_reasons']['duplicate_metadata_conflict'],2)
            db=Manifest(root/'out');self.assertEqual(db.con.execute('SELECT COUNT(*) FROM visit_members').fetchone()[0],0);db.close()

    def test_copy_creation_crash_can_adopt_valid_orphan(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();d,_=fixture(root,1);out=root/'out'
            r=dry_run(d,out,'a','e'); batch=r['batch_id']
            original_save=Manifest.save_result
            def crash(db,oid,state,result,error=None):
                if result.get('verification'):raise KeyboardInterrupt('crash after file creation')
                return original_save(db,oid,state,result,error)
            with patch.object(Manifest,'save_result',crash):
                with self.assertRaises(KeyboardInterrupt):verify_copies(out,batch)
            self.assertEqual(verify_copies(out,batch)['counts']['verified_copies'],1)
            with self.assertRaises(ValueError):verify_copies(out,'missing')

    def test_duplicate_member_paths_and_missing_sidecar_remain_reviewable(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();d,_=fixture(root,2,duplicate_names=True)
            media={'A/a.jpg':{}}
            matches,blocked=conservative_matches(media,{'A/a.jpg.json':{'title':'different.jpg'}})
            self.assertFalse(matches);self.assertIn('A/a.jpg',blocked)
            r=dry_run(d,root/'out','a','e',as_of='2026-10-29')
            self.assertEqual(r['review_reasons']['ambiguous_sidecar'],2)
            db=Manifest(root/'out')
            initial=db.con.execute('SELECT COUNT(*) FROM sample_members').fetchone()[0]
            db.close()
            with self.assertRaises(ValueError):dry_run(d,root/'out','a','e',limit=0,as_of='2026-10-29')
            db=Manifest(root/'out');self.assertEqual(db.con.execute('SELECT COUNT(*) FROM sample_members').fetchone()[0],initial);db.close()

    def test_schema_creation_failure_is_atomic_and_retryable(self):
        with tempfile.TemporaryDirectory() as t:
            out=private_root(Path(t).resolve()/'out')
            with patch('sacc_takeout.manifest.SCHEMA',"CREATE TABLE recovery_schema(version INTEGER,name TEXT); INSERT INTO recovery_schema VALUES(1,'sacc_takeout_recovery'); INVALID SQL;"):
                with self.assertRaises(sqlite3.OperationalError):Manifest(out)
            con=sqlite3.connect(out/'recovery.sqlite3');self.assertEqual(con.execute('SELECT name FROM sqlite_master').fetchall(),[]);con.close()
            db=Manifest(out);db.close()
            con=sqlite3.connect(out/'recovery.sqlite3');con.execute('DROP TABLE stage_results');con.commit();con.close()
            with self.assertRaises(ValueError):Manifest(out)


class LocationTests(unittest.TestCase):
    def test_branches_and_history_remain_distinct(self):
        doc=directory();validate_directory(doc)
        found=candidates(doc['stores'],{'latitude':10,'longitude':-30},'2020-01-01T12:00:00+00:00')
        self.assertEqual({x['store_id'] for x in found},{'nike-near','adidas','footaction','finish-line'})
        self.assertTrue(all(x['assignment_status']=='candidate_only' for x in found))
        far=candidates(doc['stores'],{'latitude':11,'longitude':-31},'2020-01-01T12:00:00+00:00')
        self.assertEqual([x['store_id'] for x in far],['nike-far'])
        old=candidates(doc['stores'],{'latitude':10,'longitude':-30},'2000-01-01T12:00:00+00:00')
        self.assertTrue(all(x['historical_status']=='outside_active_dates' for x in old))
        doc['stores'][0]['valid_from']=None
        self.assertEqual(candidates(doc['stores'][:1],{'latitude':10,'longitude':-30},'2020-01-01T12:00:00+00:00')[0]['historical_status'],'historical_review')
        doc['stores'].append(dict(doc['stores'][1],version_id='overlap'))
        with self.assertRaises(ValueError):validate_directory(doc)

    def test_transitions_and_missing_gps_do_not_force_grouping(self):
        rows=[{'media_id':str(i),'account_id':'a','capture_utc':f'2020-01-01T12:0{i}:00+00:00',
               'gps':{'latitude':10,'longitude':-30},'store_context':'Nike' if i<2 else 'adidas'} for i in range(3)]
        self.assertEqual([len(x) for x in propose_stops(rows)],[2,1])
        rows[1]['gps']=None
        self.assertEqual([len(x) for x in propose_stops(rows)],[1,1,1])

    def test_shared_timeline_confirmation_and_transitive_revocation(self):
        with tempfile.TemporaryDirectory() as t:
            db=Manifest(private_root(Path(t).resolve()/'out')); import_directory(db,directory())
            with db.con:
                db.con.execute("INSERT INTO accounts VALUES ('a','fixture',0)")
                for i in range(6): db.con.execute('INSERT INTO media(id,account_id,sha256,media_type,size_bytes) VALUES (?,?,?,?,?)',(str(i),'a',str(i),'image' if i%2==0 else 'video',1))
            version=db.con.execute("SELECT id FROM store_versions WHERE store_id='nike-near'").fetchone()[0]
            confirmations=[]
            for i in range(3):
                members=[{'media_id':str(i*2+j),'capture_utc':f'2020-01-0{i+1}T12:0{j}:00+00:00',
                          'membership_evidence':{'reviewer':'fixture','context':'local signage'}} for j in range(2)]
                visit=save_visit(db,'a',members,{'fixture':True})
                self.assertTrue(all(not r['confirmed'] for r in visit_timeline(db,visit)))
                self.assertEqual(save_visit(db,'a',members,{'fixture':True},confirmed_members=True),visit)
                evidence={'kind':'local_video','source_media_id':str(i*2+1),'reuse_context_reviewed':True}
                ident=confirm_visit(db,visit,version,'fixture reviewer',evidence,confirmations[-1:] if confirmations else ())
                confirmations.append(ident)
                self.assertEqual([x['media_type'] for x in visit_timeline(db,visit)],['image','video'])
                self.assertEqual(len(active_assignments(db,str(i*2))),1)
            root_visit=db.con.execute('SELECT visit_id FROM confirmations WHERE id=?',(confirmations[0],)).fetchone()[0]
            child_visit=db.con.execute('SELECT visit_id FROM confirmations WHERE id=?',(confirmations[-1],)).fetchone()[0]
            with db.con:db.con.execute("UPDATE visits SET status='needs_review' WHERE id=?",(root_visit,))
            self.assertEqual(active_assignments(db,'4'),[])
            with self.assertRaises(ValueError):
                confirm_visit(db,child_visit,version,'fixture',{'kind':'local_video','source_media_id':'5','reuse_context_reviewed':True},[confirmations[0]])
            with db.con:db.con.execute("UPDATE visits SET status='confirmed' WHERE id=?",(root_visit,))
            self.assertEqual(len(active_assignments(db,'4')),1)
            self.assertEqual(revoke(db,confirmations[0],'fixture correction'),set(confirmations))
            self.assertEqual(active_assignments(db,'4'),[])
            self.assertEqual(db.con.execute('SELECT COUNT(*) FROM assignments').fetchone()[0],6)
            db.add_stage_result('0','classification','fixture-v1',{'privacy':'mixed','sneaker':'present'})
            self.assertEqual(db.con.execute("SELECT remote_eligible FROM media WHERE id='0'").fetchone()[0],0)
            with self.assertRaises(ValueError):db.link_components('0','1','live_photo',{'basename':'same'})
            db.close()

    def test_separated_photo_video_paths_keep_shared_confirmed_store(self):
        with tempfile.TemporaryDirectory() as t:
            db=Manifest(private_root(Path(t).resolve()/'out'));import_directory(db,directory())
            with db.con:
                db.con.execute("INSERT INTO accounts VALUES ('a','test',0)")
                db.con.execute("INSERT INTO batches VALUES ('b','a','e','{}','hash','{}')")
                db.con.execute("INSERT INTO archives VALUES ('z','b','fixture.zip','{}')")
                for i,kind in enumerate(('image','video')):
                    mid=str(i)
                    db.con.execute('INSERT INTO media(id,account_id,sha256,media_type,size_bytes) VALUES (?,?,?,?,?)',(mid,'a',mid,kind,1))
                    db.con.execute('INSERT INTO occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?)',(mid,'b','z',mid,i,'album',kind,1,0,'{}',mid))
                    db.save_result(mid,'complete',{'paths':{'staged':'together/'+mid},'observed_gps':{'selected':None}})
            members=[{'media_id':str(i),'capture_utc':f'2020-01-01T12:0{i}:00+00:00','membership_evidence':{'source':'reviewed video sequence'}} for i in range(2)]
            visit=save_visit(db,'a',members,{'source':'fixture'},True)
            version=db.con.execute("SELECT id FROM store_versions WHERE store_id='nike-near'").fetchone()[0]
            confirm_visit(db,visit,version,'fixture',{'kind':'local_video','source_media_id':'1'})
            for i,folder in enumerate(('Photos/2020/01','Videos/2020/01')):
                result=db.result(str(i))['result'];result['paths']['staged']=folder+'/'+str(i);db.save_result(str(i),'complete',result)
            timeline=visit_timeline(db,visit)
            self.assertTrue(timeline[0]['working_path'].startswith('Photos/'))
            self.assertTrue(timeline[1]['working_path'].startswith('Videos/'))
            for i in range(2):
                self.assertEqual(active_assignments(db,str(i))[0]['store_id'],'nike-near')
                self.assertIsNone(db.result(str(i))['result']['observed_gps']['selected'])
            with db.con:db.con.execute("UPDATE visits SET status='needs_review' WHERE id=?",(visit,))
            self.assertEqual(active_assignments(db,'0'),[])
            db.close()


if __name__=='__main__': unittest.main()
