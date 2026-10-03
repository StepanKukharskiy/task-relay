"""Selected conversation outcomes stay in one committed, bounded process graph."""
from contextlib import closing
import hashlib
import json
import time

from .desktop_plans import DesktopPlanError, _database
from .relay_paths import PATHS

READ_TOOLS={'operations:web_search','operations:web_fetch'}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS conversation_followups (
        request_id TEXT PRIMARY KEY, source_request_id INTEGER NOT NULL,
        option_index INTEGER NOT NULL, selection_digest TEXT NOT NULL,
        mode TEXT NOT NULL, created REAL NOT NULL, choice_source_id INTEGER,
        UNIQUE(source_request_id,selection_digest))''')
    if 'choice_source_id' not in {r[1] for r in db.execute('PRAGMA table_info(conversation_followups)')}:
        db.execute('ALTER TABLE conversation_followups ADD COLUMN choice_source_id INTEGER')


def exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_followups'").fetchone())


def selections(db,ident):
    from .orchestrator_chat import response_json
    from .conversation_delete import _ident
    number=_ident(str(ident))
    row=db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(number,)).fetchone()
    entry=db.execute('''SELECT d.project,i.manifest FROM desktop_plan_requests d
        JOIN desktop_plan_inputs i ON i.request_id=d.request_id WHERE d.job_id=?''',(number,)).fetchone()
    channel=db.execute('SELECT channel FROM relay_request_channels WHERE request_id=?',(number,)).fetchone()
    if not row or row['status']!='answered' or row['focus'] or not entry or not channel or channel[0]!='desktop':
        raise DesktopPlanError('Select an answered standalone Desktop conversation.')
    response=response_json(row['response'])
    if response.get('action') is not None:raise DesktopPlanError('Use the owning job controls for this response.')
    options=response.get('next_options',[])
    if not isinstance(options,list) or len(options)>3:raise DesktopPlanError('The saved options are unavailable.')
    from .orchestrator_advice import options as validate_options,option_tools
    # Offered IDs were captured with the original request. Current availability
    # is checked by the worker; an option is never substituted with another route.
    captured=json.loads(row['snapshot'])
    tools=option_tools({'snapshot':captured})
    if 'option_tool_ids' in captured:
        tools=[{'id':ident} for ident in captured['option_tool_ids']]
    else:
        # Older overviews retained list heads but preserved full graph discovery
        # and the explicit web configuration marker. Recover only those captured
        # IDs, never tool names suggested by a model or current availability.
        availability=captured.get('current_execution_availability',{})
        for field,group in (('executors','graph_executors'),('operations','graph_operations')):
            tools.extend({'id':group+':'+item['id']} for item in availability.get(field,[])
                         if item.get('available') is True)
        if captured.get('capabilities',{}).get('web',{}).get('web_search')=='Gemini/Google Search; configured':
            tools.append({'id':'operations:web_search'})
    validate_options(options,tools)
    manifest=json.loads(entry['manifest'])
    digests=[hashlib.sha256(json.dumps({'prompt':row['prompt'],'response':row['response'],
               'project':entry['project'],'manifest':manifest,'option_index':index},sort_keys=True).encode()).hexdigest()
             for index in range(len(options))]
    return dict(row),dict(entry),options,digests


def selected(db,ident,index,digest):
    row,entry,options,digests=selections(db,ident)
    if type(index) is not int or not 0<=index<len(options) or digest!=digests[index]:
        raise DesktopPlanError('The recommendation changed. Refresh before selecting it.')
    option=options[index]
    mode='research' if option['tools'] and set(option['tools'])<=READ_TOOLS else 'plan'
    return row,entry,option,mode


def bind(db,selection,goal,constraints,project,files,request_id,entry_mode,research_mode):
    row,entry,option,mode=selected(db,selection['id'],selection['index'],selection['digest'])
    expected_files=[item['path'] for item in json.loads(entry['manifest'])]
    if ((goal,constraints,project,files,entry_mode,research_mode)!=
            (option['request'],'Original request:\n'+row['prompt'],entry['project'],expected_files,
             'conversation' if mode=='research' else 'plan','sources' if mode=='research' else 'suggest')):
        raise DesktopPlanError('The selected outcome does not match its frozen conversation inputs.')
    group=int(root_for(db,job_id=row['id']) or row['id'])
    prior=db.execute('SELECT * FROM conversation_followups WHERE source_request_id=? AND selection_digest=?',
                     (group,selection['digest'])).fetchone()
    if prior:
        original=db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(prior['request_id'],)).fetchone()
        return {'request_id':original['request_id'],'status':original['status'],'root_id':str(group),
                'mode':prior['mode'],'message':original['result'] or 'Selected outcome already saved.'}
    # Verify frozen bytes, not a mutable original attachment location.
    from pathlib import Path
    for item in json.loads(entry['manifest']):
        path=Path(item['path'])
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise DesktopPlanError('A frozen conversation attachment changed. No follow-up was queued.')
    return None


def choose(ident,index,digest,request_id,paths=PATHS):
    with closing(_database(paths)) as db:
        row,entry,option,mode=selected(db,ident,index,digest)
        group=root_for(db,job_id=row['id']) or str(row['id'])
    from .desktop_plans import create
    result=create(option['request'],'Original request:\n'+row['prompt'],entry['project'],None,request_id,paths,
                  files=[item['path'] for item in json.loads(entry['manifest'])],
                  entry_mode='conversation' if mode=='research' else 'plan',
                  research_mode='sources' if mode=='research' else 'suggest',
                  followup={'id':str(row['id']),'index':index,'digest':digest})
    return {**result,'root_id':group,'mode':mode}


def scope(db,job_id):
    if not exists(db):return None
    row=db.execute('''SELECT f.* FROM conversation_followups f JOIN desktop_plan_requests d
        ON d.request_id=f.request_id WHERE d.job_id=?''',(job_id,)).fetchone()
    return dict(row) if row else None


def root_for(db,*,request_id=None,job_id=None,plan_id=None):
    if not exists(db):return None
    if plan_id:
        seen=set()
        while plan_id and plan_id not in seen and len(seen)<32:
            seen.add(plan_id)
            row=db.execute('SELECT request_id,parent_id FROM production_plans WHERE id=?',(plan_id,)).fetchone()
            if not row:return None
            root=root_for(db,job_id=row['request_id'])
            if root:return root
            plan_id=row['parent_id']
        return None
    if job_id is not None:
        row=db.execute('SELECT request_id FROM desktop_plan_requests WHERE job_id=?',(job_id,)).fetchone()
        request_id=row[0] if row else None
    row=db.execute('SELECT source_request_id FROM conversation_followups WHERE request_id=?',(request_id,)).fetchone()
    return str(row[0]) if row else None


def read_steps(paths,ident):
    """Hash-checked successful/failed reads; final prose is not read evidence."""
    from pathlib import Path
    path=paths.data/'orchestrator-reads'/(hashlib.sha256(str(ident).encode()).hexdigest()+'.json')
    try:
        if not path.exists() or path.is_symlink() or path.stat().st_size>20_000_000:return []
        journal=json.loads(path.read_text());result=[]
        for turn in journal:
            for read in turn.get('reads',[]):
                call=read['call'];data=read['result']
                if call['name'] not in ('web_search','web_fetch'):continue
                if read.get('result_sha256')!=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest():continue
                args=json.loads(call['arguments'])
                result.append({'id':'read:'+str(ident)+':'+str(len(result)),
                               'objective':('Search: '+args['query'] if call['name']=='web_search' else 'Read: '+args['url']),
                               'status':'completed' if data.get('ok') is True else 'failed',
                               'instruction':'Recorded '+call['name']+' at '+str(read['read_at']),
                               'tools':['web'],'max_attempts':1,'attempts':1})
                if len(result)>=12:return result
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return []


def projection(db,root,paths):
    if not exists(db):return None
    from . import desktop_workspace,desktop_plans
    rows=db.execute('''SELECT f.*,d.job_id,d.status request_status,d.result,d.prompt FROM conversation_followups f
        JOIN desktop_plan_requests d ON d.request_id=f.request_id WHERE f.source_request_id=? ORDER BY f.created,f.request_id''',(int(root),)).fetchall()
    root_row=db.execute('SELECT status FROM orchestrator_chats WHERE id=?',(int(root),)).fetchone()
    nodes=[{'id':'conversation:'+root,'objective':'Conversation','status':root_row[0] if root_row else 'unavailable','dependencies':[],
            'instruction':'Exact saved conversation. Selecting a recommendation adds a bounded follow-up.'}]
    stages=[];latest_outputs=[];historical_outputs=[]
    for row in rows:
        stage={'request_id':row['request_id'],'job_id':str(row['job_id']),'mode':row['mode'],'prompt':row['prompt'],'option_index':row['option_index']}
        origin=db.execute('SELECT request_id FROM desktop_plan_requests WHERE job_id=?',(row['choice_source_id'],)).fetchone()
        parent=('stage:'+origin[0] if row['choice_source_id'] and str(row['choice_source_id'])!=root and origin else 'conversation:'+root)
        key='stage:'+row['request_id']
        chat=db.execute('SELECT status FROM orchestrator_chats WHERE id=?',(row['job_id'],)).fetchone()
        plans=plan_family(db,row['job_id'])
        if chat:
            value=desktop_workspace._chat(db,row['job_id'],paths,include_flow=False)
            stage.update(conversation=value,status=value['status'])
            reads=read_steps(paths,row['job_id'])
            # Edges indicate the saved follow-up and observed read sequence, not
            # a semantic claim or an artifact-consumption certificate.
            for read in reads:
                read['dependencies']=[parent];read['stage_request_id']=row['request_id'];nodes.append(read);parent=read['id']
            nodes.append({'id':key,'objective':'Research answer','status':value['status'],'dependencies':[parent],
                          'instruction':row['prompt'],'conversation_response':value['status']=='answered','stage_request_id':row['request_id']})
        elif plans:
            plan=desktop_plans.detail(plans[-1]['id'],paths,shared=True)
            stage.update(plan=plan,status=plan['status'])
            nodes.append({'id':key,'objective':'Research plan' if plan['research_mode']=='sources' else 'Plan selected outcome',
                          'status':plan['status'],'error':'Could not prepare the requested steps. No work has started.' if plan['error'] else None,'dependencies':[parent],
                          'instruction':row['prompt'],'stage_request_id':row['request_id']})
            execution=desktop_workspace.detail(plan['run'],paths) if plan['run'] else None
            if execution:
                stage.update(execution=execution,status=execution['status'])
                latest_outputs.extend({**file,'task':key+':'+file['task']} for file in execution.get('latest_outputs',[]))
                historical_outputs.extend({**file,'task':key+':'+file['task']} for file in execution.get('historical_outputs',[]))
                nodes[-1]['status']=execution['status']
            tasks=execution['tasks'] if execution else (plan.get('plan') or {}).get('tasks',[]) or plan.get('proposed_tasks',[])
            for task in tasks:
                ident=key+':'+task['id']
                deps=[key+':'+(d if isinstance(d,str) else d['task']) for d in task.get('dependencies',[])]
                nodes.append({**task,'id':ident,'dependencies':deps or [key],
                              'review_of':key+':'+task['review_of'] if task.get('review_of') else None,
                              'status':task['status'] if execution else 'pending' if plan.get('plan') else 'proposed','planned_outputs':task.get('outputs',[]),'stage_request_id':row['request_id']})
        else:
            stage.update(status=row['request_status'],result=row['result'])
            nodes.append({'id':key,'objective':'Public-source research' if row['mode']=='research' else 'Plan selected outcome',
                          'status':row['request_status'],'dependencies':[parent],'instruction':row['prompt'],
                          'stage_request_id':row['request_id']})
        stages.append(stage)
    return {'tasks':nodes,'stages':stages,'latest_outputs':latest_outputs,'historical_outputs':historical_outputs,
            'status':(summary(db,int(root)) or {}).get('status'), 'note':'Source links reflect saved page reads, not a guarantee that every claim is correct.'}


def summary(db,root):
    if not exists(db):return None
    rows=db.execute('''SELECT f.mode,f.option_index,f.choice_source_id,f.created,d.job_id,d.status,c.status chat_status FROM conversation_followups f
        JOIN desktop_plan_requests d ON d.request_id=f.request_id
        LEFT JOIN orchestrator_chats c ON c.id=d.job_id WHERE f.source_request_id=?''',(int(root),)).fetchall()
    if not rows:return None
    states=[]
    for row in rows:
        if row['mode']=='legacy_plan' and any(other['choice_source_id']==row['choice_source_id'] and other['option_index']==row['option_index'] and other['created']>row['created'] and other['mode']=='research' for other in rows):
            continue  # Retained failed preparation, replaced by an explicitly selected research stage.
        status=row['chat_status'] or row['status']
        family=plan_family(db,row['job_id']);plan=family[-1] if family else None
        if plan:
            status=plan['status']
            if plan['run']:
                run=db.execute('SELECT status FROM production_runs WHERE id=?',(plan['run'],)).fetchone()
                status=run[0] if run else status
        states.append(status)
    for status in ('uncertain','blocked','failed','needs_input','awaiting_user','ready','sending','active','running','queued','accepted'):
        if status in states:return {'status':status}
    return {'status':'completed'}


def proposed_tasks(value):
    """Label retained rejected task data explicitly as unexecuted proposals."""
    plan=value.get('plan') if isinstance(value,dict) else None
    tasks=plan.get('tasks',[]) if isinstance(plan,dict) else []
    if not isinstance(tasks,list) or not 1<=len(tasks)<=12:return []
    ids=[t.get('id') for t in tasks if isinstance(t,dict)]
    if len(ids)!=len(tasks) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):return []
    result=[]
    for task in tasks:
        deps=[]
        for field in ('dependencies','after'):
            if isinstance(task.get(field),list):deps.extend(task[field])
        bindings=task.get('input_bindings',[])
        if isinstance(bindings,list):deps.extend(item['producer'] for item in bindings if isinstance(item,dict) and 'producer' in item)
        if task.get('review_of'):deps.append(task['review_of'])
        deps=[d for d in deps if isinstance(d,str) and d in ids]
        result.append({**task,'dependencies':list(dict.fromkeys(deps)),
                       'instruction':'Rejected proposal; no assignment was executed.\n'+(task.get('instruction') if isinstance(task.get('instruction'),str) else '')})
    return result


def attach_saved(ident,index,digest,request_id,paths=PATHS):
    """Explicitly attach a proven matching, unexecuted historical outcome.

    Preserves all original request/plan/call rows. This is display lineage only,
    never acceptance, retry or authorization to start its proposed assignments.
    """
    from orchestrator.storage import transaction
    with closing(_database(paths,writable=True)) as db,transaction(db):
        initialize(db)
        row,entry,option,selection_mode=selected(db,ident,index,digest)
        if selection_mode!='research':raise DesktopPlanError('Historical attachment requires the selected public research outcome.')
        child=db.execute('SELECT * FROM desktop_plan_requests WHERE request_id=?',(request_id,)).fetchone()
        inputs=db.execute('SELECT * FROM desktop_plan_inputs WHERE request_id=?',(request_id,)).fetchone()
        plan=db.execute('SELECT * FROM production_plans WHERE request_id=?',(child['job_id'],)).fetchone() if child else None
        mode=db.execute('SELECT entry_mode FROM desktop_request_modes WHERE request_id=?',(request_id,)).fetchone()
        if (not child or not inputs or not plan or plan['status']!='blocked' or plan['run'] or child['parent_id'] or inputs['previous_run']
                or child['status']!='accepted' or not mode or mode[0]!='plan' or child['created']<row['created']
                or (inputs['goal'],inputs['constraints_text'],child['project'])!=(option['request'],'Original request:\n'+row['prompt'],entry['project'])):
            raise DesktopPlanError('This saved plan is not the exact unexecuted selected outcome.')
        left=json.loads(entry['manifest']);right=json.loads(inputs['manifest'])
        if [(f['sha256'],f['bytes']) for f in left]!=[(f['sha256'],f['bytes']) for f in right]:
            raise DesktopPlanError('The saved plan uses different frozen inputs.')
        historical=hashlib.sha256(json.dumps([digest,request_id,'historical-plan-link']).encode()).hexdigest()
        prior=db.execute('SELECT * FROM conversation_followups WHERE request_id=?',(request_id,)).fetchone()
        if prior:
            if prior['source_request_id']!=row['id'] or prior['selection_digest']!=historical:
                raise DesktopPlanError('The saved plan already has different lineage.')
        else:db.execute('INSERT INTO conversation_followups VALUES (?,?,?,?,?,?,?)',
                        (request_id,row['id'],index,historical,'legacy_plan',time.time(),row['id']))
        receipt={'source_request_id':str(row['id']),'request_id':request_id,'plan_id':plan['id'],
                 'selection_digest':historical,'scope':'display lineage only; no acceptance or execution'}
        db.execute('INSERT OR REPLACE INTO kv(key,value) VALUES (?,?)',('conversation-lineage:'+request_id,json.dumps(receipt)))
    return receipt


def plan_family(db,job_id):
    return db.execute('''WITH RECURSIVE family(id) AS (
        SELECT id FROM production_plans WHERE request_id=?
        UNION SELECT p.id FROM production_plans p JOIN family f ON p.parent_id=f.id)
        SELECT p.id,p.status,p.run FROM production_plans p JOIN family f ON f.id=p.id ORDER BY p.created,p.id''',(job_id,)).fetchall()
