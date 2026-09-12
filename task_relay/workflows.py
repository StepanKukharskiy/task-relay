"""Service-owned bounded planning/execution/review, with no coordinator LLM."""
import json
from pathlib import Path
import re
import time
import uuid

from task_relay import workflow_protocol as protocol

TERMINAL = ('paused', 'stopped', 'completed')
WAITING = ('planning', 'executing', 'reviewing', 'recovery_planning')


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS workflows (
        name TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS workflow_events (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL,
        kind TEXT NOT NULL, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS workflow_dispatches (
        marker TEXT PRIMARY KEY, name TEXT NOT NULL, thread_id TEXT NOT NULL,
        prompt TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL);
    ''')


def read(state, name):
    row = state.db.execute('SELECT * FROM workflows WHERE name=?', (name,)).fetchone()
    if not row:
        raise ValueError('Workflow not found. Use /workflow to list linked projects.')
    return json.loads(row['data']), row['revision']


def event(state, name, kind, data):
    state.db.execute('INSERT INTO workflow_events(name,created,kind,data) VALUES (?,?,?,?)',
                     (name, time.time(), kind, json.dumps(data, ensure_ascii=False)))


def save(state, data, revision, kind):
    updated = state.db.execute('UPDATE workflows SET data=?,revision=revision+1 WHERE name=? AND revision=?',
        (json.dumps(data, ensure_ascii=False), data['name'], revision)).rowcount
    if not updated:
        raise ValueError('Workflow changed while processing; no new instruction was sent.')
    event(state, data['name'], kind, data)


def notice(state, data, text, key):
    # Agent handoff JSON is retained in the ledger, not shown as product UI.
    text = re.sub(r'```relay-result\s*\n.*?\n```', '', text, flags=re.S).strip()
    state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
        (f'workflow:{data["name"]}:{data["run_id"]}:{key}', data['strategy_id'],
         f'Workflow: {data["name"]}\n{text}\n\n{data["accepted"]}/{data["step_limit"]} items accepted; '
         f'executor turns used: {data["attempts"]}/{data.get("attempt_limit", 3)} for this item.\n/workflow status {data["name"]}'))


def owns_turn(state, thread_id, turn_id):
    """Suppress routine workflow-turn notifications, never unrelated user work."""
    if state.db.execute("SELECT 1 FROM workflow_events WHERE kind='turn_result' AND json_extract(data,'$.turn_id')=? AND json_extract(data,'$.operation.thread_id')=?", (turn_id, thread_id)).fetchone():
        return True
    for row in state.db.execute('SELECT data FROM workflows'):
        data = json.loads(row[0]); op = data.get('operation', {})
        if op.get('thread_id') != thread_id or not op.get('path'):
            continue
        if op.get('turn_id') == turn_id:
            return True
        try:
            result = protocol.turn_result(op['path'], marker=op.get('marker'), offset=op.get('offset',0))
        except (ValueError, OSError):
            continue
        if result['found'] and result['turn_id'] == turn_id:
            return True
    return False


def pause(state, data, revision, reason):
    data['status'], data['reason'] = 'paused', reason
    with state.db:
        save(state, data, revision, 'paused')
        notice(state, data, reason, 'paused:' + str(revision))


def status_text(data):
    return (f'{data["name"]}: {data["status"]} · {data["phase"]}\n'
            f'{data["accepted"]}/{data["step_limit"]} accepted; executor turns used: {data["attempts"]}/{data.get("attempt_limit", 3)}\n'
            f'Strategy: {data["strategy_title"]}\nExecution: {data["executor_title"]}\n'
            f'Step: {data.get("assignment", {}).get("step_id", "not selected")}\n'
            + (data.get('reason') or data.get('wait_reason') or ''))


def user_intervention(state, thread_id):
    """A direct user instruction takes control back from the workflow."""
    in_flight = False
    for row in state.db.execute('SELECT name FROM workflows').fetchall():
        data, rev = read(state, row[0])
        if data['status'] == 'active' and thread_id in (data['strategy_id'], data['executor_id']):
            in_flight |= data['phase'] == 'dispatching'
            pause(state, data, rev, 'A direct user instruction paused automatic handoffs.')
    return in_flight




def command(bridge, arg, update_id, source_request=None):
    parts = arg.split(maxsplit=3)
    action = parts[0].lower() if parts else 'list'
    state = bridge.state
    if action in ('list', 'status') and len(parts) < 2:
        rows = state.db.execute('SELECT data FROM workflows ORDER BY name').fetchall()
        bridge.send('\n\n'.join(status_text(json.loads(r[0])) for r in rows) or
                    'No linked workflows. Use /workflow link NAME STRATEGY_ID EXECUTOR_ID.')
        return
    if action == 'link':
        if len(parts) != 4 or not re.fullmatch('[a-z0-9-]{1,40}', parts[1]):
            raise ValueError('Use /workflow link NAME STRATEGY_ID EXECUTOR_ID (name: lowercase letters, numbers, hyphens).')
        from task_relay.bridge import local_tasks
        tasks = {t['id']: t for t in local_tasks()}
        name, sid, eid = parts[1:]
        if sid == eid or sid not in tasks or eid not in tasks or Path(tasks[sid]['cwd']).resolve() != Path(tasks[eid]['cwd']).resolve():
            raise ValueError('Choose two different existing Codex tasks in the same project folder.')
        if state.db.execute('SELECT 1 FROM workflows WHERE name=?', (name,)).fetchone():
            raise ValueError('That workflow name is already linked.')
        data = {'name': name, 'cwd': str(Path(tasks[sid]['cwd']).resolve()), 'strategy_id': sid,
                'executor_id': eid, 'strategy_title': tasks[sid]['name'] or name + ' strategy',
                'executor_title': tasks[eid]['name'] or name + ' execution', 'status': 'paused',
                'phase': 'new', 'accepted': 0, 'step_limit': 1, 'attempts': 0, 'run_id': uuid.uuid4().hex,
                'planning_only': False, 'reason': 'Linked; no work started.'}
        with state.db:
            state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)', (name, json.dumps(data)))
            event(state, name, 'linked', data)
            state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'handled', sid))
        bridge.send(status_text(data), sid)
        return
    if len(parts) < 2:
        raise ValueError('Use /workflow status|run|plan|pause|resume|stop NAME. Run: /workflow run NAME 1 [direction].')
    data, rev = read(state, parts[1])
    if action == 'status':
        bridge.send(status_text(data), data['strategy_id']); return
    if data.get('migrating'):
        raise ValueError('Workflow migration is in progress. Controls will be enabled after the service takes ownership.')
    if action in ('pause', 'stop'):
        data['status'] = 'paused' if action == 'pause' else 'stopped'
        data['reason'] = 'User paused further handoffs.' if action == 'pause' else 'User stopped this run.'
    elif action == 'resume':
        if data['status'] != 'paused' or data['phase'] not in (*WAITING, 'plan_ready', 'execute_ready', 'review_ready') or data.get('blocked'):
            raise ValueError('This run cannot resume automatically. Use /workflow plan NAME [direction] for planning, or /workflow run NAME 1 [direction] to authorize a new item.')
        data['status'], data['reason'] = 'active', ''
    elif action in ('run', 'plan'):
        if data['status'] == 'active':
            raise ValueError('This workflow already has an active run. Pause or stop it first.')
        if data.get('operation') and data['phase'] in (*WAITING, 'dispatching') and not data.get('blocked'):
            raise ValueError('A dispatched turn still needs reconciliation. Resume its observation before starting a new run.')
        limit = parts[2] if len(parts) > 2 and action == 'run' else '1'
        if not limit.isascii() or not limit.isdigit() or not 1 <= int(limit) <= 10:
            raise ValueError('Choose an explicit budget from 1 to 10 accepted items: /workflow run NAME 1 [direction].')
        direction = (parts[3] if len(parts) > 3 else '') if action == 'run' else ' '.join(parts[2:])
        event(state, data['name'], 'previous_run', data)
        data = {k: data[k] for k in ('name', 'cwd', 'strategy_id', 'executor_id', 'strategy_title', 'executor_title') } | {
            'status': 'active', 'phase': 'plan_ready', 'run_id': uuid.uuid4().hex, 'accepted': 0,
            'step_limit': int(limit), 'attempts': 0, 'planning_only': action == 'plan',
            'direction': direction or 'Follow the current roadmap within existing authorization.',
            'last_summary': data.get('last_summary', data.get('reason', '')), 'reason': ''}
        if source_request is not None:
            # Relay-owned provenance, copied from the received user message, never
            # reconstructed from an LLM's proposed planning summary.
            data['source_request'] = source_request
    else:
        raise ValueError('Unknown workflow action. Use status, run, plan, pause, resume, stop, or link.')
    with state.db:
        save(state, data, rev, 'user:' + action)
        state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'handled', data['strategy_id']))
    bridge.send(status_text(data) + ('\nExisting agent work is not interrupted.' if action in ('pause', 'stop') else ''), data['strategy_id'])


class Worker:
    def __init__(self, state, desktop_factory, tasks=None):
        from task_relay.bridge import local_tasks
        self.state, self.desktop_factory = state, desktop_factory
        self.tasks = tasks or local_tasks
        self.cursor = 0

    def tick(self):
        if not self.state.get('workflow_service_enabled', False):
            return
        rows = self.state.db.execute('SELECT name FROM workflows ORDER BY name').fetchall()
        if not rows:
            return
        name = rows[self.cursor % len(rows)][0]; self.cursor += 1
        data, rev = read(self.state, name)
        if data['status'] != 'active':
            return
        try:
            self.advance(data, rev)
        except (ValueError, OSError) as exc:
            # A concurrent user pause wins over this worker's stale snapshot.
            latest, current = read(self.state, name)
            if current == rev and latest['status'] == 'active':
                latest['blocked'] = True
                pause(self.state, latest, current, str(exc))

    def available(self, data, tasks):
        if self.state.db.execute("SELECT 1 FROM task_routes WHERE cwd=? AND status IN ('queued','opening','submitting','uncertain')", (data['cwd'],)).fetchone():
            return False
        from task_relay.bridge import recent_status
        for tid in (data['strategy_id'], data['executor_id']):
            if tid not in tasks or str(Path(tasks[tid]['cwd']).resolve()) != data['cwd']:
                raise ValueError('Linked task is missing, archived, or has moved project folders.')
        for t in tasks.values():
            if str(Path(t['cwd']).resolve()) == data['cwd'] and recent_status(t['rollout_path']) != 'idle':
                return False
        for row in self.state.db.execute('SELECT data FROM workflows WHERE name!=?', (data['name'],)):
            other = json.loads(row[0])
            if other['cwd'] == data['cwd'] and other.get('operation') and other['phase'] in (*WAITING, 'dispatching'):
                return False
        if self.state.db.execute("SELECT 1 FROM backend_tasks t JOIN backend_jobs j ON j.thread_id=t.id WHERE t.cwd=? AND j.status IN ('queued','running','waiting')", (data['cwd'],)).fetchone():
            return False
        # An unresolved ordinary Telegram submission also owns the project.
        tids = [t['id'] for t in tasks.values() if str(Path(t['cwd']).resolve()) == data['cwd']]
        return not any(self.state.db.execute("SELECT 1 FROM incoming WHERE thread_id=? AND status IN ('received','submitting')", (tid,)).fetchone() for tid in tids)

    def advance(self, data, rev):
        from task_relay.bridge import recent_status
        phase = data['phase']
        tasks = {t['id']: t for t in self.tasks()}
        if phase in ('plan_ready', 'execute_ready', 'review_ready'):
            if not self.available(data, tasks):
                return
            self.dispatch(data, rev, tasks)
            return
        if phase == 'dispatching':
            # Only a restart can leave this phase for a later worker tick.
            data['blocked'] = True
            pause(self.state, data, rev, 'Relay restarted during a workflow handoff. Delivery is uncertain; it will not be replayed. Inspect the target task before authorizing a new run.')
            return
        if phase not in WAITING:
            raise ValueError('Unknown workflow phase')
        op = data['operation']
        task = tasks.get(op['thread_id'])
        if not task or str(Path(task['cwd']).resolve()) != data['cwd']:
            raise ValueError('Workflow target is missing or changed folders')
        if task['rollout_path'] != op['path']:
            raise ValueError('Workflow history moved; inspect the task before continuing')
        if recent_status(op['path']) != 'idle':
            return
        result = protocol.turn_result(op['path'], op.get('turn_id'), op.get('marker'), op.get('offset', 0))
        if result['aborted']:
            raise ValueError('Workflow turn was interrupted; no next stage was started')
        if result['text'] is None:
            raise ValueError('The dispatched turn cannot be confirmed in the task history; no replay was attempted')
        text = result['text']
        with self.state.db:
            event(self.state, data['name'], 'turn_result', {'operation': op, 'turn_id': result['turn_id'], 'text': text})
        data['last_summary'] = text
        data.pop('operation', None)
        if phase == 'recovery_planning' or data.get('planning_only') and phase == 'planning':
            data['phase'], data['blocked'] = 'plan_review', True
            pause(self.state, data, rev, 'Planning-only result ready. Execution has not been authorized.\n\n' + text)
            return
        parsed = protocol.response(text, op['marker'], phase, data.get('assignment'))
        if parsed['decision'] == 'BLOCKED':
            data['blocked'] = True
            pause(self.state, data, rev, parsed['reason'])
            return
        if phase == 'planning':
            if parsed['plan']['step_id'] in data.get('accepted_steps', []):
                raise ValueError('Planner selected an already accepted item; no repeated execution started')
            data['assignment'] = parsed['plan']; data['attempts'] = 0
            data['phase'] = 'execute_ready'; data.pop('revision', None)
        elif phase == 'executing':
            data['execution_result'] = text; data['phase'] = 'review_ready'
        elif parsed['decision'] == 'ACCEPTED':
            data['accepted'] += 1
            data.setdefault('accepted_steps', []).append(data['assignment']['step_id'])
            data['status'] = 'completed' if data['accepted'] >= data['step_limit'] else 'active'
            data['phase'] = 'done' if data['status'] == 'completed' else 'plan_ready'
        elif data['attempts'] >= data.get('attempt_limit', 3):
            data['blocked'] = True
            pause(self.state, data, rev, 'Execution attempt limit reached. Reviewer still requests changes; no further revision started.\n\n' + text)
            return
        else:
            data['revision'] = parsed['instruction']; data['phase'] = 'execute_ready'
        with self.state.db:
            save(self.state, data, rev, 'advanced')
            if parsed['decision'] == 'ACCEPTED':
                notice(self.state, data, 'Accepted: ' + data['assignment']['step_id'] + '\n' + text,
                       'accepted:' + str(data['accepted']))

    def dispatch(self, data, rev, tasks):
        from task_relay.bridge import complete_offset, BridgeError
        phase = {'plan_ready': 'planning', 'execute_ready': 'executing', 'review_ready': 'reviewing'}[data['phase']]
        if phase == 'executing':
            if data['attempts'] >= data.get('attempt_limit', 3):
                raise ValueError('Execution attempt limit reached')
            protocol.plan(data['assignment']); data['attempts'] += 1
        tid = data['executor_id'] if phase == 'executing' else data['strategy_id']
        marker = '[relay-workflow:' + uuid.uuid4().hex + ']'
        prompt = protocol.prompt(data, phase, marker)
        if len(prompt) > 180000:
            raise ValueError('Workflow handoff exceeds the prompt limit')
        with self.desktop_factory() as desktop:
            owner = desktop.ready_owner(tid)
            refreshed = {t['id']: t for t in self.tasks()}
            if not self.available(data, refreshed):
                return
            path = refreshed[tid]['rollout_path']
            offset = complete_offset(path)
            data['operation'] = {'marker': marker, 'thread_id': tid, 'path': path, 'offset': offset, 'phase': phase}
            data['phase'] = 'dispatching'
            with self.state.db:
                save(self.state, data, rev, 'dispatch_claimed')
                self.state.db.execute('INSERT INTO workflow_dispatches VALUES (?,?,?,?,?,?)',
                    (marker, data['name'], tid, prompt, 'submitting', time.time()))
            try:
                desktop.start(tid, prompt, owner)
            except Exception:
                latest, current = read(self.state, data['name'])
                latest['blocked'] = True
                with self.state.db:
                    self.state.db.execute("UPDATE workflow_dispatches SET status='uncertain' WHERE marker=?", (marker,))
                pause(self.state, latest, current, 'Workflow instruction delivery is uncertain. Check the target task; the relay will not resend it.')
                return
        # Preserve user pause/stop received while IPC was in flight.
        latest, current = read(self.state, data['name'])
        latest['phase'] = phase
        with self.state.db:
            self.state.db.execute("UPDATE workflow_dispatches SET status='submitted' WHERE marker=?", (marker,))
            save(self.state, latest, current, 'dispatch_acknowledged')
