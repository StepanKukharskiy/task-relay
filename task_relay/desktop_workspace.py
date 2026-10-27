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


def _display_backend(spec, default):
    """A connector executes its registered operation, not the graph's default AI."""
    execution=spec.get('execution')
    if execution:
        from orchestrator.execution import REGISTRY
        value=dict(type='Registered '+REGISTRY.get(execution['capability'],{}).get('kind','operation'))
        if execution.get('parameters',{}).get('model'):value['model']=execution['parameters']['model']
        return value
    from orchestrator.worker_capabilities import backend_for
    return spec.get('backend') or backend_for(spec,default)


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
        from .pipeline_lineage import collect
        memberships = {p['id']:collect(db,p['id']) for p in db.execute('SELECT id FROM relay_pipelines')}
        owned = {key:sorted(set().union(*(m[key] for m in memberships.values())))
                 for key in ('requests','plans','runs')}
        query_args = [json.dumps(owned['plans']), json.dumps(owned['runs']), json.dumps(owned['requests']), json.dumps(owned['requests'])]
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
                   WHERE d.status!='deleted' AND NOT EXISTS (SELECT 1 FROM desktop_request_modes m JOIN production_runs n ON n.id=d.result WHERE m.request_id=d.request_id AND m.entry_mode='node') AND NOT EXISTS (SELECT 1 FROM production_plans p WHERE p.request_id=d.job_id)
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
                   r.id,COALESCE((SELECT MAX(e.created) FROM production_events e WHERE e.run=r.id),0) FROM production_runs r WHERE NOT EXISTS (SELECT 1 FROM production_plans p WHERE p.run=r.id)
                   UNION ALL SELECT 'task',w.id,w.title,w.status,'shared',NULL,w.updated_at FROM watched w'''
        # One parent job owns its stages and historical recovery plans. Keep the
        # underlying records available in detail without turning each into a job.
        query = '''SELECT * FROM ('''+query+''') item WHERE NOT (
            (kind='plan' AND id IN (SELECT value FROM json_each(?))) OR
            (kind='run' AND id IN (SELECT value FROM json_each(?))) OR
            (kind='chat' AND CAST(id AS INTEGER) IN (SELECT value FROM json_each(?))) OR
            (kind='request' AND id IN (SELECT request_id FROM desktop_plan_requests
                WHERE job_id IN (SELECT value FROM json_each(?)))))
            UNION ALL SELECT 'pipeline',p.id,p.title,p.status,p.channel,NULL,
                MAX(p.created,COALESCE((SELECT MAX(e.created) FROM relay_pipeline_events e WHERE e.pipeline=p.id),p.created))
                FROM relay_pipelines p'''
        from . import conversation_flow
        # Explicit node executions belong to their existing canvas, not new Jobs.
        query="SELECT * FROM ("+query+") item WHERE NOT (kind='run' AND id IN (SELECT run FROM production_events WHERE kind='canvas_node_version'))"
        query="SELECT * FROM ("+query+") item WHERE NOT (kind='run' AND id IN (SELECT e.run FROM production_events e JOIN orchestrator_chats c ON CAST(c.id AS TEXT)=json_extract(e.data,'$.request_id') WHERE e.kind='conversation_graph_bound'))"
        if conversation_flow.exists(db):
            query='''WITH RECURSIVE linked_plans(id) AS (
                SELECT p.id FROM production_plans p JOIN desktop_plan_requests d ON d.job_id=p.request_id
                JOIN conversation_followups f ON f.request_id=d.request_id
                UNION SELECT p.id FROM production_plans p JOIN linked_plans l ON p.parent_id=l.id)
                SELECT * FROM ('''+query+''') item WHERE NOT (
                    (kind='request' AND id IN (SELECT request_id FROM conversation_followups)) OR
                    (kind='chat' AND id IN (SELECT CAST(d.job_id AS TEXT) FROM desktop_plan_requests d JOIN conversation_followups f ON f.request_id=d.request_id)) OR
                    (kind='plan' AND id IN (SELECT id FROM linked_plans)) OR
                    (kind='run' AND id IN (SELECT run FROM production_plans WHERE run IS NOT NULL AND id IN (SELECT id FROM linked_plans))))'''
        if not include_archived and db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_job_archives'").fetchone():
            query = 'SELECT * FROM (' + query + ') j WHERE NOT EXISTS (SELECT 1 FROM desktop_job_archives a WHERE a.kind=j.kind AND a.id=j.id) AND NOT EXISTS (SELECT 1 FROM desktop_job_archives a WHERE a.kind=\'run\' AND a.id=j.run)'
        result['conversation_delete_pending'] = ([dict(r) for r in db.execute("SELECT id,status,error FROM desktop_conversation_deletions WHERE status='cleanup_pending' ORDER BY created")]
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_conversation_deletions'").fetchone() else [])
        projected = [dict(r) for r in db.execute("SELECT * FROM (" + query + ") ORDER BY (kind='task'),stamp DESC,id",query_args)]
        for item in projected:
            if item.get('run'):
                row=db.execute('SELECT status,plan FROM production_runs WHERE id=?',(item['run'],)).fetchone()
                has_versions=db.execute("SELECT 1 FROM production_events WHERE kind='canvas_node_version' AND json_extract(data,'$.run')=?",(item['run'],)).fetchone()
                saved_title=db.execute("SELECT json_extract(data,'$.title') FROM production_events WHERE run=? AND kind='canvas_workflow_saved' ORDER BY id DESC LIMIT 1",(item['run'],)).fetchone()
                if saved_title and saved_title[0]:item['title']=saved_title[0]
                if row and (json.loads(row['plan']).get('job_owner') or has_versions):
                    from orchestrator.runtime import run_status
                    tasks=list(db.execute('SELECT * FROM production_tasks WHERE run=?',(item['run'],)))
                    if has_versions:
                        from .desktop_node_runs import canvas_document,canvas_current
                        from orchestrator.runtime import Runtime
                        rt=Runtime(paths.data/'orchestrator',connection=db,read_only=True)
                        record=canvas_document(rt,item['run'])
                        identities=[canvas_current(rt,record,t['id']) for t in record['workflow']['tasks']]
                        tasks=[db.execute('SELECT * FROM production_tasks WHERE run=? AND id=?',(i['run'],i['task'])).fetchone() for i in identities if i]
                    specs=[json.loads(db.execute('SELECT spec FROM production_assignments WHERE id=?',(t['assignment'],)).fetchone()[0]) for t in tasks]
                    item['status']=run_status(row['status'],tasks,specs)
            ident=(db.execute('SELECT job_id FROM desktop_plan_requests WHERE request_id=?',(item['id'],)).fetchone()[0]
                   if item['kind']=='request' else int(item['id']) if item['kind']=='chat' else None)
            if ident is not None:
                aggregate=conversation_flow.summary(db,ident)
                if aggregate:item.update(status=aggregate['status'],stamp=max(item['stamp'],aggregate['stamp']),conversation_flow=True)
        projected.sort(key=lambda item:(item['kind']=='task',-item['stamp'],item['id']))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_job_archives'").fetchone():
            for item in projected:
                item['archived'] = bool(db.execute('SELECT 1 FROM desktop_job_archives WHERE (kind=? AND id=?) OR (kind=\'run\' AND id=?)',
                                                   (item['kind'], item['id'], item['run'])).fetchone())
        review=[i for i in projected if not i.get('archived') and i['status'] in ('ready','awaiting_user','needs_input','blocked','uncertain')]
        result.update(total=len(projected),items=projected[offset:offset+40],review_total=len(review),review_items=review[:100])
        if offset + len(result['items']) < result['total']:
            result['next_offset'] = offset + len(result['items'])
    return result


def pipeline_detail(ident, paths=PATHS):
    """One committed parent, current stage heads and immutable execution history."""
    from .pipeline_lineage import collect
    from .workflow_usage import report
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        p = db.execute('SELECT * FROM relay_pipelines WHERE id=?', (ident,)).fetchone()
        if not p: raise DesktopPlanError('That saved workflow is unavailable.')
        from . import workflow_state, delivery_completion
        owner_states={v['owner']['step']:v for v in workflow_state.read(db,ident)}
        try: coverage=delivery_completion.coverage(ReadState(db,paths),p)
        except (ValueError,OSError) as exc: coverage=dict(error=str(exc))
        members = collect(db, ident)
        delivery_holds=[]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_delivery_effects'").fetchone():
            prefixes=(f'pipeline:{ident}:',*(f'production:{run}:' for run in members['runs']))
            delivery_holds=[dict(r) for r in db.execute("SELECT id,event_id,status,error FROM relay_delivery_effects WHERE status IN ('submitting','uncertain')") if r['event_id'].startswith(prefixes)]
        usage = report(ReadState(db, paths), ident)
        attempts, tasks, history, stages = [], {}, [], []
        current_runs = set()
        saved_plans = {r['id']:dict(r) for r in db.execute('SELECT id,run,status,request,error,created FROM production_plans') if r['id'] in members['plans']}
        for step in db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? ORDER BY position', (ident,)):
            stage = dict(step)
            plan = saved_plans.get(step['target'])
            run = step['target'] if step['target_kind']=='production_run' else plan['run'] if plan else None
            stage['lifecycle']=owner_states.get(step['id'])
            stage.update(run=run, plan_status=plan['status'] if plan else None,
                         sources=json.loads(step['sources'] or '[]'))
            if run: current_runs.add(run)
            stages.append(stage)
        for row in db.execute('SELECT rowid,id,plan,status FROM production_runs ORDER BY rowid'):
            if row['id'] not in members['runs']: continue
            run = row['id']; plan = json.loads(row['plan']); run_tasks = []
            for task in db.execute('SELECT t.*,a.spec FROM production_tasks t LEFT JOIN production_assignments a ON a.id=t.assignment WHERE t.run=? ORDER BY t.rowid', (run,)):
                spec = json.loads(task['spec'] or '{}')
                entry = {k:task[k] for k in ('id','status','attempts','latest')}
                entry.update(role=spec.get('role'), review_of=spec.get('review_of'),
                             objective=spec.get('objective',task['id']),
                             operation=spec.get('execution',{}).get('capability'),
                             backend=_display_backend(spec,plan.get('backend',{})))
                run_tasks.append(entry)
            tasks[run] = run_tasks
            for attempt in db.execute('SELECT id,task,state,error,frozen,receipt FROM production_attempts WHERE run=? ORDER BY rowid', (run,)):
                frozen=json.loads(attempt['frozen']); receipt=json.loads(attempt['receipt'] or '{}')
                from .production_activity import snapshot
                telemetry=snapshot(paths.runtime,attempt,frozen,plan.get('backend',{}))
                attempts.append(dict(telemetry=telemetry,id=attempt['id'],run=run,task=attempt['task'],state=attempt['state'],error=attempt['error'],
                    reviewer=bool(frozen.get('review_of')),review_of=frozen.get('review_of'),review_target=frozen.get('review_target'),
                    operation=frozen.get('execution',{}).get('capability'),backend=_display_backend(frozen,{}),
                    started=receipt.get('started'),finished=receipt.get('finished'),tool_calls=receipt.get('tool_calls'),
                    current=run in current_runs,receipt_status=receipt.get('status')))
            history.append(dict(id=run,current=run in current_runs,tasks=run_tasks))
        for stage in stages:
            stage['tasks']=tasks.get(stage['run'],[])
            plan=saved_plans.get(stage['target'])
            stage['plan_error']=plan['error'] if plan else None
            # Reuse the exact read-only execution projection. Stage order alone
            # is not a task graph and cannot establish file handoffs.
            stage['execution'] = _view(ReadState(db, paths), stage['run'], paths) if stage['run'] in tasks else None
        current_tasks=[t for run in current_runs for t in tasks.get(run,[])]
        stats=dict(stages=len(stages),stages_completed=sum(s['status']=='completed' for s in stages),
            tasks=len(current_tasks),tasks_completed=sum(t['status']=='completed' for t in current_tasks),
            workers_created=sum(not a['operation'] for a in attempts),
            reviewers_created=sum(a['reviewer'] for a in attempts),
            operations_started=sum(bool(a['operation']) for a in attempts),
            running=sum(a['state'] in ('launching','running','cancelling') for a in attempts),
            uncertain=sum(a['state']=='uncertain' for a in attempts),
            runs=len(members['runs']),plans=len(members['plans']))
        # Stage sources are committed version identities, not arbitrary files in
        # the output folder. Label intermediate and final results by their stage.
        outputs=[];seen=set()
        for stage in stages:
            for source in stage['sources']:
                aid=source.get('artifact')
                if not aid or aid in seen: continue
                file=db.execute('SELECT id,path,sha256,bytes,purpose FROM production_artifacts WHERE id=?',(aid,)).fetchone()
                if file: outputs.append({**dict(file),'stage':stage['id']});seen.add(aid)
        live_states=('launching','running','cancelling')
        active_attempts=[a for a in attempts if a['state'] in live_states]
        latest_event=db.execute('SELECT step,kind,created FROM relay_pipeline_events WHERE pipeline=? ORDER BY created DESC,rowid DESC LIMIT 1',(ident,)).fetchone()
        health=ReadState(db,paths).get('health:workflows',{})
        activity=dict(attempts=active_attempts,stages=[s['id'] for s in stages if s['status'] not in ('completed','skipped','cancelled')],
                      last_event=dict(latest_event) if latest_event else None,
                      controller_fresh=bool(0 <= time.time()-health.get('last_success',0) < 60))
        return dict(kind='pipeline',id=ident,title=p['title'],request=p['request'],status=p['status'],channel=p['channel'],
                    stages=stages,stats=stats,usage={k:v for k,v in usage.items() if k!='records'},
                    coverage=coverage,delivery_holds=delivery_holds,activity=activity,attempts=attempts,runs=history,plans=list(saved_plans.values()),outputs=outputs)


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
        if value['entry_mode'] == 'node' and value['status'] == 'accepted':
            value['node_run'] = value['result']
            value['node_view'] = _view(ReadState(db, paths), value['node_run'], paths)
            value['status'] = value['node_view']['status']
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
        value['can_message']=conversation_flow.message_available(db,ident)
        try:
            from .capability_defaults import snapshot
            choice=next(item for item in snapshot(paths)['capabilities'] if item['capability']=='text')
            if not choice['selected_available'] or not choice['selected'] or not choice['selected'].get('model'):
                raise ValueError('Conversation model not connected')
            value['message_model']=choice['selected']
        except ValueError:
            value['can_message']=False
            value['message_setup']='Choose a connected conversation model in Settings.'
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


def _project_canvas(state,rt,view,paths):
    from .desktop_node_runs import canvas_document,canvas_current,canvas_lookup,node_versions,canvas_executions,canvas_result_outdated,canvas_execution_holds
    from orchestrator import node_spec,owner_intents
    import copy
    run=view['name'];record=canvas_document(rt,run)
    view['canvas_document']=record;view['brief']=record['title']
    resolved=node_spec.resolve_workflow(record['workflow'],record['values'],artifact=canvas_lookup(rt,run),draft=True)
    originals={t['id']:t for t in view['tasks']};cache={}
    outputs=[];old_outputs=list(view.get('historical_outputs',[]));tasks=[];active=set()
    for executed in canvas_executions(rt,run):
        if rt.status(executed)['status'] in ('active','settling'):active.add(executed)
    def execution(identity):
        other=identity['run']
        if other==run:return originals.get(identity['task']),[f for f in view.get('latest_outputs',[]) if f['task']==identity['task']]
        if other not in cache:cache[other]=_view(state,other,paths,project_canvas=False)
        child=cache[other]
        return next((t for t in child['tasks'] if t['id']==identity['task']),None),[f for f in child.get('latest_outputs',[]) if f['task']==identity['task']]
    for node in resolved['tasks']:
        tid=node['id'];history=[];current=None
        baseline=record['baselines'].get(tid)
        identities=([baseline] if baseline else [])+[dict(run=r,task=tid) for r in node_versions(state.db,run,tid)]
        for identity in identities:
            item,files=execution(identity)
            if item is None:continue
            current=copy.deepcopy(item);current.update(id=tid,execution_run=identity['run'],execution_task=identity['task'])
            files=[dict(f,task=tid) for f in files]
            history.append(dict(run=identity['run'],attempt=item['latest_attempt'],prompt=item.get('prompt') or item['objective'],status=item['status'],error=item.get('error'),files=files))
            if item['status'] in ('queued','running','launching','settling','cancelling'):active.add(identity['run'])
        if current is None:current=dict(id=tid,status='draft',latest_attempt=None,attempts=0,recorded_inputs=[],planned_outputs=[],planned_inputs=[])
        current['versions']=history
        if current['status']=='uncertain':
            try:current['can_start_new_attempt']=bool(canvas_execution_holds(rt,record,tid))
            except ValueError:current['can_start_new_attempt']=False
        current['execution_prompt']=current.get('prompt') or current.get('objective')
        current['objective']=node['objective'];current['operation']=node['operation']
        current['prompt']=node['inputs'].get('prompt',{}).get('value')
        freshness=canvas_result_outdated(rt,record,resolved,node,identity) if history else False
        current['outdated']=freshness is True
        current['freshness_known']=freshness is not None
        current['definition']=node
        current['dependencies']=[];current['planned_inputs']=[]
        for link in resolved['connections']:
            if link['task']!=tid:continue
            ref=link['source']
            if 'task' in ref:
                wire_output=ref['output']
                upstream=canvas_current(rt,record,ref['task'])
                if upstream:
                    source=rt.task(upstream['run'],upstream['task'])
                    attempt=rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(source['latest'],)).fetchone()
                    if attempt:wire_output=owner_intents.ports(json.loads(attempt[0])).get(ref['output'],{}).get('path',wire_output)
                current['planned_inputs'].append(dict(path=link['input'],from_task=ref['task'],output=wire_output,purpose=link['input']))
                current['dependencies'].append(dict(task=ref['task']))
            else:current['planned_inputs'].append(dict(path=link['input'],artifact=ref.get('artifact'),purpose=link['input']))
        # Named ports belong to the authored operation, independent of filenames.
        if not history:
            from orchestrator.operation_definition import presentation
            shown=presentation(node['operation'])['outputs']
            ports=node.get('outputs') or [dict(name=k,**v) for k,v in shown.items()]
            current['planned_outputs']=[dict(path=p['name'],purpose=p.get('purpose') or p['name'],media_type=p.get('media_type'),
                label=p.get('label') or shown.get(p['name'],{}).get('label') or p['name']) for p in ports]
        if history:
            outputs.extend(history[-1]['files']);old_outputs.extend(f for h in history[:-1] for f in h['files'])
        tasks.append(current)
    # Upstream draft edits don't change the saved result consumed by a node.
    # A new completed output is compared by its exact identity above.
    view.update(tasks=tasks,latest_outputs=outputs,historical_outputs=old_outputs,executing_runs=sorted(active),completed_sources=[])
    statuses={t['status'] for t in tasks}
    if active:view['status']='active'
    elif 'uncertain' in statuses:view['status']='uncertain'
    elif 'blocked' in statuses:view['status']='blocked'
    elif statuses=={'completed'}:view['status']='completed'
    elif 'draft' in statuses:view['status']='draft'


def _port_presentation(spec, file):
    """Shared display metadata; never rewrite the declared port identity."""
    from orchestrator import operation_definition,owner_intents
    ports=owner_intents.ports(spec) if spec.get('outputs') else {}
    matching=[(name,p) for name,p in ports.items() if p['path']==file['path']]
    port=matching[0][1] if len(matching)==1 else file
    display=operation_definition.output_presentation(port)
    if len(matching)==1:display['output_port']=matching[0][0]
    op=spec.get('execution',{}).get('capability') or spec.get('operation_contract',{}).get('id')
    if op and len(matching)==1:
        try:
            shown=operation_definition.presentation(op)['outputs'].get(matching[0][0],{})
            if shown.get('path')==file['path']:
                display.update({k:shown[k] for k in ('label','role','open_with') if k in shown})
        except ValueError:pass
    return display


def _result_presentation(db, file):
    """Label an artifact through its exact producing declaration."""
    row=db.execute('SELECT frozen FROM production_attempts WHERE id=?',(file.get('attempt'),)).fetchone()
    display=_port_presentation(json.loads(row[0]) if row else {},file)
    return dict(display_name=display['label'],result_role=display['role'],
                open_with=display.get('open_with'),output_port=display.get('output_port'))


def _view(state, run, paths=PATHS, *, project_canvas=True):
    from . import production_control as pc
    from orchestrator.runtime import Runtime
    view = next(iter(pc.inspect(state, run, exact=True)), None)
    if not view:
        raise DesktopPlanError('That saved job is unavailable.')
    rt = Runtime(pc.root(state), connection=state.db, read_only=True)
    # Inspect the saved assignment and frozen attempt, never resolve or dispatch
    # inputs merely to draw a workflow. Filename equality is not version identity.
    plan = json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?', (run,)).fetchone()[0])
    if state.db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_node_runs'").fetchone():
        view['canvas_run']=bool(state.db.execute('SELECT 1 FROM desktop_node_runs WHERE run=?',(run,)).fetchone())
        view['canvas_pending']=view['canvas_run'] and bool(state.db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling')",(run,)).fetchone())
        if view['canvas_run']:
            from .desktop_node_runs import result_chats
            view['result_chats']=result_chats(state.db,run)
    if plan.get('job_owner', {}).get('node_contract'):
        from orchestrator import node_spec
        view['node'] = node_spec.presentation(plan['job_owner']['node_contract'])
    for task in view['tasks']:
        assignment = state.db.execute('''SELECT a.spec FROM production_assignments a
            JOIN production_tasks t ON t.assignment=a.id WHERE t.run=? AND t.id=?''', (run, task['id'])).fetchone()
        spec = json.loads(assignment[0])
        attempt = state.db.execute('SELECT frozen FROM production_attempts WHERE id=?', (task['latest_attempt'],)).fetchone()
        frozen = json.loads(attempt[0]) if attempt else None
        task['backend'] = _display_backend(frozen or spec, plan['backend'])
        task['prompt'] = (frozen or spec).get('execution', {}).get('parameters', {}).get('prompt')
        task['tools'] = (frozen or spec).get('tools', [])
        task['planned_inputs'] = spec.get('inputs', [])
        task['planned_outputs'] = [dict(p,label=_port_presentation(spec,p)['label']) for p in spec.get('outputs', [])]
        for file in view.get('latest_outputs',[])+view.get('historical_outputs',[]):
            if file['task']==task['id']:
                file.update(_result_presentation(state.db,file))
        task['recorded_inputs'] = []
        for item in (frozen or {}).get('inputs', []):
            value = {k: item.get(k) for k in ('path', 'sha256', 'purpose', 'authority', 'artifact')}
            registered = state.db.execute('SELECT id,path,bytes,sha256 FROM production_artifacts WHERE id=?', (item.get('artifact'),)).fetchone()
            value['file'] = dict(registered) if registered and registered['sha256'] == item.get('sha256') else None
            task['recorded_inputs'].append(value)
    if view.get('canvas_run') and project_canvas and not state.db.execute("SELECT 1 FROM production_events WHERE run=? AND kind='canvas_node_version'",(run,)).fetchone():
        _project_canvas(state,rt,view,paths)
    if project_canvas and not view.get('canvas_document') and state.db.execute(
            "SELECT 1 FROM production_events WHERE run=? AND kind='canvas_workflow_admitted'",(run,)).fetchone():
        from .desktop_node_runs import canvas_document
        try:
            authored=canvas_document(rt,run)
            view['workflow_export']={k:authored[k] for k in ('canvas','title','revision')}
        except ValueError:
            pass  # A version belongs to its owning canvas; never invent a graph.
    try:
        require_control_run(state.db, run)
        controllable = True
        control_error = None
    except DesktopPlanError as exc:
        controllable = False
        control_error = str(exc)
    controls = []
    if controllable:
        if view['status'] == 'paused' or (not view.get('canvas_run') and pc.review_resume_digest(state, run, view, legacy=True)):
            controls.append('resume')
        elif view['status'] in ('active', 'uncertain') and (view['scheduler_enabled'] or view.get('canvas_run')):
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


def artifact_preview(artifact, sha256, paths=PATHS, *, page=1):
    """Bounded, read-only display of an exact registered version; never publish."""
    import base64
    from . import production_control as pc
    from orchestrator.runtime import safe_file
    with closing(_database(paths)) as db:
        row = db.execute('SELECT path,blob,sha256,bytes FROM production_artifacts WHERE id=?', (artifact,)).fetchone()
        if not row or row['sha256'] != sha256:
            raise DesktopPlanError('That saved file version is unavailable.')
        if row['bytes'] > 8 * 1024 * 1024:
            raise DesktopPlanError('File exceeds the 8 MB inline preview limit. Open the saved file.')
        root = pc.root(ReadState(db, paths)).resolve()
        path = safe_file(root, str(Path(row['blob']).relative_to(root)))
        with path.open('rb') as stream:
            content = stream.read(8 * 1024 * 1024 + 1)
        if len(content) != row['bytes'] or hashlib.sha256(content).hexdigest() != sha256:
            raise DesktopPlanError('That file changed. Its saved version cannot be previewed.')
        suffix=Path(row['path']).suffix.lower()
        if suffix in ('.md','.markdown','.txt','.json','.csv','.py','.js'):
            try:text=content.decode('utf-8')
            except UnicodeError:raise DesktopPlanError('This saved text is not UTF-8.') from None
            return dict(sha256=sha256,media_type='text/markdown' if suffix in ('.md','.markdown') else 'text/plain',
                text=text[:40000],truncated=len(text)>40000,full_chars=len(text))
        if suffix=='.pdf':
            from .presentation_host import preview_pdf_page
            return dict(sha256=sha256,**preview_pdf_page(content,page))
        if Path(row['path']).suffix.lower() in ('.html', '.htm'):
            from .html_preview import render
            try:
                preview = render(content)
            except (ValueError, UnicodeError) as exc:
                raise DesktopPlanError('Cannot preview this HTML file. Open the saved file.') from exc
            return {'sha256': sha256, 'media_type': 'text/html', 'html': preview,
                    'transformation': 'Local preview with display-sized embedded images. Scripts, links and external resources are inactive; original unchanged.'}
        mime = ('image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/jpeg' if content.startswith(b'\xff\xd8\xff') else
                'image/gif' if content.startswith((b'GIF87a', b'GIF89a')) else
                'image/webp' if content[:4] == b'RIFF' and content[8:12] == b'WEBP' else None)
        if not mime:
            raise DesktopPlanError('This file is not a supported raster image.')
        transformation = 'original'
        # Base64 plus JSON must fit the existing 1 MB desktop bridge envelope.
        if len(content) > 650000:
            import io
            from PIL import Image, ImageOps
            try:
                with Image.open(io.BytesIO(content)) as source:
                    if source.width * source.height > 20_000_000 or getattr(source, 'n_frames', 1) != 1:
                        raise ValueError('Oversized or animated source')
                    source.load()
                    picture = ImageOps.exif_transpose(source).convert('RGBA')
                picture.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                while True:
                    buffer = io.BytesIO(); picture.save(buffer, format='PNG'); content = buffer.getvalue()
                    if len(content) <= 650000:
                        break
                    picture = picture.resize(tuple(max(1, int(n * .75)) for n in picture.size), Image.Resampling.LANCZOS)
                mime = 'image/png'; transformation = 'display-sized preview; original unchanged'
            except (OSError, ValueError) as exc:
                raise DesktopPlanError('Cannot create an inline preview. Open the saved file.') from exc
        return {'sha256': sha256, 'transformation': transformation,
                'data_url': 'data:' + mime + ';base64,' + base64.b64encode(content).decode()}


def artifact_link(value, paths=PATHS):
    """Verify a user-clicked public link against the exact displayed Markdown."""
    import html
    import re
    from .orchestrator_web import public_url
    if set(value)!={'artifact','sha256','url'}:
        raise DesktopPlanError('Choose a link in an exact saved output.')
    url=value['url']
    public_url(url)  # Existing public URL policy; no fetch, DNS lookup or dispatch.
    preview=artifact_preview(value['artifact'],value['sha256'],paths)
    if preview.get('media_type')!='text/markdown':
        raise DesktopPlanError('This output has no Markdown links.')
    # Match the complete literal destination, not a host/prefix or a fabricated
    # URL from the UI. HTML entities are decoded by the Markdown renderer too.
    text=html.unescape(preview['text'])
    if not re.search(r"(?:^|[\s(<])"+re.escape(url)+r"(?=$|[\s)>\"'])",text):
        raise DesktopPlanError('That link is not in this saved output preview.')
    return {'url':url}


def open_artifact(value, paths=PATHS):
    """Open a verified named copy with the registered application's adapter."""
    if set(value)!={'artifact','sha256'}:raise DesktopPlanError('Choose one exact saved output')
    with closing(_database(paths)) as db:
        row=db.execute('SELECT * FROM production_artifacts WHERE id=?',(value['artifact'],)).fetchone()
        if not row or row['sha256']!=value['sha256']:raise DesktopPlanError('The saved output version changed')
        application=_result_presentation(db,dict(row)).get('open_with')
        if application!='Blender' or Path(row['path']).suffix!='.blend':
            raise DesktopPlanError('This output has no supported native Open action')
    named=artifact_path(value['artifact'],paths)
    from .host import HOST
    HOST.open_result(application,named['path'])
    return dict(application=application,path=named['path'],sha256=value['sha256'],status='open_requested')


def artifact_path(artifact, paths=PATHS, *, location_only=False):
    from . import production_control as pc
    from orchestrator.runtime import safe_file, file_hash
    with closing(_database(paths)) as db:
        db.execute('BEGIN')
        row = db.execute('SELECT id,run,path,blob,sha256,bytes FROM production_artifacts WHERE id=?', (artifact,)).fetchone()
        if not row:
            raise DesktopPlanError('That registered file is unavailable.')
        root = pc.root(ReadState(db, paths)).resolve()
        path = safe_file(root, str(Path(row['blob']).relative_to(root)))
        if path.stat().st_size != row['bytes'] or file_hash(path) != row['sha256']:
            raise DesktopPlanError('That file changed. Its saved version cannot be revealed.')
        from . import workflow_files, result_handoff
        from .relay_channels import ScopedState
        state=ReadState(db,paths)
        db.commit()  # Folder publication always follows the read transaction.
        owner=None
        # Use the exporter's exact membership, including historical recovery and
        # input versions, instead of maintaining another ownership traversal.
        for pipeline in db.execute('SELECT id,channel FROM relay_pipelines ORDER BY created DESC,id').fetchall():
            if location_only:
                # Read existing export indexes, not every historical artifact and
                # runtime snapshot. The chosen file is still hash-checked below.
                folder=workflow_files.folder_path(state,pipeline['id'])
                from .production_folders import checked_directory
                checked_directory(folder)
                marker=folder/'.relay-workflow.json'
                if not marker.exists() and not marker.is_symlink():continue
                saved=json.loads(safe_file(folder,'.relay-workflow.json').read_text())
                contains=saved.get('workflow')==pipeline['id'] and artifact in saved.get('paths',{})
            else:
                report=workflow_files._snapshot(ScopedState(state,pipeline['channel']),pipeline['id'])
                contains=any(a['id']==artifact for a in report['artifacts'])
            if contains:
                owner=dict(pipeline)
                break
        uses=[row['run']] if row['run'] else []
        uses.extend(r[0] for r in db.execute("SELECT DISTINCT a.run FROM production_assignments a,json_each(a.spec,'$.inputs') i WHERE json_extract(i.value,'$.artifact')=? ORDER BY a.run",(artifact,)))
        uses.extend(r[0] for r in db.execute("SELECT p.run FROM production_plans p,json_each(p.context,'$.sources') s WHERE json_extract(s.value,'$.artifact')=? AND p.run IS NOT NULL ORDER BY p.created DESC",(artifact,)))
        standalone=next((run for run in uses
                         if db.execute('SELECT 1 FROM production_runs WHERE id=?',(run,)).fetchone()),None)
        if owner:
            scoped=ScopedState(state,owner['channel'])
            folder=workflow_files.folder_path(scoped,owner['id']) if location_only else workflow_files.sync(scoped,owner['id'])
        elif standalone:
            scoped=ScopedState(state,result_handoff.channel_for(state,standalone))
            # Publishing a display copy does not register or authorize a job.
            if location_only:
                current_owner=workflow_files.owner_for_run(scoped,standalone)
                identity=result_handoff.ancestry(scoped,standalone)[0] if not current_owner else None
                report={'id':current_owner['id'] if current_owner else 'job-'+hashlib.sha256(identity.encode()).hexdigest()[:24]}
            else:
                report=result_handoff.snapshot(scoped,standalone)
            from .host import HOST
            from .production_folders import checked_directory
            if location_only:
                folder=workflow_files.folder_path(scoped,report['id'])
            else:
                parent=checked_directory(workflow_files.folder_path(scoped,report['id']).parent)
                parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with workflow_files._safe(parent/('.'+report['id']+'.lock')).open('a') as stream:
                    HOST.lock(stream)
                    folder=workflow_files._sync(scoped,report['id'],report)
        else:
            raise DesktopPlanError('This saved file has no workflow folder yet. Open it from its owning job.')
        if location_only:
            from .production_folders import checked_directory
            checked_directory(folder)
            marker_path=folder/'.relay-workflow.json'
            if not marker_path.exists() and not marker_path.is_symlink():
                return dict(path=None,folder=str(folder),published=False)
        marker=json.loads(safe_file(folder,'.relay-workflow.json').read_text())
        relative=marker.get('paths',{}).get(artifact)
        if not relative and location_only:return dict(path=None,folder=str(folder),published=False)
        if not relative:raise DesktopPlanError('That saved version is not available in its workflow folder.')
        named=safe_file(folder,relative)
        if named.stat().st_size!=row['bytes'] or file_hash(named)!=row['sha256']:
            raise DesktopPlanError('That workflow copy changed. Refresh to reveal its exact saved version.')
        return dict(path=str(named),folder=str(folder),name=named.name)


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
                    if not current.get('canvas_run') and state.get('production-enabled:' + run) != current['contract_digest']:
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


def job_visibility(value, paths=PATHS):
    """Recoverable list deletion in the existing archive store; never stop work."""
    if not isinstance(value,dict) or set(value)!={'kind','id','deleted'} or type(value['deleted']) is not bool:
        raise DesktopPlanError('Choose a saved job and whether to delete or restore it.')
    kind,ident=value['kind'],value['id']
    if kind not in ('run','plan','pipeline','request','chat','task','draft') or not isinstance(ident,str) or not ident or len(ident)>200:
        raise DesktopPlanError('Choose a valid saved job.')
    with closing(_database(paths,writable=True)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if kind=='draft':
            import re
            from .app_updates import read
            if not re.fullmatch('[a-f0-9]{32}',ident):raise DesktopPlanError('Invalid draft identity.')
            record=read(paths.data/'node-drafts'/(ident+'.json'))
            if record is None:raise DesktopPlanError('Draft not found.')
            item=dict(kind=kind,id=ident,title=record['title'],status='draft',run=None)
        else:
            offset=0;item=None
            while True:
                page=jobs(offset,paths,include_archived=True)
                item=next((i for i in page['items'] if i['kind']==kind and i['id']==ident),None)
                if item or page['next_offset'] is None:break
                offset=page['next_offset']
            if not item:raise DesktopPlanError('That saved job is unavailable.')
        if value['deleted']:
            if item['status'] not in ('completed','cancelled','answered','failed','rejected','blocked','draft'):
                raise DesktopPlanError('This job is not finished. Finish or cancel it before deleting it from Jobs.')
            runs={item['run']} if item.get('run') else set()
            if kind=='pipeline':
                from .pipeline_lineage import collect
                runs.update(collect(db,ident)['runs'])
            for run in list(runs):
                runs.update(r[0] for r in db.execute("SELECT DISTINCT run FROM production_events WHERE kind='canvas_node_version' AND json_extract(data,'$.run')=?",(run,)))
            from orchestrator.runtime import Runtime
            rt=Runtime(paths.data/'orchestrator',connection=db,read_only=True)
            if any(rt.status(r)['status'] in ('active','paused','awaiting_user','uncertain') for r in runs):
                raise DesktopPlanError('An execution on this canvas is still active or uncertain. Its job stays visible.')
            if any(db.execute("SELECT 1 FROM production_attempts WHERE run=? AND state IN ('launching','running','cancelling','uncertain')",(r,)).fetchone() for r in runs):
                raise DesktopPlanError('A worker is still active or has an uncertain outcome. Its job stays visible.')
            digest=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO desktop_job_archives VALUES (?,?,?,?)',(kind,ident,digest,time.time()))
        else:
            db.execute('DELETE FROM desktop_job_archives WHERE kind=? AND id=?',(kind,ident))
            if item.get('run'):
                db.execute("DELETE FROM desktop_job_archives WHERE kind='run' AND id=?",(item['run'],))
    return dict(kind=kind,id=ident,deleted=value['deleted'],retained='Files and execution history are retained.')
