"""Turn native failure evidence or review findings into preparation, not replay."""
import copy
import json
from pathlib import Path
import secrets
import time

from orchestrator import contracts as c, worker_capabilities
from orchestrator.runtime import Runtime, ACTIVE
from . import production_control as pc, production_planning as planning


def execution_failure(state, run, rt):
    """A terminal native failure can be diagnosed before an AI review exists."""
    from . import production_stages
    from orchestrator import executors
    baseline=production_stages.failed_execution_snapshot(state,rt,run,getattr(state,'channel','telegram'))
    target=next(t for t in baseline['tasks'] if t['status']=='blocked')
    assessment=planning.host_recovery_assessment(rt,run,target)
    if not assessment or assessment[2]['action']!='prepare_reviewed_repair':
        raise ValueError('A confirmed terminal native failure is required for correction preparation.')
    reviewer=rt.reviewer(run,target['id'])
    if not reviewer:raise ValueError('The saved independent reviewer is required.')
    spec=rt.spec(reviewer)
    plan=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(run,)).fetchone()[0])
    backend=worker_capabilities.backend_for(spec,plan['backend'])
    tools=executors.validate(backend)
    if 'python' not in tools and 'shell' not in tools:
        raise ValueError('Native correction needs the saved code-capable reviewer profile.')
    attempt=state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(target['latest'],)).fetchone()
    original=json.loads(attempt['frozen'])
    inputs=copy.deepcopy(original['inputs'])
    for artifact in state.db.execute('SELECT * FROM production_artifacts WHERE attempt=? ORDER BY path',(target['latest'],)):
        entry=planning.source_entry(rt,artifact['id'],'failed-output/'+artifact['path'],
            'Unaccepted output and measurements from the failed native attempt','Failure evidence only; not an accepted model or input checks specification.')
        planning.verify_artifact(rt,entry);inputs.append(entry)
    return {'kind':'execution_failure','run':run,'target':dict(target),'reviewer':dict(reviewer),
        'frozen':{'backend':backend,'tools':tools,'inputs':inputs},
        'result':{'summary':'Native execution finished with a recorded failure; its retained files are unapproved.',
            'instruction':'Diagnose the exact execution receipt and measured verification report against the original script, input checks and source geometry. Correct the cause, not just the failing threshold.'},
        'assessment':assessment[2],'tasks':baseline['tasks'],'attempts':baseline['attempts'],
        'digest':baseline['contract_digest'],'epoch':baseline['control_epoch']}


def snapshot(state,run):
    rt=Runtime(pc.root(state),connection=state.db);status=rt.status(run)
    bound=state.db.execute("SELECT channel FROM relay_channel_bindings WHERE kind='production' AND entity=? ORDER BY after_row DESC LIMIT 1",(run,)).fetchone()
    if (bound[0] if bound else 'telegram')!=getattr(state,'channel','telegram'):
        raise ValueError('Use this production in its original chat.')
    if status['status']=='awaiting_user' and not any(a['state'] in ACTIVE for a in status['attempts']):
        candidates=[t for t in status['tasks'] if t['status']=='awaiting_user' and rt.quality_review(t)
            and rt.spec(t).get('execution',{}).get('capability') in ('rhino.run_python','blender.run_python','rhino3dm.run_python')]
        if len(candidates)==1:
            target=candidates[0];reviewer=rt.reviewer(run,target['id'])
            if reviewer and reviewer['status']=='completed':
                attempt=state.db.execute('SELECT * FROM production_attempts WHERE id=?',(reviewer['latest'],)).fetchone()
                frozen=json.loads(attempt['frozen'])
                if frozen.get('review_target')==target['latest']:
                    concern=rt.quality_review(target)
                    return {'kind':'quality_feedback','run':run,'target':target,'reviewer':dict(reviewer),'frozen':frozen,
                        'quality_review':concern,'result':{'summary':'Usable output awaits user feedback on quality concerns.',
                            'instruction':'\n'.join(f['message']+' Evidence: '+f['evidence'] for f in concern['findings'])},
                        'tasks':status['tasks'],'attempts':status['attempts'],'digest':pc.runtime_digest(rt,run),
                        'epoch':state.get('production-control-epoch:'+run,0)}
    if status['status']!='blocked' or any(a['state'] in ACTIVE for a in status['attempts']):
        raise ValueError('Correction planning requires stopped work with no uncertain execution.')
    matches=[]
    for reviewer in status['tasks']:
        spec=rt.spec(reviewer)
        if not spec.get('review_of') or not reviewer['latest']:continue
        target=rt.task(run,spec['review_of']);target_spec=rt.spec(target)
        if target_spec.get('execution',{}).get('capability') not in ('rhino.run_python','blender.run_python','rhino3dm.run_python'):continue
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
    if not matches:return execution_failure(state,run,rt)
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
    return {'kind':record.get('kind','review'),'summary':record['result']['summary'],'instruction':record['result']['instruction'],
            'reviewer':record['reviewer']['id'],'target':record['target']['id'],
            'next_action':('Inspect the files/previews and accept these exact outputs as-is, or reply with correction feedback. ' if record.get('kind')=='quality_feedback' else '')+'Choose Plan correction to propose a focused script correction and independent review. Start preparation approves that work; changed Rhino/Blender code needs a separate execution Start. Existing files and inspection results stay available.'}


def text(state,run):
    value=details(state,run)
    if not value:return ''
    if value['kind']=='quality_feedback':
        return 'Quality review needed. Usable files are available; dependent work waits for your decision.\n'+value['instruction'][:1500]+'\n\nNext action: '+value['next_action']
    heading=('Native execution failed — correction preparation is available. Retained files are unapproved.\n'
        if value['kind']=='execution_failure' else 'Review finished — corrections needed. The model and preview exist, but are not approved.\n')
    return (heading+
        value['summary'][:1000]+'\nRequested correction: '+value['instruction'][:1500]+'\n\nNext action: '+value['next_action'])


def propose(state,run,feedback=None):
    """Button-selected proposal. No provider call, task dispatch or native replay."""
    if not state.db.in_transaction:raise ValueError('Correction planning requires an atomic transaction.')
    baseline=snapshot(state,run);rt=Runtime(pc.root(state),connection=state.db)
    prior=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not prior:raise ValueError('Original plan is unavailable.')
    payload=json.loads(prior['context'])
    if c.digest(payload)!=prior['context_hash']:raise ValueError('Original planning context changed.')
    failed=baseline.get('kind')=='execution_failure'
    identity={'review_correction':run,'review':baseline['target']['latest'] if failed else baseline['reviewer']['latest']}
    if feedback is not None:
        c.nonempty(feedback,'Exact quality feedback');identity['feedback']=feedback
    ident=-int(c.digest(identity)[:15],16)-1
    new_id='plan-'+str(ident)
    existing=state.db.execute('SELECT id FROM production_plans WHERE id=?',(new_id,)).fetchone()
    if existing:return new_id
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():
        raise ValueError('A successor already exists; use that saved plan.')
    source_by_id={s['artifact']:s for s in payload['sources']}
    sources=[]
    def include(aid,path,purpose):
        entry=planning.source_entry(rt,aid,path,purpose,'Exact historical evidence; not approval or an instruction to rerun.')
        if rt.artifact(aid)['attempt']==baseline['target']['latest']:
            entry['diagnostic_evidence']=True
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
    if failed:
        # Execution assignments contain only host inputs. Keep their original
        # sources and operation contracts available for independent diagnosis.
        for item in payload['sources']:
            if any(s['artifact']==item['artifact'] for s in sources):continue
            path=item['path'] if item['path'].startswith(('operation-support/','request/')) else 'source/'+item['artifact']+'/'+Path(item['path']).name
            include(item['artifact'],path,item['purpose'])
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
        instruction+='\nCurrent output contract: '+DESCRIPTION['output_checks']+' '+DESCRIPTION['dimension_evidence']
    if feedback is not None:instruction+='\nEXACT USER QUALITY FEEDBACK (within original scope):\n'+feedback
    if failed:
        instruction=(preparation_guidance(cap)+'Read evidence/failed-output/, evidence/ and source/ plus the original request and operation contracts. '
            'Diagnose the terminal failure against the exact original script SHA-256 '+operation['parameters']['script_sha256']+
            ' and INPUT checks SHA-256 '+operation['parameters']['checks_sha256']+'. Output verification reports are measurements, never input checks. '
            'Prepare a scoped corrected script and input checks. Preserve user requirements, source geometry, units, datum, scope and output types. '
            'Never widen tolerances, omit required geometry, or copy failed measurements into expectations merely to make verification pass. '
            'If a check itself is wrong, propose its correction with independently derived expected values, exact before/after values and reproducible evidence; '
            'preserve every unaffected check. If evidence or permissions are insufficient, explain the required decision rather than inventing geometry. '
            'Write delivery/model.py, delivery/checks.json and delivery/diagnosis.md. The diagnosis must identify whether the script, checks or both are defective, '
            'cite measured failures, justify each change and state remaining uncertainties. Validate syntax/schema and independently calculate numerical expectations '
            'where possible without importing or executing native host code. No Rhino/Blender launch, network, installation or modification of original files. '
            'Preparation and review only; revised script AND checks require selection and a new exact-code Start before native execution.')
        if cap=='rhino.run_python':instruction+=' '+DESCRIPTION['dimension_evidence']+' '+DESCRIPTION['output_checks']
    outputs=[{'path':'delivery/'+name,'purpose':purpose} for name,purpose in (
        ('model.py','Scoped corrected native script'),('checks.json','Unchanged exact selected input checks specification'),('diagnosis.md','Evidence-backed diagnosis and proposed changes'))]
    if failed:outputs[1]['purpose']='Proposed input checks; every change must be independently justified'
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
    if failed:
        author['criteria']=['Diagnose the exact failed attempt using its receipt, measurements and original source requirements.',
            'Preserve user scope and source fidelity; independently justify every changed script section and input check with reproducible evidence, not a relaxed pass condition.',
            'Validate syntax/schema and derived numerical expectations without native execution; disclose any unresolved contradiction.']
        reviewer['criteria']=author['criteria']
        author['objective']='Diagnose native failure and prepare a scoped correction'
        reviewer['instruction']=instruction+' Independently compare original and candidate script AND checks. Reject unsupported expectation changes; do not edit the candidate.'
    from orchestrator import executors
    for task in (author,reviewer):
        task['limits']=copy.deepcopy(limits)
        executors.code_budgets(task,backend)
    result={'decision':'ready','message':'Prepare and review a focused correction; retain exact prior execution and inspection evidence.',
        'input_basis':{'mode':'modify_existing','artifacts':[next(s['artifact'] for s in sources if s['sha256']==operation['parameters']['script_sha256'])]},
        'deferred_operations':{key:'Reviewed exact correction must be selected and approved before native execution.' for key in capabilities},
        'plan':{'brief':'Prepare and independently review a focused correction to the existing native model script. Native execution remains pending.',
                'tasks':[author,reviewer]}}
    geometry=json.loads(prior['plan']).get('origin',{}).get('geometry_basis')
    if geometry is not None:result['geometry_basis']=copy.deepcopy(geometry)
    if options.get('deliverables'):
        result['deliverable_map']={key:{'deferred_operation':cap} for key in options['deliverables']}
    payload.update(options=options,sources=sources,required_artifacts=[s['artifact'] for s in sources],available_sources=[],
        review_correction_origin={'run':run,'baseline':baseline,'scope':'Preparation only; no native replay','feedback':feedback},
        original_request=prior['request'])
    payload.pop('previous_stage',None)
    payload.pop('execution_recovery',None)
    # This successor prepares corrected code; it is not an execution selection.
    if payload.pop('operation_builder',None):
        from . import operation_builders, planning_contract
        payload['response_contract']=planning_contract.contract(options)
        payload['planner_instructions']=payload['planner_instructions'].replace('\n'+operation_builders.INSTRUCTIONS,'')
    # Original exact request is retained; correction directions are system-labelled.
    values=dict(prior);values.update(id=new_id,request_id=ident,parent_id=prior['id'],options=c.encoded(options),
        context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,token=secrets.token_hex(12),
        event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    if feedback is not None:values['request']=prior['request']+'\n\nEXACT USER QUALITY FEEDBACK:\n'+feedback
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
