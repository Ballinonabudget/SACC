import json
from pathlib import Path
import tempfile
import unittest

from sacc_takeout.importer import dry_run, export_report
from sacc_takeout.manifest import Manifest
from sacc_takeout.review_policy import reviewed_result
from test_takeout_recovery import fixture


def decision(is_screenshot=True, **updates):
    return {'context_type':'screenshot_review','is_screenshot':is_screenshot,
            'reviewer':'fixture reviewer','evidence':'Locally reviewed screenshot', **updates}


class ScreenshotPolicyTests(unittest.TestCase):
    def test_exemption_is_explicit_image_only_and_preserves_other_evidence(self):
        raw={'review_reasons':['gps_missing','date_conflict','gps_invalid'],
             'observed_gps':{'available':False,'selected':None,'observations':[]},
             'privacy':'unknown','remote_eligible':False}
        before=json.dumps(raw,sort_keys=True)
        for kind,decisions in [('image',[]),('video',[{'id':'yes','payload':decision()}]),
                               ('image',[{'id':'invalid','payload':decision(is_screenshot='true')}])]:
            self.assertIn('gps_missing',reviewed_result(raw,kind,decisions)['review_reasons'])
        projected=reviewed_result(raw,'image',[{'id':'yes','payload':decision()}])
        self.assertEqual(projected['gps_requirement']['status'],'not_expected_screenshot')
        self.assertEqual(projected['review_reasons'],['date_conflict','gps_invalid'])
        self.assertEqual(projected['observed_gps'],raw['observed_gps'])
        self.assertFalse(projected['remote_eligible'])
        self.assertEqual(json.dumps(raw,sort_keys=True),before)
        existing=dict(raw,observed_gps={'available':True,'selected':{'latitude':10,'longitude':-30}},review_reasons=['gps_conflict'])
        projected=reviewed_result(existing,'image',[{'id':'yes','payload':decision()}])
        self.assertEqual(projected['observed_gps'],existing['observed_gps'])
        self.assertIn('gps_conflict',projected['review_reasons'])

    def test_report_projection_is_reversible_and_has_correct_denominators(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); discovery,_=fixture(root,1); out=root/'out'
            initial=dry_run(discovery,out,'a','b',as_of='2026-10-30');batch=initial['batch_id']
            db=Manifest(out)
            oid,mid=db.con.execute('SELECT id,media_id FROM occurrences').fetchone()
            raw=db.result(oid)['result']
            raw['review_reasons']=['gps_missing','date_conflict']
            raw['observed_gps']={'available':False,'selected':None,'observations':[]}
            db.save_result(oid,'complete',raw)
            original=db.result(oid)['result_json']
            for updates in ({'is_screenshot':1},{'reviewer':' '},{'evidence':''}):
                with self.assertRaises(ValueError):db.add_stage_result(mid,'local_context','screenshot-v1',decision(**updates))
            ids=[]
            for value in (True,False,True):
                ids.append(db.add_stage_result(mid,'local_context','screenshot-v1',decision(value)))
                report=export_report(db,batch)
                self.assertEqual(report['gps_expected_coverage']['denominator'],0 if value else 1)
                self.assertEqual(report['gps_expected_coverage']['selected'],0)
                self.assertEqual(report['gps_coverage']['denominator'],1)
                self.assertEqual(report['review_reasons'].get('gps_missing',0),0 if value else 1)
                self.assertEqual(report['review_reasons']['date_conflict'],1)
                self.assertEqual(db.result(oid)['result_json'],original)
            self.assertEqual(len(set(ids)),3)
            self.assertIsNone(report['gps_expected_coverage']['rate'])
            with db.con:
                db.con.execute('INSERT INTO stage_results(id,media_id,stage,version,payload_json) VALUES (?,?,?,?,?)',
                    ('malformed',mid,'local_context','legacy',json.dumps(decision(is_screenshot='false'))))
            report=export_report(db,batch)
            self.assertEqual(report['counts']['confirmed_screenshots_gps_exempt'],1)
            self.assertEqual(db.result(oid)['result_json'],original)
            csv=(out/'reports'/batch/'review.csv').read_text()
            self.assertIn('media_subtype,gps_requirement',csv)
            self.assertIn('not_expected_screenshot',csv)
            payload=json.loads((out/'reports'/batch/'sacc_payloads.jsonl').read_text())
            self.assertFalse(payload['live_import_eligible'])
            self.assertEqual(payload['recovery']['gps_requirement']['status'],'not_expected_screenshot')
            db.close()


if __name__=='__main__':unittest.main()
