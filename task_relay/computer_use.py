"""Native Safari diagnostics, selected worker targets and approved sessions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from . import computer_contract as contract


def write_new(path, value):
    raw = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with open(path, 'xb') as stream:
        os.chmod(path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def observe(helper, frozen, destination):
    """A new explicit diagnostic observation, not a registered Relay job.

    Exclusive intent prevents repeating an interrupted observation at the same
    destination. O15.2 will integrate authoritative assignment/action records.
    """
    folder = Path(destination).absolute()
    if folder.exists() or folder.is_symlink() or any(p.is_symlink() for p in folder.parents):
        raise ValueError('Choose a new observation directory; existing receipts are never replayed or overwritten.')
    folder.mkdir(mode=0o700, parents=True)
    write_new(folder / 'intent.json', {'schema': 'relay.computer-local-intent.v1',
              'created_at': datetime.now(timezone.utc).isoformat(), 'request': frozen,
              'request_sha256': contract.digest(frozen), 'helper': helper.identity,
              'scope': 'explicit local observation; not a production job'})
    try:
        raw = helper.call(frozen)
        data, png = contract.validate_response(raw, frozen)
        text = data.pop('text').encode()
        files = {'page.txt': text}
        if png is not None:
            files['viewport.png'] = png
        for name, content in files.items():
            write_new(folder / name, content)
        result = {'schema': 'relay.computer-local-evidence.v1', **data,
                  'request_sha256': contract.digest(frozen), 'helper': helper.identity,
                  'files': {name: {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
                            for name, content in files.items()},
                  'review_status': 'unreviewed', 'job_registered': False}
        write_new(folder / 'evidence.json', result)
        write_new(folder / 'completed.json', {'evidence_sha256': hashlib.sha256((folder / 'evidence.json').read_bytes()).hexdigest()})
        return result
    except BaseException:
        # Even a local read/capture may have occurred. Never repeat to repair it.
        write_new(folder / 'uncertain.json', {'status': 'incomplete', 'replay': 'prohibited',
                                             'reason': 'Observation or evidence publication did not finish; inspect existing receipts.'})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build', help='Explicitly compile and ad-hoc sign a new development helper')
    build.add_argument('--out', required=True)
    target_parser=sub.add_parser('worker-target',help='Select a foreground window and exact URL grant for subsequent planner-created workers')
    target_parser.add_argument('--helper',required=True)
    target_parser.add_argument('--spec-file',required=True)
    for name in ('status', 'windows', 'request-permissions', 'observe'):
        p = sub.add_parser(name)
        p.add_argument('--helper', required=True, help='Exact .app built by computer-use build')
        if name == 'observe':
            p.add_argument('--pid', required=True, type=int)
            p.add_argument('--launch-id', required=True)
            p.add_argument('--window-id', required=True, type=int)
            p.add_argument('--url', required=True, help='Exact expected active-document URL; this command does not navigate')
            p.add_argument('--request', required=True)
            p.add_argument('--out', required=True)
            p.add_argument('--capture', action='store_true')
            p.add_argument('--local-fixture', action='store_true', help='Allow loopback HTTP for a controlled page')
    for name in ('session-approve', 'session-run', 'session-inspect', 'session-pause',
                 'session-cancel', 'session-resume', 'session-stop'):
        p = sub.add_parser(name)
        p.add_argument('--database', required=True, help='Existing authoritative Relay database')
        if name == 'session-approve':
            for flag in ('job', 'request-key', 'request-file', 'spec-file', 'out', 'actor', 'helper'):
                p.add_argument('--' + flag, required=True)
        else:
            p.add_argument('--id', required=True)
        if name == 'session-run':
            p.add_argument('--helper', required=True)
        if name in ('session-pause', 'session-cancel', 'session-resume', 'session-stop'):
            p.add_argument('--actor', required=True)
            p.add_argument('--note', required=True)
        if name in ('session-resume', 'session-stop'):
            p.add_argument('--url', required=True, help='Exact current URL within the original grant')
    for name in ('evidence-export', 'evidence-inspect'):
        p = sub.add_parser(name, help='Saved evidence only; never opens a native helper')
        p.add_argument('--database', required=True)
        p.add_argument('--id', required=True, help='Assignment ID for export; pack ID for inspection')
        p.add_argument('--sync-job', action='store_true', help='Publish the committed pack in the existing .relay job view')
        if name == 'evidence-export':
            for flag in ('request-key', 'request-file', 'actor', 'out'):
                p.add_argument('--' + flag, required=True)
    p = sub.add_parser('evidence-verify', help='Verify a ZIP offline against its separately supplied SHA-256')
    p.add_argument('--file', required=True)
    p.add_argument('--sha256', required=True)
    for name in ('review-prepare','review-inspect','review-run','review-finish','review-stop'):
        p = sub.add_parser(name, help='Frozen saved-text review; no native browser actions')
        p.add_argument('--database', required=True)
        p.add_argument('--id', required=True, help='Pack ID for preparation; review ID otherwise')
        p.add_argument('--sync-job', action='store_true')
        if name == 'review-prepare':
            for flag in ('request-key','request-file','actor','model','claims-file'):
                p.add_argument('--'+flag, required=True)
            p.add_argument('--max-output-tokens', type=int, default=2048)
        if name == 'review-run':
            p.add_argument('--allow-provider-call', action='store_true', help='Authorize one billable Gemini call with the frozen text context and budget')
        if name == 'review-stop':
            p.add_argument('--actor', required=True)
            p.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    try:
        from .host_computer import Observer, build as build_helper, lease
        if args.command.startswith(('evidence-','review-')):
            result = evidence_command(args)
        elif args.command.startswith('session-'):
            result = session_command(args)
        elif args.command == 'worker-target':
            from .computer_target import select
            with lease():
                result=select(Observer(args.helper),json.loads(Path(args.spec_file).read_text()))
        elif args.command == 'build':
            result = build_helper(args.out)
        else:
            helper = Observer(args.helper)
            if args.command == 'observe':
                frozen = contract.request({'pid': args.pid, 'launch_id': args.launch_id,
                                           'window_id': args.window_id}, args.url, args.request,
                                          args.capture, args.local_fixture)
                with lease():
                    result = observe(helper, frozen, args.out)
            else:
                with lease():
                    result = helper.call({'protocol': contract.PROTOCOL, 'operation': args.command})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('ok') is False else 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)[:400]}))
        return 1


def evidence_command(args):
    import sqlite3
    from contextlib import closing
    from . import computer_evidence as packs
    if args.command == 'evidence-verify':
        return {'verified': True, 'manifest': packs.verify_bytes(packs._read(args.file), args.sha256)}
    path = Path(args.database).expanduser().absolute()
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Use an existing non-symlink authoritative Relay database.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as existing:
        if not existing.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_pipelines'").fetchone():
            raise ValueError('Database has no saved Relay jobs.')
    from .bridge import State
    from . import production_control, workflow_files
    from orchestrator.runtime import Runtime
    state = State(path)
    try:
        rt = Runtime(production_control.root(state), connection=state.db)
        if args.command.startswith('review-'):
            from . import computer_review as review
            ident = args.id
            if args.command == 'review-prepare':
                ident = review.prepare(rt, pack_id=ident, request_key=args.request_key,
                    exact_request=Path(args.request_file).read_text(), actor=args.actor, model=args.model,
                    max_tokens=args.max_output_tokens, claims=json.loads(Path(args.claims_file).read_text()))
            if args.command == 'review-run':
                saved = review._get(rt.db, ident)
                if saved['state'] == 'prepared':
                    if not args.allow_provider_call:
                        raise ValueError('Inspect the frozen review first; --allow-provider-call authorizes its one billable Gemini request.')
                    worker = review.GeminiReviewer(saved['model'], saved['max_tokens'])
                else:
                    worker = None  # Completed/received replies never need provider credentials.
                result = review.run(rt, ident, worker)
            elif args.command == 'review-finish': result = review.finish(rt, ident)
            elif args.command == 'review-stop': result = review.resolve(rt, ident, actor=args.actor, note=args.note)
            else: result = review.inspect(rt, ident)
        else:
            result = (packs.export(rt, assignment=args.id, request_key=args.request_key,
                    exact_request=Path(args.request_file).read_text(), actor=args.actor, destination=args.out)
                  if args.command == 'evidence-export' else packs.inspect(rt, args.id))
        if args.sync_job:
            state.channel = state.db.execute('SELECT channel FROM relay_pipelines WHERE id=?', (result['job'],)).fetchone()[0]
            try:
                workflow_files.sync(state, result['job'])
                result['job_view'] = {'status': 'published'}
            except Exception as exc:
                result['job_view'] = {'status': 'pending', 'error': str(exc)[:400],
                    'recovery': 'Repeat evidence-inspect --sync-job; the registered pack will not be recreated.'}
        return result
    finally:
        state.db.close()


def session_command(args):
    import sqlite3
    from orchestrator.storage import transaction
    from . import computer_sessions as sessions
    from .host_computer import Observer, lease
    path = Path(args.database).expanduser().absolute()
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Use an existing non-symlink authoritative Relay database.')
    # Opening read/write only never creates an auxiliary authority.
    db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_pipelines' AND type='table'").fetchone():
            raise ValueError('Database has no saved Relay jobs.')
        with transaction(db):
            sessions.initialize(db)
        if args.command == 'session-approve':
            ident = sessions.approve(db, job=args.job, request_key=args.request_key,
                exact_request=Path(args.request_file).read_text(), spec=json.loads(Path(args.spec_file).read_text()),
                helper=Observer(args.helper).identity, output_root=args.out, actor=args.actor)
        else:
            ident = args.id
        if args.command == 'session-run':
            with lease():
                return sessions.run(db, ident, Observer(args.helper))
        if args.command in ('session-pause', 'session-cancel'):
            sessions.control(db, ident, args.command.removeprefix('session-'), actor=args.actor, note=args.note)
        if args.command in ('session-resume', 'session-stop'):
            with lease():
                sessions.resume(db, ident, current_url=args.url, actor=args.actor, note=args.note,
                                abandon=args.command == 'session-stop')
        return sessions.inspect(db, ident)
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
