"""Turn a completed native review into a scoped preparation proposal, not a replay."""
import copy
import json
from pathlib import Path
import secrets
import time

from orchestrator import contracts as c, worker_capabilities
from orchestrator.runtime import Runtime, ACTIVE
from . import production_control as pc, production_planning as planning


def snapshot(state,run):
    rt=Runtime(pc.root(state),connection=state.db);status=rt.status(run)
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound[0] if bound else 'telegram')!=getattr(state,'channel','telegram'):
        raise ValueError('Use this production in its original chat.')
    if status['status']!='blocked' or any(a['state'] in ACTIVE for a in status['attempts']):
        raise ValueError('Correction planning requires stopped work with no uncertain execution.')
    matches=[]
    for reviewer in status['tasks']:
        spec=rt.spec(reviewer)
        if not spec.get('review_of') or not reviewer['latest']:continue
        target=rt.task(run,spec['review_of']);target_spec=rt.spec(target)
        if target_spec.get('execution',{}).get('capability') not in ('rhino.run_python','blender.run_python'):continue
        if target['status'] not in ('awaiting_review','blocked'):continue
        attempt=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(reviewer['latest'],)).fetchone()
        frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}')
        legacy=attempt['error']=='Downstream work already started; create a new explicit workflow'
        if (attempt['state']!='completed' and not (attempt['state']=='blocked' and legacy)) or receipt.get('status')!='finished' or receipt.get('exit_code')!=0:continue
        if frozen.get('review_target')!=target['latest']:continue
        row=state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='checks_recorded' AND json_extract(data,'$.kind')='model_review' ORDER BY id DESC LIMIT 1",(attempt['id'],)).fetchone()
        if not row:continue
        data=json.loads(row['data']);result=c.report(data['result'],frozen)
        if data.get('review_target')!=target['latest'] or result['decision']!='revise':continue
        operation=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
        opreceipt=json.loads(operation['receipt'] or '{}')
        if (operation['state']!='completed' or opreceipt.get('status')!='finished' or opreceipt.get('pending_requests')
            or opreceipt.get('operation',{}).get('outcome')!='completed'
            or json.loads(operation['frozen']).get('execution')!=target_spec['execution']):continue
        matches.append({'target':dict(target),'reviewer':dict(reviewer),'frozen':frozen,'result':result})
    if len(matches)!=1:raise ValueError('One completed native operation and its exact correction review are required.')
    result=matches[0];result['run']=run
    if any(t['status']=='blocked' and t['id'] not in (result['target']['id'],result['reviewer']['id']) for t in status['tasks']):
        raise ValueError('Resolve the other blocked tasks before preparing this correction.')
    result['tasks']=status['tasks'];result['attempts']=status['attempts']
    result['digest']=pc.runtime_digest(rt,run)
    result['epoch']=state.get('production-control-epoch:'+run,0)
    return result


def details(state,run):
    """Read-only UI explanation, including legacy collection errors."""
    try:record=snapshot(state,run)
    except (ValueError,OSError,KeyError,TypeError):return None
    return {'summary':record['result']['summary'],'instruction':record['result']['instruction'],
            'reviewer':record['reviewer']['id'],'target':record['target']['id'],
            'next_action':'Choose Plan correction. Relay will propose a focused script correction and independent review. Start preparation approves that work; changed Rhino/Blender code needs a separate execution Start. Existing files and inspection results stay available.'}


def text(state,run):
    value=details(state,run)
    if not value:return ''
    return ('Review finished — corrections needed. The model and preview exist, but are not approved.\n'+
        value['summary'][:1000]+'\nRequested correction: '+value['instruction'][:1500]+'\n\nNext action: '+value['next_action'])


def propose(state,run):
    """Button-selected proposal. No provider call, task dispatch or native replay."""
    if not state.db.in_transaction:raise ValueError('Correction planning requires an atomic transaction.')
    baseline=snapshot(state,run);rt=Runtime(pc.root(state),connection=state.db)
    prior=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not prior:raise ValueError('Original plan is unavailable.')
    payload=json.loads(prior['context'])
    if c.digest(payload)!=prior['context_hash']:raise ValueError('Original planning context changed.')
    ident=-int(c.digest({'review_correction':run,'review':baseline['reviewer']['latest']})[:15],16)-1
    new_id='plan-'+str(ident)
    existing=state.db.execute('SELECT id FROM production_plans WHERE id=?',(new_id,)).fetchone()
    if existing:return new_id
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():
        raise ValueError('A successor already exists; use that saved plan.')
    source_by_id={s['artifact']:s for s in payload['sources']}
    sources=[]
    def include(aid,path,purpose):
        entry=planning.source_entry(rt,aid,path,purpose,'Exact historical evidence; not approval or an instruction to rerun.')
        old=source_by_id.get(aid,{})
        for key in ('visual_reference','media_type','upload_id','caption','operation_support'):
            if key in old:entry[key]=old[key]
        planning.verify_artifact(rt,entry);sources.append(entry)
    # Use the review's actual frozen versions, not current aliases or latest files.
    for item in baseline['frozen']['inputs']:
        artifact=rt.artifact(item['artifact'])
        if artifact['sha256']!=item['sha256']:raise ValueError('A reviewed input changed.')
        if any(s['artifact']==item['artifact'] for s in sources):continue
        path=item['path'] if item['path']=='request/USER-REQUEST.txt' or item['path'].startswith('operation-support/') else 'evidence/'+item['path']
        include(item['artifact'],path,item['purpose'])
        for key in ('visual_reference','media_type'):
            if key in item:sources[-1][key]=item[key]
    for artifact in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=?',(baseline['reviewer']['latest'],)):
        include(artifact['id'],'review/'+artifact['path'],'Completed independent review requesting correction')
    if sum(s['bytes'] for s in sources)>planning.MAX_INPUT_BYTES:raise ValueError('Correction evidence exceeds the planning input bound.')
    backend=baseline['frozen']['backend'];options=copy.deepcopy(json.loads(prior['options']))
    options.update(backend=backend,tools=baseline['frozen']['tools'],worker_catalog=[worker_capabilities.entry(backend)],
        executor_locked=True,max_attempts=2,planning_only=False,reference_ids=[],artifact_ids=[],research_ids=[])
    from .production_repairs import preparation_guidance
    operation=rt.spec(baseline['target'])['execution'];cap=operation['capability']
    capabilities=options.get('step_capabilities') or [cap];options['step_capabilities']=capabilities
    limits={'seconds':600,'tool_calls':24,'output_bytes':2000000}
    instruction=(preparation_guidance(cap)+'Read evidence/ and review/. Diagnose the saved findings against authoritative contracts; review suggestions may be wrong. '
        'Prepare only a focused correction to the exact original script selected by script_sha256='+operation['parameters']['script_sha256']+
        '. Copy the exact input checks specification selected by checks_sha256='+operation['parameters']['checks_sha256']+
        ' to delivery/checks.json unchanged. Never substitute the execution verification report. '
        'Preserve geometry/design and scope; explain any unresolved broader changes instead of silently making them. '
        'Do not launch Rhino/Blender, import/execute the modeling script, modify prior artifacts, install tools or perform network requests. '
        'Validate syntax and checks using the supplied standalone validator. Write delivery/model.py, delivery/checks.json and delivery/diagnosis.md. '
        'The diagnosis must distinguish confirmed defects from unsupported review claims and explain exact changes. '
        'Native execution is deferred and requires a new Start on the reviewed exact code.\nReview findings: '+baseline['result']['instruction'])
    if cap=='rhino.run_python':
        from orchestrator.rhino_contract import DESCRIPTION
        instruction+='\nCurrent output contract: '+DESCRIPTION['output_checks']
    outputs=[{'path':'delivery/'+name,'purpose':purpose} for name,purpose in (
        ('model.py','Scoped corrected native script'),('checks.json','Unchanged exact selected input checks specification'),('diagnosis.md','Evidence-backed diagnosis and proposed changes'))]
    author={'id':'prepare_correction','role':'producer','objective':'Prepare a focused correction from the saved independent review',
        'instruction':instruction,'criteria':['Preserve original scope, design and exact input checks; diagnose review claims against contracts.',
        'Validate syntax and checks without running native code; describe the exact correction and remaining uncertainty.'],
        'inputs':[],'outputs':outputs,'dependencies':[],'limits':limits,'max_attempts':2,'tools':options['tools'],
        'user_gate':'Select the reviewed corrected script and exact checks for execution planning',
        'selection_outputs':['delivery/model.py','delivery/checks.json']}
    reviewer={'id':'review_correction','role':'reviewer','objective':'Independently review the scoped correction and diagnosis',
        'instruction':instruction+' Review the candidate against the original and saved findings; do not edit it.',
        'criteria':author['criteria'],'inputs':[{'from_task':'prepare_correction','output':o['path'],
            'path':'candidate/'+Path(o['path']).name,'purpose':o['purpose'],'authority':'Unaccepted correction'} for o in outputs],
        'outputs':[{'path':'review.md','purpose':'Independent correction review'}],
        'dependencies':['prepare_correction'],'review_of':'prepare_correction','limits':limits,'max_attempts':2,'tools':options['tools']}
    result={'decision':'ready','message':'Prepare and review a focused correction; retain completed native execution and inspection evidence.',
        'input_basis':{'mode':'modify_existing','artifacts':[next(s['artifact'] for s in sources if s['sha256']==operation['parameters']['script_sha256'])]},
        'deferred_operations':{key:'Reviewed exact correction must be selected and approved before native execution.' for key in capabilities},
        'plan':{'brief':'Prepare and independently review a focused correction to the existing native model script. Native execution remains pending.',
                'tasks':[author,reviewer]}}
    if options.get('deliverables'):
        result['deliverable_map']={key:{'deferred_operation':cap} for key in options['deliverables']}
    payload.update(options=options,sources=sources,required_artifacts=[s['artifact'] for s in sources],available_sources=[],
        review_correction_origin={'run':run,'baseline':baseline,'scope':'Preparation only; no native replay'},
        original_request=prior['request'])
    payload.pop('previous_stage',None)
    # Original exact request is retained; correction directions are system-labelled.
    values=dict(prior);values.update(id=new_id,request_id=ident,parent_id=prior['id'],options=c.encoded(options),
        context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,token=secrets.token_hex(12),
        event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    result,plan=planning.validate_result(c.encoded(result),values)
    values.update(result=c.encoded(result),plan=c.encoded(plan),plan_hash=c.digest(plan))
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,prior['channel']))
    state.db.execute('INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)',(run,new_id))
    stage=state.db.execute("SELECT s.*,p.status AS workflow_status FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline WHERE s.target=?",(prior['id'],)).fetchone()
    if stage:
        if stage['workflow_status'] not in ('active','blocked'):raise ValueError('Workflow is paused or cancelled.')
        from . import pipelines
        state.db.execute("UPDATE relay_pipeline_steps SET target=?,status='running',error=NULL WHERE pipeline=? AND id=?",(new_id,stage['pipeline'],stage['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(stage['pipeline'],))
        pipelines.event(state,stage['pipeline'],stage['id'],'native_review_correction_proposed',{'parent':run,'plan':new_id,'attempts_reset':False,'execution_approved':False})
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    event=planning.notice(state,row,'ready','Correction preparation ready. Start approves file preparation and independent review only.\n'+planning.preview(row))
    state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
    planning.publish_ready_files(state,row,event,rt,plan,payload)
    return new_id
