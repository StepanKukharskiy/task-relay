"""Shared job inspection and exact local decisions over committed Relay records."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import time

from .desktop_plans import DesktopPlanError, _database, _request_id
from .relay_paths import PATHS


class ReadState:
    def __init__(self, db, paths):
        self.db, self.media_dir = db, paths.data / 'media'

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default


def require_local_run(db, run):
    from .result_handoff import channel_for
    if not db.execute('SELECT 1 FROM production_runs WHERE id=?', (run,)).fetchone():
        raise DesktopPlanError('That saved job is unavailable.')
    if channel_for(type('State', (), {'db': db})(), run) != 'desktop':
        raise DesktopPlanError('Continue decisions in the original messenger for this job.')
    if _workflow_owns_run(db, run):
        raise DesktopPlanError('This stage belongs to a saved workflow. Use its original workflow controls.')


def require_control_run(db, run, *, allow_owned=False):
    from .result_handoff import channel_for
    if not db.execute('SELECT 1 FROM production_runs WHERE id=?', (run,)).fetchone():
        raise DesktopPlanError('That saved job is unavailable.')
    if channel_for(type('State', (), {'db': db})(), run) not in ('desktop', 'telegram', 'messages'):
        raise DesktopPlanError('That job has no supported delivery channel.')
    if _workflow_owns_run(db, run) and not allow_owned:
        raise DesktopPlanError('This stage belongs to a saved workflow. Use its workflow controls.')


def _workflow_owns_run(db, run):
    return db.execute('''SELECT 1 FROM relay_pipeline_steps s WHERE
        (s.target_kind='production_run' AND s.target=?) OR
        (s.target_kind='plan_production' AND EXISTS
         (SELECT 1 FROM production_plans p WHERE p.id=s.target AND p.run=?))''', (run,run)).fetchone()


def jobs(offset=0, paths=PATHS, *, include_archived=False):
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise DesktopPlanError('Choose a valid jobs page.')
    result = dict(items=[], total=0, next_offset=None, can_plan=False, scope=str(paths.state))
    if not paths.state.is_file():
        return result
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        from .desktop_plans import _ready
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_plan_requests'").fetchone():
            return result
        result['can_plan'] = _ready(db)
        # Plans with a run represent the same job; do not manufacture another inbox.
        query = '''SELECT 'plan' kind,p.id,p.request title,
                   CASE WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='uncertain') THEN 'uncertain'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='blocked') THEN 'blocked'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='awaiting_user') THEN 'awaiting_user'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id)
                             AND NOT EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status!='completed') THEN 'completed'
                        WHEN r.id IS NULL AND p.status='ready' AND EXISTS
                             (SELECT 1 FROM relay_pipeline_steps s JOIN relay_pipelines w ON w.id=s.pipeline
                              WHERE s.target=p.id AND w.status IN ('cancelled','paused')) THEN 'blocked'
                        ELSE COALESCE(r.status,p.status) END status,
                   p.channel,p.run,p.created stamp FROM production_plans p
                   LEFT JOIN production_runs r ON r.id=p.run
                   UNION ALL SELECT 'request',d.request_id,d.prompt,COALESCE(c.status,d.status),'desktop',NULL,d.created
                   FROM desktop_plan_requests d LEFT JOIN orchestrator_chats c ON c.id=d.job_id
                   WHERE d.status!='deleted' AND NOT EXISTS (SELECT 1 FROM production_plans p WHERE p.request_id=d.job_id)
                   UNION ALL SELECT 'chat',CAST(c.id AS TEXT),c.prompt,c.status,COALESCE(rc.channel,'telegram'),NULL,c.created
                   FROM orchestrator_chats c LEFT JOIN relay_request_channels rc ON rc.request_id=c.id
                   WHERE NOT EXISTS (SELECT 1 FROM desktop_plan_requests d WHERE d.job_id=c.id)
                   AND NOT EXISTS (SELECT 1 FROM production_plans p WHERE p.request_id=c.id)
                   UNION ALL SELECT 'run',r.id,json_extract(r.plan,'$.brief'),
                   CASE WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='uncertain') THEN 'uncertain'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='blocked') THEN 'blocked'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status='awaiting_user') THEN 'awaiting_user'
                        WHEN r.status='active' AND EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id)
                             AND NOT EXISTS (SELECT 1 FROM production_tasks t WHERE t.run=r.id AND t.status!='completed') THEN 'completed'
                        ELSE r.status END,
                   COALESCE((SELECT channel FROM relay_channel_bindings b WHERE b.kind='production' AND b.entity=r.id ORDER BY after_row DESC LIMIT 1),'telegram'),
                   r.id,0 FROM production_runs r WHERE NOT EXISTS (SELECT 1 FROM production_plans p WHERE p.run=r.id)
                   UNION ALL SELECT 'task',w.id,w.title,w.status,'shared',NULL,w.updated_at FROM watched w'''
        from . import conversation_flow
        if conversation_flow.exists(db):
            query='''WITH RECURSIVE linked_plans(id) AS (
                SELECT p.id FROM production_plans p JOIN desktop_plan_requests d ON d.job_id=p.request_id
                JOIN conversation_followups f ON f.request_id=d.request_id
                UNION SELECT p.id FROM production_plans p JOIN linked_plans l ON p.parent_id=l.id)
                SELECT * FROM ('''+query+''') item WHERE NOT (
                    (kind='request' AND id IN (SELECT request_id FROM conversation_followups)) OR
                    (kind='chat' AND id IN (SELECT CAST(d.job_id AS TEXT) FROM desktop_plan_requests d JOIN conversation_followups f ON f.request_id=d.request_id)) OR
                    (kind='plan' AND id IN (SELECT id FROM linked_plans)) OR
                    (kind='run' AND id IN (SELECT run FROM production_plans WHERE id IN (SELECT id FROM linked_plans))))'''
        if not include_archived and db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_job_archives'").fetchone():
            query = 'SELECT * FROM (' + query + ') j WHERE NOT EXISTS (SELECT 1 FROM desktop_job_archives a WHERE a.kind=j.kind AND a.id=j.id) AND NOT EXISTS (SELECT 1 FROM desktop_job_archives a WHERE a.kind=\'run\' AND a.id=j.run)'
        result['total'] = db.execute('SELECT count(*) FROM (' + query + ')').fetchone()[0]
        result['conversation_delete_pending'] = ([dict(r) for r in db.execute("SELECT id,status,error FROM desktop_conversation_deletions WHERE status='cleanup_pending' ORDER BY created")]
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_conversation_deletions'").fetchone() else [])
        result['items'] = [dict(r) for r in db.execute('SELECT * FROM (' + query + ') ORDER BY stamp DESC,id LIMIT 40 OFFSET ?', (offset,))]
        for item in result['items']:
            ident=(db.execute('SELECT job_id FROM desktop_plan_requests WHERE request_id=?',(item['id'],)).fetchone()[0]
                   if item['kind']=='request' else int(item['id']) if item['kind']=='chat' else None)
            if ident is not None:
                aggregate=conversation_flow.summary(db,ident)
                if aggregate:item.update(status=aggregate['status'],conversation_flow=True)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_job_archives'").fetchone():
            for item in result['items']:
                item['archived'] = bool(db.execute('SELECT 1 FROM desktop_job_archives WHERE (kind=? AND id=?) OR (kind=\'run\' AND id=?)',
                                                   (item['kind'], item['id'], item['run'])).fetchone())
        if offset + len(result['items']) < result['total']:
            result['next_offset'] = offset + len(result['items'])
    return result


def request_detail(request_id, paths=PATHS):
    _request_id(request_id)
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        row = db.execute('''SELECT d.request_id,d.prompt,d.project,d.status,d.result,p.id plan_id
            FROM desktop_plan_requests d LEFT JOIN production_plans p ON p.request_id=d.job_id WHERE d.request_id=?''', (request_id,)).fetchone()
        if not row:
            raise DesktopPlanError('That request has not been recorded. Retry with its original identity.')
        value = dict(row)
        mode = db.execute('SELECT entry_mode FROM desktop_request_modes WHERE request_id=?', (request_id,)).fetchone()
        value['entry_mode'] = mode[0] if mode else 'plan'
        job = db.execute('SELECT job_id FROM desktop_plan_requests WHERE request_id=?', (request_id,)).fetchone()
        if db.execute('SELECT 1 FROM orchestrator_chats WHERE id=?', (job[0],)).fetchone():
            value['conversation'] = _chat(db, job[0], paths)
            value['status'] = value['conversation']['status']
        return value


def _chat(db, ident, paths, *, include_flow=True):
    if not isinstance(ident, (str,int)) or not str(ident).lstrip('-').isdigit() or len(str(ident)) > 20:
        raise DesktopPlanError('Choose a saved orchestrator response.')
    row = db.execute('SELECT id,prompt,answer,response,status,focus FROM orchestrator_chats WHERE id=?', (int(ident),)).fetchone()
    if not row:
        raise DesktopPlanError('That orchestrator response is unavailable.')
    from . import orchestrator_advice, relay_channels
    value = dict(row)
    value['id'] = str(row['id'])  # UUID-derived IDs exceed JavaScript's integer precision.
    try:
        from .orchestrator_chat import response_json
        response = response_json(row['response']) if row['response'] else {}
    except (ValueError, TypeError):
        response = {}
    if not isinstance(response, dict):
        response = {}
    value['next_options'] = response.get('next_options', []) if row['status'] == 'answered' else []
    value['research_advice'] = (orchestrator_advice.presentation_advice(response.get('research_advice'))[0]
                                if row['status'] == 'answered' else None)
    value['channel'] = relay_channels.request_channel(ReadState(db, paths), int(ident))
    value['evidence'] = orchestrator_advice.disclosure(paths.data, int(ident))
    value['source_summary'] = orchestrator_advice.source_summary(value['research_advice'],value['evidence'])
    value['claims'] = orchestrator_advice.claim_evidence(response.get('claim_sources',[]),response.get('answer',''),value['evidence'])
    value['display_answer'] = row['answer']
    presentation = db.execute('SELECT value FROM kv WHERE key=?',('orchestrator-presentation:'+str(ident),)).fetchone()
    if presentation and row['status'] == 'answered':
        try:
            saved = json.loads(presentation[0])
            if (isinstance(saved,dict) and saved.get('version') == 1 and isinstance(saved.get('body'),str)
                    and saved.get('response_sha256') == hashlib.sha256(row['response'].encode()).hexdigest()
                    and saved.get('answer_sha256') == hashlib.sha256(row['answer'].encode()).hexdigest()):
                value['display_answer'] = saved['body']
        except (ValueError,TypeError):
            pass
    elif row['status'] == 'answered' and response.get('action') is None and isinstance(response.get('answer'),str):
        # Only remove a known legacy runtime suffix when the entire saved answer
        # is byte-identical to its reconstruction. Never guess from headings.
        expected = (response['answer'] + orchestrator_advice.legacy_render_options(value['next_options'])
                    + orchestrator_advice.legacy_render(value['research_advice'],value['evidence']))
        if row['answer'] == expected:
            value['display_answer'] = response['answer']
    value.pop('response')
    value['can_continue'] = value['channel'] == 'desktop' and row['status'] == 'answered'
    value['can_delete'] = value['channel'] == 'desktop' and row['status'] in ('answered','failed') and not row['focus']
    entry = db.execute('''SELECT d.project,i.manifest FROM desktop_plan_requests d
        JOIN desktop_plan_inputs i ON i.request_id=d.request_id WHERE d.job_id=?''', (int(ident),)).fetchone()
    value['project'] = entry['project'] if entry else None
    value['files'] = [item['path'] for item in json.loads(entry['manifest'])] if entry else []
    from . import conversation_flow
    if value['can_continue'] and not row['focus']:
        try:
            value['option_digests']=conversation_flow.selections(db,str(ident))[3]
        except (ValueError,TypeError):
            value['option_digests']=[]
    if include_flow:
        value['flow']=conversation_flow.projection(db,str(ident),paths)
    return value


def chat_detail(ident, paths=PATHS):
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        return _chat(db, ident, paths)


def chat_source(ident, url, paths=PATHS):
    value = chat_detail(ident, paths)
    if not any(s['url'] == url for s in value['evidence']['sources']):
        raise DesktopPlanError('The saved source receipt changed or is unavailable.')
    return {'url':url}


def _view(state, run, paths=PATHS):
    from . import production_control as pc
    from orchestrator.runtime import Runtime
    view = next((v for v in pc.inspect(state, run) if v['name'] == run), None)
    if not view:
        raise DesktopPlanError('That saved job is unavailable.')
    rt = Runtime(pc.root(state), connection=state.db, read_only=True)
    # Inspect the saved assignment and frozen attempt, never resolve or dispatch
    # inputs merely to draw a workflow. Filename equality is not version identity.
    plan = json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()[0])
    for task in view['tasks']:
        assignment = state.db.execute('''SELECT a.spec FROM production_assignments a
            JOIN production_tasks t ON t.assignment=a.id WHERE t.run=? AND t.id=?''', (run, task['id'])).fetchone()
        spec = json.loads(assignment[0])
        attempt = state.db.execute('SELECT frozen FROM production_attempts WHERE id=?', (task['latest_attempt'],)).fetchone()
        frozen = json.loads(attempt[0]) if attempt else None
        from orchestrator.worker_capabilities import backend_for
        task['backend'] = frozen.get('backend', {}) if frozen else backend_for(spec, plan['backend'])
        task['tools'] = (frozen or spec).get('tools', [])
        task['planned_inputs'] = spec.get('inputs', [])
        task['planned_outputs'] = spec.get('outputs', [])
        task['recorded_inputs'] = []
        for item in (frozen or {}).get('inputs', []):
            value = {k: item.get(k) for k in ('path', 'sha256', 'purpose', 'authority', 'artifact')}
            registered = state.db.execute('SELECT id,path,bytes,sha256 FROM production_artifacts WHERE id=?', (item.get('artifact'),)).fetchone()
            value['file'] = dict(registered) if registered and registered['sha256'] == item.get('sha256') else None
            task['recorded_inputs'].append(value)
    try:
        require_control_run(state.db, run)
        controllable = True
        control_error = None
    except DesktopPlanError as exc:
        controllable = False
        control_error = str(exc)
    controls = []
    if controllable:
        if view['status'] == 'paused' or pc.review_resume_digest(state, run, view, legacy=True):
            controls.append('resume')
        elif view['status'] in ('active', 'uncertain') and view['scheduler_enabled']:
            controls.append('pause')
        if view['status'] not in ('completed', 'cancelled'):
            controls.append('cancel')
        elif not state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchone():
            controls.append('archive')
    elif control_error and 'saved workflow' in control_error and view['status'] not in ('completed','cancelled'):
        controls.append('cancel')
    elif control_error and 'saved workflow' in control_error and not state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')", (run,)).fetchone():
        controls.append('archive')
    groups = []
    if controllable and view['status'] == 'awaiting_user':
        for task in state.db.execute("SELECT * FROM production_tasks WHERE run=? AND status='awaiting_user' ORDER BY id", (run,)):
            purpose = rt.decision_purpose(task)
            if not purpose:
                continue
            artifacts = [dict(a) for a in state.db.execute('SELECT id,path,sha256,bytes FROM production_artifacts WHERE run=? AND task=? AND attempt=? ORDER BY path', (run, task['id'], task['latest']))]
            selected = rt.selection_paths(task)
            sets = [[a for a in artifacts if a['path'] in selected]] if selected else [[a] for a in artifacts]
            for members in sets:
                if selected and {a['path'] for a in members} != set(selected):
                    continue
                group = dict(task=task['id'], assignment=task['assignment'], attempt=task['latest'], purpose=purpose,
                             concerns=rt.quality_review(task), members=members)
                group['id'] = hashlib.sha256(json.dumps(group, sort_keys=True).encode()).hexdigest()
                groups.append(group)
    from .result_handoff import channel_for
    archived = bool(state.db.execute("SELECT 1 FROM desktop_job_archives WHERE kind='run' AND id=?", (run,)).fetchone())
    if archived:
        controls = ['restore']
    basis = dict(run=run, status=view['status'], controls=controls, channel=channel_for(state, run),
                 revision=view['revision'], epoch=state.get('production-control-epoch:' + run, 0),
                 selections=groups, outputs=view.get('latest_outputs', []), historical=view.get('historical_outputs', []))
    view.update(channel=channel_for(state, run),
                archived=archived,
                remove_blocker='A worker is still stopping or has an unresolved outcome. Removal becomes available after reconciliation.' if view['status'] in ('completed','cancelled') and controllable and 'archive' not in controls and not archived else None,
                local=channel_for(state, run)=='desktop', controllable=controllable,
                control_error='This stage is part of a saved workflow. Continuation uses its workflow controls; cancellation and removal here apply to this stage.' if control_error and 'saved workflow' in control_error else control_error,
                controls=controls, selection_groups=groups,
                review_digest=hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest())
    events = [dict(r) for r in state.db.execute('SELECT id,text FROM outbox WHERE id LIKE ? ORDER BY rowid DESC LIMIT 30', ('production:' + run + ':%',))]
    view['messages'] = list(reversed(events))
    view['receipts'] = [dict(r) for r in state.db.execute('SELECT request_id,verb,status,result,created FROM desktop_workspace_commands WHERE run=? ORDER BY created DESC LIMIT 12', (run,))]
    from . import desktop_file_changes
    originals = desktop_file_changes.bindings(state, run, paths)
    view['file_changes'] = dict(items=desktop_file_changes.recorded(state, run),
                               original_count=len(originals), note=desktop_file_changes.NOTE)
    from .desktop_sources import inspect as inspect_sources
    view['research'] = inspect_sources(state.db, run, plan)
    return view


def detail(run, paths=PATHS):
    if not isinstance(run, str) or len(run) > 80:
        raise DesktopPlanError('Choose an exact saved job.')
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        return _view(ReadState(db, paths), run, paths)


def artifact_path(artifact, paths=PATHS):
    from . import production_control as pc
    from orchestrator.runtime import safe_file, file_hash
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT blob,sha256,bytes FROM production_artifacts WHERE id=?', (artifact,)).fetchone()
        if not row:
            raise DesktopPlanError('That registered file is unavailable.')
        root = pc.root(ReadState(db, paths)).resolve()
        path = safe_file(root, str(Path(row['blob']).relative_to(root)))
        if path.stat().st_size != row['bytes'] or file_hash(path) != row['sha256']:
            raise DesktopPlanError('That file changed. Its saved version cannot be revealed.')
        return dict(path=str(path))


def decide(run, verb, review_digest, request_id, group=None, note='', paths=PATHS):
    from .bridge import State
    from . import production_control as pc, relay_channels
    from orchestrator.runtime import Runtime
    _request_id(request_id)
    if verb not in ('pause', 'resume', 'cancel', 'select', 'archive', 'restore') or not isinstance(note, str) or len(note.encode()) > 12000:
        raise DesktopPlanError('Choose a current job action and a short decision note.')
    fingerprint = hashlib.sha256(json.dumps([run, verb, review_digest, group, note], sort_keys=True).encode()).hexdigest()
    state = State(paths.state)
    try:
        with state.db:
            state.db.execute('BEGIN IMMEDIATE')
            prior = state.db.execute('SELECT * FROM desktop_workspace_commands WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise DesktopPlanError('That action identity belongs to a different decision.')
                return dict(status=prior['status'], message=prior['result'])
            require_control_run(state.db, run, allow_owned=verb in ('cancel','archive','restore'))
            current = _view(state, run, paths)
            if current['review_digest'] != review_digest:
                raise DesktopPlanError('This job or its outputs changed. Refresh and review the current state.')
            rt = Runtime(pc.root(state), connection=state.db)
            if verb == 'select':
                selected = next((g for g in current['selection_groups'] if g['id'] == group), None)
                if not selected or not note.strip():
                    raise DesktopPlanError('Review the exact output set and enter your decision note.')
                if state.db.execute("SELECT 1 FROM orchestrator_chats WHERE focus=? AND status IN ('queued','sending','guides_pending')", (run,)).fetchone() or state.db.execute("SELECT 1 FROM production_revisions WHERE run=? AND status='queued'", (run,)).fetchone():
                    raise DesktopPlanError('A follow-up is still being processed. Wait before selecting outputs.')
                members = [m['id'] for m in selected['members']]
                rt.select(run, selected['task'], members[0], selected['purpose'], note, artifacts=members)
                message = 'Selection recorded for the reviewed output set.'
                if pc.review_resume_digest(state, run):
                    message += '\n' + pc.resume_review(state, run)
            else:
                if verb not in current['controls']:
                    raise DesktopPlanError('That control is no longer available.')
                if verb == 'pause':
                    rt.pause(run)
                    message = 'Scheduling paused. Running workers may finish.'
                elif verb == 'resume':
                    if state.get('production-enabled:' + run) != current['contract_digest']:
                        message = pc.resume_review(state, run, legacy=True)
                    else:
                        rt.resume(run)
                        message = 'Scheduling resumed within the approved stage.'
                elif verb == 'archive':
                    state.db.execute('INSERT OR IGNORE INTO desktop_job_archives VALUES (?,?,?,?)',
                                     ('run', run, review_digest, time.time()))
                    message = 'Removed from Jobs. Files, decisions and recovery history are retained.'
                elif verb == 'restore':
                    state.db.execute("DELETE FROM desktop_job_archives WHERE kind='run' AND id=?", (run,))
                    message = 'Restored to Jobs.'
                else:
                    rt.request_cancel(run)
                    state.put('production-enabled:' + run, False)
                    state.put('production-review-grant:' + run, False)
                    state.db.execute("UPDATE production_revisions SET status='failed',error='Stage cancelled by user' WHERE run=? AND status='queued'", (run,))
                    state.db.execute("UPDATE production_continuations SET status='failed',error='Parent stage cancelled by user' WHERE parent=? AND status='queued'", (run,))
                    message = 'Cancellation recorded. Saved outputs are retained; running workers may still be stopping.'
                state.put('production-control-epoch:' + run, state.get('production-control-epoch:' + run, 0) + 1)
            state.db.execute('INSERT INTO desktop_workspace_commands VALUES (?,?,?,?,?,?,?,?)',
                             (request_id, run, verb, fingerprint, 'accepted', message, note, time.time()))
            pc.notice(relay_channels.ScopedState(state, 'desktop'), run, 'desktop-action:' + request_id, message)
        return dict(status='accepted', message=message)
    finally:
        state.db.close()
