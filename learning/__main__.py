"""Local CLI. Reads/imports are local; analyze/evaluate explicitly submit evidence."""
import argparse
import json
import sys
from pathlib import Path
from .store import Store, DEFAULT_DB
from .importer import import_file
from .analyzer import analyze
from .proposals import card, decide, apply, revert, revise
from .evaluate import evaluate
from .continuity import update_state, export_context, review_state, correct_state


def analysis_options(parser):
    parser.add_argument('--backend', choices=['gemini'], default='gemini')
    parser.add_argument('--model')
    parser.add_argument('--max-calls', type=int, default=32)
    parser.add_argument('--max-input-chars', type=int, default=2000000)
    parser.add_argument('--max-output-tokens', type=int, default=8192)
    parser.add_argument('--context-chars', type=int, default=180000)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest='command', required=True)
    intake = commands.add_parser('import', help='Freeze only explicitly selected files; no model calls')
    intake.add_argument('--dataset', required=True)
    intake.add_argument('--workflow', required=True)
    intake.add_argument('--kind', choices=['conversation', 'ledger', 'guide'], required=True)
    intake.add_argument('files', nargs='+', type=Path)
    worker = commands.add_parser('analyze', help='Send selected evidence to configured Gemini in bounded calls')
    worker.add_argument('--dataset', required=True)
    worker.add_argument('--reuse-episodes', help='Incomplete run ID; reuse only identical successful episode requests')
    analysis_options(worker)
    review = commands.add_parser('review')
    review.add_argument('proposal_id')
    review.add_argument('--decision', choices=['accept', 'dismiss', 'keep', 'revise'])
    review.add_argument('--review-hash')
    review.add_argument('--note', default='')
    revision = commands.add_parser('revise', help='Create a new proposal version from a local JSON amendment; requires fresh review')
    revision.add_argument('proposal_id')
    revision.add_argument('--amendment', type=Path, required=True)
    revision.add_argument('--note', required=True)
    application = commands.add_parser('apply')
    application.add_argument('proposal_id')
    application.add_argument('--trial', required=True, type=Path, help='New isolated directory; must not exist')
    application.add_argument('--guide-path', help='Relative guide location within baseline/ and treatment/')
    rollback = commands.add_parser('revert')
    rollback.add_argument('application_id')
    rollback.add_argument('--note', default='')
    follow = commands.add_parser('evaluate')
    follow.add_argument('application_id')
    for name in ('dataset', 'job-id', 'workflow', 'mode', 'intervention-hash'):
        follow.add_argument('--' + name, required=True)
    follow.add_argument('--human-minutes', type=float)
    analysis_options(follow)
    status = commands.add_parser('status')
    status.add_argument('--dataset')
    status.add_argument('--run-id')
    show = commands.add_parser('show', help='Inspect an immutable evidence or lifecycle record')
    show.add_argument('table', choices=['sources', 'events', 'analysis_runs', 'findings', 'proposals', 'applications', 'evaluations', 'internal_jobs', 'continuity_states'])
    show.add_argument('id')
    cancel = commands.add_parser('cancel')
    cancel.add_argument('run_id')
    recover = commands.add_parser('recover-job', help='Mark an interrupted sending job uncertain, never resubmit it')
    recover.add_argument('job_id')
    maintenance = commands.add_parser('state-update', help='Propose scoped working state using the fixed continuity model')
    maintenance.add_argument('--project', required=True)
    maintenance.add_argument('--dataset', required=True)
    maintenance.add_argument('--previous')
    maintenance.add_argument('--jobs', type=Path, help='JSON object mapping known job IDs to workflows')
    maintenance.add_argument('--guides', type=Path, help='JSON list of imported guide source IDs and applicability scopes')
    maintenance.add_argument('--max-input-chars', type=int, default=120000)
    maintenance.add_argument('--max-output-tokens', type=int, default=8192)
    context = commands.add_parser('context-export', help='Write a portable TASK_CONTEXT.md for a specified next job')
    context.add_argument('state_id')
    context.add_argument('--job', required=True)
    context.add_argument('--workflow', required=True)
    context.add_argument('--directory', required=True, type=Path)
    state_review = commands.add_parser('state-review', help='Record state inspection and optional burden estimates')
    state_review.add_argument('state_id')
    state_review.add_argument('--note', required=True)
    state_review.add_argument('--metrics', type=Path)
    correction = commands.add_parser('state-correct', help='Preserve a separately labeled reviewer correction to working state')
    correction.add_argument('state_id')
    correction.add_argument('--correction', type=Path, required=True)
    correction.add_argument('--note', required=True)
    correction.add_argument('--metrics', type=Path)
    args = parser.parse_args(argv)
    store = Store(args.db)
    try:
        if args.command == 'import':
            result = [import_file(store, args.dataset, args.workflow, p, args.kind) for p in args.files]
        elif args.command in ('analyze', 'evaluate'):
            options = {k: getattr(args, k) for k in ('model', 'max_calls', 'max_input_chars', 'max_output_tokens', 'context_chars')}
            if args.command == 'analyze':
                result = analyze(store, args.dataset, reuse_episodes=args.reuse_episodes, **options)
            else:
                result = evaluate(store, args.application_id, args.dataset, args.job_id, args.workflow,
                                  args.mode, args.intervention_hash, args.human_minutes, **options)
        elif args.command == 'review':
            if args.decision:
                result = decide(store, args.proposal_id, args.decision, args.review_hash, args.note)
            else:
                print(card(store, args.proposal_id))
                return 0
        elif args.command == 'apply':
            result = apply(store, args.proposal_id, args.trial, args.guide_path)
        elif args.command == 'revise':
            result = revise(store, args.proposal_id, json.loads(args.amendment.read_text()), args.note)
        elif args.command == 'revert':
            result = revert(store, args.application_id, args.note)
        elif args.command == 'status':
            if args.run_id:
                result = store.get('analysis_runs', args.run_id)
                result['jobs'] = [dict(r) for r in store.db.execute(
                    'SELECT id,status,model,usage_json,error FROM internal_jobs WHERE owner_id=?', (args.run_id,))]
            else:
                result = {'sources': [{k: s[k] for k in ('id', 'path', 'sha256', 'kind', 'workflow')}
                                      for s in store.sources(args.dataset)] if args.dataset else [],
                          'runs': [dict(r) for r in store.db.execute('SELECT id,dataset,status,created_at FROM analysis_runs')],
                          'proposals': [dict(r) for r in store.db.execute('SELECT id,status FROM proposals')]}
        elif args.command == 'show':
            result = store.get(args.table, args.id)
            if 'raw' in result:
                result['raw'] = result['raw'].decode('utf-8')
        elif args.command == 'cancel':
            from task_relay import internal_jobs
            internal_jobs.cancel(store.db, args.run_id)
            result = {'run_id': args.run_id, 'cancel_requested': True}
        elif args.command == 'state-update':
            result = update_state(store, args.project, args.dataset, args.previous,
                                  json.loads(args.jobs.read_text()) if args.jobs else None,
                                  json.loads(args.guides.read_text()) if args.guides else None,
                                  args.max_input_chars, args.max_output_tokens)
        elif args.command == 'context-export':
            result = export_context(store, args.state_id, args.job, args.workflow, args.directory)
        elif args.command == 'state-review':
            review_state(store, args.state_id, args.note, json.loads(args.metrics.read_text()) if args.metrics else None)
            result = {'state_id': args.state_id, 'review_recorded': True}
        elif args.command == 'state-correct':
            result = correct_state(store, args.state_id, json.loads(args.correction.read_text()), args.note,
                                   json.loads(args.metrics.read_text()) if args.metrics else None)
        else:
            from task_relay import internal_jobs
            internal_jobs.recover(store.db, args.job_id)
            result = {'job_id': args.job_id, 'replayed': False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get('status') == 'incomplete' else 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
