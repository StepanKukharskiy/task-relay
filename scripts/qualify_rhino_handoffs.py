#!/usr/bin/env python3
"""Real Rhino through controlled planning, recovery, selection and delivery adapters."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true',required=True,help='Explicitly run host code in real Rhino; no live providers or messages')
    parser.add_argument('--rhino-version',choices=('7','8'),required=True)
    parser.add_argument('--prepared-dir',type=Path,help='Explicit reviewed model.py/checks.json/render.json to execute instead of the fixed fixture')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    os.environ['TASK_RELAY_RHINO_VERSION']=args.rhino_version
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
    from tests.test_rhino_handoffs import Tests
    from task_relay.rhino_host import run as real_host
    from task_relay.host_apps import rhino
    from orchestrator.runtime import file_hash
    from orchestrator.rhino_contract import validate_checks,validate_render
    app=rhino()
    if not app['available']:raise ValueError(app['evidence'])
    prepared=None
    if args.prepared_dir:
        source=args.prepared_dir.resolve()
        prepared=((source/'model.py').read_text(),validate_checks(json.loads((source/'checks.json').read_text())),
                  validate_render(json.loads((source/'render.json').read_text())))
        frozen=folder/'prepared';shutil.copytree(source,frozen)
    class HostTest(Tests):
        def fake_host(self,*params):
            request=json.loads(Path(params[2]).read_text())
            print('Rhino '+args.rhino_version+' '+request['mode']+': starting',flush=True)
            result=real_host(*params)
            print('Rhino '+args.rhino_version+' '+request['mode']+': '+str(result.get('passed')),flush=True)
            return result
        def prepared_files(self):return prepared or super().prepared_files()
    test=HostTest('test_blocked_recovery_selection_set_model_render_review_and_delivery')
    record=dict(started=time.time(),command=sys.argv,application=app,
        scope='Real Rhino host. Scripted planner/producer/reviewer responses, explicit fixture selections and fake Telegram receipts. No live provider judgment or channel sends.',passed=False)
    test.setUp();test.signature.stop();test.app.stop()
    try:
        test.test_blocked_recovery_selection_set_model_render_review_and_delivery()
        record['passed']=True
    except Exception:record['error']=traceback.format_exc();print(record['error'],flush=True)
    finally:
        record['calls']=len(test.factory.calls)
        record['outputs']=[]
        for run,tid in (('production-3','app'),('production-4','app')):
            task=test.rt.task(run,tid) if test.state.db.execute('SELECT 1 FROM production_tasks WHERE run=? AND id=?',(run,tid)).fetchone() else None
            if task and task['latest']:
                ws=Path(test.factory.sessions[task['latest']]['frozen']['workspace'])/'delivery'
                if ws.exists():
                    destination=folder/('model' if run=='production-3' else 'render');shutil.copytree(ws,destination)
                    record['outputs'].extend({'path':str(p),'sha256':file_hash(p)} for p in destination.iterdir() if p.is_file())
        test.state.db.commit();test.state.db.execute('PRAGMA wal_checkpoint(FULL)')
        shutil.copytree(test.root,folder/'controlled-state')
        record['finished']=time.time();(folder/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
        test.tearDown()
    print(str(folder/'summary.json'),flush=True)
    return 0 if record['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
