"""Index exact saved prompts, model outputs and Relay reactions without dispatch."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orchestrator.execution_audit import export

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--workers',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run');group.add_argument('--run-prefix')
    args=parser.parse_args()
    if args.run:runs=[args.run]
    else:
        with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            runs=[r[0] for r in db.execute('SELECT id FROM production_runs ORDER BY id') if r[0].startswith(args.run_prefix)]
    records=[]
    for run in runs:
        if Path(run).name!=run:raise ValueError('Invalid run path')
        records.append(export(args.database,args.workers,run,args.output/run))
    args.output.mkdir(parents=True,exist_ok=True)
    all_records=[json.loads(p.read_text()) for p in sorted(args.output.glob('*/SUMMARY.json'))]
    (args.output/'INDEX.md').write_text('# Saved execution audits\n\nPrompts, model responses, Relay tool reactions and controller events. Original journals remain authoritative.\n\n'+'\n'.join('- ['+r['run']+'](<'+r['markdown']+'>) — '+str(r['attempts'])+' attempts, '+str(r['exchanges'])+' exchanges' for r in all_records)+'\n')
    print(json.dumps(records))

if __name__=='__main__':main()
