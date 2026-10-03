"""Local administration of Relay work records; file grants never come from the model."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from . import work_state as ws, project_context as pc
from . import execution_results as results
from . import execution_capture as completion


def execution_command(db, args, request):
    if args.command == 'export-result':
        return results.export(db, args.project, args.key, args.path)
    path = Path(args.source_db).absolute()
    target = Path(db.execute('PRAGMA database_list').fetchone()[2])
    def run(source):
        if args.command == 'inspect-result':
            return results.inspect(source, args.kind, args.source_id, args.source_project)
        return results.capture(db, args.project, args.packet, source_db=source, kind=args.kind,
                               ident=args.source_id, source_project=args.source_project,
                               expected_sha256=args.sha256, request_key=args.key, request=request)
    if path.resolve() == target.resolve():
        return run(db)
    # Only the local caller can grant a source database; the MCP tools never
    # accept this argument or enumerate arbitrary production job records.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        return run(source)


def from_context(db, pid, source_database, run_id, request):
    path = Path(source_database).absolute()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        source.execute('BEGIN')
        run = pc.get(source, run_id)
        if run['status'] not in {'proposed', 'proposed_with_gaps'}:
            raise ValueError('Context analysis has not passed source coverage validation')
        original = json.loads(run['capture_json'])
        if pc.digest(pc.encoded(original).encode()) != run['capture_sha256']:
            raise ValueError('Saved context capture hash mismatch')
        capture = pc.model_evidence(original)
        proposal = json.loads(run['proposal_json'])
        # Recheck persisted memberships and citations, never call a provider.
        pc.validate(proposal, original)
        report = json.loads(source.execute('SELECT report_json FROM project_context_validation WHERE run_id=?', (run_id,)).fetchone()[0])
    prefix = 'import:' + ws.digest([run_id, run['capture_sha256']])[:16] + ':'
    ids = {s['id']: prefix + ws.digest(s['id'])[:24] for s in capture['sources']}
    topics = {s['id']: [] for s in capture['sources']}
    for topic in proposal['topics']:
        for sid in topic['source_ids']:
            topics[sid].append(topic['title'])
    rows = []
    def add(rid, kind, title, data):
        rows.append({'id': rid, 'kind': kind, 'title': title[:500], 'data': data})
    for item in capture['sources']:
        add(ids[item['id']], 'evidence', item.get('title') or item.get('path') or item['id'],
            {**item, 'refs': [], 'topics': topics[item['id']], 'run_id': run_id,
             'capture_sha256': run['capture_sha256']})
    paths = sorted({p for t in proposal['topics'] for p in t['artifact_paths']})
    for path in paths:
        file = next(f for f in capture['files'] if f['path'] == path)
        add(prefix + ws.digest(path)[:24], 'artifact', Path(path).name,
            {'path': path, 'family': path, 'version': 1, 'sha256': None,
             'bytes': file.get('bytes'), 'version_basis': 'single_captured_inventory_snapshot',
             'topics': [t['title'] for t in proposal['topics'] if path in t['artifact_paths']], 'refs': []})
    for topic in proposal['topics']:
        for index, claim in enumerate(topic['claims']):
            add(prefix + ws.digest([topic['id'], 'claim', index])[:24], 'decision', claim['statement'],
                {'text': claim['statement'], 'classification': claim['kind'], 'citations': claim['evidence'],
                 'refs': [ids[e['source_id']] for e in claim['evidence']], 'topics': [topic['title']]})
        for index, question in enumerate(topic['open_questions']):
            add(prefix + ws.digest([topic['id'], 'issue', index])[:24], 'issue', question,
                {'text': question, 'refs': [], 'topics': [topic['title']], 'basis': 'model_open_question'})
    for index, rejected in enumerate(report['rejected_claims']):
        add(prefix + ws.digest(['held', index])[:24], 'issue', 'Citation held for review',
            {'text': pc.encoded(rejected), 'refs': [], 'topics': [], 'basis': 'failed_citation_check'})
    receipt = ws.import_records(db, pid, {'schema': ws.SCHEMA, 'records': rows}, request)
    return {**receipt, 'source_run': run_id, 'source_capture_sha256': run['capture_sha256'], 'model_calls': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create'); p.add_argument('--title', required=True); p.add_argument('--request-file', required=True); p.add_argument('--root')
    for name in ('inspect-result', 'capture-execution', 'export-result'):
        p = sub.add_parser(name)
        if name != 'inspect-result':
            p.add_argument('--project', required=True); p.add_argument('--key', required=True)
        if name == 'export-result':
            p.add_argument('--path', required=True)
        else:
            p.add_argument('--source-db', required=True); p.add_argument('--kind', choices=results.KINDS, required=True)
            p.add_argument('--source-id', required=True); p.add_argument('--source-project')
        if name == 'capture-execution':
            p.add_argument('--packet', required=True); p.add_argument('--sha256', required=True); p.add_argument('--request-file', required=True)
    sub.add_parser('completion-status')
    p = sub.add_parser('recover-results'); p.add_argument('--limit', type=int, default=100)
    for name in ('bind-result', 'observe-result'):
        p = sub.add_parser(name)
        p.add_argument('--kind', choices=results.KINDS, required=True); p.add_argument('--source-id', required=True); p.add_argument('--source-project')
        if name == 'bind-result':
            p.add_argument('--project', required=True); p.add_argument('--packet', required=True)
            p.add_argument('--key', required=True); p.add_argument('--request-file', required=True)
    for name in ('import', 'import-context', 'inspect', 'graph', 'prepare', 'commit', 'continue', 'validate', 'recover-text'):
        p = sub.add_parser(name); p.add_argument('--project', required=True)
        if name in {'import', 'import-context', 'prepare', 'continue'}:
            p.add_argument('--request-file', required=True)
        if name == 'import': p.add_argument('--file', required=True)
        if name == 'import-context': p.add_argument('--context-db', required=True); p.add_argument('--run', required=True)
        if name == 'prepare': p.add_argument('--change-file', required=True); p.add_argument('--revision', type=int, required=True)
        if name == 'commit': p.add_argument('--review-file', required=True); p.add_argument('--confirm', action='store_true')
        if name == 'continue': p.add_argument('--revision', type=int, required=True); p.add_argument('--topic'); p.add_argument('--max-chars', type=int, default=60000)
        if name == 'validate': p.add_argument('--packet', required=True)
        if name == 'recover-text': p.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    request = Path(args.request_file).read_text() if hasattr(args, 'request_file') else None
    db = ws.connect(args.db)
    try:
        if args.command == 'create': result = {'project_id': ws.create(db, args.title, request, args.root)}
        elif args.command in {'inspect-result', 'capture-execution', 'export-result'}: result = execution_command(db, args, request)
        elif args.command == 'bind-result': result = completion.bind(db, args.project, args.packet, kind=args.kind, ident=args.source_id,
            source_project=args.source_project, request_key=args.key, request=request)
        elif args.command == 'observe-result': result = {'observation_id': completion.notify(db, args.kind, args.source_id, args.source_project), 'execution_dispatch': False}
        elif args.command == 'recover-results': result = completion.recover(db, args.limit)
        elif args.command == 'completion-status':
            with ws.transaction(db): completion.initialize(db); result = completion.status(db)
        elif args.command == 'import': result = ws.import_records(db, args.project, json.loads(Path(args.file).read_text()), request)
        elif args.command == 'import-context': result = from_context(db, args.project, args.context_db, args.run, request)
        elif args.command == 'inspect': result = ws.snapshot(db, args.project)
        elif args.command == 'graph': result = ws.graph(db, args.project)
        elif args.command == 'prepare': result = ws.prepare_change(db, args.project, args.revision, request, json.loads(Path(args.change_file).read_text()))
        elif args.command == 'commit':
            review = json.loads(Path(args.review_file).read_text())
            result = ws.commit_change(db, args.project, review['review_id'], review['confirmation_token'], args.confirm)
            if result.get('run_id'): result = ws.run_text(db, args.project, result['run_id'], recover=result.get('recover') is True)
        elif args.command == 'continue': result = ws.prepare_packet(db, args.project, args.revision, request, args.topic, args.max_chars)
        elif args.command == 'validate': result = ws.validate_packet(db, args.project, args.packet)
        else: result = ws.run_text(db, args.project, args.run, recover=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
