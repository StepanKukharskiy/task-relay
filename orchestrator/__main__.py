"""Local-only interface; does not start or change the Telegram service."""
import argparse
import json
from pathlib import Path
import time

from .runtime import Runtime
from task_relay.relay_paths import PATHS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PATHS.runtime)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('import-file'); p.add_argument('path', type=Path); p.add_argument('--purpose', required=True)
    p = sub.add_parser('create'); p.add_argument('plan', type=Path)
    for name in ('replace-future', 'add-future'):
        p = sub.add_parser(name); p.add_argument('run'); p.add_argument('assignment', type=Path)
    p = sub.add_parser('template'); p.add_argument('name', choices=['competition','carousel','office-anime'])
    p.add_argument('--id', required=True); p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--model', required=True); p.add_argument('--reasoning', default='high')
    for name in ('status', 'tick', 'events', 'cancel'):
        sub.add_parser(name).add_argument('run')
    p = sub.add_parser('run'); p.add_argument('run'); p.add_argument('--seconds', type=int, default=1800)
    p = sub.add_parser('export'); p.add_argument('run'); p.add_argument('task'); p.add_argument('destination', type=Path)
    p = sub.add_parser('revise'); p.add_argument('run'); p.add_argument('task'); p.add_argument('--instruction', required=True)
    p = sub.add_parser('select'); p.add_argument('run'); p.add_argument('task'); p.add_argument('artifact')
    p.add_argument('--purpose', required=True); p.add_argument('--note', required=True)
    for name in ('artifact-lineage', 'artifact-impact'):
        p = sub.add_parser(name); p.add_argument('artifact')
        p.add_argument('--limit', type=int, default=100)
        if name == 'artifact-impact':
            p.add_argument('--replacement', help='Exact candidate ID to compare; does not select it')
    for name in ('replacement-preview','replace-selection'):
        p=sub.add_parser(name);p.add_argument('old_decision');p.add_argument('new_decision')
        if name=='replace-selection':
            p.add_argument('--revision',type=int,required=True);p.add_argument('--receipt',required=True);p.add_argument('--note',required=True)
    args = parser.parse_args(); runtime = Runtime(args.root)
    try:
        if args.command == 'template':
            from .templates import build
            result = build(args.name, args.id, json.loads(args.inputs.read_text()),
                           {'type':'codex-cli','model':args.model,'reasoning':args.reasoning})
        elif args.command == 'import-file':
            with runtime.transaction():
                result = {'artifact': runtime.register(args.path, args.purpose)}
        elif args.command == 'create':
            result = {'run': runtime.create(json.loads(args.plan.read_text()))}
        elif args.command == 'replace-future':
            runtime.replace_future(args.run, json.loads(args.assignment.read_text())); result = runtime.status(args.run)
        elif args.command == 'add-future':
            runtime.add_future(args.run, json.loads(args.assignment.read_text())); result = runtime.status(args.run)
        elif args.command == 'replacement-preview':
            from .artifact_replacements import preview
            result=preview(runtime,args.old_decision,args.new_decision)
        elif args.command == 'replace-selection':
            result=runtime.replace_selection(args.old_decision,args.new_decision,args.revision,args.receipt,args.note)
        elif args.command == 'artifact-lineage':
            result = runtime.artifact_lineage(args.artifact, args.limit)
        elif args.command == 'artifact-impact':
            result = runtime.artifact_impact(args.artifact, args.replacement, args.limit)
        elif args.command == 'status':
            result = runtime.status(args.run)
        elif args.command == 'export':
            result = runtime.export(args.run, args.task, args.destination)
        elif args.command == 'events':
            result = [dict(e) for e in runtime.db.execute('SELECT * FROM production_events WHERE run=? ORDER BY id', (args.run,))]
            for e in result:
                e['data'] = json.loads(e['data'])
        elif args.command == 'tick':
            result = runtime.tick(args.run)
        elif args.command == 'run':
            if not 1 <= args.seconds <= 7200:
                raise ValueError('Scheduler window must be 1–7200 seconds')
            until = time.monotonic() + args.seconds; previous = None
            while True:
                result = runtime.tick(args.run)
                compact = [(t['id'], t['status'], t['attempts']) for t in result['tasks']]
                if compact != previous:
                    print(json.dumps({'progress': compact}), flush=True); previous = compact
                if result['status'] != 'active' or time.monotonic() >= until:
                    break
                time.sleep(.5)
        elif args.command == 'cancel':
            runtime.cancel(args.run); result = runtime.status(args.run)
        elif args.command == 'revise':
            runtime.revise(args.run, args.task, args.instruction); result = runtime.status(args.run)
        else:
            runtime.select(args.run, args.task, args.artifact, args.purpose, args.note); result = runtime.status(args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    finally:
        runtime.db.close()


if __name__ == '__main__':
    main()
