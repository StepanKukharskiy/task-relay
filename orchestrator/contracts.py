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
    elif 'review_correction' in a:
        raise ValueError('Operation correction policy requires a registered operation.')
    elif a.setdefault('tools', ['files', 'shell']) not in (['files','shell'],['files'],['files','browser'],['files','python']):
        raise ValueError('Use a supported files or files + shell capability profile')
    outputs = a.get('outputs')
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 30:
        raise ValueError('Specify 1–30 output files')
    paths = set()
    for output in outputs:
        if 'media_type' in output:nonempty(output['media_type'],'output media type')
        if 'handoff' in output:
            from .handoff_contracts import descriptor
            descriptor(output['handoff'])
            if output.get('media_type')!=output['handoff']['media_type']:raise ValueError('Output handoff type differs from its declared media type.')
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
        from .browser_contract import validate,validate_files
        policy=validate(a.get('browser'))
        validate_files(a)
        resource='browser-'+hashlib.sha256(policy['profile'].encode()).hexdigest()
        if a.setdefault('resource',resource)!=resource:raise ValueError('Browser resource ownership must match its profile')
        if not set(policy['uploads'])<=set(i['path'] for i in inputs) or not set(policy['downloads'])<=set(o['path'] for o in outputs):
            raise ValueError('Browser transfers must name declared input/output paths')
        if a.get('review_of') and (policy['interaction_scope'] or policy['uploads'] or policy['downloads']):
            raise ValueError('Independent browser reviewers may only read/navigate')
        if a.setdefault('max_attempts',1)!=1:
            revision=a.get('revision',{})
            if not (a['max_attempts']==2 and a.get('review_of') and policy.get('visual_inputs')
                    and revision.get('kind')=='visual_review_recovery' and revision.get('previous_attempt')):
                raise ValueError('Browser work permits one attempt; revisions require an explicit visual review recovery')
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
    if 'provider_requests' in limits:
        from .executors import request_limit
        request_limit(a)
    if 'response_tokens' in limits:
        from .executors import response_limit
        response_limit(a)
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
    if 'worker' in a:
        from .worker_capabilities import validate
        validate(a)
    if 'source_fidelity' in a:
        from .source_fidelity import validate_assignment
        validate_assignment(a)
    if len(encoded(a)) > 180000:
        raise ValueError('Assignment exceeds 180,000 characters')
    return a


def review_evidence_dependencies(specs):
    """Only registered inspections feeding the producer's own reviewer get drafts.

    This permission comes from capability code and declared graph edges, never a
    model-supplied role/name/authority. Ordinary downstream work remains gated.
    """
    from .execution import REGISTRY
    tasks = {a['id']: a for a in specs}
    evidence = {}
    for reviewer in specs:
        target = reviewer.get('review_of')
        if not target:
            continue
        for dep in reviewer['dependencies']:
            helper = tasks.get(dep, {})
            operation = helper.get('execution', {})
            capability = REGISTRY.get(operation.get('capability'), {})
            if (not capability.get('review_evidence') or operation.get('version') != capability.get('version')
                or helper.get('review_of') or helper.get('user_gate')
                or target not in helper.get('dependencies', [])
                or not any(i.get('from_task') == target for i in helper.get('inputs', []))
                or not any(i.get('from_task') == dep for i in reviewer.get('inputs', []))):
                continue
            evidence.setdefault(dep, set()).add(target)
    return evidence


def validate_review_order(specs):
    """Include completion gates in cycle detection, beyond plain task edges."""
    evidence = review_evidence_dependencies(specs)
    reviewers = {a['review_of']: a['id'] for a in specs if a.get('review_of')}
    edges = {}
    for a in specs:
        draft_deps = evidence.get(a['id'], set()) | ({a['review_of']} if a.get('review_of') else set())
        edges[('delivered', a['id'])] = [('delivered' if d in draft_deps else 'completed', d) for d in a['dependencies']]
        edges[('completed', a['id'])] = [('delivered', a['id'])]
        if a['id'] in reviewers:
            edges[('completed', a['id'])].append(('completed', reviewers[a['id']]))
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            raise ValueError('Review dependency cycle: review prerequisites must be registered inspections of the unaccepted candidate.')
        if node in visited:
            return
        visiting.add(node)
        for dep in edges[node]:
            visit(dep)
        visiting.remove(node); visited.add(node)
    for node in edges:
        visit(node)


def plan(value):
    p = copy.deepcopy(value)
    label(p['id'])
    nonempty(p.get('brief'), 'brief')
    backend = p.get('backend', {})
    from .executors import validate, limits_for, API_TYPES, BROWSER_TYPES, CODE_TYPES
    validate(backend)
    if not isinstance(p.get('tasks'), list) or not 1 <= len(p['tasks']) <= 30:
        raise ValueError('Workflow permits 1–30 tasks')
    p['tasks'] = [assignment(a) for a in p['tasks']]
    for a in p['tasks']:
        if a.get('execution'):continue
        from .worker_capabilities import backend_for
        chosen=backend_for(a,backend)
        profile=validate(chosen)
        if a['tools']!=profile:raise ValueError('Assignment tools do not match the selected execution provider.')
        if chosen['type'] in API_TYPES:
            if any(a['limits'][k]>v for k,v in limits_for(chosen).items()):raise ValueError('API assignment exceeds its bounded executor limits.')
            if chosen['type'] not in (*BROWSER_TYPES,*CODE_TYPES) and any(o.get('media_type','text/plain') not in ('text/plain','text/markdown','application/json') for o in a['outputs']):
                raise ValueError('API file executor produces UTF-8 text only.')
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
            expected_criteria=tasks[target]['criteria']
            if a.get('source_fidelity',{}).get('phase')=='comparison':
                from .source_fidelity import CRITERION
                from .native_apps import SCRIPT_OPERATIONS
                if (tasks[target].get('execution',{}).get('capability') not in SCRIPT_OPERATIONS
                    or a['source_fidelity']['criterion']!=len(expected_criteria)+1):
                    raise ValueError('Source comparison must strengthen a native producer review.')
                expected_criteria=expected_criteria+[CRITERION]
            if a['criteria'] != expected_criteria:
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
    validate_review_order(p['tasks'])
    from .corrections import validate as validate_corrections
    validate_corrections(p['tasks'])
    p.setdefault('concurrency', 2)
    if type(p['concurrency']) is not int or not 1 <= p['concurrency'] <= 4:
        raise ValueError('Concurrency must be 1–4')
    return p


# The service verifies output files itself. These checks are model reports, not proof.
from . import outcomes
REPORT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'assignment_id': {'type': 'string'},
        'summary': {'type': 'string'},
        'decision': {'type': 'string', 'enum': ['delivered', 'accept', 'revise', 'blocked']},
        'instruction': {'type': 'string'},
        'findings': outcomes.SCHEMA,
        'checks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'criterion': {'type': 'integer'}, 'passed': {'type': 'boolean'},
                           'evidence': {'type': 'string'}},
            'required': ['criterion', 'passed', 'evidence']}},
    }, 'required': ['assignment_id', 'summary', 'decision', 'instruction', 'checks', 'findings']}


def report(value, frozen):
    if isinstance(value,dict) and isinstance(value.get('checks'),dict):
        from .report_builder import build
        value=build(value,frozen)
    if not isinstance(value, dict) or value.get('assignment_id') != frozen['assignment_id']:
        raise ValueError('Result belongs to a different assignment')
    nonempty(value.get('summary'), 'result summary')
    outcomes.validate(value.get('findings',[]))
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
    from .source_fidelity import validate_report
    validate_report(value, frozen)
    return value
