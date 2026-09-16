"""Reviewed, immutable procedures extracted from completed Relay workflows.

Only literal project variables are generalized. Runs use the normal scheduler;
past outputs, accepted choices, scripts and execution approvals are provenance,
never new inputs or execution authority.
"""
import copy
import hashlib
import json
import re
import time

from . import pipelines

ACTIONS = {'draft_procedure', 'run_procedure'}
INSTRUCTIONS = '''Reusable procedures learn from completed Relay workflows, not
desktop recordings. snapshot.procedure_sources contains completed examples;
snapshot.procedures lists immutable versions. Only when the user requests saving
a workflow, propose {kind:"draft_procedure", pipeline_id:string, name:string,
parameters:[{name:string, example:string}]}. Each example must be an exact literal
in that workflow's request or stage text; use variables for project-specific brief
paths, locations and requirements. Do not invent a replacement pipeline. Relay
extracts its existing stages and review boundaries deterministically. Explain any
project-specific constants that remain. The user reviews the full template and
approves its exact version with /procedures approve ID. Never approve for them.
For a requested new run of an approved version use {kind:"run_procedure",
procedure_id:string, bindings:{parameter_name:new_value}} with ALL parameters
explicitly supplied by the user. Ask for missing values; never reuse examples as
defaults. This prepares a fresh workflow for Resume, preserving exact-code Start
and selections. Never replay old files or choices. /procedures shows versions;
/procedures ID shows the full template; /procedures source WORKFLOW_ID shows an
older completed example. Listing, saving or approving starts no workers. A saved
procedure is a reusable example, not proof of quality on unseen projects.
'''


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS relay_procedures(
        id TEXT PRIMARY KEY, channel TEXT NOT NULL, definition TEXT NOT NULL,
        sha256 TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS relay_procedure_events(
        id INTEGER PRIMARY KEY, procedure TEXT NOT NULL, kind TEXT NOT NULL,
        request_id TEXT NOT NULL, request TEXT NOT NULL, detail TEXT NOT NULL,
        created REAL NOT NULL, UNIQUE(procedure,kind,request_id));
      CREATE TABLE IF NOT EXISTS relay_procedure_runs(
        pipeline TEXT PRIMARY KEY, procedure TEXT NOT NULL, context TEXT NOT NULL);
    ''')
    from . import opportunities
    opportunities.initialize(db)


def channel(state):
    return getattr(state, 'channel', 'telegram')


def digest(value):
    return hashlib.sha256(pipelines.encoded(value).encode()).hexdigest()


def atomic(state):
    if not state.db.in_transaction:
        raise ValueError('Procedure changes require an atomic transaction.')


def source(state, ident):
    row = state.db.execute('SELECT * FROM relay_pipelines WHERE id=? AND channel=?',
                           (ident, channel(state))).fetchone()
    if not row or row['status'] != 'completed':
        raise ValueError('Select a completed workflow in this channel.')
    spec = json.loads(row['spec'])
    steps = [dict(s) for s in state.db.execute(
        'SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position', (ident,))]
    if ([s['id'] for s in steps] != [s['id'] for s in spec['stages']]
            or any(s['status'] != 'completed' for s in steps)):
        raise ValueError('Every source stage must be completed, including its decisions.')
    # Capture the exact receipts without making their contents future instructions.
    events = [dict(e) for e in state.db.execute(
        'SELECT * FROM relay_pipeline_events WHERE pipeline=? ORDER BY id', (ident,))]
    previous = run_context(state, ident)
    return dict(pipeline_id=ident, request=row['request'], spec=spec,
                bound_request=previous['request'] if previous else row['request'],
                evidence_sha256=digest(dict(steps=steps, events=events)),
                output_references=sorted({v for s in steps for a in json.loads(s['sources'])
                                          for v in (a.get('artifact'), a.get('path')) if v}))


def catalog(state):
    result = []
    for r in state.db.execute('SELECT id FROM relay_procedures WHERE channel=? ORDER BY created DESC LIMIT 30',
                              (channel(state),)):
        try:
            row, value = load(state, r['id'])
        except ValueError:
            result.append(dict(id=r['id'], status='unavailable', error='Procedure version changed.'))
            continue
        runs = state.db.execute('''SELECT p.status FROM relay_procedure_runs r
            JOIN relay_pipelines p ON p.id=r.pipeline WHERE r.procedure=?''', (row['id'],)).fetchall()
        result.append(dict(id=row['id'], name=value['name'], status=row['status'], sha256=row['sha256'],
                           parameters=[p['name'] for p in value['template']['parameters']],
                           completed_runs=sum(r['status'] == 'completed' for r in runs)))
    return result


def examples(state):
    # Bound prompt growth; older examples remain available through /procedures source.
    result = []; size = 0
    for row in state.db.execute("SELECT id FROM relay_pipelines WHERE channel=? AND status='completed' ORDER BY created DESC LIMIT 3", (channel(state),)):
        try:
            value = source(state, row['id'])
        except ValueError:
            continue
        size += len(pipelines.encoded(value))
        if size <= 24000:
            result.append(value)
    return result


def load(state, ident):
    row = state.db.execute('SELECT * FROM relay_procedures WHERE id=? AND channel=?',
                           (ident, channel(state))).fetchone()
    if not row:
        raise ValueError('Procedure is not available in this channel. Use /procedures.')
    value = json.loads(row['definition'])
    sha = digest(value)
    if sha != row['sha256'] or row['id'] != 'proc-' + sha[:24] or value['channel'] != channel(state):
        raise ValueError('Procedure version changed; it cannot be used.')
    return row, value


def validate(action, snap):
    if snap.get('pipeline_step'):
        raise ValueError('Finish the current workflow stage; do not create a nested procedure.')
    if action.get('kind') == 'draft_procedure':
        if (set(action)-{'opportunity_id'} != {'kind', 'pipeline_id', 'name', 'parameters'}
                or ('opportunity_id' in action and not pipelines.bounded(action['opportunity_id'],80))
                or not pipelines.bounded(action['pipeline_id'], 80)
                or not pipelines.bounded(action['name'], 150)
                or not isinstance(action['parameters'], list) or not 1 <= len(action['parameters']) <= 12):
            raise ValueError('Provide a completed workflow, name and 1–12 literal parameters.')
        names = set(); values = []
        for p in action['parameters']:
            if (not isinstance(p, dict) or set(p) != {'name', 'example'}
                    or not isinstance(p['name'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', p['name'])
                    or p['name'] in names or not pipelines.bounded(p['example'], 2000)
                    or len(p['example']) < 2 or '{{' in p['example'] or '}}' in p['example']):
                raise ValueError('Parameters need unique names and exact nonempty example text.')
            if p['example'] in values:
                raise ValueError('Parameter examples must be distinct.')
            names.add(p['name']); values.append(p['example'])
    elif action.get('kind') == 'run_procedure':
        if (set(action) != {'kind', 'procedure_id', 'bindings'}
                or not pipelines.bounded(action['procedure_id'], 80)
                or not isinstance(action['bindings'], dict) or not 1 <= len(action['bindings']) <= 12
                or any(not isinstance(k, str) or not pipelines.bounded(v, 2000)
                       or '{{' in v or '}}' in v for k, v in action['bindings'].items())):
            raise ValueError('Choose an exact approved procedure and supply every new parameter.')
    else:
        raise ValueError('Unknown procedure action.')


def map_text(template, transform):
    """Never parameterize routes, capabilities, stage IDs or decision boundaries."""
    value = copy.deepcopy(template)
    for key in ('title', 'request'):
        value[key] = transform(value[key])
    for stage in value['stages']:
        stage['instruction'] = transform(stage['instruction'])
        stage['deliverables'] = {k: transform(v) for k, v in stage['deliverables'].items()}
    return value


def record(state, ident, kind, job, detail):
    state.db.execute('INSERT OR IGNORE INTO relay_procedure_events(procedure,kind,request_id,request,detail,created) VALUES (?,?,?,?,?,?)',
                     (ident, kind, str(job['id']), job['prompt'], pipelines.encoded(detail), time.time()))


def draft(state, job, action):
    origin = source(state, action['pipeline_id'])
    opportunity=None
    if action.get('opportunity_id'):
        from . import opportunities
        opportunity=opportunities.exemplar(state,action['opportunity_id'],action['pipeline_id'])
    template = dict(title=origin['spec']['title'], request=origin['bound_request'],
                    stages=origin['spec']['stages'], parameters=action['parameters'])
    texts = []
    map_text(template, lambda text: texts.append(text) or text)
    if any('{{' in t or '}}' in t for t in texts):
        raise ValueError('Source already contains template markers; use a concrete completed workflow.')
    for p in action['parameters']:
        if not any(p['example'] in t for t in texts):
            raise ValueError('Parameter example is absent from the completed request and stage text: ' + p['name'])
    lookup = {p['example']: '{{' + p['name'] + '}}' for p in action['parameters']}
    # A location may also occur inside a brief path. Replace the longer literal
    # first in one pass so neither parameter rewrites the other's placeholder.
    pattern = re.compile('|'.join(re.escape(v) for v in sorted(lookup, key=len, reverse=True)))
    template = map_text(template, lambda t: pattern.sub(lambda m: lookup[m[0]], t))
    retained = []
    map_text(template, lambda t: retained.append(t) or t)
    if any(not any('{{' + p['name'] + '}}' in t for t in retained) for p in action['parameters']):
        raise ValueError('A parameter has no independent occurrence outside another parameter. Remove the unused parameter.')
    if any(ref in t for ref in origin['output_references'] for t in retained):
        raise ValueError('The template retains an old output identity. Parameterize explicit file inputs; new stage outputs must come from the new workflow.')
    value = dict(name=action['name'], channel=channel(state), source=origin, template=template)
    if opportunity:value['opportunity']=opportunity
    sha = digest(value); ident = 'proc-' + sha[:24]
    state.db.execute('INSERT OR IGNORE INTO relay_procedures VALUES (?,?,?,?,?,?)',
                     (ident, channel(state), pipelines.encoded(value), sha, 'draft', time.time()))
    record(state, ident, 'drafted', job, dict(source=origin['pipeline_id'], sha256=sha))
    return describe(state, ident)


def describe(state, ident):
    row, value = load(state, ident)
    return (f"{value['name']} · {row['status']}\nVersion: {row['id']}\n"
            'Review every retained constant and variable before approving. Examples are not defaults.\n\n'
            + json.dumps(value['template'], ensure_ascii=False, indent=2)
            + '\n\nDerived from completed workflow: ' + value['source']['pipeline_id']
            + '\nPast files and decisions remain provenance; each run produces new outputs and asks for new selections.'
            + ('\nApprove this exact template: /procedures approve ' + row['id'] if row['status'] == 'draft' else
               '\nAsk Relay to run this version and supply every parameter. Review the new workflow, then Resume.')
            + '\nSaving or approval starts no work. Native code still requires its exact Start.')


def approve(state, job, ident):
    atomic(state)
    row, value = load(state, ident)
    if row['status'] == 'approved':
        return 'This exact procedure version is already approved. No work started.'
    if source(state, value['source']['pipeline_id']) != value['source']:
        raise ValueError('Source receipts changed after extraction. Draft and review a new version.')
    if value.get('opportunity'):
        from . import opportunities
        opportunities.exemplar(state,value['opportunity']['id'],value['source']['pipeline_id'])
    state.db.execute("UPDATE relay_procedures SET status='approved' WHERE id=?", (ident,))
    record(state, ident, 'approved', job, dict(sha256=row['sha256']))
    return 'Procedure approved: ' + ident + '\nSupply every new parameter to prepare a run. No workers started.'


def dispatch(state, job, action, snap):
    atomic(state); validate(action, snap)
    if action['kind'] == 'draft_procedure':
        return draft(state, job, action), None
    row, value = load(state, action['procedure_id'])
    if row['status'] != 'approved':
        raise ValueError('Review and approve this exact procedure before preparing a run.')
    bindings = action['bindings']
    if set(bindings) != {p['name'] for p in value['template']['parameters']}:
        raise ValueError('Supply every parameter exactly once; saved examples are not defaults.')
    template = map_text(value['template'], lambda t: re.sub(
        r'\{\{([a-z][a-z0-9_]*)\}\}', lambda m: bindings[m[1]], t))
    # An approved older template already declared these generation operations.
    # Preserve that meaning in the new reviewable plan, never rewrite its version.
    legacy_visuals=[]
    for stage in template['stages']:
        if 'visual_intent' not in stage and pipelines.generates_images(stage):
            stage['visual_intent']='synthetic';legacy_visuals.append(stage['id'])
    plan = dict(kind='plan_pipeline', title=template['title'], planning_only=True, stages=template['stages'])
    # Existing approved templates keep their exact contract and remain reviewable.
    # Typed templates retain their declarations; legacy templates are not upgraded
    # by inventing ports, quantities or conversions.
    if all(s.get('handoff') for s in template['stages']):plan['contract_version']=1
    else:snap={**snap,'workflow_contract_version':0}
    # The ordinary validator checks current operations and expanded text bounds.
    result = pipelines.dispatch(state, job, plan, snap)
    pid = state.db.execute('SELECT id FROM relay_pipelines WHERE request_id=?', (job['id'],)).fetchone()[0]
    context = dict(procedure_id=row['id'], sha256=row['sha256'], bindings=bindings,
                   request=template['request'])
    if legacy_visuals:context['legacy_generation_stages']=legacy_visuals
    old = state.db.execute('SELECT context FROM relay_procedure_runs WHERE pipeline=?', (pid,)).fetchone()
    if old and old[0] != pipelines.encoded(context):
        raise ValueError('Procedure run identity conflict.')
    state.db.execute('INSERT OR IGNORE INTO relay_procedure_runs VALUES (?,?,?)',
                     (pid, row['id'], pipelines.encoded(context)))
    record(state, row['id'], 'run_prepared', job, dict(pipeline_id=pid, **context))
    # Include the fully bound brief in the same review card as the Resume control.
    key = f'pipeline:{pid}:workflow:created'
    detail = '\n\nProcedure: ' + row['id'] + '\nBound request:\n' + template['request']
    if legacy_visuals:
        detail+='\nLegacy image-generation stages retain their approved behavior: '+', '.join(legacy_visuals)+'. Review before Resume; these stages do not source reference photos.'
    if not old:
        state.db.execute('UPDATE outbox SET text=text || ? WHERE id=?', (detail, key))
    return result[0] + detail, None


def run_context(state, pid):
    # The read-only history analyzer can inspect pre-procedure installations.
    if not state.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_procedure_runs'").fetchone():return None
    row = state.db.execute('SELECT context FROM relay_procedure_runs WHERE pipeline=?', (pid,)).fetchone()
    return json.loads(row[0]) if row else None


def command(state, argument, request_id, original):
    """Read or approve without asking a provider to interpret acceptance."""
    parts = argument.split()
    if not parts:
        values = catalog(state)
        return ('Reusable procedures:\n' + ('\n'.join(
            (f"{v['id']} — {v['name']} · {v['status']} · {v['completed_runs']} completed reuse runs"
             if 'name' in v else f"{v['id']} — unavailable: {v['error']}") for v in values)
            or 'No saved procedures yet.') + '\nAsk Relay to save a completed workflow with named project variables. '
            'Use /procedures ID to inspect an exact version.')
    if len(parts) == 1:
        return describe(state, parts[0])
    if len(parts) == 2 and parts[0] == 'source':
        return json.dumps(source(state, parts[1]), ensure_ascii=False, indent=2)
    if len(parts) == 2 and parts[0] == 'approve':
        return approve(state, dict(id=request_id, prompt=original), parts[1])
    raise ValueError('Use /procedures, /procedures ID, /procedures source WORKFLOW_ID or /procedures approve ID.')
