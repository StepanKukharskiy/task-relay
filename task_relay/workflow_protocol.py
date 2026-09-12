"""Strict handoff contracts and read-only Codex turn tracking."""
import json
from pathlib import Path
import re

MAX_RESULT = 100000


def strings(value, name):
    if not isinstance(value, list) or not value or len(value) > 40 or any(
            not isinstance(v, str) or not v.strip() or len(v) > 10000 for v in value):
        raise ValueError(f'Invalid {name} in workflow handoff')
    return value


def plan(value):
    if not isinstance(value, dict):
        raise ValueError('Missing workflow plan')
    for name in ('step_id', 'objective', 'instruction', 'bounds'):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError(f'Missing {name} in workflow plan')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value['step_id']):
        raise ValueError('Invalid workflow step ID')
    for name in ('scope', 'exclusions', 'deliverables', 'criteria'):
        strings(value.get(name), name)
    if len(json.dumps(value)) > MAX_RESULT:
        raise ValueError('Workflow plan exceeds the handoff limit')
    return value


def response(text, marker, phase, assignment=None):
    if len(text) > MAX_RESULT:
        raise ValueError('Workflow response exceeds the handoff limit')
    blocks = re.findall(r'```relay-result\s*\n(.*?)\n```', text, re.S)
    if len(blocks) != 1:
        raise ValueError('Expected one relay-result handoff; no automatic reformatting turn was started')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key in workflow response')
            result[key] = value
        return result
    result = json.loads(blocks[0], object_pairs_hook=unique)
    if not isinstance(result, dict) or result.get('marker') != marker:
        raise ValueError('Workflow response belongs to another dispatch')
    verdict = result.get('decision')
    if verdict == 'BLOCKED':
        if not isinstance(result.get('reason'), str) or not result['reason'].strip():
            raise ValueError('Blocked response lacks its reason')
        return result
    if phase == 'planning':
        if verdict != 'READY':
            raise ValueError('Planner did not return READY or BLOCKED')
        plan(result.get('plan'))
    elif phase == 'executing':
        if verdict != 'RESULT' or result.get('step_id') != assignment['step_id']:
            raise ValueError('Execution result does not match the frozen step')
        strings(result.get('evidence'), 'execution evidence')
    elif phase == 'reviewing':
        if verdict not in ('ACCEPTED', 'REVISE') or result.get('step_id') != assignment['step_id']:
            raise ValueError('Review does not match the frozen step')
        checks = result.get('checks')
        if not isinstance(checks, list) or len(checks) != len(assignment['criteria']):
            raise ValueError('Review must address every frozen acceptance criterion')
        for index, check in enumerate(checks, 1):
            if not isinstance(check, dict) or type(check.get('criterion')) is not int or check['criterion'] != index or type(check.get('passed')) is not bool:
                raise ValueError('Invalid criterion review')
            strings(check.get('evidence'), 'review evidence')
        if verdict == 'ACCEPTED' and (not all(c['passed'] for c in checks) or result.get('human_gate_remaining') is not False):
            raise ValueError('Acceptance requires all criteria and no outstanding human gate')
        if verdict == 'REVISE' and (result.get('scope_unchanged') is not True or not isinstance(result.get('instruction'), str) or not result['instruction'].strip()):
            raise ValueError('Revision must stay within the frozen scope')
    return result


def turn_result(path, turn_id=None, marker=None, offset=0):
    """Find exact turn and marker; never mistake a later user's turn for its result.

    A start event precedes input items in desktop rollouts. Scan complete records
    only. Imported turns scan once from zero; service dispatches use a byte cursor.
    """
    current = None
    target = turn_id
    found = False
    completed = None
    aborted = False
    marker_turns = set()
    extra_user_input = False
    user_seen = False
    with Path(path).open('rb') as stream:
        if offset > stream.seek(0, 2):
            raise ValueError('Codex history was replaced during the workflow')
        stream.seek(offset)
        for raw in stream:
            if not raw.endswith(b'\n'):
                break
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            p = e.get('payload', {})
            if e.get('type') == 'event_msg' and p.get('type') == 'task_started':
                current = p.get('turn_id')
                if current == target:
                    found = True
                    user_seen = False
            if e.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
                text = '\n'.join(c.get('text', '') for c in p.get('content', []) if isinstance(c, dict))
                if marker and marker in text:
                    marker_turns.add(current)
                    if target and current != target:
                        raise ValueError('Workflow marker appeared in multiple turns')
                    target, found = current, True
                    user_seen = True
                elif found and current == target and text.strip() and not text.lstrip().startswith(('<environment_context>', '<permissions instructions>')):
                    if user_seen:
                        extra_user_input = True
                    user_seen = True
            if e.get('type') == 'event_msg' and p.get('turn_id') == target and target:
                if p.get('type') == 'task_complete':
                    completed = p.get('last_agent_message')
                    if completed is None:
                        raise ValueError('Completed workflow turn has no final response')
                elif p.get('type') == 'turn_aborted':
                    aborted = True
    if len(marker_turns) > 1 or (found and current != target) or extra_user_input:
        raise ValueError('User activity changed this task after the workflow dispatch; review before resuming')
    return {'turn_id': target, 'found': found, 'text': completed, 'aborted': aborted}


def prompt(data, phase, marker):
    common = (f'{marker}\nTask Relay coordinates this bounded workflow. Work only on this dispatch. '
              'Preserve all existing project instructions, approval gates, numerical criteria and accepted deliverables. '
              'Do not contact other tasks or start another roadmap item. If blocked or a user decision is needed, stop and report BLOCKED. '
              'Finish with exactly one ```relay-result JSON block matching the schema below. '
              'This is a machine handoff, not permission to change the scope. Include a short human-readable summary before it.\n')
    blocked = {'marker': marker, 'decision': 'BLOCKED', 'reason': 'exact blocker or question'}
    source = data.get('source_request')
    if source:
        common += ('Original user message (verbatim; the relay summary below must not replace its questions or constraints). '
                   'Address its questions explicitly. Treat user hypotheses as hypotheses to investigate, not established causes. '
                   'This context does not expand the stage authorization or change frozen execution criteria.\n'
                   '--- BEGIN ORIGINAL USER MESSAGE ---\n' + source['text'] +
                   '\n--- END ORIGINAL USER MESSAGE ---\n')
        if source.get('reference_context'):
            common += source['reference_context']+'\n'
    if phase == 'planning':
        schema = {'marker': marker, 'decision': 'READY', 'plan': {'step_id': 'unique-step-id',
            'objective': 'one bounded roadmap item', 'scope': ['permitted work'], 'exclusions': ['forbidden work'],
            'deliverables': ['exact outputs'], 'criteria': ['measurable acceptance criterion'],
            'bounds': 'explicit runtime, search and resource limits', 'instruction': 'full executor instruction'}}
        body = ('READ-ONLY PLANNING. Review the current roadmap and previous workflow evidence, then select one bounded item. '
                'Do not perform implementation, solve, train, or change the roadmap in this turn. '
                'Separate valid negative experiment evidence from acceptance of a finished product.\n'
                'Separate executor-turn budgets from numerical launch budgets. For one-shot work, include read-only '
                'environment and permission checks before any attempt claim or terminal experiment record. '
                'Do not invent a numerical attempt for a permission failure before launch.\n'
                f'User direction: {data.get("direction", "Follow the current roadmap within existing authorization.")}\n'
                f'Previous result/review: {data.get("last_summary", "none")}\n')
    else:
        assignment = data['assignment']
        body = 'Frozen assignment (unchanged throughout this item):\n' + json.dumps(assignment, ensure_ascii=False, indent=2) + '\n'
        if phase == 'executing':
            body += (f'EXECUTION attempt {data["attempts"]}/{data.get("attempt_limit", 3)}. Implement only the frozen assignment and run only its permitted checks. '
                     'This counter counts executor turns, not numerical launches; use the project attempt registry for launch counts. '
                     'Before entering a one-shot runner, check required environment capabilities without launching numerical work. '
                     'If a read-only check such as ps is denied by the sandbox, use the available tool approval/escalation flow '
                     'for that check according to the governing tool instructions; never bypass the check or treat denial as proof of concurrency. '
                     'Approval of a standalone command does not grant permission to a Python subprocess. '
                     'Resolve the runner execution permissions before launch. If approval is unavailable or denied, report the infrastructure blocker '
                     'and actual claim count. Never replay a claimed attempt, overwrite terminal evidence, or relax a frozen contract to recover. '
                     'Stop at the assignment boundary. Report failures and unresolved questions honestly.\n'
                     f'Reviewer correction, if any: {data.get("revision", "none")}\n')
            schema = {'marker': marker, 'decision': 'RESULT', 'step_id': assignment['step_id'],
                      'summary': 'what changed and what remains unresolved', 'evidence': ['exact artifact paths and measured checks']}
        else:
            body += ('INDEPENDENT REVIEW. Inspect the actual evidence and relevant files; do not merely trust the executor summary. '
                     'Do not implement fixes. Review every frozen criterion in its original order. '
                     'If accepted, record this exact item in the roadmap only when project rules permit. '
                     'Do not authorize gated numerical work or claim a product accepted from a diagnostic result.\n'
                     f'Executor result:\n{data["execution_result"]}\n')
            schema = {'marker': marker, 'decision': 'ACCEPTED or REVISE', 'step_id': assignment['step_id'],
                'checks': [{'criterion': i, 'passed': False, 'evidence': ['specific inspected evidence']} for i in range(1, len(assignment['criteria'])+1)],
                'human_gate_remaining': False, 'scope_unchanged': True, 'instruction': 'bounded correction if REVISE', 'summary': 'review finding'}
    return common + body + '\nResult schema:\n' + json.dumps(schema, indent=2) + '\nOr blocked:\n' + json.dumps(blocked)
