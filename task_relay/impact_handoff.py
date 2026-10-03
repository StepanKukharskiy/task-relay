"""Model-neutral, immutable handoffs for reviewed change impact plans.

The authoritative record contains the exact request and the plan seen by an
agent. Recording or reading it never approves a revision or dispatches work.
"""

import hashlib
import json
from pathlib import Path
import time
import uuid

from orchestrator.storage import transaction


SCHEMA = 'task-relay.impact-handoff'
VERSION = 1
NATIVE_WITHDRAWAL = 'native_subject_withdrawal'
NATIVE_REPLACEMENT = 'native_subject_replacement'
XLSX_FACT_CHANGE = 'xlsx_fact_change'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relay_impact_handoffs(
        id TEXT PRIMARY KEY, job TEXT NOT NULL, request_key TEXT NOT NULL,
        exact_request TEXT NOT NULL, kind TEXT NOT NULL, baseline_artifact TEXT NOT NULL,
        inputs TEXT NOT NULL,
        plan_digest TEXT NOT NULL, plan TEXT NOT NULL, actor TEXT NOT NULL,
        created REAL NOT NULL, UNIQUE(job,request_key))''')


def _plan(db, kind, job, inputs):
    expected = {
        NATIVE_WITHDRAWAL: {'entity_key', 'baseline_artifact'},
        NATIVE_REPLACEMENT: {'entity_key', 'baseline_artifact', 'replacement_artifact'},
        XLSX_FACT_CHANGE: {'old_source', 'replacement_source', 'baseline_artifact'},
    }
    if kind not in expected or not isinstance(inputs, dict) or set(inputs) != expected[kind]:
        raise ValueError('Unsupported impact handoff kind or inputs.')
    if kind == XLSX_FACT_CHANGE:
        from . import fact_revisions
        return fact_revisions.plan_impact(db, job=job, **inputs)
    from . import native_links
    plan = native_links.plan_withdrawal(db, job=job,
        entity_key=inputs['entity_key'], baseline_artifact=inputs['baseline_artifact'])
    if kind == NATIVE_REPLACEMENT:
        if not any(item['location']['type'] == 'pptx_picture'
                   for item in plan['affected']):
            raise ValueError('Replacement handoff needs an affected native picture.')
        replacement = native_links._artifact(db, inputs['replacement_artifact'])
        if (replacement['run'] is not None or replacement['attempt'] is not None
                or replacement['task'] != 'agent_candidate'
                or not replacement['path'].startswith('inputs/')):
            raise ValueError('Replacement picture needs a job-owned input registration.')
        from orchestrator import pptx_edit
        pptx_edit._checked_image(Path(replacement['blob']).read_bytes(),
                                  replacement['path'])
        plan = {**plan, 'replacement_artifact': inputs['replacement_artifact'],
                'replacement_sha256': replacement['sha256']}
    return plan


def record_native_withdrawal(db, *, job, request_key, exact_request, actor,
                             entity_key, baseline_artifact):
    """Freeze one exact request and pre-agent plan in an atomic job record."""
    if not all(isinstance(item, str) and item.strip() for item in
               (job, request_key, exact_request, actor, entity_key, baseline_artifact)):
        raise ValueError('Impact handoff needs exact request, actor and inputs.')
    if len(request_key) > 200 or len(exact_request) > 100_000:
        raise ValueError('Impact handoff request exceeds the bounded record.')
    inputs = {'entity_key': entity_key, 'baseline_artifact': baseline_artifact}
    return _record(db, job=job, request_key=request_key, exact_request=exact_request,
                   actor=actor, kind=NATIVE_WITHDRAWAL, inputs=inputs)


def record_native_replacement(db, *, job, request_key, exact_request, actor,
                              entity_key, baseline_artifact, replacement_artifact):
    if not isinstance(replacement_artifact, str) or not replacement_artifact.strip():
        raise ValueError('Replacement handoff needs a registered picture input.')
    inputs = {'entity_key': entity_key, 'baseline_artifact': baseline_artifact,
              'replacement_artifact': replacement_artifact}
    return _record(db, job=job, request_key=request_key, exact_request=exact_request,
                   actor=actor, kind=NATIVE_REPLACEMENT, inputs=inputs)


def record_xlsx_change(db, *, job, request_key, exact_request, actor,
                       old_source, replacement_source, baseline_artifact):
    """Freeze a reviewed XLSX fact impact before any external agent receives it."""
    inputs = {'old_source': old_source, 'replacement_source': replacement_source,
              'baseline_artifact': baseline_artifact}
    return _record(db, job=job, request_key=request_key, exact_request=exact_request,
                   actor=actor, kind=XLSX_FACT_CHANGE, inputs=inputs)


def _record(db, *, job, request_key, exact_request, actor, kind, inputs):
    if not all(isinstance(item, str) and item.strip() for item in
               (job, request_key, exact_request, actor, *inputs.values())):
        raise ValueError('Impact handoff needs exact request, actor and inputs.')
    if len(request_key) > 200 or len(exact_request) > 100_000:
        raise ValueError('Impact handoff request exceeds the bounded record.')
    with transaction(db):
        plan = _plan(db, kind, job, inputs)
        digest = _digest(plan)
        prior = db.execute('''SELECT * FROM relay_impact_handoffs
            WHERE job=? AND request_key=?''', (job, request_key)).fetchone()
        if prior:
            if (prior['exact_request'] != exact_request or prior['actor'] != actor
                    or prior['kind'] != kind
                    or prior['baseline_artifact'] != inputs['baseline_artifact']
                    or prior['inputs'] != _json(inputs)
                    or prior['plan_digest'] != digest or prior['plan'] != _json(plan)):
                raise ValueError('Impact request key already has a different frozen plan.')
            return prior['id']
        ident = uuid.uuid4().hex
        db.execute('''INSERT INTO relay_impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                   (ident, job, request_key, exact_request, kind,
                    inputs['baseline_artifact'],
                    _json(inputs), digest, _json(plan), actor, time.time()))
        return ident


def records(db, job):
    return [dict(row) for row in db.execute('''SELECT * FROM relay_impact_handoffs
        WHERE job=? ORDER BY created,id''', (job,))]


def view_records(rows):
    """Use nested JSON in agent context, preserving malformed source text."""
    result = []
    for row in rows:
        item = dict(row)
        for key in ('inputs', 'plan'):
            try:
                item[key] = json.loads(item[key])
            except (ValueError, TypeError):
                item['parse_error'] = 'Saved impact ' + key + ' is malformed.'
        result.append(item)
    return result


def inspect(db, ident):
    """Compare a saved handoff to current committed links without mutation."""
    row = db.execute('SELECT * FROM relay_impact_handoffs WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('Unknown impact handoff.')
    row = dict(row)
    plan, inputs = row['plan'], row['inputs']
    try:
        plan = json.loads(plan)
        inputs = json.loads(inputs)
        if inputs['baseline_artifact'] != row['baseline_artifact']:
            raise ValueError('Saved impact baseline changed.')
        if _digest(plan) != row['plan_digest']:
            raise ValueError('Saved impact plan digest changed.')
    except (ValueError, OSError, TypeError, KeyError) as exc:
        status, reason = 'invalid', str(exc)
    else:
        try:
            current = _plan(db, row['kind'], row['job'], inputs)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            status, reason = 'unverifiable', str(exc)
        else:
            status = 'current' if current == plan else 'stale'
            reason = ('Frozen plan matches current registered evidence.' if status == 'current'
                      else 'Registered evidence or coverage changed; compute a new handoff.')
    return {'schema': SCHEMA, 'version': VERSION, 'id': ident, 'job': row['job'],
            'request_key': row['request_key'], 'exact_request': row['exact_request'],
            'kind': row['kind'], 'baseline_artifact': row['baseline_artifact'],
            'inputs': inputs, 'plan_digest': row['plan_digest'],
            'plan': plan, 'actor': row['actor'], 'created': row['created'],
            'status': status, 'reason': reason,
            'authorization': 'Inspection only; no edit, selection or dispatch.'}


def main(argv=None):
    """Desktop-independent entry point for an agent to freeze or inspect a plan."""
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('create-native-withdrawal')
    create.add_argument('--database', required=True)
    create.add_argument('--job', required=True)
    create.add_argument('--request-key', required=True)
    create.add_argument('--request-file', required=True)
    create.add_argument('--actor', required=True)
    create.add_argument('--entity-key', required=True)
    create.add_argument('--baseline-artifact', required=True)
    replace = sub.add_parser('create-native-replacement')
    for flag in ('database', 'job', 'request-key', 'request-file', 'actor',
                 'entity-key', 'baseline-artifact', 'replacement-artifact'):
        replace.add_argument('--' + flag, required=True)
    xlsx = sub.add_parser('create-xlsx-change')
    for flag in ('database', 'job', 'request-key', 'request-file', 'actor',
                 'old-source', 'replacement-source', 'baseline-artifact'):
        xlsx.add_argument('--' + flag, required=True)
    read = sub.add_parser('inspect')
    read.add_argument('--database', required=True)
    read.add_argument('--id', required=True)
    sync = sub.add_parser('sync')
    sync.add_argument('--database', required=True)
    sync.add_argument('--job', required=True)
    args = parser.parse_args(argv)
    supplied_path = Path(args.database).expanduser()
    if not supplied_path.is_file() or supplied_path.is_symlink():
        parser.error('An existing non-symlink authoritative Relay database is required.')
    path = supplied_path.resolve()
    if args.action == 'inspect':
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            result = inspect(db, args.id)
    else:
        from .bridge import State
        from . import workflow_files
        state = State(path)
        try:
            owner = state.db.execute('SELECT channel FROM relay_pipelines WHERE id=?',
                                     (args.job,)).fetchone()
            if owner is None:
                raise ValueError('Unknown job.')
            state.channel = owner['channel']
            creating = args.action in ('create-native-withdrawal',
                                       'create-native-replacement', 'create-xlsx-change')
            if creating:
                supplied_request = Path(args.request_file).expanduser()
                if not supplied_request.is_file() or supplied_request.is_symlink():
                    parser.error('An existing non-symlink exact request file is required.')
                exact_request = supplied_request.resolve().read_text(encoding='utf-8')
                common = dict(job=args.job, request_key=args.request_key,
                    exact_request=exact_request, actor=args.actor,
                    baseline_artifact=args.baseline_artifact)
                if args.action == 'create-xlsx-change':
                    ident = record_xlsx_change(state.db, old_source=args.old_source,
                        replacement_source=args.replacement_source, **common)
                else:
                    common['entity_key'] = args.entity_key
                    ident = (record_native_replacement(state.db,
                        replacement_artifact=args.replacement_artifact, **common)
                        if args.action == 'create-native-replacement' else
                        record_native_withdrawal(state.db, **common))
            view = workflow_files.sync(state, args.job)
            result = ({**inspect(state.db, ident), 'job_view': str(view / '.relay/job.sqlite')}
                      if creating else
                      {'schema': SCHEMA, 'version': VERSION, 'job': args.job,
                       'job_view': str(view / '.relay/job.sqlite'),
                       'authorization': 'Projection retry only; no edit, selection or dispatch.'})
        finally:
            state.db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
