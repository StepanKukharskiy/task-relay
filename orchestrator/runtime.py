"""Durable local graph scheduler built around frozen worker dispatches.

Like workflows.py, claims precede transport and ambiguous launches never replay.
Unlike linked workflows, this runtime owns worker creation and artifact copies.
"""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid

from . import contracts as c
from . import storage
from . import execution
from .adapters import ExecutionFactory

ACTIVE = ('launching', 'running', 'cancelling', 'uncertain')


def blocked_report_text(result):
    reasons=[f"Criterion {check['criterion']}: {check['evidence'][:1000]}" for check in result['checks'] if not check['passed']]
    if result.get('instruction'):reasons.append('Worker suggestion: '+result['instruction'][:1500])
    reasons.append(result['summary'][:1500])
    return '\n'.join(reasons)


def failure_detail(db,attempt):
    """Expose a validated saved worker blocker without rewriting old receipts."""
    if not attempt:return None
    original=attempt['error']
    revision=db.execute("SELECT e.data FROM production_events e JOIN production_tasks t ON t.run=e.run AND t.id=e.task WHERE e.attempt=? AND e.kind='revision_limit' AND t.latest=e.attempt AND t.status='blocked' ORDER BY e.id DESC LIMIT 1",(attempt['id'],)).fetchone() if db is not None else None
    if revision:
        detail=json.loads(revision['data'])
        return 'Review correction allowance exhausted: '+str(detail.get('instruction','See the saved review.'))[:1800]
    correction=db.execute("SELECT e.data FROM production_events e JOIN production_tasks t ON t.run=e.run AND t.id=e.task WHERE e.attempt=? AND e.kind='review_correction_required' AND t.latest=e.attempt AND t.status='blocked' ORDER BY e.id DESC LIMIT 1",(attempt['id'],)).fetchone() if db is not None else None
    if correction:
        detail=json.loads(correction['data'])
        return 'Review requested corrections: '+detail['summary'][:900]+'\nRequested correction: '+detail['instruction'][:1500]
    receipt=json.loads(attempt['receipt'] or '{}')
    operation=receipt.get('operation') or {}
    if (attempt['state']=='uncertain' and isinstance(operation,dict) and operation.get('outcome')=='uncertain'
        and isinstance(operation.get('reason'),str) and operation['reason'].strip()):
        detail=operation['reason'][:1800]
        category={'connection':'Connection failed','timeout':'Request timed out',
                  'invalid-response':'Invalid response'}.get(operation.get('failure_kind'))
        if category:detail=category+': '+detail
        return detail+'\nOutcome remains unknown. No automatic retry.'
    if attempt['state']!='blocked':return original
    if (original=='Worker failed' and receipt.get('status')=='finished' and isinstance(operation,dict)
        and operation.get('outcome') in ('failed','rejected') and isinstance(operation.get('reason'),str) and operation['reason'].strip()):
        return 'Registered operation failed: '+operation['reason'][:1800]
    if original and not original.startswith(('Missing, linked, or non-regular artifact:',
            'Declared output byte limit exceeded','Input copy changed:')):return original
    receipt=json.loads(attempt['receipt'] or '{}')
    if receipt.get('status')!='finished' or receipt.get('exit_code')!=0:return original
    row=db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='first_response' ORDER BY id LIMIT 1",(attempt['id'],)).fetchone()
    if not row:return original
    try:
        raw=json.loads(row['data'])['text']
        if not isinstance(raw,str) or len(raw)>180000:return original
        result=c.report(json.loads(raw),json.loads(attempt['frozen']))
        if result['decision']!='blocked':return original
        detail=blocked_report_text(result)
        if original and detail in original:return original
        return 'Worker report: '+detail+ ('\nArtifact checks: '+original if original else '')
    except (ValueError,KeyError,TypeError):return original


def dependencies_ready(spec, tasks, specs=()):
    states = {t['id']: t['status'] for t in tasks}
    evidence = c.review_evidence_dependencies(specs).get(spec['id'], set())
    return all(states.get(dep) == 'awaiting_review' if dep == spec.get('review_of') and not spec.get('review_snapshot')
               else states.get(dep) == 'completed' or (dep in evidence and states.get(dep) == 'awaiting_review')
               for dep in spec['dependencies'])


def uncertainty_progress(tasks, specs, attempts, concurrency, locked_resources=()):
    """Describe independent progress without releasing unknown provider calls."""
    roots = {t['id'] for t in tasks if t['status'] == 'uncertain'}
    held = set(roots)
    while True:
        expanded = held | {s['id'] for s in specs if
            (set(s.get('dependencies', ())) | {s.get('review_of')} |
             {i.get('from_task') for i in s.get('inputs', ())}).intersection(held)}
        if expanded == held: break
        held = expanded
    occupied = sum(a['state'] in ACTIVE for a in attempts)
    active = [t['id'] for t in tasks if t['id'] not in held and t['status'] in ('launching', 'running')]
    ready = [t['id'] for t, s in zip(tasks, specs) if t['id'] not in held
             and t['status'] == 'queued' and t['attempts'] < s['max_attempts']
             and dependencies_ready(s, tasks, specs)
             and not (s.get('resource') and s['resource'] in locked_resources)]
    runnable = ready if occupied < concurrency else []
    return {'uncertain_tasks': sorted(roots), 'held_dependents': sorted(held - roots),
            'active_independent': active, 'runnable_independent': runnable,
            'can_continue': bool(active or runnable)}


def stop_status(stored_status, tasks, specs):
    """Shared read-only status derivation for scheduler and conversation snapshots."""
    from .job_owner import state as owner_state
    owned=owner_state(stored_status,tasks,specs)
    if owned is not None:return owned
    if stored_status != 'active':
        return stored_status
    states = {t['status'] for t in tasks}
    if 'uncertain' in states:
        return 'uncertain'
    if 'awaiting_user' in states:
        return 'awaiting_user'
    if states == {'completed'}:
        return 'completed'
    runnable = any(t['status'] == 'queued' and dependencies_ready(a, tasks, specs) for t, a in zip(tasks, specs))
    if not states.intersection(ACTIVE) and not runnable:
        return 'awaiting_user' if 'awaiting_user' in states else 'blocked'
    return 'active'


def settlement(stored_status,tasks,specs):
    """Every stop reason shares one collection-only lifetime."""
    terminal=stop_status(stored_status,tasks,specs)
    pending=[t['id'] for t in tasks if t['status'] in ('launching','running','cancelling')]
    if terminal!='active' and pending:
        return dict(terminal_outcome=terminal,dispatch_allowed=False,pending=pending)
    return None


def run_status(stored_status,tasks,specs):
    return 'active' if settlement(stored_status,tasks,specs) else stop_status(stored_status,tasks,specs)


def uid():
    return uuid.uuid4().hex


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_file(root, relative):
    c.relative(relative)
    root = Path(root).resolve(); current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlinks are not artifact files')
    if not current.is_file() or not stat.S_ISREG(current.stat().st_mode) or current.stat().st_nlink != 1:
        raise ValueError('Missing, linked, or non-regular artifact: ' + relative)
    if not current.resolve().is_relative_to(root):
        raise ValueError('Artifact escapes its workspace')
    return current


class Runtime:
    def __init__(self, root, factory=None, connection=None, *, read_only=False):
        self.root = Path(root).resolve()
        self.read_only = read_only
        if not read_only:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.factory = None if read_only else factory or ExecutionFactory()
        self.owns_connection = connection is None
        path = storage.database_path(self.root)
        self.db = connection if connection is not None else sqlite3.connect(path.as_uri() + '?mode=ro' if read_only else path, uri=read_only, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if self.owns_connection and not read_only:
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
        try:
            if not read_only:
                storage.initialize(self.db, self.root / 'runtime.sqlite')
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        if self.read_only:
            raise ValueError('This runtime view is read-only.')
        with storage.transaction(self.db):
            yield

    def close(self):
        if self.owns_connection:
            self.db.close()

    def event(self, run, task, attempt, kind, data):
        self.db.execute('INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (?,?,?,?,?,?)',
                        (time.time(), run, task, attempt, kind, c.encoded(data)))

    def artifact(self, aid):
        row = self.db.execute('SELECT * FROM production_artifacts WHERE id=?', (aid,)).fetchone()
        if row is None:
            raise ValueError('Unknown artifact ' + aid)
        return dict(row)

    def register(self, source, purpose, run=None, task=None, attempt=None, path=None):
        if not self.db.in_transaction:
            with self.transaction():
                return self._register(source, purpose, run, task, attempt, path)
        return self._register(source, purpose, run, task, attempt, path)

    def _register(self, source, purpose, run, task, attempt, path):
        source = Path(source).absolute()
        # Reject symlinks in every component, including ancestors of external imports.
        safe_file(Path(source.anchor), str(source.relative_to(source.anchor)))
        before = source.stat()
        if before.st_size > 500000000:
            raise ValueError('Artifact exceeds 500 MB')
        aid = uid(); target = self.root / 'artifacts' / aid / 'content'
        target.parent.mkdir(parents=True, mode=0o700)
        shutil.copyfile(source, target)
        after = source.stat()
        sha = file_hash(target)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or sha != file_hash(source):
            raise ValueError('Artifact changed while it was being registered')
        target.chmod(0o400)
        self.db.execute('INSERT INTO production_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)',
            (aid, run, task, attempt, path or source.name, str(target), sha, after.st_size,
             c.nonempty(purpose, 'artifact purpose'), str(source)))
        self.event(run, task, attempt, 'artifact_registered', {'artifact': aid, 'sha256': sha,
            'path': path or source.name, 'purpose': purpose})
        if run and self.db.execute('SELECT 1 FROM production_runs WHERE id=?',(run,)).fetchone():
            from .artifact_replacements import scope,refresh
            refresh(self,scope(self.db,run))
        return aid

    def export(self, run, tid, destination):
        """Copy registered output versions; never trust mutable worker files for delivery."""
        task = self.task(run, tid)
        if not task['latest']:
            raise ValueError('Task has no delivery')
        rows = [dict(a) for a in self.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path', (task['latest'],))]
        if not rows:
            raise ValueError('Task has no registered output files')
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        for artifact in rows:
            if file_hash(artifact['blob']) != artifact['sha256']:
                raise ValueError('Registered output content changed')
            target = destination / artifact['path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact['blob'], target)
        manifest = {'run':run,'task':tid,'attempt':task['latest'],'status':task['status'], 'artifacts':rows,
                    'decisions':[dict(d) for d in self.db.execute('SELECT * FROM production_decisions WHERE run=? AND task=?', (run,tid))]}
        (destination / 'RELAY-DELIVERY.json').write_text(c.encoded(manifest)+'\n')
        return manifest

    def spec(self, task):
        return json.loads(self.db.execute('SELECT spec FROM production_assignments WHERE id=?', (task['assignment'],)).fetchone()[0])

    def quality_review(self, task):
        row=self.db.execute("SELECT data FROM production_events WHERE run=? AND task=? AND attempt=? AND kind='quality_review_required' ORDER BY id DESC LIMIT 1",
            (task['run'],task['id'],task['latest'])).fetchone()
        return json.loads(row['data']) if row else None

    def decision_purpose(self, task):
        from .outcomes import GATE
        return GATE if self.quality_review(task) else self.spec(task).get('user_gate')

    def selection_paths(self, task):
        spec=self.spec(task)
        if self.quality_review(task):return [o['path'] for o in spec['outputs']]
        return spec.get('selection_outputs')

    def task(self, run, tid):
        row = self.db.execute('SELECT * FROM production_tasks WHERE run=? AND id=?', (run, tid)).fetchone()
        if row is None:
            raise ValueError('Unknown task')
        return dict(row)

    def continue_attempt(self, run, tid, parent, *, kind, allocation=None):
        """One atomic checkpoint/review continuation; dispatch stays in tick."""
        from .connector_protocol import receipt as normalize_receipt
        from .continuations import proposal
        from .operation_session import transition
        with self.transaction():
            task=self.task(run,tid)
            attempt=self.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent,)).fetchone()
            if (not attempt or attempt['run']!=run or attempt['task']!=tid
                    or task['latest']!=parent or task['assignment']!=attempt['assignment']
                    or task['status']!='blocked' or attempt['state']!='blocked'
                    or self.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active'):
                return False
            receipt=json.loads(attempt['receipt'] or '{}')
            normalized=normalize_receipt(receipt)
            if normalized['status']!='finished' or receipt.get('cleanup_error'):return False
            if self.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='continuation_committed'",(parent,)).fetchone():return False
            prepared=proposal(self,task,attempt,kind,allocation)
            if not prepared:return False
            action=transition(prepared['outcome'],remaining_attempts=prepared['remaining_attempts'],confirmed=True,unchanged=True)
            if action!='continue_local':return False
            previous=self.spec(task);spec=prepared['spec']
            aid=task['assignment'] if spec==previous else self.new_assignment(run,spec)
            self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,tid))
            detail=dict(version=1,kind=kind,adapter=prepared['adapter'],parent=parent,previous_assignment=task['assignment'],assignment=aid,
                receipt_sha256=c.digest(receipt),proof=prepared['proof'],outcome=prepared['outcome'],
                allocation=prepared['allocation'],action=action,attempts_reset=False,acceptance=False,
                invocation_limits_before=previous['limits'],invocation_limits_after=spec['limits'],
                task_attempt_limit_before=previous['max_attempts'],task_attempt_limit_after=spec['max_attempts'])
            self.event(run,tid,parent,'continuation_committed',detail)
            from .continuation_adapters import definition
            for event,data in definition(kind).events(prepared,attempt,receipt):
                self.event(run,tid,parent,event,data)
            return detail

    def new_assignment(self, run, spec, *, fresh_review=False):
        from .connector_protocol import bind
        spec=bind(spec)
        if fresh_review:
            if not spec.get('review_of'):raise ValueError('Fresh review requires a candidate owner')
            # A new candidate starts a new review obligation. Invocation-level
            # continuation instructions/checkpoints belong to the old candidate
            # and remain in its immutable assignments, attempts and receipts.
            current=self.db.execute('SELECT assignment FROM production_tasks WHERE run=? AND id=?',(run,spec['id'])).fetchone()
            previous=self.spec(current) if current else {}
            if spec.get('revision')==previous.get('revision'):spec.pop('revision',None)
            spec.pop('review_checkpoint',None)
        version = self.db.execute('SELECT coalesce(max(version),0)+1 FROM production_assignments WHERE run=? AND task=?', (run, spec['id'])).fetchone()[0]
        aid = uid()
        self.db.execute('INSERT INTO production_assignments VALUES (?,?,?,?,?)', (aid, run, spec['id'], version, c.encoded(spec)))
        self.event(run, spec['id'], None, 'assignment_created', {'assignment': aid, 'version': version, 'spec': spec})
        return aid

    def create(self, value):
        plan = c.plan(value)
        from .connector_protocol import bind
        plan['tasks']=[bind(a) for a in plan['tasks']]
        from contextlib import nullcontext
        with (nullcontext() if self.db.in_transaction else self.transaction()):
            for a in plan['tasks']:
                for item in a['inputs']:
                    if 'artifact' in item:
                        self.artifact(item['artifact'])
            self.db.execute('INSERT INTO production_runs VALUES (?,?,?)', (plan['id'], c.encoded(plan), 'active'))
            for a in plan['tasks']:
                aid = self.new_assignment(plan['id'], a)
                self.db.execute('INSERT INTO production_tasks(run,id,assignment,status) VALUES (?,?,?,?)',
                                (plan['id'], a['id'], aid, 'queued'))
            self.event(plan['id'], None, None, 'plan_registered', plan)
        return plan['id']

    def replace_future(self, run, value):
        """Revise only a never-dispatched assignment; validate the complete future graph."""
        with self.transaction():
            task = self.task(run, value['id'])
            if task['status'] != 'queued' or task['attempts']:
                raise ValueError('Only never-dispatched assignments may be replanned')
            plan = json.loads(self.db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()[0])
            plan['tasks'] = [value if t['id'] == value['id'] else self.spec(t)
                             for t in self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,))]
            plan = c.plan(plan,bindable_ids={value['id']})
            spec = next(a for a in plan['tasks'] if a['id'] == value['id'])
            # Changing an existing producer cannot silently invalidate its review contract.
            for a in spec['inputs']:
                if 'artifact' in a:
                    self.artifact(a['artifact'])
            aid = self.new_assignment(run, spec)
            self.db.execute('UPDATE production_tasks SET assignment=? WHERE run=? AND id=?', (aid, run, spec['id']))
            self.event(run, spec['id'], None, 'future_assignment_replaced', {'previous': task['assignment'], 'next': aid})

    def add_future(self, run, value):
        """Append a bounded step without editing any existing assignment."""
        return self.add_futures(run, [value])

    def add_futures(self, run, values, *, request_id=None):
        """Admit an owner's delegation batch atomically; the scheduler dispatches later.

        This is the trusted admission interface, not a worker tool or a new
        authorization grant. Callers must apply their saved scope before admission.
        A stable request ID makes an interrupted admission safe to repeat.
        """
        if not isinstance(values,list) or not values:
            raise ValueError('Delegation requires a nonempty assignment batch')
        if request_id is not None:c.label(request_id)
        proposal=c.digest(values)
        with self.transaction():
            row = self.db.execute('SELECT * FROM production_runs WHERE id=?', (run,)).fetchone()
            if request_id is not None:
                previous=self.db.execute("SELECT data FROM production_events WHERE run=? AND kind='future_tasks_added' AND json_extract(data,'$.request_id')=?",(run,request_id)).fetchone()
                if previous:
                    receipt=json.loads(previous['data'])
                    if receipt['proposal_sha256']!=proposal:
                        raise ValueError('Delegation request ID already belongs to a different batch')
                    return receipt
            if row is None or row['status'] != 'active':
                raise ValueError('An active workflow is required')
            plan = json.loads(row['plan'])
            existing={t['id']:t for t in self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,))}
            plan['tasks'] = [self.spec(t) for t in existing.values()] + values
            plan = c.plan(plan,bindable_ids={v['id'] for v in values})
            for previous,compiled in zip(existing.values(),plan['tasks']):
                if self.spec(previous)!=compiled:raise ValueError('Delegation cannot change an existing assignment')
            from .connector_protocol import bind
            specs=[bind(spec) for spec in plan['tasks'][len(existing):]]
            for spec in specs:
                target=existing.get(spec.get('review_of'))
                from .review_snapshot import check as check_snapshot
                if spec.get('review_snapshot') and plan.get('job_owner',{}).get('review_snapshot_version')!=1:raise ValueError('Snapshot reviews require a prospective owner grant')
                check_snapshot(self,run,spec)
                if target and target['attempts'] and not spec.get('review_snapshot'):
                    raise ValueError('A review gate must be defined before its producer starts')
                for item in spec['inputs']:
                    if 'artifact' in item:self.artifact(item['artifact'])
            assignments={}
            for spec in specs:
                aid = self.new_assignment(run, spec)
                self.db.execute('INSERT INTO production_tasks(run,id,assignment,status) VALUES (?,?,?,?)', (run,spec['id'],aid,'queued'))
                assignments[spec['id']]=aid
                self.event(run, spec['id'], None, 'future_task_added', {'assignment': aid})
            receipt=dict(request_id=request_id,proposal_sha256=proposal,assignments=assignments,dispatched=False)
            self.event(run,None,None,'future_tasks_added',receipt)
            return receipt

    def output(self, run, tid, path):
        task = self.task(run, tid)
        row = self.db.execute('SELECT id FROM production_artifacts WHERE attempt=? AND path=?', (task['latest'], path)).fetchone()
        if row is None:
            raise ValueError('Missing upstream artifact ' + tid + '/' + path)
        return self.artifact(row['id'])

    def ready(self, run, spec):
        tasks = self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,)).fetchall()
        return dependencies_ready(spec, tasks, [self.spec(t) for t in tasks])

    def checked_inputs(self, run, spec, backend):
        """Validate exact late-bound sources before creating or spending an attempt."""
        from . import executors
        from .browser_contract import png_input, png_info
        if spec.get('execution'):execution.validate_inputs(spec)
        resolved=[]
        for item in spec['inputs']:
            artifact=self.artifact(item['artifact']) if 'artifact' in item else self.output(run,item['from_task'],item['output'])
            if artifact is None:raise ValueError('Missing upstream artifact: '+item['path'])
            blob=Path(artifact['blob'])
            safe_file(self.root,str(blob.relative_to(self.root)))
            if blob.stat().st_size!=artifact['bytes'] or file_hash(blob)!=artifact['sha256']:
                raise ValueError('Registered artifact content changed: '+item['path'])
            resolved.append({**{k:v for k,v in item.items() if k not in ('native_evidence','sourcing_source_receipt')},'artifact':artifact['id'],'sha256':artifact['sha256'],
                             'bytes':artifact['bytes'],'blob':blob})
        from .computer_review_inputs import review_input
        native_input=review_input(self,run,spec)
        if native_input:
            if native_input['path'] in {i['path'] for i in resolved}|{o['path'] for o in spec['outputs']}:
                raise ValueError('Raw Safari evidence path conflicts with a declared file.')
            resolved.append(native_input)
        from .browser_review_inputs import review_input as browser_review_input
        browser_input=browser_review_input(self,run,spec)
        if browser_input:
            if browser_input['path'] in {i['path'] for i in resolved}|{o['path'] for o in spec['outputs']}:
                raise ValueError('Browser evidence path conflicts with a declared file.')
            resolved.append(browser_input)
        from .execution_evidence import inputs as execution_inputs
        resolved.extend(execution_inputs(self,run,spec,resolved))
        if spec.get('execution'):
            ceiling=execution.REGISTRY[spec['execution']['capability']]['input_bytes']
            if sum(i['bytes'] for i in resolved)>ceiling:
                raise ValueError(f'Registered operation input byte limit exceeded ({ceiling} bytes).')
            if spec['execution']['capability']=='pptx.create':
                from .pptx_document import preflight_inputs
                preflight_inputs(resolved)
            if execution.REGISTRY[spec['execution']['capability']].get('native_adapter')=='record-slides':
                from .sourcing_slides import build
                by_path={i['path']:i for i in resolved}
                build({**spec,'inputs':resolved},lambda p:by_path[p]['blob'].read_bytes())
                from task_relay.external_evidence import recorded_sources
                source=by_path[spec['execution']['parameters']['source_pack_path']]
                if not recorded_sources(self,[source],allow_empty=True):raise ValueError('Sourcing assembly needs exact native saved-page provenance')
        elif backend['type'] in executors.API_TYPES:
            from .evidence_context import bind as bind_evidence_context
            bind_evidence_context(self,run,spec,backend,resolved)
            executors.validate_input_sizes(resolved,backend,spec)
            if backend['type'] not in executors.CODE_TYPES and not spec.get('job_owner'):
                for item in resolved:
                    raw=item['blob'].read_bytes()
                    if (backend['type'] in executors.BROWSER_TYPES or backend['type'] in executors.VISION_FILE_TYPES and item.get('visual_reference')) and png_input(item):png_info(raw)
                    elif executors.inspection_input(spec,item) or executors.asset_input(spec,item):pass # Exact local bytes; inspection and consumption have separate contracts.
                    else:
                        try:raw.decode('utf-8')
                        except UnicodeError:raise ValueError('API executors require UTF-8 text inputs: '+item['path']) from None
        from .worker_tools import native_assignment
        native=native_assignment(spec)
        if native is not None:
            native_inputs=self.checked_inputs(run,native,backend)
            by_path={i['path']:i for i in native_inputs}
            execution.adapter(native['execution']['capability']).validate_content(native,lambda path:by_path[path]['blob'].read_bytes())
        from .record_lifecycle import definition
        hooks=definition(spec['operation_contract']) if spec.get('operation_contract') else None
        if hooks and hooks.preflight:
            by_path={i['path']:i for i in resolved}
            bound={**spec,'inputs':resolved}
            ctx=hooks.context(bound,lambda p:by_path[p]['blob'].read_bytes())
            hooks.preflight(bound,ctx)
            if hooks.review_units:
                from .review_inputs import interface
                cost=interface(bound,lambda p:by_path[p]['blob'].read_bytes())
                if min(executors.request_limit(spec),spec['limits']['tool_calls'])<cost['required_requests']:
                    raise ValueError('Registered review obligations exceed frozen capacity before dispatch')
            from task_relay.external_evidence import recorded_sources
            if hooks.evidence_parameter:
                page_input=by_path[spec['operation_contract']['parameters'][hooks.evidence_parameter]]
                proof=recorded_sources(self,[page_input],allow_empty=True)
                if not proof:raise ValueError('Typed sourcing requires an exact completed native source-pack receipt; supplied JSON cannot assert fetched evidence')
                page_input['sourcing_source_receipt']=proof[0]
        return resolved

    def claim(self, run, authorize=None):
        if self.db.in_transaction:
            raise ValueError('Worker claims require a transaction boundary before transport.')
        with self.transaction():
            row = self.db.execute('SELECT * FROM production_runs WHERE id=?', (run,)).fetchone()
            if row is None:
                raise ValueError('Unknown workflow')
            if row['status'] != 'active':
                return None
            # Collection lifetime and dispatch permission are separate.
            tasks=list(self.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)))
            if stop_status(row['status'],tasks,[self.spec(t) for t in tasks])!='active':return None
            if authorize is not None and not authorize(self,run):return None
            plan = json.loads(row['plan'])
            occupied = self.db.execute("SELECT count(*) FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchone()[0]
            if occupied >= plan['concurrency']:
                return None
            for task in self.db.execute("SELECT * FROM production_tasks WHERE run=? AND status='queued' ORDER BY rowid", (run,)).fetchall():
                spec = self.spec(task)
                try:
                    from .continuations import validate_dispatch as validate_continuation
                    validate_continuation(self,task)
                    from .review_snapshot import check as check_snapshot
                    check_snapshot(self,run,spec)
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                    self.event(run,task['id'],None,'continuation_preflight_blocked',{'reason':str(exc),'dispatched':False})
                    continue
                if not self.ready(run, spec):
                    continue
                from .operation_lifecycle import resources as operation_resources
                required_resources=operation_resources(spec)
                active_specs=[json.loads(a['frozen']) for a in self.db.execute("SELECT frozen FROM production_attempts WHERE state IN ('launching','running','cancelling','uncertain')")]
                if any(required_resources & operation_resources(active) for active in active_specs):continue
                if task['attempts'] >= spec['max_attempts']:
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?", (run, task['id']))
                    self.event(run, task['id'], None, 'attempt_limit',
                        {'assignment':task['assignment'],'attempts':task['attempts'],'max_attempts':spec['max_attempts'],
                         'review_target':self.task(run,spec['review_of'])['latest'] if spec.get('review_of') else None})
                    continue
                if spec.get('execution'):
                    from .execution import available
                    try:
                        available(spec)
                        execution.adapter(spec['execution']['capability']).bind_inputs(self,spec,run=run)
                    except ValueError as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'capability_unavailable',{'reason':str(exc)})
                        continue
                from . import host_code
                authorization=None
                if host_code.required(spec):
                    try:authorization=host_code.approved(self,run,task['id'],spec)
                    except (ValueError,OSError,SyntaxError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'host_code_approval_blocked',{'reason':str(exc)})
                        continue
                from .worker_capabilities import backend_for
                backend=backend_for(spec,plan['backend'])
                if spec.get('execution') and plan.get('job_owner'):
                    from .model_binding import selected
                    backend=selected(plan['job_owner'],spec['execution']['capability'],backend)
                try:
                    resolved_inputs=self.checked_inputs(run,spec,backend)
                    if spec.get('execution'):
                        from .operation_inputs import resolved as check_content_inputs
                        check_content_inputs(spec,resolved_inputs)
                    if spec.get('review_of'):
                        from .artifact_structure import inspect_cached as inspect_structure
                        for item in resolved_inputs:
                            if item.get('from_task')==spec['review_of']:
                                inspect_structure(item,item['blob'].read_bytes(),self.root/'structural-checks')
                except (ValueError,OSError) as exc:
                    from .evidence_context import admission_failure
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                    self.event(run,task['id'],None,'input_preflight_blocked',
                               {'assignment':task['assignment'],'reason':str(exc),'dispatched':False,'failure':admission_failure(exc)})
                    continue
                from task_relay.input_preflight_recovery import validate_dispatch as validate_input_recovery
                if plan.get('origin',{}).get('registered_revision'):
                    from task_relay.registered_revision import validate_dispatch
                    try:validate_dispatch(self,plan)
                    except (ValueError,OSError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'registered_revision_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                try:validate_input_recovery(self,task,resolved_inputs)
                except ValueError as exc:
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                    self.event(run,task['id'],None,'input_recovery_preflight_blocked',{'reason':str(exc),'dispatched':False})
                    continue
                if spec.get('revision',{}).get('kind')=='registered_input_preflight':
                    from task_relay.native_preflight import validate_dispatch
                    try:validate_dispatch(self,task,spec,backend,resolved_inputs)
                    except (ValueError,OSError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'native_preflight_continuation_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                resume_parent=None;review_checkpoint=None
                if spec.get('revision',{}).get('kind')=='local_review_session':
                    from task_relay.local_review import validate_dispatch
                    try:review_checkpoint=validate_dispatch(self,task,spec,backend,resolved_inputs)
                    except (ValueError,OSError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'review_session_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                if spec.get('revision',{}).get('kind')=='confirmed_local_revision':
                    from task_relay.completion_recovery import validate_local_revision
                    try:validate_local_revision(self,task,spec,backend)
                    except (ValueError,OSError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'local_revision_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                if spec.get('revision',{}).get('kind') in ('confirmed_review_generation','confirmed_review_input'):
                    from task_relay.review_budget_recovery import validate_generation_parent
                    try:validate_generation_parent(self,task,spec,backend,resolved_inputs)
                    except (ValueError,OSError) as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'generation_review_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                if spec.get('revision',{}).get('kind')=='saved_review_budget':
                    from task_relay.review_budget_recovery import validate_parent
                    try:validate_parent(self,task,spec,backend,resolved_inputs)
                    except ValueError as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'review_budget_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                if spec.get('revision',{}).get('kind')=='public_photo_setup_recovery':
                    from task_relay.public_photo_recovery import validate_parent
                    try:validate_parent(self,task,spec,backend,resolved_inputs)
                    except ValueError as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'public_photo_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                from .record_recovery import supports
                if supports(spec,'resumable'):
                    from .record_recovery import parent_for,validate_parent
                    try:
                        resume_parent=parent_for(self,task)
                        if resume_parent:
                            preview={**spec,'run':run,'backend':backend,'inputs':resolved_inputs}
                            if spec.get('review_of'):preview['review_target']=self.task(run,spec['review_of'])['latest']
                            validate_parent(self,preview,resume_parent)
                    except ValueError as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'checkpoint_preflight_blocked',{'reason':str(exc),'dispatched':False})
                        continue
                if not spec.get('execution') and hasattr(self.factory,'available'):
                    try:self.factory.available(backend)
                    except ValueError as exc:
                        from .review_recovery import admission_failure
                        detail=admission_failure(self,run,task,spec,backend,resolved_inputs,str(exc))
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'capability_unavailable',detail)
                        continue
                attempt = uid(); workspace = self.root / 'workspaces' / attempt
                workspace.mkdir(parents=True, mode=0o700)
                frozen = copy.deepcopy(spec)
                frozen.pop('computer_review',None)
                frozen['inputs']=[{k:v for k,v in item.items() if k not in ('blob','bytes','native_evidence')} for item in resolved_inputs]
                if frozen.get('artifact_roles'):
                    for item in frozen['inputs']:
                        if item['path'] not in frozen['artifact_roles']['inputs'] and item['path'].startswith('execution-evidence/'):
                            frozen['artifact_roles']['inputs'][item['path']]=dict(origin=dict(kind='inherited',via=['execution_receipt']),consumes=[],inspection=dict(tool='file_read',path=item['path']),provenance=dict(artifact=item['artifact']))
                for item in resolved_inputs:
                    if 'native_evidence' in item:frozen['computer_review']=item['native_evidence']
                # Never trust a model-supplied authorization field.
                frozen.pop('host_code_authorization',None);frozen.pop('authorized_assignment_digest',None)
                if authorization:
                    frozen['host_code_authorization']=authorization
                    frozen['authorized_assignment_digest']=c.digest(spec)
                frozen.update(assignment_id=attempt, assignment_version=task['assignment'],
                              run=run, workspace=str(workspace), brief=plan['brief'], backend=backend)
                from .job_owner import freeze as freeze_owner
                freeze_owner(self,plan,task,frozen)
                from .provider_cooldown import freeze as freeze_cooldown
                freeze_cooldown(self,plan,frozen)
                frozen.pop('review_checkpoint',None)
                if review_checkpoint:frozen['review_checkpoint']=review_checkpoint
                frozen.pop('record_resume',None)
                if resume_parent:frozen['record_resume']={'parent':resume_parent}
                from .review_followup import bind as bind_followup
                bind_followup(self,plan,frozen)
                if not frozen.get('execution'):
                    from .report_builder import freeze as report_form
                    frozen['report_contract']=report_form(frozen)
                from .operation_records import freeze as freeze_records
                freeze_records(frozen,self.db)
                from task_relay.host import support_hashes
                frozen['host_support'] = support_hashes()
                frozen['runtime_sources'] = {p.name: file_hash(p) for p in Path(__file__).parent.glob('*.py')}
                # Pin shared compiler/transport hooks too, including lazy imports.
                frozen['runtime_sources'].update({'task_relay/'+p.name:file_hash(p)
                    for p in (Path(__file__).resolve().parents[1]/'task_relay').glob('*.py')})
                if frozen.get('operation_contract'):
                    from .record_lifecycle import implementation_sources
                    frozen['runtime_sources'].update(implementation_sources(frozen['operation_contract']))
                if frozen.get('execution'):
                    capability=frozen['execution']['capability']
                    execution.adapter(capability).freeze(frozen,execution.REGISTRY[capability])
                if frozen.get('work_tools'):
                    from .worker_tools import freeze as freeze_work
                    freeze_work(frozen,self)
                for item,artifact in zip(frozen['inputs'],resolved_inputs):
                    item.update(artifact=artifact['artifact'], sha256=artifact['sha256'])
                    target = workspace / item['path']; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(artifact['blob'], target); target.chmod(0o400)
                    if file_hash(target)!=artifact['sha256']:raise ValueError('Registered artifact changed while staging: '+item['path'])
                if spec.get('review_of'):
                    frozen['review_target'] = self.task(run, spec['review_of'])['latest']
                relay = workspace / '.relay'; relay.mkdir()
                from task_relay.saved_evidence_revision import stage_helper
                stage_helper(plan,frozen,relay)
                from .verification import stage as stage_verification
                stage_verification(self,plan,frozen,relay)
                if spec.get('review_of') and backend['type']=='codex-cli':
                    target=self.task(run,spec['review_of']);target_spec=self.spec(target)
                    metadata=execution.REGISTRY.get(target_spec.get('execution',{}).get('capability'),{}).get('saved_evidence',{})
                    if metadata.get('kind')=='pages':
                        from .evidence_workload import review_batches
                        packs=[i for i in frozen['inputs'] if i.get('from_task')==target['id'] and i.get('media_type')=='application/json']
                        if len(packs)==1:
                            pack=json.loads(safe_file(workspace,packs[0]['path']).read_text())
                            workload=review_batches(pack,frozen['limits']['tool_calls']);batch_paths=[]
                            for index,batch in enumerate(workload.pop('batches')):
                                path=relay/('evidence-batch-'+str(index+1)+'.json');path.write_text(c.encoded(batch)+'\n');path.chmod(0o400)
                                batch_paths.append(dict(path=str(path.relative_to(workspace)),sha256=file_hash(path)))
                            frozen['evidence_workload']={**workload,'batches':batch_paths,'source_sha256':packs[0]['sha256']}
                (relay / 'ASSIGNMENT.json').write_text(c.encoded(frozen) + '\n')
                session = self.factory.create(self.root / 'workers' / attempt, workspace, frozen, backend)
                self.db.execute('INSERT INTO production_attempts(id,run,task,assignment,state,resource,frozen,session) VALUES (?,?,?,?,?,?,?,?)',
                    (attempt, run, task['id'], task['assignment'], 'launching', spec.get('resource'), c.encoded(frozen), c.encoded(session)))
                if resume_parent:
                    from .record_recovery import seed
                    seed(self,frozen,resume_parent)
                self.db.execute("UPDATE production_tasks SET status='launching',attempts=attempts+1,latest=? WHERE run=? AND id=?",
                                (attempt, run, task['id']))
                self.event(run, task['id'], attempt, 'dispatch_claimed', {'frozen': frozen, 'session': session})
                return session
        return None

    def set_state(self, attempt, status, error=None):
        self.db.execute('UPDATE production_attempts SET state=?,error=? WHERE id=?', (status, error, attempt['id']))
        self.db.execute('UPDATE production_tasks SET status=? WHERE run=? AND id=?', (status, attempt['run'], attempt['task']))

    def reviewer(self, run, tid):
        return next((t for t in self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,)).fetchall()
                     if self.spec(t).get('review_of') == tid and not self.spec(t).get('review_snapshot')), None)

    def retry_review(self,run,tid,instruction,source='user',*,additional_inputs=()):
        """Explicit local API review recovery within its existing attempt budget."""
        from . import executors
        with self.transaction():
            c.nonempty(instruction,'Review recovery request')
            task=self.task(run,tid);spec=self.spec(task)
            if task['status']!='blocked' or not spec.get('review_of') or spec.get('browser') or spec.get('execution'):
                raise ValueError('Only a stopped local review can recover here.')
            if task['attempts']>=spec['max_attempts']:raise ValueError('Review attempt budget exhausted.')
            if self.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0]!='active':
                raise ValueError('Paused or cancelled work cannot recover here.')
            attempt=self.db.execute('SELECT * FROM production_attempts WHERE id=?',(task['latest'],)).fetchone()
            frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
            backend=frozen['backend']['type']
            confirmed=(receipt.get('external_outcome')=='no_pending_response' or
                       backend=='codex-cli' and receipt.get('exit_code')==0 and receipt.get('external_outcome') is None)
            if (attempt['state']!='blocked' or receipt.get('status')!='finished'
                or not confirmed or receipt.get('pending_requests')
                or backend not in (*executors.FILE_TYPES,*executors.CODE_TYPES,'codex-cli')):
                raise ValueError('Confirmed finished API review with no pending response is required; no uncertain replay.')
            target=self.task(run,spec['review_of'])
            if target['status']!='awaiting_review' or target['latest']!=frozen['review_target']:
                raise ValueError('The exact review target changed.')
            for other in self.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)):
                if other['status'] in ACTIVE or (other['attempts'] and tid in self.spec(other)['dependencies']):
                    raise ValueError('Active or downstream work prevents review recovery.')
            added=[]
            if not isinstance(additional_inputs,(list,tuple)) or len(additional_inputs)>4:
                raise ValueError('Review recovery permits at most four declared text support inputs.')
            paths={i['path'] for i in spec['inputs']}
            from .worker_capabilities import TEXT_TYPES
            for item in additional_inputs:
                if not isinstance(item,dict) or not item.get('artifact') or item.get('media_type') not in TEXT_TYPES or item.get('path') in paths:
                    raise ValueError('Review recovery requires distinct immutable text support artifacts.')
                artifact=self.artifact(item['artifact'])
                paths.add(item['path']);spec['inputs'].append(dict(item))
                added.append({'artifact':artifact['id'],'path':item['path'],'sha256':artifact['sha256'],'bytes':artifact['bytes']})
            spec['revision']={'instruction':instruction,'source':source,'previous_attempt':attempt['id']}
            if added:spec['revision']['added_inputs']=added
            aid=self.new_assignment(run,c.assignment(spec))
            self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,tid))
            self.event(run,tid,attempt['id'],'review_retry_requested',spec['revision'])

    def revise(self, run, tid, instruction, source='user'):
        with self.transaction():
            self._revise(run, tid, instruction, source)

    def _revise(self, run, tid, instruction, source):
        task = self.task(run, tid); spec = self.spec(task)
        from .corrections import layout_task, schedule_specification
        if layout_task(spec):
            if schedule_specification(self,run,tid,instruction,source):return
            self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,tid))
            self.event(run,tid,task['latest'],'correction_limit',dict(instruction=instruction,source=source,reason='Native specification has no remaining permitted layout correction; retained findings require different work.'))
            return
        if spec.get('review_correction'):
            from .corrections import schedule
            if schedule(self,run,tid,instruction,source):return
        if task['status'] in ACTIVE or spec.get('review_of') or not task['latest']:
            raise ValueError('Cannot revise an active, unstarted, or reviewer assignment')
        reviewer = self.reviewer(run, tid)
        if reviewer and reviewer['status'] in ACTIVE:
            raise ValueError('Cannot revise during an active review')
        # No already dispatched downstream task may silently retain an obsolete version.
        for other in self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,)).fetchall():
            if other['attempts'] and tid in self.spec(other)['dependencies'] and (not reviewer or other['id'] != reviewer['id']):
                raise ValueError('Downstream work already started; create a new explicit workflow')
        limit=spec['max_attempts']
        for downstream in self.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)):
            if self.spec(downstream).get('review_correction',{}).get('producer')==tid and downstream['attempts']==0:
                limit=min(limit,2)  # Reserve the third draft for a built-document correction.
        review_exhausted=bool(reviewer and reviewer['attempts']>=self.spec(reviewer)['max_attempts'])
        if task['attempts'] >= limit or review_exhausted:
            self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?", (run, tid))
            self.event(run, tid, task['latest'], 'revision_limit', {'instruction': instruction, 'source': source,
                'code':'review_capacity_exhausted' if review_exhausted else 'producer_capacity_exhausted'})
            return
        c.nonempty(instruction, 'revision instruction')
        spec['revision'] = {'instruction': instruction, 'source': source, 'previous_attempt': task['latest']}
        # Prior output versions remain immutable and are explicitly passed for revision.
        spec['inputs'] = [i for i in spec['inputs'] if not i.get('previous_delivery')]
        for a in self.db.execute('SELECT * FROM production_artifacts WHERE attempt=?', (task['latest'],)):
            spec['inputs'].append({'artifact': a['id'], 'path': 'previous/' + a['path'],
                'purpose': 'Previous delivery to revise', 'authority': 'Prior candidate, not user approval',
                'previous_delivery': True})
        if reviewer and source=='model_review:'+str(reviewer['latest']):
            for a in self.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(reviewer['latest'],)):
                spec['inputs'].append({'artifact':a['id'],'path':'previous-review/'+a['path'],
                    'purpose':'Exact independent review of the previous candidate',
                    'authority':'Review evidence for correction, not user approval','previous_delivery':True})
        spec = c.assignment(spec)
        review_spec=self.spec(reviewer) if reviewer else None
        if spec.get('design_intent_state') and (source=='user' or source.startswith('telegram:')):
            from task_relay.design_intent import feedback_record, bind
            record=feedback_record(spec['design_intent_state'],instruction,source)
            bind([spec]+([review_spec] if review_spec else []),record)
            spec=c.assignment(spec)
        aid = self.new_assignment(run, spec)
        self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?", (aid, run, tid))
        if reviewer:
            aid = self.new_assignment(run, c.assignment(review_spec),fresh_review=True)
            self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?", (aid, run, reviewer['id']))
        self.event(run, tid, task['latest'], 'revision_requested', spec['revision'])

    def preserve_stopped_outputs(self, attempt_id):
        """Snapshot declared drafts after a confirmed stop, without advancing state."""
        attempt = self.db.execute('SELECT * FROM production_attempts WHERE id=?', (attempt_id,)).fetchone()
        receipt = json.loads(attempt['receipt'] or '{}') if attempt else {}
        stopped=receipt.get('status')=='finished' or (receipt.get('status')=='uncertain' and receipt.get('local_terminal') is True)
        if not attempt or attempt['state'] not in ('blocked', 'cancelled') or not stopped:
            raise ValueError('Draft recovery requires a terminal attempt and a confirmed stopped worker.')
        old = self.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='draft_outputs_preserved'", (attempt_id,)).fetchone()
        if old:
            return json.loads(old['data'])
        frozen = json.loads(attempt['frozen']); workspace = Path(frozen['workspace'])
        result = {'artifacts': [], 'failures': [], 'approved': False}
        total = 0
        for output in frozen['outputs']:
            try:
                if output==frozen.get('work_tools',{}).get('diagnostics'):
                    from .operation_diagnostics import verify_projection
                    verify_projection(frozen,Path(json.loads(attempt['session'])['control']))
                path = safe_file(workspace, output['path']); total += path.stat().st_size
                if total > frozen['limits']['output_bytes']:
                    raise ValueError('Declared output byte limit exceeded')
                existing = self.db.execute('SELECT id FROM production_artifacts WHERE attempt=? AND path=?', (attempt_id, output['path'])).fetchone()
                aid = existing['id'] if existing else self.register(path,
                    'Unreviewed draft from stopped worker: ' + output['purpose'],
                    attempt['run'], attempt['task'], attempt_id, output['path'])
                result['artifacts'].append(aid)
            except (ValueError, OSError) as exc:
                result['failures'].append(output['path'] + ': ' + str(exc))
        self.event(attempt['run'], attempt['task'], attempt_id, 'draft_outputs_preserved', result)
        return result

    def collect(self, attempt, receipt):
        with self.transaction():
            from .job_owner import collect as collect_owner
            if collect_owner(self,attempt,receipt):return
            self._collect(attempt, receipt)
            from .record_recovery import queue as queue_record_resume
            queue_record_resume(self,attempt,receipt)
            from task_relay.execution_capture import notify
            notify(self.db, 'production_attempt', attempt['id'])

    def _collect(self, attempt, receipt):
        frozen = json.loads(attempt['frozen']); workspace = Path(frozen['workspace'])
        calls=receipt.get('tool_calls')
        if calls is not None and (type(calls) is not int or calls<0):
            receipt={**receipt,'reason':receipt.get('reason') or 'invalid_tool_count'}
        if type(calls) is int and calls > frozen['limits']['tool_calls'] and not receipt.get('reason'):
            receipt = {**receipt, 'reason':'tool_limit'}
        if not self.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='worker_started'", (attempt['id'],)).fetchone():
            self.event(attempt['run'], attempt['task'], attempt['id'], 'worker_started',
                       {'observed_at_completion': True, 'started': receipt.get('started'), 'thread_id': receipt.get('thread_id')})
        self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?', (c.encoded(receipt), attempt['id']))
        self.event(attempt['run'], attempt['task'], attempt['id'], 'worker_finished', receipt)
        if receipt.get('reason') or receipt.get('exit_code') != 0 or attempt['state'] == 'cancelling':
            state = 'cancelled' if receipt.get('reason') == 'cancelled' or attempt['state'] == 'cancelling' else 'blocked'
            self.set_state(attempt, state, receipt.get('reason') or 'Worker failed')
            self.preserve_stopped_outputs(attempt['id'])
            if (state=='blocked' and frozen.get('review_correction')
                    and receipt.get('operation',{}).get('outcome')=='failed'):
                from .corrections import schedule
                schedule(self,attempt['run'],attempt['task'],
                    'Correct the saved specification using this local operation failure receipt: '+c.encoded(receipt['operation']),
                    'local_operation_failure:'+attempt['id'])
            return
        try:
            from .record_tool import reconcile as reconcile_fragments
            reconcile_fragments(frozen,self.db)
        except (ValueError,OSError) as exc:
            self.set_state(attempt,'blocked',str(exc));return
        artifacts, failures = [], []
        total = 0
        for output in frozen['outputs']:
            try:
                path = safe_file(workspace, output['path']); total += path.stat().st_size
                if total > frozen['limits']['output_bytes']:
                    raise ValueError('Declared output byte limit exceeded')
                if output.get('handoff'):
                    from .handoff_contracts import check_file
                    check_file(path,output['handoff'])
                artifacts.append(self.register(path, output['purpose'], attempt['run'], attempt['task'], attempt['id'], output['path']))
            except (ValueError, OSError) as exc:
                failures.append(str(exc))
        self.event(attempt['run'], attempt['task'], attempt['id'], 'output_delivered', {'artifacts': artifacts})
        try:
            if frozen.get('work_tools'):
                from .worker_tools import verify_delivery
                verify_delivery(frozen,Path(json.loads(attempt['session'])['control']),self.db)
            from .browser_contract import validate_captures
            validate_captures(frozen,workspace)
            from .host_script import validate_prepared
            validate_prepared(frozen, workspace)
            from .artifact_structure import check_outputs as inspect_outputs
            structure=inspect_outputs(frozen,lambda path:safe_file(workspace,path).read_bytes(),self.root/'structural-checks')
            if structure:self.event(attempt['run'],attempt['task'],attempt['id'],'artifact_structure_checked',dict(checks=structure,acceptance=False))
            from .deliverable_outputs import check_delivery as check_outputs
            check_outputs(frozen,lambda path:safe_file(workspace,path).read_bytes())
            from task_relay.registered_revision import check_output as check_revision_output
            check_revision_output(self,frozen,lambda path:safe_file(workspace,path).read_bytes())
            from .text_outputs import check_delivery
            check_delivery(frozen,lambda path:safe_file(workspace,path).read_bytes())
        except (ValueError, OSError) as exc:
            failures.append(str(exc))
        for item in frozen['inputs']:
            try:
                if file_hash(safe_file(workspace, item['path'])) != item['sha256']:
                    failures.append('Input copy changed: ' + item['path'])
            except (OSError, ValueError) as exc:
                failures.append(str(exc))
        self.event(attempt['run'], attempt['task'], attempt['id'], 'checks_recorded',
            {'kind': 'procedural', 'checks': ['declared files present, regular and bounded', 'input copies unchanged'], 'passed': not failures, 'failures': failures})
        try:
            result_path = workspace / '.relay/result.json'
            if (workspace / '.relay').is_symlink() or result_path.is_symlink() or not result_path.is_file() or result_path.stat().st_size > 180000:
                raise ValueError('Missing or oversized structured result')
            raw = result_path.read_text()
            self.event(attempt['run'], attempt['task'], attempt['id'], 'first_response', {'text': raw})
            result = c.report(json.loads(raw), frozen)
            if frozen.get('computer') and result['decision']!='blocked':
                from .computer_review_inputs import validate_delivery
                validate_delivery(self.db,attempt['id'])
                from .research_quality import check_delivery
                pack=None
                if frozen.get('research_delivery'):
                    from .computer_review_inputs import capture_pack
                    pack=capture_pack(self.db,frozen,self.root/'workers'/attempt['id']/'computer-evidence')
                check_delivery(frozen,lambda p:safe_file(workspace,p).read_bytes(),pack)
            if frozen.get('operation_contract') and result['decision']!='blocked':
                from .operation_records import Store
                store=Store(frozen,self.db)
                store.verify_export(lambda p:safe_file(workspace,p).read_bytes())
                store.verify_result(result)
            if failures and result['decision'] != 'blocked':
                raise ValueError('; '.join(failures))
        except (ValueError, OSError) as exc:
            self.set_state(attempt, 'blocked', str(exc)); return
        self.event(attempt['run'], attempt['task'], attempt['id'], 'checks_recorded', {
            'kind': 'registered_operation' if frozen.get('execution') else 'model_review' if frozen.get('review_of') else 'worker_self_report',
            'result': result, 'review_target': frozen.get('review_target'), 'artifacts': artifacts})
        if result['decision'] == 'blocked':
            reason=blocked_report_text(result)
            if failures:reason+='\nArtifact checks: '+'; '.join(failures)
            self.set_state(attempt, 'blocked', reason); return
        from .outcomes import disposition
        findings=result.get('findings',[])
        action=disposition(findings)
        if frozen.get('review_snapshot'):
            from .review_snapshot import check as check_snapshot
            check_snapshot(self,attempt['run'],frozen)
            self.event(attempt['run'],attempt['task'],attempt['id'],'snapshot_review_recorded',dict(decision=result['decision'],disposition=action,targets=frozen['review_snapshot'],producer_state_changed=False))
            if action not in ('block','reconcile'):
                self.set_state(attempt,'blocked' if action=='user_review' else 'completed',
                    'Snapshot review requires a user decision; producer state is unchanged' if action=='user_review' else None)
                return
        if action=='block' and frozen.get('review_of') and result['decision']=='revise':
            target=self.task(attempt['run'],frozen['review_of'])
            from .corrections import specification_policy
            if (target['latest']==frozen.get('review_target') and target['status']=='awaiting_review'
                    and (self.spec(target).get('review_correction') or specification_policy(self,attempt['run'],target['id']))
                    and all(f['category'] in ('requirements','execution','integrity','advisory') for f in findings)):
                # Preserve defect classification. The reviewed candidate stays
                # unaccepted while its already frozen correction grant is used.
                self.event(attempt['run'],target['id'],target['latest'],'review_defects_routed_to_correction',
                    dict(review_attempt=attempt['id'],findings=findings,user_approval=False))
                action='continue'
        if action in ('block','reconcile'):
            self.set_state(attempt,'uncertain' if action=='reconcile' else 'blocked','; '.join(f['category']+': '+f['message'] for f in findings))
            self.event(attempt['run'],attempt['task'],attempt['id'],'result_recovery_required',{'disposition':action,'findings':findings,'automatic_dispatch':False})
            return
        advisory=[f for f in findings if f['category']=='advisory']
        if advisory:
            self.event(attempt['run'],attempt['task'],attempt['id'],'result_advisories_recorded',
                {'findings':advisory,'user_approval':False,'review_target':frozen.get('review_target')})
        if action=='user_review':
            target=self.task(attempt['run'],frozen.get('review_of') or attempt['task'])
            if frozen.get('review_of') and (target['latest']!=frozen['review_target'] or target['status']!='awaiting_review'):
                self.set_state(attempt,'blocked','Stale review target');return
            prior=self.quality_review(target)
            combined=(prior or {}).get('findings',[])+[f for f in findings if f not in (prior or {}).get('findings',[])]
            self.event(attempt['run'],target['id'],target['latest'],'quality_review_required',
                {'policy_version':1,'findings':combined,'reported_by':attempt['id'],'user_approval':False})
        self.set_state(attempt, 'completed')
        if frozen.get('review_of'):
            target = self.task(attempt['run'], frozen['review_of'])
            if target['latest'] != frozen['review_target'] or target['status'] != 'awaiting_review':
                self.set_state(attempt, 'blocked', 'Stale review target'); return
            if result['decision'] == 'revise' and action!='user_review':
                target_spec=self.spec(target)
                from .corrections import specification_policy
                owner_job=json.loads(self.db.execute('SELECT plan FROM production_runs WHERE id=?',(attempt['run'],)).fetchone()[0]).get('job_owner')
                if owner_job:
                    # The job owner receives the exact rejected candidate and
                    # review. Do not also run the legacy per-task correction path,
                    # which cannot revise after render/inspection helpers started.
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(attempt['run'],target['id']))
                    self.event(attempt['run'],target['id'],target['latest'],'owner_correction_required',dict(review_attempt=attempt['id'],summary=result['summary'],instruction=result['instruction']))
                elif target_spec.get('execution') and not target_spec.get('review_correction') and not specification_policy(self,attempt['run'],target['id']):
                    # A review is complete even when its candidate needs correction.
                    # Native/external work requires a new exact approval, never replay.
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(attempt['run'],target['id']))
                    self.event(attempt['run'],target['id'],target['latest'],'review_correction_required',
                        {'review_attempt':attempt['id'],'summary':result['summary'],'instruction':result['instruction'],
                         'reason':'Registered operation needs a separately approved correction; existing downstream evidence is preserved.'})
                else:
                    self._revise(attempt['run'], target['id'], result['instruction'], 'model_review:' + attempt['id'])
            else:
                state = 'awaiting_user' if self.decision_purpose(target) else 'completed'
                self.db.execute('UPDATE production_tasks SET status=? WHERE run=? AND id=?', (state, attempt['run'], target['id']))
                self.event(attempt['run'], target['id'], target['latest'], 'quality_review_completed' if result['decision']=='revise' else 'model_review_accepted',
                           {'review_attempt': attempt['id'], 'user_approval': False})
        else:
            state = 'awaiting_review' if self.reviewer(attempt['run'], attempt['task']) else ('awaiting_user' if self.decision_purpose(self.task(attempt['run'],attempt['task'])) else 'completed')
            self.db.execute('UPDATE production_tasks SET status=? WHERE run=? AND id=?', (state, attempt['run'], attempt['task']))

    def tick(self, run, dispatch=True, authorize=None):
        if self.db.in_transaction:
            raise ValueError('Commit pending database changes before running the scheduler.')
        for attempt in self.db.execute("SELECT * FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchall():
            if attempt['state']=='uncertain' and self.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='result_recovery_required' AND json_extract(data,'$.disposition')='reconcile'",(attempt['id'],)).fetchone():
                continue  # A retained ambiguous result requires explicit reconciliation.
            if attempt['state'] == 'cancelling':
                # Intent survives a crash before the adapter receives cancellation.
                self.factory.cancel(json.loads(attempt['session']))
            raw_receipt = self.factory.inspect(json.loads(attempt['session']))
            from .connector_protocol import receipt as normalize_receipt
            receipt = normalize_receipt(raw_receipt)
            with self.transaction():
                fresh = self.db.execute('SELECT * FROM production_attempts WHERE id=?', (attempt['id'],)).fetchone()
                if fresh['state'] not in ACTIVE:
                    continue
                if receipt['status'] == 'finished':
                    try:
                        self.collect(fresh, receipt)
                    except (ValueError, OSError) as exc:
                        self.set_state(fresh, 'blocked', str(exc))
                        self.event(run, fresh['task'], fresh['id'], 'collection_blocked', {'reason':str(exc)})
                elif receipt['status'] == 'uncertain' and fresh['state'] == 'cancelling':
                    self.db.execute('UPDATE production_attempts SET error=?,receipt=? WHERE id=?', (receipt['reason'],c.encoded(receipt),fresh['id']))
                    if receipt.get('local_terminal') is True:
                        # Explicit cancellation ends local work, not the unknown
                        # remote effect. Never collect or mark that effect confirmed.
                        self.set_state(fresh,'cancelled',receipt['reason'])
                        self.event(run,fresh['task'],fresh['id'],'cancelled_with_uncertain_effect',receipt)
                        self.preserve_stopped_outputs(fresh['id'])
                elif receipt['status'] == 'uncertain' and fresh['state'] != 'uncertain':
                    self.set_state(fresh, 'uncertain', receipt['reason'])
                    self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(receipt),fresh['id']))
                    self.event(run, fresh['task'], fresh['id'], 'dispatch_uncertain', receipt)
                elif receipt['status'] == 'running' and fresh['state'] == 'launching':
                    self.set_state(fresh, 'running')
                    self.event(run, fresh['task'], fresh['id'], 'worker_started', receipt)
                current = self.db.execute('SELECT state FROM production_attempts WHERE id=?', (fresh['id'],)).fetchone()[0]
                if current in ('completed', 'blocked', 'cancelled', 'uncertain'):
                    from task_relay.execution_capture import notify
                    notify(self.db, 'production_attempt', fresh['id'])
        if dispatch:
            from .review_recovery import requeue as requeue_review
            requeue_review(self,run)
        from .job_owner import wake as wake_owner
        wake_owner(self,run)
        while dispatch:
            session = self.claim(run,authorize=authorize)
            if not session:
                break
            try:
                acknowledgement = self.factory.submit(session)
                with self.transaction():
                    attempt = self.db.execute('SELECT * FROM production_attempts WHERE id=?', (session['id'],)).fetchone()
                    self.event(run, attempt['task'], session['id'], 'dispatch_submitted', acknowledgement)
            except Exception as exc:
                with self.transaction():
                    attempt = self.db.execute('SELECT * FROM production_attempts WHERE id=?', (session['id'],)).fetchone()
                    self.set_state(attempt, 'uncertain', str(exc))
                    self.event(run, attempt['task'], session['id'], 'dispatch_uncertain', {'reason': str(exc)})
                    from task_relay.execution_capture import notify
                    notify(self.db, 'production_attempt', session['id'])
        return self.status(run)

    def pause(self, run):
        with self.transaction():
            if self.status(run)['status'] not in ('active','uncertain'):
                raise ValueError('Only a scheduled production can be paused')
            self.db.execute("UPDATE production_runs SET status='paused' WHERE id=?", (run,))
            self.event(run,None,None,'production_paused',{})

    def resume(self, run):
        with self.transaction():
            if self.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()[0] != 'paused':
                raise ValueError('Only a paused production can be resumed')
            self.db.execute("UPDATE production_runs SET status='active' WHERE id=?", (run,))
            self.event(run,None,None,'production_resumed',{})

    def request_cancel(self, run):
        """Persist cancellation without adapter I/O; safe inside a caller transaction."""
        with self.transaction():
            status = self.status(run)['status']
            if status == 'cancelled':return
            if status == 'completed':raise ValueError('A completed production cannot be cancelled')
            self.db.execute("UPDATE production_runs SET status='cancelled' WHERE id=?", (run,))
            self.db.execute("UPDATE production_tasks SET status='cancelled' WHERE run=? AND status IN ('queued','awaiting_review','awaiting_user')", (run,))
            for attempt in self.db.execute("SELECT * FROM production_attempts WHERE run=? AND state IN ('launching','running','uncertain')", (run,)).fetchall():
                self.set_state(attempt, 'cancelling')
            self.event(run, None, None, 'cancellation_requested', {})

    def cancel(self, run):
        if self.db.in_transaction:
            raise ValueError('Commit pending database changes before cancelling workers.')
        self.request_cancel(run)
        for attempt in self.db.execute("SELECT session FROM production_attempts WHERE run=? AND state='cancelling'", (run,)).fetchall():
            self.factory.cancel(json.loads(attempt['session']))

    def select(self, run, tid, artifact, purpose, note, artifacts=None):
        with self.transaction():
            row=self.db.execute('SELECT status FROM production_runs WHERE id=?',(run,)).fetchone()
            if not row or row['status']!='active':
                raise ValueError('A cancelled or inactive workflow cannot accept a selection')
            task = self.task(run, tid); spec = self.spec(task); a = self.artifact(artifact)
            if task['status'] != 'awaiting_user' or a['attempt'] != task['latest'] or purpose != self.decision_purpose(task):
                raise ValueError('Selection must match the current delivered artifact and exact decision purpose')
            members=[self.artifact(i) for i in (artifacts if artifacts is not None else [artifact])]
            expected=self.selection_paths(task) or [a['path']]
            if (not members or artifact not in [m['id'] for m in members]
                or len(members)!=len(expected) or {m['path'] for m in members}!=set(expected)
                or any(m['attempt']!=task['latest'] or m['task']!=tid or m['run']!=run for m in members)):
                raise ValueError('Select the complete declared output set from the current attempt')
            for member in members:
                blob=safe_file(self.root,str(Path(member['blob']).relative_to(self.root)))
                if file_hash(blob)!=member['sha256'] or blob.stat().st_size!=member['bytes']:
                    raise ValueError('A selected output changed')
            c.nonempty(note, 'user decision note')
            for member in members:
                self.db.execute('INSERT INTO production_decisions VALUES (?,?,?,?,?,?,?)', (uid(), run, tid, member['id'], purpose, note, time.time()))
            self.db.execute("UPDATE production_tasks SET status='completed' WHERE run=? AND id=?", (run, tid))
            self.event(run, tid, task['latest'], 'user_selected', {'artifact': artifact, 'sha256': a['sha256'], 'purpose': purpose, 'note': note,
                'quality_review':self.quality_review(task),
                'members':[{'artifact':m['id'],'sha256':m['sha256'],'path':m['path']} for m in members]})

    def artifact_lineage(self, artifact, limit=100):
        from .artifact_dependencies import trace
        return trace(self.db, [artifact], limit=limit)

    def replace_selection(self, old, new, revision, receipt, note):
        from .artifact_replacements import replace
        return replace(self,old,new,revision,receipt,note)

    def artifact_impact(self, artifact, replacement=None, limit=100):
        from .artifact_dependencies import impact
        return impact(self.db, artifact, replacement, limit)

    def status(self, run):
        row = self.db.execute('SELECT * FROM production_runs WHERE id=?', (run,)).fetchone()
        if row is None:
            raise ValueError('Unknown workflow')
        tasks = [dict(t) for t in self.db.execute('SELECT * FROM production_tasks WHERE run=? ORDER BY rowid', (run,))]
        specs = [self.spec(t) for t in tasks]
        state = run_status(row['status'], tasks, specs)
        progress = {}
        drain=settlement(row['status'],tasks,specs)
        if drain:progress['settlement']=drain
        if stop_status(row['status'],tasks,specs) == 'uncertain' and row['status'] == 'active':
            attempts = [dict(a) for a in self.db.execute('SELECT state FROM production_attempts WHERE run=?', (run,))]
            locked = {a[0] for a in self.db.execute("SELECT resource FROM production_attempts WHERE state IN ('launching','running','cancelling','uncertain')")}
            uncertainty=uncertainty_progress(tasks,specs,attempts,json.loads(row['plan'])['concurrency'],locked)
            uncertainty.update(runnable_independent=[],can_continue=bool(uncertainty['active_independent']),dispatch_allowed=False)
            progress['uncertainty_progress']=uncertainty
        report = {'id': run, 'status': state, 'tasks': tasks, **progress,
            'attempts': [dict(a) for a in self.db.execute('SELECT id,task,state,error,receipt FROM production_attempts WHERE run=? ORDER BY rowid', (run,))],
            'artifacts': [dict(a) for a in self.db.execute('SELECT id,task,attempt,path,sha256,bytes,purpose FROM production_artifacts WHERE run=? ORDER BY rowid', (run,))]}
        if state in ('blocked','uncertain'):
            from .partial_delivery import snapshot
            delivery=snapshot(self,report)
            if delivery:report['delivery']=delivery
        return report
