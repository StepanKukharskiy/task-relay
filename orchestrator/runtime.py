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
    if attempt['state']!='blocked':return original
    receipt=json.loads(attempt['receipt'] or '{}')
    operation=receipt.get('operation') or {}
    if (original=='Worker failed' and receipt.get('status')=='finished' and isinstance(operation,dict)
        and operation.get('outcome')=='failed' and isinstance(operation.get('reason'),str) and operation['reason'].strip()):
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
    return all(states.get(dep) == 'awaiting_review' if dep == spec.get('review_of')
               else states.get(dep) == 'completed' or (dep in evidence and states.get(dep) == 'awaiting_review')
               for dep in spec['dependencies'])


def run_status(stored_status, tasks, specs):
    """Shared read-only status derivation for scheduler and conversation snapshots."""
    if stored_status != 'active':
        return stored_status
    states = {t['status'] for t in tasks}
    if 'uncertain' in states:
        return 'uncertain'
    if states == {'completed'}:
        return 'completed'
    runnable = any(t['status'] == 'queued' and dependencies_ready(a, tasks, specs) for t, a in zip(tasks, specs))
    if not states.intersection(ACTIVE) and not runnable:
        return 'awaiting_user' if 'awaiting_user' in states else 'blocked'
    return 'active'


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
    def __init__(self, root, factory=None, connection=None):
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.factory = factory or ExecutionFactory()
        self.owns_connection = connection is None
        self.db = connection if connection is not None else sqlite3.connect(storage.database_path(self.root), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if self.owns_connection:
            self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
        try:
            storage.initialize(self.db, self.root / 'runtime.sqlite')
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
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

    def new_assignment(self, run, spec):
        version = self.db.execute('SELECT coalesce(max(version),0)+1 FROM production_assignments WHERE run=? AND task=?', (run, spec['id'])).fetchone()[0]
        aid = uid()
        self.db.execute('INSERT INTO production_assignments VALUES (?,?,?,?,?)', (aid, run, spec['id'], version, c.encoded(spec)))
        self.event(run, spec['id'], None, 'assignment_created', {'assignment': aid, 'version': version, 'spec': spec})
        return aid

    def create(self, value):
        plan = c.plan(value)
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
            plan = c.plan(plan)
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
        with self.transaction():
            row = self.db.execute('SELECT * FROM production_runs WHERE id=?', (run,)).fetchone()
            if row is None or row['status'] != 'active':
                raise ValueError('An active workflow is required')
            plan = json.loads(row['plan'])
            plan['tasks'] = [self.spec(t) for t in self.db.execute('SELECT * FROM production_tasks WHERE run=?', (run,))] + [value]
            plan = c.plan(plan); spec = plan['tasks'][-1]
            if spec.get('review_of') and self.task(run, spec['review_of'])['attempts']:
                raise ValueError('A review gate must be defined before its producer starts')
            for item in spec['inputs']:
                if 'artifact' in item:
                    self.artifact(item['artifact'])
            aid = self.new_assignment(run, spec)
            self.db.execute('INSERT INTO production_tasks(run,id,assignment,status) VALUES (?,?,?,?)', (run,spec['id'],aid,'queued'))
            self.event(run, spec['id'], None, 'future_task_added', {'assignment': aid})

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
        resolved=[]
        for item in spec['inputs']:
            artifact=self.artifact(item['artifact']) if 'artifact' in item else self.output(run,item['from_task'],item['output'])
            if artifact is None:raise ValueError('Missing upstream artifact: '+item['path'])
            blob=Path(artifact['blob'])
            safe_file(self.root,str(blob.relative_to(self.root)))
            if blob.stat().st_size!=artifact['bytes'] or file_hash(blob)!=artifact['sha256']:
                raise ValueError('Registered artifact content changed: '+item['path'])
            resolved.append({**item,'artifact':artifact['id'],'sha256':artifact['sha256'],
                             'bytes':artifact['bytes'],'blob':blob})
        if spec.get('execution'):
            ceiling=execution.REGISTRY[spec['execution']['capability']]['input_bytes']
            if sum(i['bytes'] for i in resolved)>ceiling:
                raise ValueError(f'Registered operation input byte limit exceeded ({ceiling} bytes).')
        elif backend['type'] in executors.API_TYPES:
            executors.validate_input_sizes(resolved,backend)
            if backend['type'] not in executors.CODE_TYPES:
                for item in resolved:
                    raw=item['blob'].read_bytes()
                    if backend['type'] in executors.BROWSER_TYPES and png_input(item):png_info(raw)
                    else:
                        try:raw.decode('utf-8')
                        except UnicodeError:raise ValueError('API executors require UTF-8 text inputs: '+item['path']) from None
        return resolved

    def claim(self, run):
        if self.db.in_transaction:
            raise ValueError('Worker claims require a transaction boundary before transport.')
        with self.transaction():
            row = self.db.execute('SELECT * FROM production_runs WHERE id=?', (run,)).fetchone()
            if row is None:
                raise ValueError('Unknown workflow')
            if row['status'] != 'active':
                return None
            plan = json.loads(row['plan'])
            occupied = self.db.execute("SELECT count(*) FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchone()[0]
            if occupied >= plan['concurrency']:
                return None
            for task in self.db.execute("SELECT * FROM production_tasks WHERE run=? AND status='queued' ORDER BY rowid", (run,)).fetchall():
                spec = self.spec(task)
                if not self.ready(run, spec):
                    continue
                if spec.get('resource') and self.db.execute("SELECT 1 FROM production_attempts WHERE resource=? AND state IN ('launching','running','cancelling','uncertain')", (spec['resource'],)).fetchone():
                    continue
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
                        if spec['execution']['capability']=='rhino.render':
                            from .rhino_render import bind_registered
                            bind_registered(self,spec)
                        if spec['execution']['capability']=='blender.animate':
                            from .blender_animation import bind_registered
                            bind_registered(self,spec)
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
                try:resolved_inputs=self.checked_inputs(run,spec,backend)
                except (ValueError,OSError) as exc:
                    self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                    self.event(run,task['id'],None,'input_preflight_blocked',
                               {'assignment':task['assignment'],'reason':str(exc),'dispatched':False})
                    continue
                if not spec.get('execution') and hasattr(self.factory,'available'):
                    try:self.factory.available(backend)
                    except ValueError as exc:
                        self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?",(run,task['id']))
                        self.event(run,task['id'],None,'capability_unavailable',{'reason':str(exc)})
                        continue
                attempt = uid(); workspace = self.root / 'workspaces' / attempt
                workspace.mkdir(parents=True, mode=0o700)
                frozen = copy.deepcopy(spec)
                # Never trust a model-supplied authorization field.
                frozen.pop('host_code_authorization',None);frozen.pop('authorized_assignment_digest',None)
                if authorization:
                    frozen['host_code_authorization']=authorization
                    frozen['authorized_assignment_digest']=c.digest(spec)
                frozen.update(assignment_id=attempt, assignment_version=task['assignment'],
                              run=run, workspace=str(workspace), brief=plan['brief'], backend=backend)
                if not frozen.get('execution'):
                    from .report_builder import freeze as report_form
                    frozen['report_contract']=report_form(frozen)
                from task_relay.host import support_hashes
                frozen['host_support'] = support_hashes()
                frozen['runtime_sources'] = {p.name: file_hash(p) for p in Path(__file__).parent.glob('*.py')}
                if spec.get('execution',{}).get('capability') in ('media.compose','hyperframes.preview','hyperframes.render'):
                    from task_relay import media_host
                    frozen['media_runtime']=media_host.available('project' if spec['execution']['capability'].startswith('hyperframes.') else 'template')
                    frozen['runtime_sources']['task_relay/media_host.py']=file_hash(Path(media_host.__file__))
                if spec.get('execution',{}).get('capability','').startswith('sketchup.'):
                    from .sketchup_execution import application_binding
                    frozen['sketchup_application']=application_binding()
                if frozen.get('execution',{}).get('capability') in ('images.collect','images.fetch'):
                    from task_relay import orchestrator_web
                    frozen['runtime_sources']['task_relay/orchestrator_web.py']=file_hash(Path(orchestrator_web.__file__))
                if frozen.get('execution',{}).get('capability') in execution.CLOUD_MEDIA:
                    from task_relay import cloud_providers
                    frozen['runtime_sources']['task_relay/cloud_providers.py'] = file_hash(Path(cloud_providers.__file__))
                if spec.get('execution',{}).get('capability','').startswith('rhino.'):
                    from task_relay import rhino_host,host_apps
                    frozen['rhino_host_sources']={m.__name__:file_hash(Path(m.__file__)) for m in (rhino_host,host_apps)}
                    from task_relay.host_evidence import application_signature
                    rhino_app=host_apps.rhino()
                    frozen['rhino_application']={'signature':application_signature(rhino_app['executable']),
                        'major':rhino_app.get('major',8),'version':rhino_app.get('version')}
                for item,artifact in zip(frozen['inputs'],resolved_inputs):
                    item.update(artifact=artifact['artifact'], sha256=artifact['sha256'])
                    target = workspace / item['path']; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(artifact['blob'], target); target.chmod(0o400)
                    if file_hash(target)!=artifact['sha256']:raise ValueError('Registered artifact changed while staging: '+item['path'])
                if spec.get('review_of'):
                    frozen['review_target'] = self.task(run, spec['review_of'])['latest']
                relay = workspace / '.relay'; relay.mkdir()
                (relay / 'ASSIGNMENT.json').write_text(c.encoded(frozen) + '\n')
                session = self.factory.create(self.root / 'workers' / attempt, workspace, frozen, backend)
                self.db.execute('INSERT INTO production_attempts(id,run,task,assignment,state,resource,frozen,session) VALUES (?,?,?,?,?,?,?,?)',
                    (attempt, run, task['id'], task['assignment'], 'launching', spec.get('resource'), c.encoded(frozen), c.encoded(session)))
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
                     if self.spec(t).get('review_of') == tid), None)

    def retry_review(self,run,tid,instruction,source='user'):
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
            if (attempt['state']!='blocked' or receipt.get('status')!='finished'
                or receipt.get('external_outcome')!='no_pending_response' or receipt.get('pending_requests')
                or frozen['backend']['type'] not in (*executors.FILE_TYPES,*executors.CODE_TYPES)):
                raise ValueError('Confirmed finished API review with no pending response is required; no uncertain replay.')
            target=self.task(run,spec['review_of'])
            if target['status']!='awaiting_review' or target['latest']!=frozen['review_target']:
                raise ValueError('The exact review target changed.')
            for other in self.db.execute('SELECT * FROM production_tasks WHERE run=?',(run,)):
                if other['status'] in ACTIVE or (other['attempts'] and tid in self.spec(other)['dependencies']):
                    raise ValueError('Active or downstream work prevents review recovery.')
            spec['revision']={'instruction':instruction,'source':source,'previous_attempt':attempt['id']}
            aid=self.new_assignment(run,c.assignment(spec))
            self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?",(aid,run,tid))
            self.event(run,tid,attempt['id'],'review_retry_requested',spec['revision'])

    def revise(self, run, tid, instruction, source='user'):
        with self.transaction():
            self._revise(run, tid, instruction, source)

    def _revise(self, run, tid, instruction, source):
        task = self.task(run, tid); spec = self.spec(task)
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
        if task['attempts'] >= limit:
            self.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id=?", (run, tid))
            self.event(run, tid, task['latest'], 'revision_limit', {'instruction': instruction, 'source': source})
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
        aid = self.new_assignment(run, spec)
        self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?", (aid, run, tid))
        if reviewer:
            aid = self.new_assignment(run, self.spec(reviewer))
            self.db.execute("UPDATE production_tasks SET assignment=?,status='queued' WHERE run=? AND id=?", (aid, run, reviewer['id']))
        self.event(run, tid, task['latest'], 'revision_requested', spec['revision'])

    def preserve_stopped_outputs(self, attempt_id):
        """Snapshot declared drafts after a confirmed stop, without advancing state."""
        attempt = self.db.execute('SELECT * FROM production_attempts WHERE id=?', (attempt_id,)).fetchone()
        receipt = json.loads(attempt['receipt'] or '{}') if attempt else {}
        if not attempt or attempt['state'] not in ('blocked', 'cancelled') or receipt.get('status') != 'finished':
            raise ValueError('Draft recovery requires a terminal attempt and a confirmed stopped worker.')
        old = self.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='draft_outputs_preserved'", (attempt_id,)).fetchone()
        if old:
            return json.loads(old['data'])
        frozen = json.loads(attempt['frozen']); workspace = Path(frozen['workspace'])
        result = {'artifacts': [], 'failures': [], 'approved': False}
        total = 0
        for output in frozen['outputs']:
            try:
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
        frozen = json.loads(attempt['frozen']); workspace = Path(frozen['workspace'])
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
            from .browser_contract import validate_captures
            validate_captures(frozen,workspace)
            from .host_script import validate_prepared
            validate_prepared(frozen, workspace)
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
        if action in ('block','reconcile'):
            self.set_state(attempt,'uncertain' if action=='reconcile' else 'blocked','; '.join(f['category']+': '+f['message'] for f in findings))
            self.event(attempt['run'],attempt['task'],attempt['id'],'result_recovery_required',{'disposition':action,'findings':findings,'automatic_dispatch':False})
            return
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
                if target_spec.get('execution') and not target_spec.get('review_correction'):
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

    def tick(self, run, dispatch=True):
        if self.db.in_transaction:
            raise ValueError('Commit pending database changes before running the scheduler.')
        for attempt in self.db.execute("SELECT * FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchall():
            if attempt['state']=='uncertain' and self.db.execute("SELECT 1 FROM production_events WHERE attempt=? AND kind='result_recovery_required' AND json_extract(data,'$.disposition')='reconcile'",(attempt['id'],)).fetchone():
                continue  # A retained ambiguous result requires explicit reconciliation.
            if attempt['state'] == 'cancelling':
                # Intent survives a crash before the adapter receives cancellation.
                self.factory.cancel(json.loads(attempt['session']))
            receipt = self.factory.inspect(json.loads(attempt['session']))
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
                    self.db.execute('UPDATE production_attempts SET error=? WHERE id=?', (receipt['reason'],fresh['id']))
                elif receipt['status'] == 'uncertain' and fresh['state'] != 'uncertain':
                    self.set_state(fresh, 'uncertain', receipt['reason'])
                    self.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(c.encoded(receipt),fresh['id']))
                    self.event(run, fresh['task'], fresh['id'], 'dispatch_uncertain', receipt)
                elif receipt['status'] == 'running' and fresh['state'] == 'launching':
                    self.set_state(fresh, 'running')
                    self.event(run, fresh['task'], fresh['id'], 'worker_started', receipt)
        while dispatch:
            session = self.claim(run)
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
        return self.status(run)

    def pause(self, run):
        with self.transaction():
            if self.status(run)['status'] not in ('active','uncertain'):
                raise ValueError('Only a scheduled production can be paused')
            self.db.execute("UPDATE production_runs SET status='paused' WHERE id=?", (run,))
            self.event(run,None,None,'production_paused',{})

    def resume(self, run):
        with self.transaction():
            if self.status(run)['status'] != 'paused':
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
        state = run_status(row['status'], tasks, [self.spec(t) for t in tasks])
        return {'id': run, 'status': state, 'tasks': tasks,
            'attempts': [dict(a) for a in self.db.execute('SELECT id,task,state,error,receipt FROM production_attempts WHERE run=? ORDER BY rowid', (run,))],
            'artifacts': [dict(a) for a in self.db.execute('SELECT id,task,attempt,path,sha256,bytes,purpose FROM production_artifacts WHERE run=? ORDER BY rowid', (run,))]}
