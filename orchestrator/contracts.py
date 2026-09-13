"""Bounded, explicit assignments; no conversation-based execution-state inference."""
import copy
import hashlib
import json
from pathlib import PurePosixPath
import re


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value):
        raise ValueError('Invalid identifier')
    return value


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Expected a relative file path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('File path must stay inside its workspace')
    if path.parts[0] == '.relay':
        raise ValueError('.relay is reserved')
    return value


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 60000:
        raise ValueError('Missing or oversized ' + name)
    return value


def assignment(value):
    a = copy.deepcopy(value)
    label(a['id'])
    for field in ('objective', 'role', 'instruction'):
        nonempty(a.get(field), field)
    deps = a.setdefault('dependencies', [])
    if not isinstance(deps, list) or len(deps) != len(set(deps)):
        raise ValueError('Invalid dependencies')
    for dep in deps:
        label(dep)
    if a['id'] in deps:
        raise ValueError('Self dependency')
    if 'execution' in a:
        from .execution import validate
        validate(a)
    elif a.setdefault('tools', ['files', 'shell']) not in (['files','shell'],['files'],['files','browser']):
        raise ValueError('Use a supported files or files + shell capability profile')
    outputs = a.get('outputs')
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 30:
        raise ValueError('Specify 1–30 output files')
    paths = set()
    for output in outputs:
        if 'media_type' in output:nonempty(output['media_type'],'output media type')
        p = relative(output['path'])
        nonempty(output.get('purpose'), 'output purpose')
        if p in paths:
            raise ValueError('Duplicate output path')
        paths.add(p)
    inputs = a.setdefault('inputs', [])
    if not isinstance(inputs, list) or len(inputs) > 300:
        raise ValueError('At most 300 explicit input files')
    for entry in inputs:
        if 'media_type' in entry:nonempty(entry['media_type'],'input media type')
        p = relative(entry['path'])
        nonempty(entry.get('purpose'), 'input purpose')
        nonempty(entry.get('authority'), 'input authority')
        if p in paths:
            raise ValueError('Input/output paths must be unique')
        paths.add(p)
        if ('artifact' in entry) == ('from_task' in entry):
            raise ValueError('Input needs exactly one artifact or upstream task')
        if 'artifact' in entry:
            label(entry['artifact'])
        else:
            label(entry['from_task']); relative(entry['output'])
            if entry['from_task'] not in deps:
                raise ValueError('Artifact producer must be an explicit dependency')
    if a.get('tools')==['files','browser']:
        from .browser_contract import validate
        policy=validate(a.get('browser'))
        resource='browser-'+hashlib.sha256(policy['profile'].encode()).hexdigest()
        if a.setdefault('resource',resource)!=resource:raise ValueError('Browser resource ownership must match its profile')
        if not set(policy['uploads'])<=set(i['path'] for i in inputs) or not set(policy['downloads'])<=set(o['path'] for o in outputs):
            raise ValueError('Browser transfers must name declared input/output paths')
        if a.get('review_of') and (policy['interaction_scope'] or policy['uploads'] or policy['downloads']):
            raise ValueError('Independent browser reviewers may only read/navigate')
        if a.setdefault('max_attempts',1)!=1:raise ValueError('Browser work permits one attempt; revisions require a new explicit stage')
    elif 'browser' in a:raise ValueError('Browser authority requires the browser executor profile')
    criteria = a.get('criteria')
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 30:
        raise ValueError('Specify 1–30 review criteria')
    for criterion in criteria:
        nonempty(criterion, 'criterion')
    limits = a.setdefault('limits', {})
    for key, default, upper in [('seconds', 600, 1800), ('tool_calls', 60, 200),
                                ('output_bytes', 100000000, 500000000)]:
        limits.setdefault(key, default)
        if type(limits[key]) is not int or not 1 <= limits[key] <= upper:
            raise ValueError('Invalid ' + key + ' limit')
    a.setdefault('max_attempts', 2)
    if type(a['max_attempts']) is not int or not 1 <= a['max_attempts'] <= 3:
        raise ValueError('Execution permits 1–3 attempts')
    if a.get('review_of'):
        label(a['review_of'])
        if a['review_of'] not in deps or a.get('user_gate'):
            raise ValueError('Reviewer must depend on its producer; user gate belongs to producer')
    if a.get('user_gate'):
        nonempty(a['user_gate'], 'user decision purpose')
    if 'selection_outputs' in a:
        selected=a['selection_outputs']
        if (not a.get('user_gate') or not isinstance(selected,list) or not 2<=len(selected)<=6
            or any(not isinstance(p,str) for p in selected) or len(set(selected))!=len(selected)
            or not set(selected)<=set(o['path'] for o in outputs)):
            raise ValueError('A selection set requires a user gate and 2–6 distinct declared output paths')
    if a.get('resource'):
        label(a['resource'])
    if len(encoded(a)) > 180000:
        raise ValueError('Assignment exceeds 180,000 characters')
    return a


def plan(value):
    p = copy.deepcopy(value)
    label(p['id'])
    nonempty(p.get('brief'), 'brief')
    backend = p.get('backend', {})
    from .executors import validate, GEMINI_LIMITS
    profile=validate(backend)
    if not isinstance(p.get('tasks'), list) or not 1 <= len(p['tasks']) <= 30:
        raise ValueError('Workflow permits 1–30 tasks')
    p['tasks'] = [assignment(a) for a in p['tasks']]
    for a in p['tasks']:
        if a.get('execution'):continue
        if a['tools']!=profile:raise ValueError('Assignment tools do not match the selected execution provider.')
        if backend['type'] in ('gemini-agent','gemini-browser'):
            if any(a['limits'][k]>v for k,v in GEMINI_LIMITS.items()):raise ValueError('Gemini assignment exceeds its bounded file-executor limits.')
            if any(o.get('media_type','text/plain') not in ('text/plain','text/markdown','application/json') for o in a['outputs']):
                raise ValueError('Gemini file executor produces UTF-8 text only.')
    tasks = {a['id']: a for a in p['tasks']}
    if len(tasks) != len(p['tasks']):
        raise ValueError('Duplicate task ID')
    visiting, visited, reviewers = set(), set(), set()
    def visit(tid):
        if tid not in tasks or tid in visiting:
            raise ValueError('Missing dependency or dependency cycle')
        if tid in visited:
            return
        visiting.add(tid)
        for dep in tasks[tid]['dependencies']:
            visit(dep)
        visiting.remove(tid); visited.add(tid)
    for a in tasks.values():
        visit(a['id'])
        if a.get('review_of'):
            target = a['review_of']
            if target in reviewers or tasks[target].get('review_of'):
                raise ValueError('One independent reviewer per producer; no nested review')
            if a['max_attempts'] < tasks[target]['max_attempts']:
                raise ValueError('Reviewer budget must cover every permitted producer attempt')
            if a['criteria'] != tasks[target]['criteria']:
                raise ValueError('Reviewer must check the producer criteria without weakening them')
            reviewers.add(target)
            for out in tasks[target]['outputs']:
                if not any(i.get('from_task') == target and i.get('output') == out['path'] for i in a['inputs']):
                    raise ValueError('Reviewer must receive every declared producer output')
        for item in a['inputs']:
            if 'from_task' in item and item['output'] not in [o['path'] for o in tasks[item['from_task']]['outputs']]:
                raise ValueError('Unknown upstream output')
            if 'from_task' in item and item.get('media_type'):
                output=next(o for o in tasks[item['from_task']]['outputs'] if o['path']==item['output'])
                if item['media_type']!=output.get('media_type'):
                    raise ValueError('Upstream output type does not match the declared input type')
    p.setdefault('concurrency', 2)
    if type(p['concurrency']) is not int or not 1 <= p['concurrency'] <= 4:
        raise ValueError('Concurrency must be 1–4')
    return p


# The service verifies output files itself. These checks are model reports, not proof.
REPORT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'assignment_id': {'type': 'string'},
        'summary': {'type': 'string'},
        'decision': {'type': 'string', 'enum': ['delivered', 'accept', 'revise', 'blocked']},
        'instruction': {'type': 'string'},
        'checks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'criterion': {'type': 'integer'}, 'passed': {'type': 'boolean'},
                           'evidence': {'type': 'string'}},
            'required': ['criterion', 'passed', 'evidence']}},
    }, 'required': ['assignment_id', 'summary', 'decision', 'instruction', 'checks']}


def report(value, frozen):
    if not isinstance(value, dict) or value.get('assignment_id') != frozen['assignment_id']:
        raise ValueError('Result belongs to a different assignment')
    nonempty(value.get('summary'), 'result summary')
    blocked = value.get('decision') == 'blocked'
    allowed = ('accept', 'revise', 'blocked') if frozen.get('review_of') else ('delivered', 'blocked')
    if value.get('decision') not in allowed:
        raise ValueError('Invalid result decision for role')
    checks = value.get('checks')
    if not isinstance(checks, list) or (not blocked and len(checks) != len(frozen['criteria'])):
        raise ValueError('Every frozen criterion requires an explicit check')
    # A blocked worker may stop before checking every criterion, but supplied
    # checks still cross the same validation boundary before notice formatting.
    previous = 0
    for index, check in enumerate(checks, 1):
        if not isinstance(check, dict) or type(check.get('criterion')) is not int or type(check.get('passed')) is not bool:
            raise ValueError('Invalid criterion check')
        if not previous < check['criterion'] <= len(frozen['criteria']) or (not blocked and check['criterion'] != index):
            raise ValueError('Invalid criterion check')
        previous = check['criterion']
        nonempty(check.get('evidence'), 'check evidence')
    if not isinstance(value.get('instruction'), str) or len(value['instruction']) > 60000:
        raise ValueError('Invalid result instruction')
    if value['decision'] in ('accept', 'delivered') and not all(c['passed'] for c in checks):
        raise ValueError('Delivery/acceptance cannot advance with reported failed criteria')
    if value['decision'] == 'revise':
        nonempty(value.get('instruction'), 'revision instruction')
    return value
