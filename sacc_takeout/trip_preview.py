"""Read-only, evidence-linked trip/stop proposals. Never writes measured GPS."""
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import csv
import io
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3

from .common import atomic_text, canonical, child, finite, private_root, run_lock, token
from .manifest import SCHEMA
from .metadata import capture_proposal, gps_proposal, distance_m, parse_date
from .locations import active_assignments
from .review_policy import reviewed_result

VERSION = 'trip-preview-v1'
DEFAULTS = {'neighbor_seconds':300, 'stop_pause_seconds':300, 'continuity_seconds':5400,
            'trip_gap_seconds':10800, 'trip_span_seconds':43200, 'movement_m':150}
BAD = {'gps_conflict','gps_invalid','gps_conflicting_reference','date_conflict','invalid_photo_taken_time',
       'invalid_embedded_date','suspicious_capture_date','selected_timezone_unknown','duplicate_metadata_conflict',
       'ambiguous_sidecar','missing_sidecar','embedded_read_error','detected_media_type_mismatch'}


def sequence(name):
    match = re.search(r'(?:^|_)IMG[_ -]?(\d{4,6})(?=\D|$)', PurePosixPath(name).name, re.I)
    return int(match[1]) if match else None


def observed(point):
    return bool(isinstance(point,dict) and finite(point.get('latitude')) and finite(point.get('longitude'))
                and -90<=point['latitude']<=90 and -180<=point['longitude']<=180
                and (point['latitude']!=0 or point['longitude']!=0))


def branch(record, when):
    c = record.get('confirmed_context')
    if not isinstance(c,dict) or c.get('active') is not True or not c.get('confirmation_id') or not c.get('store_version_id'):
        return None
    if c.get('account_id') != record.get('account_id') or not when:
        return None
    day = when.date().isoformat()
    if not c.get('valid_from') and not c.get('historical_evidence'):
        return None
    if (c.get('valid_from') and day<c['valid_from']) or (c.get('valid_to') and day>c['valid_to']):
        return None
    return c


def propose_trips(records, config=None):
    policy = {**DEFAULTS, **(config or {})}
    if set(policy)!=set(DEFAULTS) or any(not finite(v) or v<=0 for v in policy.values()):
        raise ValueError('Invalid trip-preview policy')
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Duplicate occurrence identity in preview')
    prepared=[]
    for source in records:
        r=dict(source); dt=parse_date(r.get('capture_utc'))
        r['_time']=dt.astimezone(timezone.utc) if dt and dt.tzinfo and not r.get('date_uncertain') else None
        r['_gps']=r.get('gps') if observed(r.get('gps')) and not (set(r.get('review_reasons',[])) & BAD) and r.get('media_subtype')!='screenshot' else None
        r['_branch']=branch(r,r['_time']) if not (set(r.get('review_reasons',[])) & BAD) and r.get('media_subtype')!='screenshot' else None
        r['_seq']=sequence(r.get('filename',''))
        prepared.append(r)
    prepared.sort(key=lambda r:(r.get('account_id',''),r['_time'] is None,r['_time'] or datetime.max.replace(tzinfo=timezone.utc),r['_seq'] if r['_seq'] is not None else -1,r['id']))
    anchors=[r for r in prepared if r['_time'] and (r['_gps'] or r['_branch'])]
    suggestions={}
    for r in prepared:
        if r['_gps'] or r.get('media_subtype')=='screenshot':
            continue
        reasons=[]; selected=[]; candidate=None; strength='unresolved'
        if r['_branch'] and not r.get('context_truncated'):
            suggestions[r['id']]={'occurrence_id':r['id'],'status':'needs_review','strength':'confirmed_context_reference',
                'candidate_store_version_id':r['_branch']['store_version_id'],'anchor_occurrence_ids':[r['id']],
                'anchor_confirmation_ids':[r['_branch']['confirmation_id']],'reasons':['existing_confirmed_context_not_new_assignment']}
            continue
        if not r['_time']:
            reasons=['capture_date_uncertain']
        elif r.get('context_truncated'):
            reasons=['context_window_truncated']
        elif set(r.get('review_reasons',[])) & BAD:
            reasons=['conflicting_source_evidence']
        else:
            nearby=[a for a in anchors if a['account_id']==r['account_id'] and
                    abs((a['_time']-r['_time']).total_seconds())<=policy['neighbor_seconds']
                    and (a['_gps'] or branch(a,r['_time']))]
            # Known different devices cannot establish a filename capture stream;
            # GPS/time may still be inspected but do not infer across them.
            nearby=[a for a in nearby if not (r.get('device_id') and a.get('device_id') and r['device_id']!=a['device_id'])]
            ties=[a for a in nearby if a['_time']==r['_time']]
            left=[a for a in nearby if a['_time']<r['_time']]
            right=[a for a in nearby if a['_time']>r['_time']]
            if ties:
                reasons=['timestamp_tie_needs_review']
            else:
                lt=max((a['_time'] for a in left),default=None); rt=min((a['_time'] for a in right),default=None)
                selected=[a for a in left if a['_time']==lt]+[a for a in right if a['_time']==rt]
                # Several album occurrences with a known hash are one evidence item.
                raw_selected=list(selected)
                unique={}
                for a in selected:unique.setdefault(a.get('media_id') or a['id'],a)
                selected=list(unique.values())
                versions={a['_branch']['store_version_id'] for a in raw_selected if a['_branch']}
                movement=any(a['_gps'] and b['_gps'] and distance_m(a['_gps'],b['_gps'])>policy['movement_m'] for i,a in enumerate(raw_selected) for b in raw_selected[i+1:])
                streams={a.get('device_id') for a in selected if a.get('device_id')}
                lo=min([r['_time'],*(a['_time'] for a in selected)]);hi=max([r['_time'],*(a['_time'] for a in selected)])
                intervening={a['_branch']['store_version_id'] for a in prepared if a['_time'] and a['_branch']
                    and a['account_id']==r['account_id'] and lo<=a['_time']<=hi}
                if len(intervening|versions)>1:
                    reasons=['intervening_confirmed_store_boundary']
                elif movement or len(versions)>1 or len(streams)>1:
                    reasons=['conflicting_neighbor_anchors']
                elif not selected:
                    reasons=['no_observed_gps_anchor_in_window']
                else:
                    sides={-1 if a['_time']<r['_time'] else 1 for a in selected}
                    strength='compatible_bracketing' if sides=={-1,1} else 'one_sided_hint'
                    reasons=[strength]
                    if strength=='compatible_bracketing':
                        before=[a for a in selected if a['_time']<r['_time']]
                        after=[a for a in selected if a['_time']>r['_time']]
                        def compatible(a,b):
                            aa,bb=branch(a,r['_time']),branch(b,r['_time'])
                            return bool((a['_gps'] and b['_gps'] and distance_m(a['_gps'],b['_gps'])<=policy['movement_m'])
                                or (aa and bb and aa['store_version_id']==bb['store_version_id']))
                        if not all(compatible(a,b) for a in before for b in after):
                            strength='unresolved';reasons=['neighbor_evidence_incomparable']
                    if any(a['_branch'] and not a['_gps'] for a in selected):
                        reasons.append('confirmed_branch_context_without_measured_gps')
                    if any(a.get('context_source')=='registered_sidecar_cache' for a in selected):
                        reasons.append('cached_context_not_media_verified')
                    if any(not a.get('device_id') or not r.get('device_id') for a in selected):
                        reasons.append('filename_device_stream_unknown')
                    for a in selected:
                        if a.get('device_id') and a.get('device_id')==r.get('device_id') and a['_seq'] is not None and r['_seq'] is not None:
                            delta=(r['_seq']-a['_seq'])*(1 if a['_time']<r['_time'] else -1)
                            reasons.append('filename_sequence_supports_order' if 0<delta<=100 else 'filename_sequence_reset_or_disagreement')
                    valid_branches=[branch(a,r['_time']) for a in selected]
                    valid_branches=[b for b in valid_branches if b]
                    if strength=='compatible_bracketing' and len(versions)==1 and valid_branches:
                        candidate=valid_branches[0]['store_version_id']
        suggestions[r['id']]={'occurrence_id':r['id'],'status':'needs_review','strength':strength,
                              'candidate_store_version_id':candidate,'anchor_occurrence_ids':[a['id'] for a in selected],
                              'anchor_confirmation_ids':sorted({a['_branch']['confirmation_id'] for a in selected if a['_branch']}),
                              'reasons':sorted(set(reasons))}
    trips=[]; stop=None; previous=None; trip=None
    for r in prepared:
        when=r['_time']; prior=previous['_time'] if previous else None
        gap=(when-prior).total_seconds() if when and prior else None
        new_trip=not trip or not when or not prior or r['account_id']!=previous['account_id'] or gap>policy['trip_gap_seconds'] or (when-trip['_start']).total_seconds()>policy['trip_span_seconds']
        if new_trip:
            trip={'trip_id':token(VERSION,'trip',r['account_id'],r['id']),'account_id':r['account_id'],'stops':[],'_start':when}
            trips.append(trip);stop=None
        suggestion=suggestions.get(r['id'],{})
        boundary = suggestion.get('strength')=='unresolved' and r.get('media_subtype')!='screenshot' and not r['_gps']
        previous_boundary=previous and suggestions.get(previous['id'],{}).get('strength')=='unresolved' and previous.get('media_subtype')!='screenshot' and not previous['_gps']
        weak_unlocated_join=bool(stop and gap is not None and gap<=policy['stop_pause_seconds']
            and when and prior and not r['_gps'] and not r['_branch']
            and all(not a['_gps'] and not a['_branch'] and a['_time']
                    and not (set(a.get('review_reasons',[])) & BAD)
                    and suggestions.get(a['id'],{}).get('strength')=='unresolved'
                    and suggestions.get(a['id'],{}).get('reasons')==['no_observed_gps_anchor_in_window']
                    for a in stop['_records'])
            and suggestion.get('reasons')==['no_observed_gps_anchor_in_window']
            and len({a['device_id'] for a in [*stop['_records'],r] if a.get('device_id')})<=1
            and not (set(r.get('review_reasons',[])) & BAD))
        if weak_unlocated_join:
            boundary=False;previous_boundary=False
            stop['reasons'].append('unlocated_temporal_bundle_not_store_evidence')
            if not r.get('device_id') or not previous.get('device_id'):stop['reasons'].append('capture_device_stream_unknown')
        versions={a['_branch']['store_version_id'] for a in stop['_records'] if a['_branch']} if stop else set()
        gps_points=[a['_gps'] for a in stop['_records'] if a['_gps']] if stop else []
        latest_gps=gps_points[-1] if gps_points else None
        gps_jump=bool(r['_gps'] and any(distance_m(gps,r['_gps'])>policy['movement_m'] for gps in gps_points))
        changed_branch=bool(r['_branch'] and versions and r['_branch']['store_version_id'] not in versions)
        stable_gps=bool(latest_gps and r['_gps'] and not gps_jump)
        stable_branch=bool(r['_branch'] and versions=={r['_branch']['store_version_id']})
        duration=(when-stop['_records'][0]['_time']).total_seconds() if stop and when and stop['_records'][0]['_time'] else None
        pause_ok=bool(gap is not None and (gap<=policy['stop_pause_seconds'] or
                    (gap<=policy['continuity_seconds'] and (stable_gps or stable_branch))))
        split=not stop or boundary or previous_boundary or gps_jump or changed_branch or not pause_ok or (duration is not None and duration>policy['continuity_seconds'])
        if split:
            why=['initial_or_uncertain_boundary']
            if gps_jump:why=['observed_gps_movement']
            elif changed_branch:why=['confirmed_store_transition']
            elif stop and not pause_ok:why=['pause_without_positive_continuity']
            stop={'stop_id':token(VERSION,'stop',r['account_id'],r['id']),'status':'needs_review','reasons':why,'_records':[]}
            trip['stops'].append(stop)
        elif gap>policy['stop_pause_seconds']:
            stop['reasons'].append('long_pause_supported_by_gps_or_confirmed_branch')
        if r.get('context_source')=='registered_sidecar_cache':stop['reasons'].append('contains_unverified_cached_context')
        stop['_records'].append(r);previous=r
    for t in trips:
        t.pop('_start')
        for s in t['stops']:
            members=s.pop('_records');times=[r['_time'].isoformat() for r in members if r['_time']]
            s.update({'occurrence_ids':[r['id'] for r in members],'start_utc':min(times) if times else None,
                      'end_utc':max(times) if times else None,'first_filename':members[0].get('filename'),
                      'last_filename':members[-1].get('filename'),'photos':sum(r.get('media_type')=='image' for r in members),
                      'videos':sum(r.get('media_type')=='video' for r in members),
                      'missing_gps':sum(not observed(r.get('gps')) and r.get('media_subtype')!='screenshot' for r in members),
                      'screenshots_gps_not_expected':sum(r.get('media_subtype')=='screenshot' for r in members),
                      'supporting_store_version_ids':sorted({r['_branch']['store_version_id'] for r in members if r['_branch']}),
                      'reasons':sorted(set(s['reasons']))})
    return {'version':VERSION,'policy':policy,'trips':trips,'location_proposals':list(suggestions.values())}


class ReadOnlyPreview:
    """Only the query interface needed by existing active-assignment validation."""
    def __init__(self,path):
        path=Path(path).resolve(strict=True)
        self.con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        self.con.row_factory=sqlite3.Row
        try:
            self.con.execute('PRAGMA query_only=ON')
            tables={r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            required=set(re.findall(r'CREATE (?:TABLE|VIEW) (\w+)',SCHEMA))
            if not required<=tables or [tuple(r) for r in self.con.execute('SELECT version,name FROM recovery_schema')]!=[(1,'sacc_takeout_recovery')]:
                raise ValueError('Missing or incompatible recovery manifest')
            self.con.execute('BEGIN')
        except Exception:
            self.con.close();raise

    def close(self):self.con.close()


def confirmed_context(db,media_id,account):
    if not media_id:return None
    assignments=active_assignments(db,media_id)
    if len({a['store_version_id'] for a in assignments})!=1:return None
    if not assignments:return None
    a=assignments[0]
    row=db.con.execute('''SELECT s.valid_from,s.valid_to,c.payload_json FROM store_versions s
        JOIN confirmations c ON c.store_version_id=s.id WHERE c.id=?''',(a['confirmation_id'],)).fetchone()
    payload=json.loads(row['payload_json'])
    return {'store_version_id':a['store_version_id'],'confirmation_id':a['confirmation_id'],'active':True,
            'account_id':account,'valid_from':row['valid_from'],'valid_to':row['valid_to'],
            'historical_evidence':payload.get('historical_evidence')}


def sample_record(db,row,account):
    result=json.loads(row['result_json'])
    sha=result.get('source_sha256')
    if not (result.get('source_verified') is True and isinstance(sha,str) and re.fullmatch('[0-9a-f]{64}',sha)
            and sha==row['linked_sha256'] and row['linked_account_id']==account
            and result.get('account_id')==account and result.get('media_id')==row['media_id']
            and row['media_id']==token('media',account,sha)
            and row['media_type']==row['linked_media_type'] and row['size_bytes']==row['linked_size_bytes']):
        raise ValueError('Completed sample lacks consistent recorded source-verification provenance')
    decisions=[]
    for d in db.con.execute("SELECT id,payload_json FROM stage_results WHERE media_id=? AND stage='local_context' ORDER BY rowid DESC",(row['media_id'],)):
        try:decisions.append({'id':d['id'],'payload':json.loads(d['payload_json'])})
        except ValueError:continue
    r=reviewed_result(result,row['media_type'],decisions)
    capture=r.get('capture',{});selected=capture.get('selected') or {}
    return {'id':row['id'],'media_id':row['media_id'],'account_id':account,'filename':row['member'],
            'media_type':row['media_type'],'capture_utc':selected.get('utc'),
            'date_uncertain':not capture.get('safe_to_embed'),'gps':r.get('observed_gps',{}).get('selected'),
            'review_reasons':r.get('review_reasons',[]),'media_subtype':r['media_subtype'],'device_id':None,
            'context_source':'verified_sample','confirmed_context':confirmed_context(db,row['media_id'],account)}


def manifest_records(db,batch,neighbor_seconds=300,context_limit=5000):
    if type(context_limit) is not int or not 0<=context_limit<=5000:
        raise ValueError('Context cap must be 0..5000')
    batch_row=db.con.execute('SELECT * FROM batches WHERE id=?',(batch,)).fetchone()
    if not batch_row:raise ValueError('Unknown manifest batch ID')
    config=json.loads(batch_row['config_json']);account=batch_row['account_id']
    rows=list(db.con.execute('''SELECT o.*,r.result_json,m.sha256 AS linked_sha256,m.account_id AS linked_account_id,
        m.media_type AS linked_media_type,m.size_bytes AS linked_size_bytes
        FROM sample_members s JOIN occurrences o ON o.id=s.occurrence_id
        JOIN recovery_results r ON r.occurrence_id=o.id LEFT JOIN media m ON m.id=o.media_id
        WHERE s.batch_id=? AND r.state='complete' ORDER BY s.ordinal''',(batch,)))
    records=[sample_record(db,r,account) for r in rows]
    targets=[r for r in records if not r['gps'] and not r['date_uncertain'] and r['media_subtype']!='screenshot']
    epochs=[int(parse_date(r['capture_utc']).timestamp()) for r in targets if parse_date(r['capture_utc'])]
    cached=[];truncated=False
    if epochs:
        expr="CAST(json_extract(o.match_json,'$.cached_document.photoTakenTime.timestamp') AS INTEGER)"
        conditions=' OR '.join(expr+' BETWEEN ? AND ?' for _ in epochs)
        params=[v for epoch in epochs for v in (epoch-neighbor_seconds,epoch+neighbor_seconds)]
        cached=list(db.con.execute("SELECT o.* FROM occurrences o WHERE o.batch_id=? AND o.media_type IN ('image','video') "
            "AND json_extract(o.match_json,'$.status')='matched' AND o.id NOT IN (SELECT occurrence_id FROM sample_members WHERE batch_id=?) AND ("+
            conditions+") ORDER BY "+expr+",o.id LIMIT ?",[batch,batch,*params,context_limit+1]))
        truncated=len(cached)>context_limit;cached=cached[:context_limit]
    for row in cached:
        doc=json.loads(row['match_json'])['cached_document']
        capture,date_issues=capture_proposal(doc,{},None,date.fromisoformat(config['as_of']))
        gps,gps_issues=gps_proposal(doc,{},config['gps_tolerance_m'])
        records.append({'id':row['id'],'media_id':row['media_id'],'account_id':account,'filename':row['member'],
            'media_type':row['media_type'],'capture_utc':(capture.get('selected') or {}).get('utc'),
            'date_uncertain':not capture['safe_to_embed'],'gps':gps['selected'],'review_reasons':sorted(set(date_issues+gps_issues)),
            'media_subtype':'unspecified','device_id':None,'context_source':'registered_sidecar_cache',
            'confirmed_context':None})
    if truncated:
        # Conservative global abstention avoids pretending the capped prefix is complete.
        for r in records:r['context_truncated']=True
    return records,{'verified_sample_records':len(rows),'sample_missing_gps':sum(not r['gps'] for r in records[:len(rows)]),
                    'eligible_missing_gps_targets':len(targets),'cached_neighbor_records':len(cached),
                    'context_limit':context_limit,'context_truncated':truncated,
                    'truncated_target_ids':[r['id'] for r in targets] if truncated else []}


def run_preview(output,batch,neighbor_seconds=300,context_limit=5000):
    if not finite(neighbor_seconds) or neighbor_seconds<=0 or neighbor_seconds>3600:
        raise ValueError('Neighbor window must be positive and at most one hour')
    manifest=Path(output).expanduser()/'recovery.sqlite3'
    if not manifest.is_file():raise ValueError('Existing recovery manifest required')
    root=private_root(output)
    with run_lock(root):
        db=ReadOnlyPreview(child(root,'recovery.sqlite3'))
        try:records,scope=manifest_records(db,batch,neighbor_seconds,context_limit)
        finally:db.close()
        preview=propose_trips(records,{'neighbor_seconds':neighbor_seconds})
        preview.update({'batch_id':batch,'scope':scope,'inputs':records})
        sample_target_ids={r['id'] for r in records if r['context_source']=='verified_sample' and not r.get('gps') and r.get('media_subtype')!='screenshot'}
        target_proposals=[p for p in preview['location_proposals'] if p['occurrence_id'] in sample_target_ids]
        summary={k:v for k,v in scope.items() if k!='truncated_target_ids'}
        summary.update({'version':VERSION,'batch_id':batch,'input_records':len(records),'trips':len(preview['trips']),
            'stops':sum(len(t['stops']) for t in preview['trips']),
            'sample_location_opportunities':dict(Counter(p['strength'] for p in target_proposals)),
            'sample_unresolved_reasons':dict(Counter(reason for p in target_proposals if p['strength']=='unresolved' for reason in p['reasons'])),
            'confirmed_assignments_created':0,'observed_gps_written':0,'media_extracted_or_rewritten':0,
            'real_branch_accuracy':None,'status':'proposal_only_needs_review','neighbor_window_seconds':neighbor_seconds})
        directory=child(root,'reports',batch)
        atomic_text(child(directory,'trip_preview.json'),json.dumps(preview,indent=2)+'\n')
        atomic_text(child(directory,'trip_summary.json'),json.dumps(summary,indent=2)+'\n')
        text=io.StringIO();fields=['trip','stop','start_utc','end_utc','photos','videos','missing_gps','screenshots_gps_not_expected',
                                 'first_filename','last_filename','supporting_store_version_ids','review_reasons']
        writer=csv.DictWriter(text,fieldnames=fields);writer.writeheader()
        for i,t in enumerate(preview['trips'],1):
            for j,s in enumerate(t['stops'],1):
                row={k:s.get(k) for k in fields};row.update(trip=i,stop=j,
                    supporting_store_version_ids='; '.join(s['supporting_store_version_ids']),review_reasons='; '.join(s['reasons']))
                writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
        atomic_text(child(directory,'trip_preview.csv'),text.getvalue())
        atomic_text(child(directory,'trip_summary.md'),'# Trip and stop preview\n\n'+
            f"{len(records)} metadata records: {scope['verified_sample_records']} verified sample, {scope['cached_neighbor_records']} cached neighbors.\n\n"+
            f"{summary['trips']} proposed trips and {summary['stops']} proposed stops.\n\n"+
            'All proposals need review. Cached neighbors are not media-verified. No camera GPS, store assignments, source media or database records were changed.\n')
        return summary
