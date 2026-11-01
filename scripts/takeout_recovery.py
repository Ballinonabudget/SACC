#!/usr/bin/env python3
"""Local Takeout recovery: bounded samples and explicitly approved resumable plans."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sacc_takeout.common import private_root, run_lock
from sacc_takeout.importer import dry_run, verify_copies, export_report
from sacc_takeout.locations import import_directory
from sacc_takeout.manifest import Manifest
from sacc_takeout.trip_preview import run_preview
from sacc_takeout.full_recovery import (create_plan,approve_plan,run_recovery,status,
                                       export_reports,refresh_reviews)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['dry-run', 'verify-copies', 'report', 'lookup', 'import-directory', 'compare','trip-preview',
        'full-plan','full-approve','full-run','full-status','full-report','full-refresh-reviews'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--discovery', type=Path)
    parser.add_argument('--account')
    parser.add_argument('--batch', help='Export label for dry-run; manifest batch ID for other commands')
    parser.add_argument('--old-batch')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--seed', type=int, default=20261029)
    parser.add_argument('--as-of', help='Date policy cutoff; defaults to initial run date and persists on resume')
    parser.add_argument('--query', default='')
    parser.add_argument('--neighbor-seconds',type=int,default=300)
    parser.add_argument('--context-limit',type=int,default=5000)
    parser.add_argument('--source-root',type=Path,help='Existing milestone output; never a live SACC database')
    parser.add_argument('--plan-id',help='Exact immutable plan ID, required for approvals/execution')
    parser.add_argument('--mode',choices=['pilot','full'],default='full')
    parser.add_argument('--source-kind',choices=['zip','sample'],default='zip')
    parser.add_argument('--max-files',type=int,default=12,help='Pilot selection cap, at most12')
    parser.add_argument('--max-bytes',type=int,default=128*1024**2,help='Pilot source-byte cap, at most128MiB')
    parser.add_argument('--max-items',type=int,help='Pause this invocation after this many item phases; selection stays fixed')
    parser.add_argument('--scope',choices=['pilot','full'],help='Approval/execution scope; never implied from mode')
    parser.add_argument('--reviewer')
    parser.add_argument('--evidence',help='Record the actual human approval; this flag does not obtain consent')
    args = parser.parse_args()
    if args.command.startswith('full-'):
        if args.command=='full-plan':
            if not args.source_root or not args.batch:
                parser.error('full-plan requires --source-root and manifest --batch')
            result=create_plan(args.source_root,args.batch,args.output,mode=args.mode,source_kind=args.source_kind,
                               max_files=args.max_files,max_bytes=args.max_bytes)
        elif args.command=='full-status':
            result=status(args.output,args.plan_id)
        else:
            if not args.plan_id:
                parser.error('This command requires the exact --plan-id')
            if args.command=='full-approve':
                if not all((args.scope,args.reviewer,args.evidence)):
                    parser.error('Approval requires --scope, --reviewer and actual human --evidence')
                result=approve_plan(args.output,args.plan_id,scope=args.scope,reviewer=args.reviewer,evidence=args.evidence)
            elif args.command=='full-run':
                if not args.scope:
                    parser.error('Execution requires explicit --scope pilot or full')
                last_stage=[None]
                def progress(event):
                    if event['stage']!=last_stage[0] or event['stage_completed']%100==0 or event['stage_completed']==event['total']:
                        print(json.dumps(event),file=sys.stderr,flush=True)
                    last_stage[0]=event['stage']
                result=run_recovery(args.output,args.plan_id,scope=args.scope,max_items=args.max_items,progress=progress)
            elif args.command=='full-report':
                result=export_reports(args.output,args.plan_id)
            else:
                if not args.source_root:
                    parser.error('Review refresh requires --source-root')
                result=refresh_reviews(args.source_root,args.output,args.plan_id)
    elif args.command == 'dry-run':
        if not args.discovery or not args.account or not args.batch:
            parser.error('dry-run requires --discovery, --account and --batch')
        last = [-1]
        def progress(event):
            done = event['prepared']+event['resumed']
            if done//20 != last[0]:
                print(json.dumps(event), file=sys.stderr, flush=True); last[0] = done//20
        result = dry_run(args.discovery, args.output, args.account, args.batch, args.limit, args.seed, args.as_of, progress)
    elif args.command == 'trip-preview':
        result=run_preview(args.output,args.batch,args.neighbor_seconds,args.context_limit)
    elif args.command == 'verify-copies':
        result = verify_copies(args.output, args.batch)
    else:
        root = private_root(args.output)
        with run_lock(root):
            db = Manifest(root)
            try:
                if args.command == 'report': result = export_report(db, args.batch)
                elif args.command == 'lookup': result = db.lookup(args.query, args.batch, args.limit)
                elif args.command == 'compare': result = db.compare_batches(args.old_batch, args.batch)
                else:
                    if not args.directory: parser.error('import-directory requires --directory')
                    import_directory(db, json.loads(args.directory.read_text()))
                    result = {'status': 'snapshot_imported_locally'}
            finally:
                db.close()
    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and result.get('counts', {}).get('error', 0):
        return 1
    if isinstance(result,dict) and (result.get('failed',0) or result.get('paused_reason')):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
