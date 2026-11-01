#!/usr/bin/env python3
"""Explicit local catalogue setup and reversible organization commands."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sacc_takeout.library import LibraryDB


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db');s=p.add_subparsers(dest='command',required=True)
    init=s.add_parser('init');init.add_argument('--base-db')
    imp=s.add_parser('import');imp.add_argument('recovery_root')
    s.add_parser('status')
    pre=s.add_parser('preview');pre.add_argument('--filters',default='{}')
    apply=s.add_parser('apply');apply.add_argument('plan_dir');apply.add_argument('--approve-plan',required=True)
    roll=s.add_parser('rollback');roll.add_argument('plan_dir')
    args=p.parse_args();db=LibraryDB(args.db)
    if args.command=='init':result=db.initialize(args.base_db)
    elif args.command=='import':result=db.import_recovery(args.recovery_root,lambda n,t:print(f'Imported {n}/{t}',file=sys.stderr,flush=True))
    elif args.command=='status':result=db.status()
    else:
        from sacc_takeout.organization import create_plan,inspect_plan,apply_plan,rollback_plan,iter_outputs
        if args.command=='preview':result=create_plan(db.layout_rows(json.loads(args.filters)),db.path.parent.parent/'organized',db.path.parent.parent/'organization-plans',binding={'library_db':str(db.path)})
        else:
            plan=inspect_plan(args.plan_dir)
            if plan.get('binding',{}).get('library_db')!=str(db.path):raise ValueError('Plan belongs to a different catalogue')
            if args.command=='apply':
                if args.approve_plan!=plan['plan_id']:raise ValueError('Exact reviewed plan approval is required')
                result=apply_plan(args.plan_dir,approve=True,revision_check=db.revision_matches)
                db.sync_layout((e for e in iter_outputs(args.plan_dir) if e['state']=='published'),plan['plan_id'])
            else:
                def owns(row):
                    with db.connection() as c:
                        r=c.execute('SELECT organization_plan,organized_path FROM library_occurrences WHERE id=?',(row['id'],)).fetchone()
                        return bool(r and r['organization_plan']==plan['plan_id'] and r['organized_path']==str(row['target']))
                result=rollback_plan(args.plan_dir,ownership_check=owns)
                db.sync_layout((e for e in iter_outputs(args.plan_dir) if e['state']=='rolled_back'),plan['plan_id'],rollback=True)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
