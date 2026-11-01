from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sacc_takeout.importer import dry_run
from sacc_takeout.manifest import Manifest
from sacc_takeout.trip_preview import propose_trips, run_preview, ReadOnlyPreview
from test_takeout_recovery import fixture


def item(n,minutes=0,gps=True,store=None,**kw):
    r={'id':str(n),'media_id':str(n),'filename':f'IMG_{11000+n}.JPG','account_id':'a','device_id':'device-a',
       'capture_utc':(datetime(2020,1,1,12,tzinfo=timezone.utc)+timedelta(minutes=minutes)).isoformat(),
       'media_type':'image','date_uncertain':False,'context_source':'verified_sample','review_reasons':[],
       'gps':gps if isinstance(gps,dict) else {'latitude':10.,'longitude':-30.} if gps else None}
    if store:r['confirmed_context']={'active':True,'store_version_id':store,'confirmation_id':'confirmation-'+store,
        'account_id':'a','valid_from':'2010-01-01','valid_to':None}
    r.update(kw);return r


def sizes(result):return [len(s['occurrence_ids']) for t in result['trips'] for s in t['stops']]


class TripInferenceTests(unittest.TestCase):
    def test_footlocker_to_jd_same_mall_pin_is_two_stops(self):
        r=propose_trips([item(1,0,store='footlocker'),item(2,5,store='footlocker'),
                         item(3,10,store='jd'),item(4,15,False,store='jd',media_type='video')])
        self.assertEqual(len(r['trips']),1);self.assertEqual(sizes(r),[2,2])
        self.assertEqual(r['trips'][0]['stops'][1]['reasons'],['confirmed_store_transition'])

    def test_bracketed_missing_gps_has_evidence_but_no_measured_coordinate(self):
        records=[item(1,0,store='nike-192'),item(2,2,False,media_type='video'),item(3,4,store='nike-192')]
        original=deepcopy(records);r=propose_trips(records);p=r['location_proposals'][0]
        self.assertEqual(p['strength'],'compatible_bracketing')
        self.assertEqual(p['candidate_store_version_id'],'nike-192')
        self.assertEqual(p['anchor_occurrence_ids'],['1','3'])
        self.assertEqual(p['status'],'needs_review');self.assertEqual(records,original)
        self.assertFalse('latitude' in p);self.assertEqual(sizes(r),[3])

    def test_transition_and_gps_jump_protect_missing_middle(self):
        for right in (item(3,4,store='jd'),item(3,4,gps={'latitude':11.,'longitude':-30.})):
            records=[item(1,0,store='footlocker'),item(2,2,False),right]
            r=propose_trips(records);p=r['location_proposals'][0]
            self.assertEqual(p['strength'],'unresolved');self.assertIsNone(p['candidate_store_version_id'])
            self.assertEqual(sizes(r),[1,1,1])
        r=propose_trips([item(1,0,store='footlocker'),item(2,1,False,store='jd'),item(3,2,False),item(4,4,store='footlocker')])
        p=next(p for p in r['location_proposals'] if p['occurrence_id']=='3')
        self.assertEqual(p['strength'],'unresolved');self.assertIsNone(p['candidate_store_version_id'])
        self.assertIn('intervening_confirmed_store_boundary',p['reasons'])
        r=propose_trips([item(1,0,store='footlocker'),item(2,1,False,store='jd'),item(3,2,False)])
        p=next(p for p in r['location_proposals'] if p['occurrence_id']=='3')
        self.assertEqual(p['anchor_occurrence_ids'],['2'])
        self.assertNotIn('1',p['anchor_occurrence_ids'])

    def test_confirmed_branch_without_gps_can_anchor_location_but_not_coordinates(self):
        records=[item(1,0,False,'jd'),item(2,2,False),item(3,4,False,'jd')]
        r=propose_trips(records);p=next(p for p in r['location_proposals'] if p['occurrence_id']=='2')
        self.assertEqual(p['strength'],'compatible_bracketing')
        self.assertEqual(p['candidate_store_version_id'],'jd')
        self.assertIn('confirmed_branch_context_without_measured_gps',p['reasons'])
        self.assertEqual(sizes(r),[3]);self.assertTrue(all(a['gps'] is None for a in records))
        mixed=[item(1,0,False,'jd'),item(2,2,False),item(3,4,gps={'latitude':-45.,'longitude':120.})]
        p=next(p for p in propose_trips(mixed)['location_proposals'] if p['occurrence_id']=='2')
        self.assertEqual(p['strength'],'unresolved');self.assertIsNone(p['candidate_store_version_id'])
        self.assertIn('neighbor_evidence_incomparable',p['reasons'])

    def test_filename_and_time_can_bundle_unlocated_media_without_assigning_location(self):
        records=[item(1,0,False),item(2,2,False,media_type='video'),item(3,4,False)]
        r=propose_trips(records)
        self.assertEqual(sizes(r),[3])
        self.assertTrue(all(p['candidate_store_version_id'] is None and p['strength']=='unresolved' for p in r['location_proposals']))
        self.assertIn('unlocated_temporal_bundle_not_store_evidence',r['trips'][0]['stops'][0]['reasons'])

    def test_long_pause_uses_positive_evidence_and_brand_alone_is_insufficient(self):
        for pause in (30,60,90):
            self.assertEqual(sizes(propose_trips([item(1),item(2,pause)])),[2])
            self.assertEqual(sizes(propose_trips([item(1,0,False,'nike'),item(2,pause,False,'nike')])),[2])
        self.assertEqual(sizes(propose_trips([item(1),item(2,91)])),[1,1])
        self.assertEqual(sizes(propose_trips([item(1,0,False,shoe_brand='Nike'),item(2,30,False,shoe_brand='Nike')])),[1,1])
        self.assertEqual(sizes(propose_trips([item(1,0,store='nike-192'),item(2,30,store='nike-idrive',gps={'latitude':11.,'longitude':-31.})])),[1,1])

    def test_unlocated_bundles_preserve_conflicts_and_known_device_boundaries(self):
        for change in ({'review_reasons':['duplicate_metadata_conflict']},
                       {'review_reasons':['gps_conflict']}, {'date_uncertain':True},
                       {'media_subtype':'screenshot'}):
            self.assertEqual(sizes(propose_trips([item(1,0,False,**change),item(2,2,False)])),[1,1])
        # An unknown stream between two known devices cannot bridge their boundary.
        records=[item(1,0,False),item(2,2,False,device_id=None),item(3,4,False,device_id='other')]
        self.assertEqual(sizes(propose_trips(records)),[2,1])
        records=[item(1,0,False),item(2,2,False,review_reasons=['duplicate_metadata_conflict']),item(3,4,False)]
        self.assertEqual(sizes(propose_trips(records)),[1,1,1])

    def test_inferences_never_anchor_more_inferences_and_window_is_bounded(self):
        r=propose_trips([item(1),item(2,5,False),item(3,5.01,False),item(4,10,False)])
        proposals={p['occurrence_id']:p for p in r['location_proposals']}
        self.assertEqual(proposals['2']['strength'],'one_sided_hint')
        self.assertEqual(proposals['3']['strength'],'unresolved');self.assertEqual(proposals['4']['strength'],'unresolved')
        self.assertEqual(proposals['2']['anchor_occurrence_ids'],['1'])

    def test_ties_device_identity_and_repeated_content_are_uncertain(self):
        r=propose_trips([item(1),item(2,0,False),item(3,0,store='jd')])
        self.assertEqual(r['location_proposals'][0]['strength'],'unresolved')
        self.assertIn('timestamp_tie_needs_review',r['location_proposals'][0]['reasons'])
        r=propose_trips([item(1,device_id=None),item(2,2,False,device_id=None),item(3,4,device_id=None)])
        self.assertIn('filename_device_stream_unknown',r['location_proposals'][0]['reasons'])
        r=propose_trips([item(1,device_id='other'),item(2,2,False),item(3,4,device_id='other')])
        self.assertEqual(r['location_proposals'][0]['strength'],'unresolved')
        r=propose_trips([item(1),item(2,2,False),item(3,4,media_id='1')])
        self.assertEqual(r['location_proposals'][0]['strength'],'one_sided_hint')

    def test_disputed_bad_dates_and_screenshots_cannot_supply_anchors(self):
        for change in ({'media_subtype':'screenshot'},{'review_reasons':['duplicate_metadata_conflict']},
                       {'date_uncertain':True},{'review_reasons':['gps_conflict']}):
            r=propose_trips([item(1,**change),item(2,2,False)])
            p=next(p for p in r['location_proposals'] if p['occurrence_id']=='2')
            self.assertEqual(p['strength'],'unresolved')
        r=propose_trips([item(1),item(2,2,False,media_subtype='screenshot')])
        self.assertEqual(r['location_proposals'],[])
        self.assertEqual(sizes(propose_trips([item(1),item(2,2,False,capture_utc=None)])),[1,1])

    def test_historical_and_account_context_do_not_leak(self):
        records=[item(1,0,store='nike'),item(2,2,False),item(3,4,store='nike')]
        for anchor in (records[0],records[2]):anchor['confirmed_context']['valid_to']='2019-12-31'
        p=propose_trips(records)['location_proposals'][0]
        self.assertIsNone(p['candidate_store_version_id'])
        records=[item(1,0,store='nike'),item(2,2,False,account_id='b'),item(3,4,store='nike')]
        p=propose_trips(records)['location_proposals'][0]
        self.assertEqual(p['strength'],'unresolved')
        records=[item(1,0,store='nike'),item(2,2,False),item(3,4,store='nike')]
        for a in (records[0],records[2]):a['confirmed_context']['active']=False
        self.assertIsNone(propose_trips(records)['location_proposals'][0]['candidate_store_version_id'])

    def test_truncation_and_filename_resets_cannot_hide_transitions(self):
        r=propose_trips([item(1),item(2,2,False,context_truncated=True),item(3,4)])
        self.assertEqual(r['location_proposals'][0]['strength'],'unresolved')
        self.assertIn('context_window_truncated',r['location_proposals'][0]['reasons'])
        r=propose_trips([item(1,filename='IMG_99999.JPG'),item(2,2,False,filename='IMG_00001.JPG'),item(3,4,filename='IMG_00002.JPG')])
        self.assertIn('filename_sequence_reset_or_disagreement',r['location_proposals'][0]['reasons'])
        # Gradual movement must not chain many short steps into one distant stop.
        r=propose_trips([item(1),item(2,2,gps={'latitude':10.001,'longitude':-30.}),item(3,4,gps={'latitude':10.002,'longitude':-30.})])
        self.assertEqual(sizes(r),[2,1])


class TripAdapterTests(unittest.TestCase):
    def test_adapter_is_read_only_and_cache_neighbors_are_labeled(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();d,_=fixture(root,4);out=root/'out'
            report=dry_run(d,out,'a','e',limit=1,as_of='2026-10-30')
            db=Manifest(out);oid=db.con.execute('SELECT occurrence_id FROM sample_members').fetchone()[0]
            result=db.result(oid)['result'];result['observed_gps']={'selected':None,'available':False};result['review_reasons']=['gps_missing']
            db.save_result(oid,'complete',result);db.close()
            path=out/'recovery.sqlite3';before=hashlib.sha256(path.read_bytes()).hexdigest()
            with (patch('sacc_takeout.importer.read_member',side_effect=AssertionError('No media reads')),
                  patch.object(Manifest,'save_result',side_effect=AssertionError('No mutations'))):
                summary=run_preview(out,report['batch_id'])
            self.assertEqual(summary['cached_neighbor_records'],3)
            self.assertEqual(summary['confirmed_assignments_created'],0)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            payload=json.loads((out/'reports'/report['batch_id']/'trip_preview.json').read_text())
            self.assertEqual(sum(r['context_source']=='registered_sidecar_cache' for r in payload['inputs']),3)
            truncated=run_preview(out,report['batch_id'],context_limit=1)
            self.assertTrue(truncated['context_truncated'])
            self.assertEqual(truncated['sample_location_opportunities'],{'unresolved':1})
            ro=ReadOnlyPreview(path)
            with self.assertRaises(sqlite3.OperationalError):ro.con.execute("DELETE FROM accounts")
            ro.close()
            with self.assertRaises(ValueError):run_preview(out,'unknown')
            with self.assertRaises(ValueError):run_preview(root/'missing','unknown')
            self.assertFalse((root/'missing').exists())
            db=Manifest(out)
            original=db.result(oid)['result']
            for corruption in ({'source_verified':False},{'source_sha256':'0'*64},{'account_id':'other'},{'media_id':'other'}):
                db.save_result(oid,'complete',{**original,**corruption})
                with self.assertRaises(ValueError):run_preview(out,report['batch_id'])
            db.save_result(oid,'complete',original);db.close()


if __name__=='__main__':unittest.main()
