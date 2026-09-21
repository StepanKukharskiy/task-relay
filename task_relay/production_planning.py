"""Durable natural-request planning over the existing production runtime.

Planning does not execute workers. A delivered, version-bound action card starts
one validated producer/reviewer stage, atomically with its registration receipt.
"""
import copy
import ast
import json
import re
from pathlib import Path
import secrets
import time

from task_relay import gemini
from task_relay import api_providers as api
from task_relay import production_control as pc
from task_relay import relay_channels
from task_relay import planning_contract
from orchestrator import contracts as c, templates
from orchestrator.cloud_media import KINDS as CLOUD_MEDIA
from orchestrator.runtime import Runtime, safe_file, file_hash
from orchestrator.native_apps import SCRIPT_OPERATIONS, NATIVE_MEDIA, profile as native_profile

MAX_CONTEXT = 400000
MAX_INPUT_BYTES = 150000000
INSTRUCTIONS = '''You can plan a NEW bounded production with plan_production.
Use this when the user wants a new stage/workflow rather than an existing task or
same-scope continuation. Action fields: kind, template (competition, carousel,
office-anime or custom), project (one known project path or null for a standalone
workspace), reference_pack_id (ready pack ID or null), research_ids (explicit IDs
or []), planning_only (boolean). Optional parent_id names one saved needs_input or
ready or blocked plan when the user clarifies/revises/repeats its request; preserve
the original request. Historical worker_catalog entries describe the old proposal,
not current availability. If previously missing capabilities are now available,
use parent_id to propose again; do not repeat obsolete setup instructions.
For an explicit next-stage request after exact output selection, set previous_run
to the completed production run. Its selected versions, instructions and original
job identity are carried automatically to both workers. Do not use this for a
status question or infer a selection from conversational text. A saved unfinished
next-stage plan is clarified with parent_id, not a second unrelated plan.
Optional artifact_ids selects exact generated source files from snapshot.production_artifacts
(e.g. an existing .blend for inspection); [] selects none. For an
uploaded reference, reference_ids selects its exact ready ID from snapshot.uploaded_files.
When ready uploads are listed, include reference_ids explicitly: select the files
the user asks to use, or [] for unrelated uploads. Resolve "this image" using the
upload caption/reply context; ask only when the identity is ambiguous. Never claim
an uploaded reference is included without selecting its ID. Uploads are distinct
from generated artifact_ids and research_ids.
Optional project_files selects up to ten exact project-relative source paths from
the selected known project (100 MB total). Use file_list to resolve filenames.
For modeling from a local DXF, survey, scene or drawing, select the actual file,
not merely a conversation describing it. Its immutable bytes reach author and
reviewer. Never substitute a summary, guessed contour, synthetic slope or an
approximate footprint when the user requested source-derived geometry. If the
source cannot be identified or opened, ask for that specific source before work.
For a named existing scene, select its exact artifact ID or ask which version if absent/ambiguous.
Relative edits such as "make it twice as tall" need the existing artifact, even
without a filename. Resolve it from conversation/reply provenance and select the
exact editable source (for a generated tower, scene.json), not just a preview or
conversation.json. If multiple baselines fit, ask which one. Selecting a baseline
does not mark it accepted or supersede it. Do not send a relative revision with []
merely because the current user did not repeat the artifact name.
Optional executor is an available ID from snapshot.capabilities.graph_executors.
Use it when the user names a provider; never substitute another provider. Available
Gemini/OpenAI/Qwen/DeepSeek/OpenRouter file workers support bounded text work.
Their -code profiles provide isolated Python only when the native runtime is verified.
The gemini-browser, openai-browser and
qwen-browser executors support general website work with declared origins and
interaction scope, using a dedicated profile. Select the requested available provider;
never infer browser access from the file-only executor. A selected provider stays fixed.
New scopes capture available worker profiles. The stage planner can create task-
specific roles and match files.text, files.binary, code.execute or browser.use to
those profiles. Missing adapters stay explicit blockers. A named executor locks
the scope; other proposed backend choices require stage Start before dispatch.
For every new production request, include deliverables as {stable_id: exact requested output description}, covering every requested result regardless of tool or file type. Do not add outcomes beyond the user request.
For a requested mixed workflow, optional step_capabilities lists needed IDs
from snapshot.capabilities.graph_operations (hyperframes.preview, hyperframes.render, media.compose, pptx.create, text.bundle, gemini.text, gemini.image,
openai.image, openrouter.image, runway.image, runway.video, higgsfield.image,
higgsfield.video, meshy.mesh, Blender operations, rhino.startup, rhino.inspect, rhino.run_python,
rhino.render, rhino3dm.create, rhino3dm.run_python, sketchup.startup, sketchup.inspect or sketchup.run_ruby).
These grant the planner permission to PROPOSE those operations, not to run them.
Each API operation makes one external request with an exact model and bounded
parameters; do not include it unless the user's work needs it. The plan card
shows that external call before execution is authorized. New mixed scopes allow
at most twelve graph steps; saved scopes retain their own limits.
When reply_plan_id identifies a started plan, use its run for production status,
revision or continuation; do not create an unrelated new planning request.
The planner creates at most one producer and one independent reviewer, each with
one initial attempt and one review-directed correction for local drafting, at most
1800 seconds/60 tools per attempt (profile tool limits may be lower). Registered
operations and browser work retain one attempt; failures never automatically replay.
Optional task_seconds sets the maximum per-task time in seconds, 60–1800, when
the user specifies a time budget. The planner chooses each task’s own deadline
within that ceiling, separately for production and review. Existing plans keep their
frozen limits; extending them requires a new proposed plan. It can ask a
specific question or report a blocker. It never launches workers while planning.
The service returns a concrete plan card, and its Start action authorizes that exact
stage. Planning-only results have no Start button. On a subsequent explicit request
to execute a planning-only result, use authorize_production_plan with plan_id; this
presents its exact scope for approval. No new scope, rendering or acceptance is
implied by asking a status question. Saved production_plans are authoritative for
planner state. Never claim workers started from model text or a queued plan request.
'''


UPLOAD_PLANNER_INSTRUCTIONS = '\nSelected uploaded images are present in sources (visual_reference=true); missing_text_artifacts means binary pixels are not inline text, not a missing attachment. Plan workers to inspect those exact files visually before authoring and during review. Require images.view for their worker profiles. Do not invent an image description from captions or ask to upload an already selected source. This text-only planner can delegate image inspection without seeing the pixels itself.'


def initialize(db):
    from task_relay import production_stages
    production_stages.initialize(db)
    db.executescript('''CREATE TABLE IF NOT EXISTS production_plans (
      id TEXT PRIMARY KEY, request_id INTEGER UNIQUE NOT NULL, parent_id TEXT,
      channel TEXT NOT NULL, request TEXT NOT NULL, options TEXT NOT NULL,
      context TEXT NOT NULL, context_hash TEXT NOT NULL, provider TEXT NOT NULL,
      model TEXT NOT NULL, status TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
      result TEXT, plan TEXT, plan_hash TEXT, token TEXT UNIQUE NOT NULL,
      event_id TEXT, expires REAL NOT NULL, run TEXT UNIQUE, error TEXT, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS production_plan_calls (
      plan_id TEXT NOT NULL, number INTEGER NOT NULL, request TEXT NOT NULL,
      response TEXT, usage TEXT, error TEXT, created REAL NOT NULL,
      PRIMARY KEY(plan_id,number));''')
    db.executescript('''CREATE TABLE IF NOT EXISTS production_plan_messages (
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, plan_id TEXT NOT NULL,
        PRIMARY KEY(chat_id,message_id));
      CREATE TABLE IF NOT EXISTS production_plan_replies (
        request_id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL);''')


def context(state):
    rows=state.db.execute('''SELECT id,request_id,parent_id,request,status,calls,result,
        plan_hash,run,error,options FROM production_plans WHERE channel=? ORDER BY created DESC LIMIT 12''',
        (getattr(state,'channel','telegram'),))
    return [{**dict(r),'options':json.loads(r['options']),
             'result':{k:v for k,v in json.loads(r['result']).items() if k!='plan'} if r['result'] else None} for r in rows]


def normalize_action(action, snap):
    """An omitted unused pack is null, not a source choice or new permission."""
    if (isinstance(action,dict) and action.get('kind')=='plan_production'
        and 'reference_pack_id' not in action
        and not any(p.get('status')=='ready' for p in snap.get('reference_packs',[]))):
        return {**action, 'reference_pack_id':None}
    return action


class StartedPlanningRequest(ValueError):
    """An existing execution must use continuation, not planning revision."""


def started_plan_continuation(action,snap,request):
    """Resolve only an exact started-plan target with unchanged saved scope.

    The result enters ordinary continuation validation and its approval gates.
    No names are guessed, source choices dropped, or new scope authorized.
    """
    action=normalize_action(action,snap)
    if snap.get('pipeline_step') or action.get('kind')!='plan_production':return None
    if not isinstance(request,str) or not 1<=len(request.strip())<=4000:return None
    matches=[p for p in snap.get('production_plans',[]) if p['id']==action.get('parent_id')]
    if len(matches)!=1:return None
    plan=matches[0]
    if plan.get('status')!='started' or not plan.get('run'):return None
    runs=[r for r in snap.get('production_runs',[]) if r['name']==plan['run']]
    if len(runs)!=1 or runs[0].get('status')!='blocked':return None
    saved=plan.get('options',{})
    if action.get('planning_only') is not False:return None
    # Validate all normal fields before considering a routing correction.
    probe={k:v for k,v in action.items() if k not in ('parent_id','previous_run')}
    validate_action(probe,snap)
    for key in ('template','project','reference_pack_id','research_ids','planning_only'):
        if key not in saved or action.get(key)!=saved[key]:return None
    for key in ('artifact_ids','reference_ids','project_files'):
        if action.get(key):return None  # New source selection needs new planning.
    for key in ('deliverables','executor','starter_workflow','starter_stage'):
        if key in action and action[key]!=saved.get(key):return None
    if 'task_seconds' in action and action['task_seconds']!=saved.get('limits',{}).get('seconds'):return None
    if 'step_capabilities' in action and set(action['step_capabilities'])!=set(saved.get('step_capabilities',[])):return None
    if action.get('previous_run') and action['previous_run']!=saved.get('previous_run'):return None
    return dict(kind='continue_production',workflow=plan['run'],items=None,direction=request)


def validate_action(action,snap):
    action=normalize_action(action,snap)
    if action['kind']=='authorize_production_plan':
        if set(action)!={'kind','plan_id'}:raise ValueError('Specify the saved plan ID.')
        if not any(p['id']==action['plan_id'] and p['status']=='ready' for p in snap.get('production_plans',[])):
            raise ValueError('The selected plan is not ready.')
        return
    required={'kind','template','project','reference_pack_id','research_ids','planning_only'}
    if set(action)-{'parent_id','previous_run','step_capabilities','executor','artifact_ids','reference_ids','project_files','starter_workflow','starter_stage','deliverables','task_seconds'}!=required or action['template'] not in (*templates.STAGES,'custom') or type(action['planning_only']) is not bool:
        raise ValueError('Specify a template, project, sources and planning-only intent for the new stage.')
    if 'task_seconds' in action and (type(action['task_seconds']) is not int or not 60<=action['task_seconds']<=1800):
        raise ValueError('Task time ceiling must be between 60 and 1800 seconds.')
    if 'starter_workflow' in action:
        from .workflow_library import freeze
        freeze(action['starter_workflow'],action.get('starter_stage'))
        if action['template']!='custom':raise ValueError('Use custom with a starter workflow; do not combine distinct templates.')
    elif 'starter_stage' in action:
        raise ValueError('Select a starter workflow with its stage.')
    roots=set(snap.get('project_roadmaps',{}).get('available_projects',[]))
    roots.update(t['cwd'] for t in snap.get('codex_tasks',[]))
    roots.update(p['cwd'] for p in snap.get('codex_projects',[]))
    if action['project'] is not None and action['project'] not in roots:raise ValueError('Choose a known project or a standalone workspace.')
    if action['reference_pack_id'] is not None and not any(p['id']==action['reference_pack_id'] and p['status']=='ready' for p in snap.get('reference_packs',[])):
        raise ValueError('Choose a ready reference pack.')
    from task_relay import routing_inputs
    routing_inputs.validate_project_files(action.get('project_files',[]),action['project'])
    if 'reference_ids' not in action and any(f['status']=='ready' for f in snap.get('uploaded_files',[])):
        raise routing_inputs.MissingSourceSelection(['reference_ids'])
    if 'reference_ids' in action:routing_inputs.validate_upload_ids(action['reference_ids'],snap.get('uploaded_files',[]))
    routing_inputs.validate_ids(action['research_ids'],snap.get('research_documents',[]))
    if 'artifact_ids' in action:
        routing_inputs.validate_artifact_ids(action['artifact_ids'],snap.get('production_artifacts',[]))
    if action.get('parent_id') and not any(p['id']==action['parent_id'] and p['status'] in ('needs_input','ready','blocked') for p in snap.get('production_plans',[])):
        if any(p['id']==action['parent_id'] and p['status']=='started' and p.get('run') for p in snap.get('production_plans',[])):
            raise StartedPlanningRequest('This plan already has an execution. Continue its recorded production; planning revision cannot resume executed work.')
        raise ValueError('Choose an unstarted planning request to clarify or revise.')
    if action.get('previous_run'):
        if action.get('parent_id'):raise ValueError('Clarify the saved plan or continue a completed stage, not both.')
        if not any(p['name']==action['previous_run'] and p['status']=='completed' for p in snap.get('production_runs',[])):
            raise ValueError('Choose a completed production with a recorded output selection.')
    if 'executor' in action:
        eligible={x['id'] for x in snap.get('capabilities',{}).get('graph_executors',[]) if x['available']}
        if action['executor'] not in eligible:raise ValueError('The requested executor is unavailable; no fallback.')
    deliverables=action.get('deliverables',{})
    if not isinstance(deliverables,dict) or len(deliverables)>8 or any(not isinstance(k,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',k) or not isinstance(v,str) or not 1<=len(v)<=500 for k,v in deliverables.items()):
        raise ValueError('List up to eight deliverables with stable IDs and concise descriptions.')
    requested=action.get('step_capabilities',[])
    if not isinstance(requested,list) or any(not isinstance(x,str) for x in requested) or len(requested)!=len(set(requested)):
        raise ValueError('Choose distinct registered graph capability IDs.')
    supported={x['id'] for x in snap.get('capabilities',{}).get('graph_operations',[]) if x['available']}
    if any(x not in supported for x in requested):raise ValueError('A requested graph capability is unavailable.')


def verify_artifact(rt, item):
    a=rt.artifact(item['artifact'])
    blob=safe_file(rt.root,str(Path(a['blob']).relative_to(rt.root)))
    if a['sha256']!=item['sha256'] or a['bytes']!=item['bytes'] or file_hash(blob)!=a['sha256'] or blob.stat().st_size!=a['bytes']:
        raise ValueError('A frozen planning input changed: '+item['path'])
    return blob


def source_entry(rt,aid,path,purpose,authority):
    a=rt.artifact(aid)
    return dict(artifact=aid,path=path,purpose=purpose,authority=authority,sha256=a['sha256'],bytes=a['bytes'],
                **({'media_type':'image/png'} if Path(path).suffix.lower()=='.png' else {}))


def validate_bound_worker_inputs(rt,plan,payload):
    """Check assigned files, never the entire catalog, before worker creation."""
    from orchestrator import executors,worker_capabilities
    from orchestrator.browser_contract import png_input,png_info
    known={s['artifact']:s for s in source_catalog(payload)}
    for task in plan['tasks']:
        if task.get('execution'):continue
        backend=worker_capabilities.backend_for(task,plan['backend'])
        if backend['type'] not in executors.API_TYPES:continue
        inputs=[{**known[i['artifact']],**i} for i in task['inputs'] if 'artifact' in i]
        executors.validate_input_sizes(inputs,backend)
        if backend['type'] in executors.CODE_TYPES:continue
        for item in inputs:
            raw=verify_artifact(rt,item).read_bytes()
            if backend['type'] in executors.BROWSER_TYPES and png_input(item):png_info(raw)
            else:
                try:raw.decode('utf-8')
                except UnicodeError:raise ValueError('API executors require UTF-8 text inputs: '+item['path']) from None


def blender_preparation_validator(capability):
    """Freeze the actual pure validators without importing host execution in workers."""
    from orchestrator import blender_edit,blender_assets,blender_animation
    module,names,entry={
        'blender.run_python':(blender_edit,{'validate_checks'},'validate_checks'),
        'blender.import_asset':(blender_assets,{'TYPES','portable','validate'},'validate'),
        'blender.animate':(blender_animation,{'DESCRIPTION','validate'},'validate'),
    }[capability]
    source=Path(module.__file__).read_text(encoding='utf-8')
    chunks=[]
    for node in ast.parse(source).body:
        defined={node.name} if isinstance(node,ast.FunctionDef) else {n.id for n in node.targets if isinstance(n,ast.Name)} if isinstance(node,ast.Assign) else set()
        if defined & names:chunks.append(ast.get_source_segment(source,node))
    return ('import json, math, re, sys, unicodedata\nfrom pathlib import PurePosixPath\n\n'+
        '\n\n'.join(chunks)+'\n\nwith open(sys.argv[1], encoding="utf-8") as source:\n    '+entry+
        '(json.load(source))\nprint("RELAY_BLENDER_CONTRACT_VALID")\n')


def repeated_blocked_request(state,job,snap):
    """An exact renewed request may replan after capability discovery improves.

    No fuzzy intent inference, model call, dispatch or mutation. Existing enqueue
    validation and the exact plan Start boundary still apply.
    """
    rows=state.db.execute("SELECT * FROM production_plans WHERE channel=? AND status='blocked' AND run IS NULL AND plan IS NULL AND request=? ORDER BY created DESC",
                          (getattr(state,'channel','telegram'),job['prompt']))
    matches=list(rows)
    if len(matches)!=1:return None
    row=matches[0];options=json.loads(row['options'])
    if options.get('executor_locked') or options.get('executor') or row['error']:return None
    if not row['result'] or json.loads(row['result']).get('decision')!='blocked':return None
    if c.digest(json.loads(row['context']))!=row['context_hash']:return None
    prior={cap for entry in options.get('worker_catalog',[]) for cap in entry.get('capabilities',[])}
    current={cap for entry in snap.get('capabilities',{}).get('graph_executors',[])
             if entry.get('available') for cap in entry.get('capabilities',[])}
    if not current-prior:return None
    action=dict(kind='plan_production',template=options['template'],project=options['project'],
                reference_pack_id=None,research_ids=[],planning_only=options['planning_only'],parent_id=row['id'])
    validate_action(action,snap)
    return {'answer':'Available worker capabilities have changed. Preparing a new proposal from your saved request and sources; no workers have started.',
            'action':action}


def enqueue(state,job,action,snap):
    action=normalize_action(action,snap)
    validate_action(action,snap)
    ident='plan-'+str(job['id']);channel=relay_channels.request_channel(state,job['id'])
    previous=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    if previous:return 'Planning request already saved: '+ident+' · '+previous['status']
    rt=Runtime(pc.root(state),connection=state.db)
    request=job['prompt'];sources=[];parent=None;stage=None;stage_job=None
    from task_relay import production_stages
    if action.get('parent_id'):
        parent=state.db.execute('SELECT * FROM production_plans WHERE id=?',(action['parent_id'],)).fetchone()
        if not parent or parent['channel']!=channel or parent['status'] not in ('needs_input','ready','blocked'):
            raise ValueError('The prior plan changed or belongs to another channel.')
        prior=json.loads(parent['context'])
        request=parent['request']+'\n\n--- USER FOLLOW-UP ---\n'+job['prompt']
        sources=[d for d in prior['sources'] if not d.get('request_context')]
        if parent['plan']:
            selected={i['artifact'] for t in json.loads(parent['plan'])['tasks'] for i in t['inputs'] if 'artifact' in i}
            sources.extend(d for d in prior.get('available_sources',[]) if d['artifact'] in selected)
        stage=prior.get('previous_stage')
        if stage:production_stages.verify(state,rt,prior,parent['id'],channel,job['id'])
    elif action.get('previous_run'):
        run=action['previous_run']
        link=state.db.execute('''SELECT p.id,p.status FROM production_stage_links l
            JOIN production_plans p ON p.id=l.plan_id WHERE l.parent=?''',(run,)).fetchone()
        if link and link['status']!='discarded':
            return 'Next-stage plan already '+link['status']+': '+link['id']+'. Use that saved plan; no duplicate was created.'
        stage,sources,stage_job=production_stages.sources(state,rt,run,channel,job['id'])
    policy=state.get('production-planner-policy',{})
    backend=json.loads(parent['options'])['backend'] if parent else None
    if stage and backend is None:
        backend=json.loads(state.db.execute('SELECT plan FROM production_runs WHERE id=?',(stage['run'],)).fetchone()['plan'])['backend']
    if backend is None:backend=policy.get('backend')
    if action.get('executor'):
        from orchestrator.executors import catalog
        selected=next((x for x in catalog(state) if x['id']==action['executor'] and x['available']),None)
        if not selected:raise ValueError('The requested executor is unavailable; no fallback.')
        backend=selected['backend']
    if backend is None:
        row=state.db.execute('SELECT plan FROM production_runs ORDER BY rowid DESC LIMIT 1').fetchone()
        if row:backend=json.loads(row['plan'])['backend']
    if backend is None:
        from orchestrator import executors
        # Bootstrap only new, unassigned work from verified configuration. Browser
        # and code profiles remain task-specific choices in the frozen catalog.
        candidates=[x for x in executors.catalog(state) if x['available']
                    and x['id'] in (*executors.FILE_TYPES,'codex-cli')]
        candidates.sort(key=lambda x:(x['id']!=job['provider']+'-agent',
                                      x['id']=='codex-cli',x['id']))
        if candidates:backend=copy.deepcopy(candidates[0]['backend'])
    if not backend:
        raise ValueError('No verified production worker is available. In Relay, connect a provider, '
                         'select its text model, then select its Worker provider and click Check worker connection')
    from orchestrator import executors
    tools=executors.validate(backend)
    executors.available(backend)
    options={**action,'backend':backend,'limits':{'seconds':1800,'tool_calls':60,'output_bytes':100000000},'max_attempts':2,'max_tasks':12,'local_corrections':True,'response_budgets':True,
             'planning_limits':{'calls':2,'max_output_tokens':10000,'request_timeout_seconds_at_most':180,'context_chars':MAX_CONTEXT}}
    options['tools']=tools
    if backend['type'] in executors.API_TYPES:options['limits']=executors.limits_for(backend)
    if parent:
        options['limits']=json.loads(parent['options'])['limits'].copy()
        options['max_attempts']=json.loads(parent['options']).get('max_attempts',1)
        options['max_tasks']=json.loads(parent['options']).get('max_tasks',6)
    if 'task_seconds' in action:options['limits']['seconds']=action['task_seconds']
    from orchestrator import worker_capabilities
    # Clarifications retain captured choices. A fresh proposal after a blocked
    # planner (no executable plan/run) may discover newly available workers.
    # Named executors remain locked; saved executable plans are never rebound.
    prior_options=json.loads(parent['options']) if parent else {}
    if stage and not parent:
        prior_plan=state.db.execute('SELECT options FROM production_plans WHERE run=?',(stage['run'],)).fetchone()
        if prior_plan:prior_options=json.loads(prior_plan['options'])
    options['executor_locked']=bool(action.get('executor') or prior_options.get('executor_locked') or prior_options.get('executor'))
    refresh_workers=bool(parent and parent['status']=='blocked' and not parent['plan']
                         and not parent['run'] and not options['executor_locked'])
    if prior_options and not action.get('executor') and not refresh_workers:
        if 'worker_catalog' in prior_options:options['worker_catalog']=copy.deepcopy(prior_options['worker_catalog'])
    else:
        options['worker_catalog']=worker_capabilities.capture(state,backend,options['executor_locked'])
    if parent and 'step_capabilities' not in action:options['step_capabilities']=json.loads(parent['options']).get('step_capabilities',[])
    if parent and 'deliverables' not in action:options['deliverables']=json.loads(parent['options']).get('deliverables',{})
    options['job_request_id']=json.loads(parent['options']).get('job_request_id',parent['request_id']) if parent else (stage_job if stage else job['id'])
    pack=None
    if action['reference_pack_id']:
        from task_relay import reference_packs
        reference_packs.handoff(state,action['reference_pack_id'])
        row=state.db.execute('SELECT * FROM reference_packs WHERE id=?',(action['reference_pack_id'],)).fetchone()
        pack={'id':row['id'],'manifest':row['manifest'],'sha256':row['manifest_sha256']}
        data=json.loads(Path(row['manifest']).read_text())
        versions={f['artifact']:f for f in data['files']}
        for entry in data['inputs']:
            source=source_entry(rt,entry['artifact'],entry['path'],entry['purpose'],entry['authority'])
            frozen=versions.get(entry['artifact'])
            if not frozen or any(source[k]!=frozen[k] for k in ('sha256','bytes')):
                raise ValueError('A selected reference-pack artifact version changed: '+entry['path'])
            sources.append(source)
        pack['unresolved']=data.get('unresolved',[])
    from task_relay import routing_inputs; from task_relay import orchestrator_guides
    manifest=routing_inputs.freeze(state,job,[],action['research_ids'],action.get('artifact_ids'))+orchestrator_guides.selected(state,job['id'])
    manifest+=routing_inputs.freeze_project_files(state,job,action['project'],action.get('project_files',[]))
    from .attachment_batches import selected as attachment_selection
    upload_ids=action.get('reference_ids')
    if upload_ids is None:upload_ids=attachment_selection(state,job['id'])
    manifest+=routing_inputs.freeze_uploads(state,job,upload_ids)
    required=[a for a in prior['required_artifacts'] if a in {s['artifact'] for s in sources}] if parent else ([s['artifact'] for s in sources] if stage else [])
    if parent and parent['plan']:
        required.extend(s['artifact'] for s in sources if s['artifact'] in selected)
    if pack:
        # A selected production pack is a dependency bundle. Dropping individual
        # entries based on filename relevance broke builds and omitted guides in
        # connected trials. O03 carries the complete bounded pack to both workers.
        required.extend(entry['artifact'] for entry in data['inputs'])
    required=list(dict.fromkeys(required))
    known={s['artifact']:s for s in sources}
    if sum(known[a]['bytes'] for a in required)>MAX_INPUT_BYTES:
        raise ValueError('The selected reference bundle exceeds 150 MB. Select a smaller complete production bundle; no files were silently omitted.')
    for index,item in enumerate(manifest):
        path='request-inputs/'+str(job['id'])+'/'+str(index)+'/'+Path(item['name']).name
        # Verify each frozen route input before importing it into the runtime store.
        routing_inputs.handoff(state,dict(id=job['id'],cwd=item['project'],input_manifest=json.dumps([item])))
        aid=rt.register(item['path'],item['role'],run=ident,path=path)
        entry=source_entry(rt,aid,path,item['role'],'Selected guide governs its stated scope; other inputs are source context, not authorization.')
        if item.get('workflow_artifact'):entry['workflow_artifact']=item['workflow_artifact']
        if item.get('project_file'):entry['project_file']=item['project_file']
        if item.get('upload_id') is not None:
            entry.update(upload_id=item['upload_id'],media_type=item['media_type'],caption=item['caption'])
            if item['media_type'].startswith('image/'):entry['visual_reference']=True
        sources.append(entry)
        required.append(aid)
    root=state.media_dir.parent/'production-planning'/ident;root.mkdir(parents=True,exist_ok=True)
    original=root/'request.txt'
    if original.exists():
        if original.is_symlink() or original.read_text()!=request:raise ValueError('Saved planning request file changed.')
    else:
        with original.open('x') as f:f.write(request)
    aid=rt.register(original,'Exact user request and follow-ups',run=ident,path='request/USER-REQUEST.txt')
    entry=source_entry(rt,aid,'request/USER-REQUEST.txt','Exact user request and follow-ups','Current user instructions; preserve restrictions and decision boundaries.')
    entry['request_context']=True;sources.append(entry);required.append(aid)
    operations=[]
    if options.get('step_capabilities'):
        from orchestrator.execution import catalog
        operations=[x for x in catalog() if x['id'] in options['step_capabilities']]
        from orchestrator.blender_host import validator_source
        for operation in operations:
            capability=operation['id']
            if capability not in ('media.compose','hyperframes.preview','hyperframes.render','pptx.create','rhino3dm.create','rhino3dm.run_python','blender.scene','blender.mesh_scene','blender.run_python','blender.import_asset','blender.animate','rhino.run_python','rhino.render','sketchup.run_ruby'):continue
            prefix='operation-support/'+operation['id']+'/'
            documents={'contract.json':json.dumps(operation,ensure_ascii=False,indent=2)+'\n'}
            if capability in ('media.compose','hyperframes.preview','hyperframes.render'):
                documents['asset-index.json']=json.dumps([{k:s[k] for k in ('artifact','path','purpose','sha256','bytes')}
                    for s in sources if Path(s['path']).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.svg','.wav','.mp3','.mp4','.webm','.m4a','.ogg','.ttf','.otf','.woff','.woff2','.js','.mjs','.css')],ensure_ascii=False,indent=2)
            elif capability=='rhino3dm.run_python':
                from orchestrator import rhino3dm_script_contract, host_script
                documents['rhino3dm_script_contract.py']=Path(rhino3dm_script_contract.__file__).read_text(encoding='utf-8')
                documents['host_script.py']=Path(host_script.__file__).read_text(encoding='utf-8')
                documents['validate.py']=('import json, sys\nfrom rhino3dm_script_contract import validate_checks\n'
                    'from host_script import validate_script_bytes\n'
                    'with open(sys.argv[1], encoding="utf-8") as f: validate_checks(json.load(f))\n'
                    'if len(sys.argv)>2:\n'
                    '    with open(sys.argv[2], "rb") as f: compile(validate_script_bytes(f.read()).decode("utf-8"),sys.argv[2],"exec")\n'
                    'print("RELAY_RHINO3DM_SCRIPT_CONTRACT_VALID")\n')
            elif capability=='rhino3dm.create':
                from orchestrator import rhino3dm_contract
                documents['rhino3dm_contract.py']=Path(rhino3dm_contract.__file__).read_text(encoding='utf-8')
                documents['validate.py']=('import sys\nfrom rhino3dm_contract import load, validate\n'
                    'with open(sys.argv[1], encoding="utf-8") as f: validate(load(f.read()))\n'
                    'print("RELAY_RHINO3DM_CONTRACT_VALID")\n')
            elif capability=='pptx.create':
                from orchestrator.pptx_document import validator_source as pptx_validator
                documents['validate.py']=pptx_validator()
            elif capability=='sketchup.run_ruby':
                from orchestrator import sketchup_contract, host_script
                documents['sketchup_contract.py']=Path(sketchup_contract.__file__).read_text(encoding='utf-8')
                documents['host_script.py']=Path(host_script.__file__).read_text(encoding='utf-8')
                documents['validate.py']=('import json, sys\nfrom sketchup_contract import validate_checks\n'
                    'from host_script import validate_script_bytes\n'
                    'with open(sys.argv[1], encoding="utf-8") as f: validate_checks(json.load(f))\n'
                    'if len(sys.argv)>2:\n'
                    '    with open(sys.argv[2], "rb") as f: validate_script_bytes(f.read()).decode("utf-8")\n'
                    'print("RELAY_SKETCHUP_CONTRACT_VALID")\n')
            elif capability.startswith('rhino.'):
                from orchestrator import rhino_contract, host_script
                validator='validate_checks' if capability=='rhino.run_python' else 'validate_render'
                documents['rhino_contract.py']=Path(rhino_contract.__file__).read_text(encoding='utf-8')
                documents['validate.py']=('import json, sys\nfrom rhino_contract import '+validator+'\n'
                    'with open(sys.argv[1], encoding="utf-8") as source:\n'
                    '    '+validator+'(json.load(source))\nprint("RELAY_RHINO_CONTRACT_VALID")\n')
                if capability=='rhino.run_python':
                    documents['host_script.py']=Path(host_script.__file__).read_text(encoding='utf-8')
                    documents['validate.py']+=('from host_script import validate_script_bytes\n'
                        'if len(sys.argv)>2:\n'
                        '    with open(sys.argv[2], "rb") as script: validate_script_bytes(script.read())\n'
                        '    print("RELAY_HOST_SCRIPT_BOUNDS_VALID")\n')
            elif capability in ('blender.scene','blender.mesh_scene'):
                documents['validate_scene.py']=validator_source(capability=='blender.mesh_scene')
            else:documents['validate.py']=blender_preparation_validator(capability)
            for name,text in documents.items():
                path=prefix+name
                if any(s['path']==path for s in sources):continue
                file=root/prefix/name;file.parent.mkdir(parents=True,exist_ok=True)
                with file.open('x',encoding='utf-8') as stream:stream.write(text)
                aid=rt.register(file,'Registered operation support',run=ident,path=path)
                support=source_entry(rt,aid,path,'Exact operation contract and standalone data validation',
                                     'Relay operation contract; validates JSON only, does not authorize host execution.')
                support['operation_support']=operation['id'];sources.append(support);required.append(aid)
    # Keep records distinct by artifact identity, avoiding a full copy per stage.
    sources=list({s['artifact']:s for s in sources}.values())
    # This is the workflow source catalog, not any worker's input pack. A later
    # stage can retain a photo ZIP while a browser needs only research text.
    # Validate actual bindings after role-specific source selection below.
    texts=[];used=0
    for source in sources:
        blob=verify_artifact(rt,source)
        if Path(source['path']).suffix.lower() in ('.md','.txt','.json','.csv','.py') and source['bytes']<=100000:
            raw=blob.read_bytes()
            try:text=raw.decode('utf-8-sig')
            except UnicodeError:continue
            if used+len(text)<=220000:texts.append({'artifact':source['artifact'],'text':text});used+=len(text)
    template_plan=templates.build(action['template'],'template',[],backend) if action['template']!='custom' else None
    if template_plan:
        for task in template_plan['tasks']:
            task['max_attempts']=options['max_attempts'];task['limits']=copy.deepcopy(options['limits'])
        template_plan={k:template_plan[k] for k in ('brief','tasks')}
    from task_relay.host_apps import catalog as app_catalog
    payload={'original_request':request,'project':action['project'],'template':action['template'],
        'host_applications':app_catalog(state) if 'shell' in options['tools'] or any('code.execute' in x['capabilities'] for x in options.get('worker_catalog',[])) else [],
        'planner_instructions':PLANNER_SYSTEM,
        'template_definition':templates.STAGES.get(action['template']),'template_plan':template_plan, 'options':options,'sources':sources,
        'required_artifacts':required,'source_texts':texts,'reference_pack':pack,
        'missing_text_artifacts':[s['artifact'] for s in sources if s['artifact'] not in {t['artifact'] for t in texts}],
        'max_selected_input_bytes':MAX_INPUT_BYTES}
    if set(options.get('step_capabilities',[])) & set(SCRIPT_OPERATIONS):
        from .geometry_sources import INSTRUCTIONS as geometry_instructions
        payload['geometry_source_policy']=1
        payload['planner_instructions']+=geometry_instructions
    if any(s.get('visual_reference') for s in sources):
        if set(options.get('step_capabilities',[])) & {'media.compose','hyperframes.preview','hyperframes.render'}:
            payload['planner_instructions']+=('\nFor media.compose, uploaded images may be exact render assets rather than visual references for an author. '
                'Bind render assets explicitly to the operation and use the asset index for text authors. '
                'Do not infer their visible content from filenames. If the user asks for image interpretation or design matching, '
                'bind those exact images explicitly to the relevant agent tasks with images.view; report a missing visual capability rather than bypass it. '
                'Delivery code review must disclose its lack of visual inspection; human visual selection remains required.')
        else:payload['planner_instructions']+=UPLOAD_PLANNER_INSTRUCTIONS
    from . import pipelines
    pipeline=pipelines.request_context(state,job['id'])
    if not pipeline and action.get('previous_run'):pipeline=pipelines.context_for_run(state,action['previous_run'])
    if not pipeline and parent and prior.get('pipeline_step'):
        pipeline={'stage':prior['pipeline_step'],'inputs':{'handoffs':prior.get('handoff_sources',[])}}
    if pipeline:
        payload['pipeline_step']=pipeline['stage']
        payload['handoff_sources']=pipeline.get('inputs',{}).get('handoffs',[])
        payload['planner_instructions']+='\nThis is one stage of an authorized saved workflow. Its exact stage scope is pipeline_step. A selection gate must select the complete deliverable set, using selection_outputs for related native model/preview files. A gate of none requires independent review but no invented user selection gate, except exact host-script preparation retains its required script/checks selection. Unknown host code is still deferred for exact Start approval. Do not include later-stage capabilities or deliverables. The scheduler advances automatically after completion or required selection.'
    from . import workflow_library
    starter=prior.get('starter_workflow') if parent else None
    if action.get('starter_workflow'):
        if starter:
            if action['starter_workflow']!=starter['definition']['id'] or action.get('starter_stage',starter['stage'])!=starter['stage']:
                raise ValueError('A revision cannot silently switch the frozen starter workflow or stage. Make a separate stage request.')
        else:
            starter=workflow_library.freeze(action['starter_workflow'],action.get('starter_stage'))
    if starter:
        payload['starter_workflow']=copy.deepcopy(starter)
        selected=next(s for s in starter['definition']['stages'] if s['id']==starter['stage'])
        payload['planner_instructions']+='\nBundled starter: '+json.dumps(selected)+(
            '\nUse only this selected stage as a starting point. The exact user request takes precedence. '
            'Do not execute later stages or assume listed tools are installed. Check the executor/operation contracts; '
            'return blocked or needs_input when required tooling or exact inputs are missing.')
    if options.get('backend',{}).get('type') in executors.BROWSER_TYPES or any('browser.use' in x['capabilities'] for x in options.get('worker_catalog',[])):
        from task_relay.orchestrator_chat import clock_context
        from task_relay.browser_sites import catalog as site_catalog
        payload['browser_account_sites']=site_catalog(state.db)
        from .managed_browser import status as managed_status
        payload['managed_browser']=managed_status()
        payload['planner_instructions']+='\nFor work requiring the user\'s signed-in website account, use browser profile "accounts" and only exact sites listed as confirmed_by_user in browser_account_sites. Otherwise return needs_input with /browser sites add and /browser sites login commands. Never substitute an anonymous profile for an account request. Public research may still use separate public profiles. A saved session does not expand the task origins or interaction_scope.'
        payload['host_clock']=clock_context()
        payload['planner_instructions']+='\nUse host_clock for date interpretation. Disclose inferred years and search defaults in the brief/instructions. Require observed evidence for factual website claims; unverified dates remain unverified, not assumed unavailable.'
    selected_ids={s['artifact'] for s in sources}
    selected_ids.update(action.get('artifact_ids',[]))
    payload['available_sources']=[dict(artifact=a['id'],
        path='prior-outputs/'+a['id']+'/'+Path(a['path']).name,
        purpose=a['purpose'],authority='Prior output candidate; source use is not acceptance or replacement.',
        sha256=a['sha256'],bytes=a['bytes'],run=a['run'],task=a['task'],
        original_path=a['path'],attempt=a['attempt'],attempt_state=a['attempt_state'])
        for a in routing_inputs.artifact_catalog(state) if a['id'] not in selected_ids and not a['id'].startswith('media-')]
    if stage:payload['previous_stage']=stage
    if options.get('step_capabilities'):
        payload['graph_operations']=operations
        payload['planner_instructions']+=MIXED_INSTRUCTIONS
    from .image_sourcing_policy import describe as image_sourcing
    payload['image_sourcing']=image_sourcing(operations,options.get('worker_catalog',[]),payload.get('managed_browser',{}))
    from . import operation_builders
    builder=operation_builders.freeze(payload)
    if builder:
        payload['operation_builder']=builder
        payload['planner_instructions']+='\n'+operation_builders.INSTRUCTIONS
    if not builder:
        from . import artifact_bindings
        payload['artifact_binding_version']=1
        payload['planner_instructions']+='\n'+artifact_bindings.INSTRUCTIONS
    payload['response_contract']=planning_contract.contract(options,builder,bindings=not builder)
    encoded=c.encoded(payload)
    if len(encoded)>MAX_CONTEXT:raise ValueError('Planning context exceeds its limit; select a smaller reference set.')
    if parent:state.db.execute("UPDATE production_plans SET status='superseded' WHERE id=?",(parent['id'],))
    state.db.execute('''INSERT INTO production_plans(id,request_id,parent_id,channel,request,options,context,context_hash,
        provider,model,status,token,expires,created) VALUES (?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)''',
        (ident,job['id'],parent['id'] if parent else None,channel,request,c.encoded(options),encoded,c.digest(payload),
         job['provider'],job['model'],secrets.token_hex(12),time.time()+86400,time.time()))
    if stage:
        state.db.execute('''INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)
            ON CONFLICT(parent) DO UPDATE SET plan_id=excluded.plan_id''',(stage['run'],ident))
    return 'Planning queued: '+ident+'\nOne bounded producer/reviewer stage will be proposed. No workers have started.'


PLANNER_SYSTEM='''Plan one bounded stage from the exact request and selected sources.
Return JSON with exactly decision (ready, needs_input, blocked), message, plan.
For a ready response when available_sources is nonempty, also include input_basis:
{"mode":"new","artifacts":[]} for independent new work, or
{"mode":"modify_existing","artifacts":["exact baseline artifact ID"]} for revisions.
Classify the current request using its conversation context. A relative change
(for example "twice as tall", "shorten this", "use the same design") requires
the exact baseline, not a newly invented approximation. available_sources contains
prior output versions that were omitted by upstream routing; select the relevant
IDs there or in sources. Include each baseline as an artifact input to the producer;
the reviewer receives the same version. These are candidates, not acceptance.
Choose editable data rather than a preview when the change needs source geometry
or text. If no unique baseline is available, return needs_input with a concrete
source/version question and no plan. Do not leave missing-baseline discovery to
workers or pretend conversation references contain the original file.
Use only necessary prior outputs; catalog presence alone does not make them inputs.
For needs_input/blocked, plan is null and message explains the specific missing
decision/input/capability. Never guess user acceptance or broaden scope.
When options.deliverables is present, return deliverable_map with exactly those IDs. Each value is {task: producer_id, output: exact_declared_output_path} with independent review of that output, or {deferred_operation: capability} for an explicitly deferred operation.
Every selected step_capability must occur in the graph or in deferred_operations.
If an exact-input host operation needs prior script/manifest preparation, declare
deferred_operations as {capability: reason} in the result envelope and include a
gated preparation producer with selection_outputs and independent review. Related
selected host operations (such as startup or inspection of the future native file)
may be deferred together to that execution phase, with a reason for each. Keep ALL
deferred operations in the envelope; they remain required in the later plan. At
least one deferred operation must require registered inputs. This never defers an
unrelated API/media operation or completes the deferred outcome. Other omissions
require needs_input/blocked.
For ready, plan has exactly brief and tasks. Tasks use the supplied assignment
contract: id, role, objective, instruction, inputs, outputs, dependencies, criteria,
limits, max_attempts, optional review_of and user_gate. Every input has artifact,
path, purpose, authority OR from_task, output, path, purpose, authority.
Every output has path,purpose. Use exactly one producer and one independent reviewer.
Reviewer dependencies include producer, inputs include every output under candidate/,
and criteria exactly equal the producer's. Local drafting/review tasks have
max_attempts=options.max_attempts (one initial attempt plus at most one correction).
Browser tasks and registered operations have max_attempts=1. Stay within options.limits. When options.worker_catalog exists, compose each agent dynamically:
include worker={"requires":["files.text"]}. Relay compiles the executor, model and
tools from the frozen catalog. When options.executor_locked is true, omit executor
everywhere: the service already owns that exact selection. Otherwise an explicitly
selected per-task executor goes ONLY inside worker, for example
worker={"requires":["files.text"],"executor":"exact-catalog-id"}.
Never put executor, model or backend at task level. Follow response_contract.schema
when present; it describes proposal fields, not the compiled runtime assignment.
Choose a task-specific role, objective, exact inputs, outputs and review criteria.
Use code.execute for local calculations/validation, files.binary for binary files,
browser.use for scoped website control. These are adapter capabilities, not role names.
Omit tools: Relay resolves and freezes the actual tools and model from that catalog.
Leave executor unset unless the user explicitly selected it. Relay prefers the
narrowest suitable configured API file/Python worker; do not demand Codex or shell
for ordinary drafting, schema validation or document inspection. An explicitly named executor never falls
back. Respect the chosen profile's limits as well as options.limits. Missing
capabilities require a specific blocker, not a fabricated worker or an installation.
Registered execution steps never have worker. Do not call native applications or
external generation through code.execute to bypass registered operation approval.
Legacy plans without worker use options.tools and the selected default backend.
The gemini-agent, openai-agent, qwen-agent, deepseek-agent and openrouter-agent
profiles have declared text file tools only. Their -code variants also have
python_run: isolated Python, exact input copies, declared binary outputs, 100 MB
input/output ceilings and at most 120 seconds per code call within task limits.
Use runtime_tools from the captured profile to check format libraries. Missing
libraries are blockers; do not install packages. These workers have no subprocess,
network, browser, native application or media-encoder access. They do not replace
Rhino/Blender, generation, or registered pptx.create/media.compose operations. Binary input bytes
remain local; read text, code logs and extracted summaries go to the selected model.
Format save/reopen checks do not prove visual quality or Office/Keynote compatibility.
For an existing storyboard or a custom reel design, use hyperframes.preview followed
by hyperframes.render. Read project_schema in their frozen catalog. Any provider can
author full HTML/CSS/JavaScript as the files object of one project.json; this JSON is
only a source transport, not a scene/layout template. Give authors the existing
storyboard, guides and asset index, with enough response/tool budget for real source.
Do not recreate an already completed article/thread/storyboard workflow. Keep source
paths exact and preserve revision constraints. Include local libraries as declared
assets or use paused browser-native animations; do not invent installed GSAP paths.
Plan author -> independent source review -> hyperframes.preview -> independent
preview review. Preview findings/confirmed failures may use the explicitly proposed
local correction allowance to revise source and recheck. Require human preview
selection of project.json, project.zip, frames.zip, contact-sheet.png and verification.json.
When hyperframes.render is also selected but no exact passed preview exists, defer
only that operation with an explicit reason; the gated preview task is the preparation.
After preview selection, plan the exact registered project.zip/verification.json pair
with project_sha256 and preview_sha256; no source redesign in the rendering step.
Rendered video also needs independent review and human selection. Code-only reviewers
must disclose that diagnostics and binary inspection do not establish visual quality.
Never demand Codex or a provider-specific video worker to render a local composition.
media.compose is the legacy fixed-template convenience operation. Use it only when
its constrained design is explicitly appropriate; it cannot fulfill arbitrary authored
HyperFrames storyboards. For that limited operation, use the chosen
model provider. Read its composition_schema and operation-support/media.compose/
contract.json plus asset-index.json. Plan a text JSON author, independent JSON review,
the registered render dependent on that review, and independent delivery review.
Raw image/audio inputs belong to the operation; give the text author the asset index,
storyboard and guides, not binary assets. Bind exact asset paths explicitly. The JSON
is data only: no HTML, JS, arbitrary commands, downloads or TTS. Keep narration within
180 wpm and on-screen copy within the declared reading bound; request a revised timing
decision if an accepted storyboard cannot fit. No audio means a silent video.
The delivery reviewer receives ALL four outputs and uses files.binary/code.execute
on the same model provider where available. Code inspection is technical/editorial
review, not visual inspection; explicitly disclose that limit. Require a human visual
selection gate on the render. Do not demand Codex merely to encode a video. If an
exact locked text-only executor cannot review binary files, report that specific
profile limitation and propose its same-provider code profile for approval.
Choose limits.seconds independently for each
task based on its actual work; the ceiling is not a required duration. Complex
authoring may need 1200–1800 seconds; a focused review may need 300–900 seconds.
Respect any time budgets in the user request. Include saving required outputs,
validation and the final completion response in that task budget. Prioritize
required deliverables and completion before optional analysis or long notes. gemini-agent has only file tools and text outputs.
gemini-browser, openai-browser and qwen-browser have text file and browser tools.
They can also save explicitly granted viewport PNG screenshots. For that task use
browser.capture with browser.use; declare image/png outputs and an application/json
provenance output for each PNG at its exact path plus .json (map.png.json).
Add the PNG paths to browser.screenshots. These reserved pairs are written only by
browser_screenshot. A task has a total output budget up to 10 MB. PNG inputs with
media_type=image/png can be read as metadata (up to 10 MB combined). For visual
review explicitly list the exact reviewer input paths in browser.visual_inputs;
Start then authorizes sending those PNG pixels to the selected model. Review the
saved image and provenance without requiring live DOM text from canvas pages. Text input
limits remain 512 KB. Screenshot pixels are NOT sent to these workers' models.
Reviewers can check file metadata, provenance and independent DOM evidence but
cannot verify screenshot appearance or canvas content. Require user visual review,
or a separately available capable reviewer, for map completeness/visual criteria.
Keep attribution visible; no automatic full-page scrolling, canvas clicking or GIS
analysis is provided. Request the actual location if essential and missing.
When the user requests a map screenshot in a presentation, include a browser capture
task and its review in the same proposed graph as image sourcing and deck creation.
Use the requested map service and location from the user/context. A Google Maps
request must capture Google Maps, not a generated map or another provider. Preserve
visible map attribution and the full captured viewport. Retain the capture URL and
time from map.png.json; give the specification author this provenance and pass the
exact map.png to pptx.create alongside sourced image bundles. Keep provenance JSON
as author/reviewer context, not a second PPTX slide specification. Consent, login,
unloaded map content or verification barriers are concrete blockers, not successful
map captures. Never claim canvas/map completeness from PNG metadata alone.
For any browser executor each task requires browser with profile (a dedicated
profile name), origins (exact https://host origins without paths/wildcards),
interaction_scope (precise authorized website actions, empty for reading/navigation),
max_tabs (1–8), max_actions (1–60), uploads (exact declared input paths), downloads
(exact declared text output paths), and optional screenshots (exact PNG output paths).
Choose origins and actions only from the request's
scope, and preserve an explicitly named profile. If the needed account/site is
ambiguous, ask; never invent a signed-in session. Empty transfer lists by default.
When managed_browser.enabled and managed_browser.available are true, prefer
profile "managed" with session_source="settings" for general website tasks: it uses the same saved Chrome profile
as Settings Browser use. Do not invent a fresh profile when the user says they
already signed in there. Manual sign-in still in progress must finish before work.
The "accounts" profile retains its separate exact-site confirmation rules.
Include required consent/redirect origins explicitly in the proposed scope; a
redirect is evidence for a proposed recovery, never permission to expand a running
assignment. Bot challenges require user resolution; do not route around them.
The reviewer uses the same profile/origins but empty interaction_scope/uploads/downloads.
No login automation, secret entry, arbitrary JavaScript or shell is available.
Retain evidence URLs and distinguish observed interactions from verified remote
outcomes. An uncertain action stops the worker without resubmission. Completion
may require the user to sign in locally. Never promise support for every website.
Never propose shell work for API profiles. Python-only document/data tasks require
a verified -code profile; media composition still needs its own renderer. Examples below show the Codex
profile; adapt capabilities and limits to the frozen catalog. Never invent models
or change a resolved executor after approval.
Put user_gate on the PRODUCER ONLY; omit it entirely from the reviewer. Reviewers
must not have user_gate, even when their report is presented for user review.
In a mixed graph requested to deliver a visual/native artifact, the relevant
producer is the final rendering/model operation. Put visual selection after its
preview exists. Do not insert a user gate on intermediate scene JSON or a generator
script unless the user explicitly requested approval before rendering. Independent
data review remains a dependency and does not need another user approval.
Use a user_gate only where the request or supplied decisions need a human selection.
Required artifacts are stage context, not mandatory arguments to every operation.
The service includes them in authoring/review workers. Registered operations receive
only compatible implicit sources, according to the capability input_types. Keep
incompatible native files as context for authors/reviewers; do not request their
removal from workflow history merely because a later operation cannot consume them.
Explicit operation inputs must be compatible. Do not manually repeat required context. Other artifact IDs must come from sources. Select only inputs needed
for this stage; total distinct input bytes must fit max_selected_input_bytes.
All files in a selected reference pack are required: its guides and dependencies
travel together. Do not infer missing inputs from their absence in your task list;
the service preserves these exact versions in authoring/review workers and binds
compatible versions to registered operations.
Use template_definition as a starting point, adapting to the request's actual scope.
Do not force a preparation stage on an authorized local rendering request.
host_applications supplies detected executables, invocation flags and verification
requirements. For application execution requests, assign actual local execution
through blender.scene for primitives or blender.mesh_scene for arbitrary
agent-computed mesh geometry; select that
registered operation in step_capabilities. Use a files/shell worker to compute geometry with its own code and prepare scene JSON
and a reviewer for that producer, followed by the selected host operation and optional independent
review of its native outputs. Do not execute Blender in the restricted agent shell.
Use blender.startup for a fixed host startup diagnostic. These are explicit host
operations in the proposed stage; they do not change the agent sandbox. A gyroid or unfamiliar surface can be computed in the agent sandbox and passed as
mesh vertices/faces; no shape-specific host command is needed. Use the exact mesh
scene schema and have the agent save its generator and geometry checks alongside
the JSON. Existing-scene editing uses the separate exact-approved blender.run_python stage
described in MIXED_INSTRUCTIONS; never run Blender in the restricted agent shell. Declare the native editable file, a PNG preview and
source script/evidence as outputs, and give all of them to review. Require opening
the saved native file and checking its actual contents; a script or prose alone
is not a completed model. Installed executable presence does not establish a
successful render or override sandbox permissions. Do not install missing apps.
Read execution_environments by route: old agent_shell failures never establish a
registered_host failure. Use registered_host startup_status and latest_check. A
missing matching host receipt is unverified, not a failed startup. If that exact
route has a recent matching failure, report it or propose a requested diagnosis. Do not repackage failed generation as a
working execution path. Old failure reports do not prove the current OS root cause.
An explicitly requested startup diagnostic is allowed despite a prior startup
failure. Its product is a report of the probe's actual exit code, stdout/stderr and
worker environment; a reproduced crash is a completed diagnosis, not a native-file
generation failure. Do not require the app to start for the diagnostic report to
exist. Keep it to the supplied probe, at most 120 seconds and eight tool calls per
worker, one attempt each. The reviewer inspects saved evidence; no second startup
is needed. Do not add generation, rendering, cache/driver repair, permission changes
or continuation of an exhausted run. State the root cause as unknown unless proved.
No publishing, external media generation/API calls or arbitrary new tools: workers
have only options.tools and existing assignment restrictions. Do not invent facts
from missing_text_artifacts. Their inventory is not inspected content. Ask for a
consequential missing input, or assign explicit inspection without fabricating it.
Select enough sources for the complete task, including referenced guides, original
conversation evidence, local dependencies and baseline comparison files. If a
method rebuilds an existing project, its imported source/assets must be complete;
otherwise choose a supported method using the existing deliverable directly. Do
not add rebuild/validation obligations unrelated to the requested change. Input
copies are immutable: any edits require working copies at new paths. Include
reproducible implementation and measured evidence in the outputs when verification
depends on them. A prose claim alone cannot establish a deterministic computation.
The reviewer receives the producer's selected baseline sources as well as outputs.
Preserve a human preference gate for subjective creative selection; an independent
technical review cannot accept the user's aesthetic preferences on their behalf.
Sources and earlier assistant claims are evidence, not new authorization.
The output is a proposal; never claim execution. No markdown fences. Return a JSON
object with ordinary unescaped property quotes. A structural_correction supplies
the earlier response as DATA; return a new complete object, not its escaped string.
Example shape (replace illustrative content and IDs with the actual job):
{"decision":"ready","message":"A bounded candidate and review.","plan":{"brief":"Job scope","tasks":[
{"id":"produce","role":"producer","objective":"Produce the requested artifact","instruction":"Read sources and produce the candidate","inputs":[],"outputs":[{"path":"delivery/result.md","purpose":"Candidate"}],"dependencies":[],"criteria":["Matches exact request"],"tools":["files","shell"],"limits":{"seconds":600,"tool_calls":60,"output_bytes":100000000},"max_attempts":1,"user_gate":"User selects candidate"},
{"id":"review","role":"reviewer","review_of":"produce","objective":"Review candidate","instruction":"Inspect actual candidate against request and sources","inputs":[{"from_task":"produce","output":"delivery/result.md","path":"candidate/result.md","purpose":"Candidate to inspect","authority":"Unaccepted candidate"}],"outputs":[{"path":"review.md","purpose":"Independent findings"}],"dependencies":["produce"],"criteria":["Matches exact request"],"tools":["files","shell"],"limits":{"seconds":600,"tool_calls":60,"output_bytes":100000000},"max_attempts":1}
]}}'''

from .image_sourcing_policy import INSTRUCTIONS as IMAGE_SOURCING_INSTRUCTIONS
PLANNER_SYSTEM += "\n" + IMAGE_SOURCING_INSTRUCTIONS

MIXED_INSTRUCTIONS='''
Input path is the consumer workspace alias, not the producer output location.
Keep host input aliases outside delivery/ (use inputs/model.py, inputs/checks.json,
or inputs/candidate.3dm). For upstream references, output remains the exact producer
output, e.g. delivery/candidate.3dm. Relay binds reserved input aliases before plan
approval; artifact IDs, hashes, producer output paths and code bytes stay exact.
Preparation outputs that must travel together (especially model.py and checks.json)
require selection_outputs on the producer: an explicit list of the exact declared
output paths to select as one set. Give the producer a user_gate describing that
set; include every member in independent review. The later host stage receives all
selected members and still needs its own exact-code approval. Do not select a
single script and assume its sibling checks are selected. For a blocked attempt,
prepare a NEW bounded stage using its exact draft artifact_ids and report as
unaccepted source inputs; do not reset budgets or replay the old attempt.
For a requested rendered Rhino model, preparation must create a named view/camera
and document its exact name. The host inspection's named_views is the source for
the later render manifest; a viewport preview is insufficient. Include a render
manifest draft in the preparation outputs when useful, without authorizing render.

blender.animate adds numeric linear transform/camera tracks or renders existing
animation from one registered .blend plus an exact registered JSON manifest.
Use graph_operations.animation_schema, exact registered criteria and six outputs.
Prepare the manifest in a separate agent stage if it does not exist. Every render
stage requires independent output review and a user selection gate. Preview and final
are separate exact manifests and approvals; never expand frame/quality budgets.
Parameters: manifest_sha256. An optional selected checkpoint.zip must originate from
a confirmed stopped blender.animate attempt with the identical manifest. It reuses
verified frames only; unresolved frame intents block. Do not reset or retry old jobs.
blender.import_asset appends named mesh objects from selected .blend libraries and
packs selected PNG/JPEG dependencies into a portable candidate. It accepts an exact
registered asset manifest plus every selected scene/library/image. Use asset_schema
from the catalog. Manifest file paths preserve the original relative layout; entries
bind selected hashes and supplied provenance/license (unknown license=null). Supported
imports are append_objects and image_texture to an existing named Image Texture node.
No persistent links, downloads, arbitrary scripts or inferred dependencies. If no
manifest exists, first prepare/review one as a separate text stage; do not invent
hashes or authorize future unselected files. The execution stage has host import,
independent review of all six outputs and a candidate user_gate. All assets must be
already registered inputs; no from_task inputs. Set manifest_sha256 to its selected
source hash. Media types: application/json only for manifest, application/x-blender
for scenes/libraries, image/png or image/jpeg for textures, text/plain for context.
The plan delivers the complete manifest before Start. The candidate is packed;
bundle.zip retains selected original paths/versions. Verification reopens its candidate
after extraction to a fresh location with the build directory moved away. Object
renaming, missing/unselected dependencies and unsupported sources stop the job.

Blender edits use TWO stages. First inspect the selected scene, have an agent write
edit.py and edit-checks.json using the run_python checks_schema, and independently
review them. Do not execute this script in the agent shell. Stop for user review.
rhino.render uses an exact existing named view and bounded resolution from an attached
manifest, with the built-in Rhino Render engine; it requires independent review and
a candidate selection gate. It never substitutes a viewport preview.
Direct SketchUp: sketchup.startup runs a fixed owned-process diagnostic; sketchup.inspect
reads one exact application/vnd.sketchup.skp artifact. sketchup.run_ruby creates/edits
using embedded Ruby on macOS SketchUp 2025/2026. Prepare model.rb and checks.json
with independent review and selection_outputs including BOTH files; defer execution
until exact registered script/checks/model versions are selected. Ruby is text/x-ruby;
scene_sha256 is null only for create. Use the catalog checks_schema, exact outputs
and criteria. Every candidate requires independent output review and a user_gate.
Do not substitute Rhino/Blender or perform host work in a preparation task.
Full standalone library: rhino3dm.run_python exposes the installed rhino3dm Python
API without a Relay geometry whitelist, including NURBS, surfaces/BReps, annotations,
document tables and any other API present in that library version. It creates or
edits a File3dm without running Rhino. Prepare/review model.py and checks JSON using
its checks_schema and supplied validate.py. Select both exact registered artifacts
before a separate execution Start; scene_sha256=null for create, selected primary
.3dm hash for edit. Additional binary inputs use application/octet-stream. Scripts
receive rhino3dm, model, input_paths and workspace; Relay saves model afterward.
file_version in checks is explicit: 7 for Rhino 7, 8 for Rhino 8; the library version
does not determine the requested file version. Independent output review and user
selection are required. Full library access does not mean all Rhino commands,
plugins, rendering or Rhino.Compute are available/authorized. Normal host Python
permissions apply. Native Rhino execution/verification remains a separate route.
Standalone 3DM convenience builder: rhino3dm.create is a local procedure using the rhino3dm library,
without Rhino. Prepare bounded geometry JSON from geometry_schema (points,
polylines, meshes including terrain, layers and units); independently review it
before generation. Read operation-support/rhino3dm.create/contract.json and run its
validate.py against the geometry JSON. Use the exact registered outputs and criteria,
independent output review and a user selection gate. Geometry JSON is data, never
Python. Generation is new-file only, with no previews, rendering, model imports,
plugins or Rhino modeling commands. Unsupported requests must remain explicit;
never silently mesh a requested NURBS surface. A .3dm format request alone does
not require Rhino execution. Explicit Rhino execution/verification or an existing
Rhino stage must keep rhino.*; switching routes needs a newly reviewed plan and Start.
Report library-generated/library-reopened separately from native Rhino verification.
Direct Rhino: rhino.startup is a fixed version/interpreter startup diagnostic; rhino.inspect
inventories one exact application/vnd.rhino .3dm with its source unchanged.
rhino.run_python creates/edits through IronPython 2.7 on Rhino 7 or CPython 3 on
Rhino 8, using RhinoCommon in an owned macOS process or separate documents in connected Rhino 8. First prepare and independently review model.py and checks JSON
using its catalog checks_schema. Only a later stage with already registered exact
script/checks and optional scene can execute. Prepared scripts must be at most
100000 UTF-8 bytes. Validate BOTH checks and script with validate.py checks.json
model.py before delivery and review. For flat drawings save a Top orthographic
named view and set preview.named_view to it so the delivered preview is face-on.
The assigned Rhino document is headless; doc.Views.ActiveView is None. Use the
contract's named_view_example with a standalone RhinoViewport and ViewInfo, sized
to the requested preview and actual geometry bounds. Never require an active UI view.
Bind script_sha256/checks_sha256 and
permissions=unrestricted_host; scene_sha256=null for create, exact source hash for
edit. Use text/x-python and application/json for code/checks. Edits require selected
application/vnd.rhino. Use exact catalog outputs/criteria, independent output review
and a user selection gate. A viewport preview is not a production render. Preserve
undeclared geometry/attributes and the documented table/settings scope. Do not
approve future scripts or invoke Grasshopper; GH support is paused.

Only AFTER exact script/checks artifacts exist, propose a separate blender.run_python
stage with those registered artifacts and the exact original scene. It accepts no
from_task inputs: an initial job approval cannot approve unknown future host code.
Use text/x-python for the one script, application/json for the one checks contract,
application/x-blender for the one scene and text/plain for other context. Bind the
three SHA-256 parameters to the selected source hashes; permissions=unrestricted_host.
The plan card discloses normal host filesystem/network access and delivers the
complete script/checks before Start can authorize execution. No permission checkboxes
or sandbox promises. This v1 edits existing objects in self-contained scenes, preserving
other objects, cameras and materials, collection membership and active frame.
The operation saves a new candidate with exact source/script/attempt lineage,
independently reopens it, checks declared dimensions/preservation and renders CPU
previews through the same selected camera. Include an independent reviewer of all
six outputs and a user_gate on the host task for candidate selection. No automatic
selection or dependent render stage. B03 handles external asset imports/bundles.

blender.inspect inventories one exact registered .blend plus text context. Set its
input media_type to application/x-blender; use the catalog outputs/criteria and
120-second limit. A host inspection plus independent agent review is a complete
inspection stage; it needs no agent producer. No native-file edits, render or
arbitrary Python execution occurs. Disclose host library resolution. Do not
pretend this inspection operation implements a requested edit; use it as the first
explicitly described stage while Blender script editing remains a separate milestone.

For blender.startup, blender.scene and blender.mesh_scene use their catalog outputs/criteria/limits
exactly, including every output media_type. Relay fills omitted types for fixed
registered outputs and their consumers; conflicting explicit types are rejected.
For scene generation, identify one upstream scene JSON (application/json); other
JSON reports are context, not additional scene inputs. A fixed host operation has
one operation invocation and no agent tools, so use tool_calls=1. Keep both the
data producer and its reviewer as dependencies of the scene operation. These registered host operations run
fixed trusted Blender code with normal OS permissions, independently of the agent
sandbox. Explain host execution in the proposed scope. No arbitrary scripts,
commands, imported blends, drivers or external assets are supported.
blender.startup accepts the request/context as text and produces delivery/execution.json;
a failed probe is a valid diagnostic, not a successful app startup. It can be followed
by an independent reviewer without a separate agent producer.
blender.scene and blender.mesh_scene accept exactly one application/json scene input
produced by an agent. Use mesh_scene for unfamiliar/generated topology: the agent
computes vertices/faces using local code (no Blender launch), writes version-2 JSON
and keeps its source generator and geometry checks for review. Model-specific mesh
validity, visual intent and any requested thickness/manifoldness are agent/reviewer
criteria, not inferred by the generic renderer.
For both scene operations,
all request/context inputs use text/plain. Follow scene_schema in the operation catalog.
It returns the four fixed outputs (native scene, PNG, trusted script and receipt).
Use at most 6 tasks: scene-data producer, its reviewer, scene operation, optional
scene-output reviewer. Make the scene operation depend on the data review.
For pptx.create, prepare slides.json using slide_schema in the frozen operation
catalog and operation-support/pptx.create/contract.json. The operation accepts one
application/json specification and optional exact PNG/JPEG inputs, sourced-image
bundles (application/zip from images.collect or images.fetch), plus text context.
For images.collect, subjects in parameters contain the complete literal search inputs.
Use concise subject queries, not prose captions. Set optional identity to the exact
botanical name, place or landmark established by the request/research. The collector
tries the phrase and the same words in any order; it never invents synonyms or drops
required words. Avoid overconstraining one query with several redundant descriptions.
A wholly empty collection fails with diagnostic receipts; partial missing subjects
remain explicit for review and any user-authorized omissions.
The registered result is a ZIP containing image bytes and manifest.json; bind the
photo-bundle deliverable directly to that ZIP. Do not add a JSON conversion to
replace it. Its independent reviewer must review the collector's exact ZIP even
when another task derives a summary or manifest.
Use inputs=[]; retain research/context with the independent reviewer and deck author,
not with the download operation. Never attach conversation histories just for provenance.
For factual research, identification guides, real examples and documentary decks,
default to authentic sourced photographs, even when the user only says images or
visuals. Synthetic illustrations require a requested illustrative/design purpose;
generic research does not authorize inventing reference examples. Honor the saved
stage's visual_intent; do not replace its sourcing operation with a media provider.
For Google Images, Bing, DuckDuckGo or browser-based source discovery, use a
browser.use producer with browser.image_sources=[{path:"delivery/image-sources.json",
subjects:[{id,label,query}]}]. It searches a suitable service chosen using image_sourcing (or the explicit
user-selected service) in the existing managed browser and exports observed originals using browser_image_source. Include
necessary exact search/consent origins; do not invent unseen publisher domains or
expand navigation scope. Search result previews can expose original image and
publisher links without navigating to that publisher. Thumbnails are rejected.
Then images.fetch consumes exactly that JSON and returns a ZIP. Use an independent
binary-capable reviewer for the ZIP and a selection gate, checking subject identity,
coverage and source rights. Unknown licences stay unknown; never claim cleared reuse.
Pass the exact ZIP to pptx.create. No search API key, model-generated URL list,
screenshot-as-photo, paid search subscription or image generation is needed.
Plan small discovery batches (normally one to three subjects). Set explicit
provider_requests up to 24 and enough tool_calls for navigation, preview loading,
source export and finish; keep the user's lower budgets. Larger collections need
multiple bounded producers/downloads, with their exact ZIPs passed to the deck.
Report challenges as manual
verification and retain successful prior results. Do not silently replay a blocked
approved stage or switch an explicitly requested search service.
When images.collect is selected by image_sourcing or the user constraints, use it
with the exact subject list, then review its manifest and candidates before slide
preparation. Follow image_source_schema; missing matches stay explicit. Never use
image generation as an implicit substitute for image search. This is generic image
sourcing, not a plant-specific workflow. For plants, use botanical names from the
research and preserve common names as labels; do not infer taxonomic synonyms.
Use bundle paths as <staged-bundle.zip>/images/<subject-id>.jpg|png in slides.json,
and pass the exact reviewed ZIP to pptx.create. If the user permits missing photos
to be skipped, omit unavailable image elements and photo-only slides, retain the
subject's research/text, and record omissions in the summary. Apply that permission
to author and reviewer criteria; missing permitted photos alone must not block.
Otherwise honor explicit complete-photo requirements. Include every requested subject,
visible subject captions, author/licence credits and source-page references.
Review identity, coverage and suitability; metadata matches alone do not prove them.
Image paths inside JSON must match the staged image input paths in the operation.
Use parameters={}, one .pptx output with the registered MIME type and criteria,
and tools=[]. Require the specification producer and its independent reviewer as
dependencies before creation, then a separate reviewer of the actual PPTX and a
user selection gate. Local native text/shapes/tables/charts stay editable. The
operation does not launch Keynote, render previews or prove visual quality. If
previews are requested, plan a separate rendering/review step with verified tools;
never substitute an unrelated image for a render of the actual PPTX. Existing
PPTX/template editing is not supported by this creation operation.
The text-only input/output rules below apply only to text.bundle and gemini.text.
gemini.image accepts text plus PNG/JPEG/WEBP references, including a dependency on
a Blender preview. Use its frozen configured image model, max_output_tokens and
aspect_ratio parameters; one image/png output and the exact registered criteria.
openrouter.image uses the configured OpenRouter image slug and aspect_ratio through the dedicated images endpoint, with fallbacks disabled. It has the same references, review and selection contract.
openai.image serves the same graph role through the configured GPT Image model,
with model, size and quality parameters from its registered schema. It accepts
text-only generation or image edits. Respect the selected provider; do not switch
to another model or provider on failure or because a text model is configured.
It is one bounded external request, followed by independent review and selection.
runway.image, runway.video, higgsfield.image, higgsfield.video and meshy.mesh use
the frozen configured model and an explicit parameters.prompt. Write that prompt
as the actual generation brief, preserving constraints without Relay instructions.
The input text files retain the full original request locally; they are not sent
as extra prompt text. Meshy currently creates only an untextured GLB from text,
with a prompt of at most 800 characters. Image-to-3D and texture refinement are
not implemented. Other cloud prompts are at most 1000 characters. Use the exact
registered parameters, output MIME/extension and criteria. Runway accepts up to
three image references for images (@ref1, @ref2, @ref3 in order), or one first
frame for video; each reference is at most 3.5 MB. Higgsfield operations currently
accept text only. Never discard requested references or turn a requested editable
CAD model into a mesh without asking. Media needs independent output review and
a user selection gate. These operations submit once, save the remote identity,
poll and download into the existing artifact store; queued is not completed.
For a model + photoreal image request, include both native rendering and image
generation in the same graph when these operations are selected. Do not silently
drop the image outcome at the Blender preview gate. For any outcome that requires
a separate approval stage, explain the pending outcome and its gate in the brief.

For this request, graph_operations explicitly extends the two-agent contract:
use 2–options.max_tasks tasks (6 when absent in an older scope), with at least one
supported agent and only the permitted registered
operations when useful. Each registered task has execution={capability,version,
parameters}, tools=[], one attempt, exactly the registered criteria, and its smaller
time/output limits. It has 1–20 explicitly typed text inputs and one text/plain
output; set media_type on every upstream output feeding such an input too.
Use input media_type text/plain or text/markdown. text.bundle concatenates source
texts with identities; parameters is {}. gemini.text makes one tool-free text API
request; parameters contains model (exact configured or user-specified ID) and
max_output_tokens (1–4096). Never invent a configured model. Only catalogued APIs are allowed.
Only agent tasks may be independent reviewers. Every agent producer still
requires its independent reviewer, using matching criteria and all its outputs.
Registered operation checks establish mechanical success only. Use an agent for
semantic review where needed; never report generated text as independently verified.
External requests and source transfer must be explicit in the proposed scope.
No arbitrary commands, endpoints, tools or credentials can be supplied in execution.
'''


def generate(row,payload):
    """One provider request; native usage and the first response are retained."""
    provider=row['provider'];config=gemini.read_config() if provider=='gemini' else api.read_config(provider)
    if not config:raise ValueError('The planning provider is disconnected.')
    body=json.dumps(payload,ensure_ascii=False)
    system=payload['planner_instructions']
    if provider=='gemini':
        generation={'responseMimeType':'application/json','maxOutputTokens':10000}
        if payload.get('response_contract'):
            generation['responseJsonSchema']=payload['response_contract']['schema']
        response=gemini.Client(config['api_key']).request('models/'+gemini.model_name(row['model'])+':generateContent',
            {'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':body}]}],
             'generationConfig':generation})
        text=''.join(p.get('text','') for candidate in response.get('candidates',[]) for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
        return text,response.get('usageMetadata',{})
    client=api.Client(provider,config['api_key'],config.get('base_url'))
    if provider=='openai':
        response=client.request('responses',{'model':row['model'],'instructions':system,
            'input':[{'role':'user','content':body}],'store':False,'max_output_tokens':10000})
        text=''.join(p.get('text','') for item in response.get('output',[]) for p in item.get('content',[]) if p.get('type')=='output_text')
    else:
        response=client.request('chat/completions',{'model':row['model'],'messages':[{'role':'system','content':system},{'role':'user','content':body}],'stream':False,'max_tokens':10000})
        text=response['choices'][0]['message']['content']
    return text,response.get('usage',{})


def plan_origin(payload,supplied,request_id):
    """Record exact template-relative edits; never mutate reusable templates."""
    name=payload['template'];definition=payload.get('template_definition')
    origin={'kind':'generated','job_request_id':payload['options'].get('job_request_id',request_id),
            'template_id':None,'template_version':None,'modifications':[]}
    if payload.get('starter_workflow'):
        starter=payload['starter_workflow']
        selected=next(s for s in starter['definition']['stages'] if s['id']==starter['stage'])
        origin.update(kind='adapted_template',template_id=starter['definition']['id'],
            template_version=starter['sha256'],starter_stage=starter['stage'],
            modifications=[{'path':'/stage-to-plan','before':copy.deepcopy(selected),'after':copy.deepcopy(supplied)}])
        return origin
    if definition is None:return origin
    # Compare to the captured definition, not a potentially updated module.
    baseline=copy.deepcopy(payload['template_plan'])
    origin.update(kind='adapted_template',template_id=name,template_version=c.digest({'definition':definition,'bounded_plan':baseline}))
    def diff(before,after,path=''):
        if isinstance(before,dict) and isinstance(after,dict):
            for key in sorted(before.keys()|after.keys()):
                diff(before.get(key),after.get(key),path+'/'+key)
        elif before!=after:
            origin['modifications'].append({'path':path,'before':before,'after':after})
    diff(baseline,supplied)
    if not origin['modifications']:origin['kind']='known_template'
    return origin


def complete_operation_wiring(tasks):
    """Compile fixed operation metadata; never replace explicit type choices.

    Runs on the candidate copy before approval, not on frozen assignments.
    Declared file edges imply dependencies; additional review gates stay intact.
    """
    from orchestrator.execution import REGISTRY
    if not any(t.get('execution') or t.get('browser') for t in tasks):return
    def typed(item, media):
        if 'media_type' in item and item['media_type'] != media:
            raise ValueError('Conflicting media type for '+str(item.get('path'))+': expected '+media)
        item['media_type'] = media
    outputs = {(t['id'],o['path']):o for t in tasks for o in t['outputs']}
    for task in tasks:
        for path in task.get('browser',{}).get('screenshots',[]):
            for output,media in ((path,'image/png'),(path+'.json','application/json')):
                item=outputs.get((task['id'],output))
                if item is not None:typed(item,media)
        e = task.get('execution')
        if not e:continue
        spec = REGISTRY.get(e.get('capability'))
        if not spec or e.get('version') != spec['version']:continue
        for output in task['outputs']:
            media = spec.get('outputs',{}).get(output['path'])
            if spec.get('output_type'):media=spec['output_type']
            if media:typed(output,media)
        if e['capability'] in ('blender.scene','blender.mesh_scene','pptx.create') and not (
            e['capability']=='pptx.create' and any('artifact' in i and i.get('media_type')=='application/json' for i in task['inputs'])):
            scene_inputs = [i for i in task['inputs'] if 'from_task' in i and
                            (i.get('media_type')=='application/json' or
                             Path(i.get('output','')).suffix.lower()=='.json')]
            if len(scene_inputs) != 1:
                raise ValueError('Scene operation needs one unambiguous upstream scene JSON; mark its media_type application/json.')
            scene = scene_inputs[0]
            typed(scene,'application/json')
            source = outputs.get((scene['from_task'],scene['output']))
            if source is not None:typed(source,'application/json')
        # This is a fixed operation, with no agent tools. The runtime accounts for
        # one operation invocation; zero/agent-style tool counts are not its schema.
        tools = task['limits'].get('tool_calls')
        if type(tools) is int and 0 <= tools <= 60:
            task['limits']['tool_calls'] = 1
    for task in tasks:
        for item in task['inputs']:
            if 'from_task' not in item:continue
            source = outputs.get((item['from_task'],item.get('output')))
            if source is not None and source.get('media_type'):
                typed(item,source['media_type'])
            if item['from_task'] not in task['dependencies']:
                task['dependencies'].append(item['from_task'])


def bind_host_input_paths(tasks):
    """Assign consumer paths before approval; producer identities remain exact.

    delivery/ belongs to outputs in every host workspace. This only relocates
    declared input copies, never upstream output names, file bytes or parameters.
    Runtime validation still rejects invalid frozen assignments.
    """
    from orchestrator.execution import REGISTRY
    import unicodedata
    def key(path):return unicodedata.normalize('NFC',path).casefold()
    changes=[]
    for task in tasks:
        spec=REGISTRY.get(task.get('execution',{}).get('capability'),{})
        if not spec.get('outputs'):continue
        occupied={key(c.relative(i['path'])) for i in task['inputs']}
        occupied.update(key(c.relative(o['path'])) for o in task['outputs'])
        for item in task['inputs']:
            old=c.relative(item['path'])
            if old.split('/')[0]!='delivery':continue
            new='source-inputs/'+old
            canonical=key(new)
            if any(canonical==p or canonical.startswith(p+'/') or p.startswith(canonical+'/') for p in occupied):
                raise ValueError('Host input staging path conflicts with another declared file: '+new)
            item['path']=new;occupied.add(canonical)
            changes.append({'task':task['id'],'from':old,'to':new,
                            'source':{k:item[k] for k in ('artifact','from_task','output') if k in item}})
    return changes


def source_catalog(payload):
    return payload['sources']+payload.get('available_sources',[])


def compatible_implicit_source(capability, source):
    """Capability input types govern operation arguments, not workflow provenance."""
    import mimetypes
    from orchestrator.execution import REGISTRY
    if capability in ('images.collect','images.fetch'):return False  # Literal parameters are the operation input.
    allowed=REGISTRY[capability]['input_types']
    suffix=Path(source['path']).suffix.lower()
    media=source.get('media_type')
    if not media or media=='application/octet-stream':
        media={'.3dm':'application/vnd.rhino','.blend':'application/x-blender','.skp':'application/vnd.sketchup.skp','.rb':'text/x-ruby',
               '.py':'text/plain','.csv':'text/plain'}.get(suffix) or mimetypes.guess_type(source['path'])[0]
    # Existing plain-text context files (including JSON receipts) remain readable
    # context. Explicit JSON specs are bound separately by the declared operation.
    if suffix in ('.txt','.md','.json','.csv','.py','.rb') and 'text/plain' in allowed:return True
    return media in allowed


def validate_recovery_result(result, values):
    """Compile a fresh recovery proposal against current service-owned criteria.

    Historical assignments/receipts stay immutable. Only same-version registered
    criteria can refresh; all parameters, outputs, limits and scope still pass the
    full validator and the successor still needs its own delivered Start.
    """
    from orchestrator.execution import REGISTRY
    if not values.get('parent_id') or values.get('status')!='ready' or values.get('run'):
        raise ValueError('Criteria refresh requires a new, unstarted recovery proposal.')
    result=copy.deepcopy(result)
    updates=[]
    for task in result['plan']['tasks']:
        operation=task.get('execution')
        if not operation:continue
        spec=REGISTRY.get(operation.get('capability'))
        if not spec or operation.get('version')!=spec['version']:
            raise ValueError('The saved operation version is no longer supported. A new execution plan is required; nothing was dispatched.')
        if task.get('criteria')!=spec['criteria']:
            updates.append({'task':task['id'],'capability':operation['capability'],
                'version':operation['version'],'previous':copy.deepcopy(task.get('criteria')),
                'current':copy.deepcopy(spec['criteria'])})
            task['criteria']=copy.deepcopy(spec['criteria'])
    # A registered producer and its independent reviewer share the operation
    # criteria. Retain any additional reviewer requirements verbatim.
    for update in updates:
        update['reviewers']=[]
        for task in result['plan']['tasks']:
            if task.get('review_of')!=update['task']:continue
            previous=update['previous'];criteria=task.get('criteria',[])
            if not isinstance(previous,list) or criteria[:len(previous)]!=previous:
                raise ValueError('Saved reviewer criteria no longer match the operation. A new reviewed plan is required; nothing was dispatched.')
            task['criteria']=copy.deepcopy(update['current'])+criteria[len(previous):]
            update['reviewers'].append(task['id'])
    candidate=dict(values)
    if updates:
        payload=json.loads(candidate['context'])
        payload['registered_criteria_updates']=updates
        candidate.update(context=c.encoded(payload),context_hash=c.digest(payload))
    result,plan=validate_result(c.encoded(result),candidate,compiled=True)
    values.update(context=candidate['context'],context_hash=candidate['context_hash'])
    return result,plan


def validate_result(raw,row,*,compiled=False):
    from orchestrator.execution import REGISTRY
    if not isinstance(raw,str) or len(raw)>100000:raise ValueError('Planner response exceeds 100,000 characters.')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('Duplicate JSON key: '+k)
            result[k]=v
        return result
    result=json.loads(raw,object_pairs_hook=unique)
    payload=json.loads(row['context']);options=json.loads(row['options'])
    proposal,field_bindings=planning_contract.prepare(result,payload,options,compiled=compiled)
    builder_receipt=None;binding_receipts=[]
    if payload.get('artifact_binding_version') and not compiled:
        from .artifact_bindings import build as bind_artifacts
        proposal,binding_receipts=bind_artifacts(proposal,payload)
        if binding_receipts:result=copy.deepcopy(proposal)
    if payload.get('operation_builder') and not compiled and proposal.get('decision')=='ready':
        from .operation_builders import build
        result,builder_receipt=build(proposal,payload,options)
        proposal=copy.deepcopy(result)
    if not isinstance(result,dict) or set(result)-{'input_basis','geometry_basis','deferred_operations','deliverable_map'}!={'decision','message','plan'} or result['decision'] not in ('ready','needs_input','blocked'):
        raise ValueError('Invalid planning response envelope.')
    c.nonempty(result['message'],'planning message')
    if len(result['message'])>3000:raise ValueError('Planning message too long.')
    if result['decision']!='ready':
        if result['plan'] is not None:raise ValueError('An unresolved plan cannot include executable tasks.')
        return result,None
    supplied=proposal['plan']
    mixed=bool(options.get('step_capabilities'))
    max_tasks=options.get('max_tasks',6)
    if type(max_tasks) is not int or not 2<=max_tasks<=12:raise ValueError('Invalid saved planning task limit.')
    if not isinstance(supplied,dict) or set(supplied)!={'brief','tasks'} or not isinstance(supplied['tasks'],list) or not (2<=len(supplied['tasks'])<=max_tasks if mixed else len(supplied['tasks'])==2):
        raise ValueError('Use one producer/reviewer pair, or 2–'+str(max_tasks)+' tasks for a permitted mixed graph.')
    plan=copy.deepcopy(supplied);plan.update(id='production-'+str(row['request_id']),backend=options['backend'],concurrency=2)
    if not isinstance(plan['brief'],str) or not 1<=len(plan['brief'])<=1500:raise ValueError('Use a concise stage brief.')
    known={s['artifact']:s for s in source_catalog(payload)};used=set(payload['required_artifacts'])
    from . import geometry_sources
    geometry=geometry_sources.basis(result,payload,known)
    # Source geometry is required for both agents, including sources selected
    # from the available-artifact catalog instead of the initial routing action.
    required_artifacts=list(dict.fromkeys(payload['required_artifacts']+(geometry['artifacts'] if geometry else [])))
    used.update(required_artifacts)
    basis=result.get('input_basis')
    if payload.get('available_sources') or basis is not None:
        if not isinstance(basis,dict) or set(basis)!={'mode','artifacts'} or basis['mode'] not in ('new','modify_existing'):
            raise ValueError('Declare input_basis as new work or a modification with exact baseline artifacts; ask for missing sources before proposing workers.')
        ids=basis['artifacts']
        if not isinstance(ids,list) or len(ids)>10 or any(not isinstance(i,str) or i not in known for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Select distinct baseline artifacts from the captured source catalog.')
        if (basis['mode']=='new' and ids) or (basis['mode']=='modify_existing' and not ids):
            raise ValueError('A modification requires exact baseline artifacts; independent new work has none.')
    for task_index,task in enumerate(plan['tasks']):
        if not isinstance(task,dict):raise ValueError('Invalid task object.')
        unknown=set(task)-{'id','role','objective','instruction','inputs','outputs','dependencies','criteria','limits','max_attempts','review_of','user_gate','selection_outputs','tools','execution','browser','worker'}
        if unknown:
            hint=' Executor belongs inside worker; omit it when the executor is already locked.' if 'executor' in unknown else ''
            raise ValueError('$.plan.tasks['+str(task_index)+']: unsupported assignment fields: '+', '.join(sorted(unknown))+'.'+hint)
        registered='execution' in task
        if not registered and payload.get('response_contract') and 'worker' not in task:
            # Do not make the model repeat configuration to enter resolution.
            required=['files.text']+(['browser.use'] if task.get('browser') else [])
            task['worker']={'requires':required}
        if registered:
            if 'worker' in task:raise ValueError('Registered operations cannot carry agent workers.')
            e=task['execution']
            if not isinstance(e,dict) or e.get('capability') not in options.get('step_capabilities',[]):
                raise ValueError('This operation was not included in the planning scope.')
            if e['capability'] in ('gemini.text','gemini.image','openai.image','openrouter.image',*CLOUD_MEDIA):
                capability=next((x for x in payload.get('graph_operations',[]) if x['id']==e['capability']),None)
                if not capability or not isinstance(e.get('parameters'),dict) or e['parameters'].get('model')!=capability['configured_model']:
                    raise ValueError('Use the frozen configured model for this capability; no model fallback or invented availability.')
        for field,maximum in [('role',150),('objective',1500),('instruction',12000)]:
            if not isinstance(task.get(field),str) or not 1<=len(task[field])<=maximum:raise ValueError('Missing or oversized task '+field)
        if not isinstance(task.get('criteria'),list) or not 1<=len(task['criteria'])<=8 or any(not isinstance(x,str) or len(x)>500 for x in task['criteria']):
            raise ValueError('Use at most eight concise criteria.')
        if not isinstance(task.get('outputs'),list) or not 1<=len(task['outputs'])<=6:raise ValueError('Use at most six outputs per task.')
        if 'selection_outputs' in task and (not isinstance(task['selection_outputs'],list) or any(not isinstance(p,str) for p in task['selection_outputs'])):
            raise ValueError('selection_outputs must list exact declared output paths')
        if not isinstance(task.get('inputs',[]),list) or any(not isinstance(i,dict) for i in task.get('inputs',[])):
            raise ValueError('Inputs must be a list of artifact references.')
        for item in task.get('inputs',[]):
            if 'artifact' in item:
                if item['artifact'] not in known:raise ValueError('Unknown input artifact.')
                used.add(item['artifact'])
        declared_inputs=copy.deepcopy(task.get('inputs',[]))
        explicit_inputs={i['artifact'] for i in declared_inputs if 'artifact' in i}
        bound_artifacts=list(dict.fromkeys(required_artifacts+
            ([i['artifact'] for i in declared_inputs if 'artifact' in i] if registered else [])))
        task['inputs']=[i for i in task.get('inputs',[]) if i.get('artifact') not in bound_artifacts]
        for aid in bound_artifacts:
            source=known[aid]
            if (set(options.get('step_capabilities',[])) & {'media.compose','hyperframes.preview','hyperframes.render'} and not registered and aid not in explicit_inputs
                    and Path(source['path']).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.wav','.mp3','.mp4','.webm','.ttf','.otf','.woff','.woff2')):
                # Media bytes are operation arguments, not implicit model context.
                # Explicit requests to inspect an image retain their visual grant.
                continue
            browser_role=bool(task.get('browser') or 'browser.use' in task.get('worker',{}).get('requires',[]))
            if not registered and browser_role and aid not in explicit_inputs and not source.get('visual_reference'):
                # Stage-wide document contracts/bundles are not browser inputs.
                # Keep explicit source choices; only omit incompatible implicit
                # context which would demand Python or binary document tooling.
                from orchestrator.worker_capabilities import has_binary
                source_png=source.get('media_type')=='image/png' and Path(source['path']).suffix.lower()=='.png'
                if source.get('operation_support') or (has_binary({'inputs':[source]}) and not source_png):
                    continue
            if registered and aid not in explicit_inputs and not compatible_implicit_source(e['capability'],source):
                continue
            if registered and source.get('operation_support') in ('media.compose','hyperframes.preview','hyperframes.render','pptx.create','rhino3dm.create','rhino3dm.run_python','rhino.run_python','rhino.render','blender.run_python','blender.import_asset','blender.animate','sketchup.run_ruby'):
                continue
            item={k:source[k] for k in ('artifact','path','purpose','authority')}
            if source.get('media_type'):item['media_type']=source['media_type']
            if source.get('visual_reference') and not registered:item['visual_reference']=True
            if any(i.get('artifact')!=aid and i['path']==item['path'] for i in declared_inputs):
                item['path']='context/'+aid+'/'+item['path']
            if registered:
                if (e['capability'] in ('media.compose','hyperframes.preview','hyperframes.render','rhino3dm.create','rhino3dm.run_python','rhino.inspect','rhino.run_python','rhino.render','blender.inspect','blender.run_python','blender.import_asset','blender.animate','sketchup.inspect','sketchup.run_ruby')
                    and aid not in explicit_inputs):
                    # Historical inputs are context, even when their bytes equal
                    # a selected script/model. Bind native arguments explicitly;
                    # an inspector's upstream model must not acquire old versions.
                    if Path(source['path']).suffix.lower() not in ('.txt','.md','.json','.csv','.py','.rb'):continue
                    item['media_type']='text/plain';task['inputs'].append(item);continue
                asset_alias=next((i for i in declared_inputs if i.get('artifact')==aid and i.get('media_type') in ('application/octet-stream','image/png','image/jpeg')),None)
                if e['capability']=='hyperframes.preview' and Path(source['path']).suffix.lower() not in ('.txt','.md','.json','.csv'):
                    import mimetypes
                    item['media_type']=source.get('media_type') or mimetypes.guess_type(source['path'])[0]
                    if item['media_type']=='application/octet-stream':item['media_type']=mimetypes.guess_type(source['path'])[0]
                elif e['capability']=='hyperframes.render' and Path(source['path']).suffix.lower()=='.zip':
                    item['media_type']='application/zip'
                elif e['capability']=='rhino3dm.run_python' and asset_alias:
                    item['media_type']=asset_alias['media_type']
                elif e['capability'].startswith('sketchup.') and Path(source['path']).suffix.lower()=='.skp':
                    item['media_type']='application/vnd.sketchup.skp'
                elif e['capability'] in ('rhino.inspect','rhino.run_python','rhino.render','rhino3dm.run_python') and Path(source['path']).suffix.lower()=='.3dm' and source.get('media_type')!='application/octet-stream':
                    item['media_type']='application/vnd.rhino'
                elif e['capability'] in ('blender.inspect','blender.run_python','blender.import_asset','blender.animate') and Path(source['path']).suffix.lower()=='.blend':
                    item['media_type']='application/x-blender'
                elif e['capability']=='media.compose' and Path(source['path']).suffix.lower() in ('.wav','.mp3'):
                    item['media_type']='audio/wav' if Path(source['path']).suffix.lower()=='.wav' else 'audio/mpeg'
                elif e['capability'] in ('media.compose','hyperframes.preview','hyperframes.render','pptx.create','rhino3dm.create') and source['artifact'] in explicit_inputs and Path(source['path']).suffix.lower()=='.json':
                    item['media_type']='application/json'
                elif e['capability'] in ('media.compose','hyperframes.preview','hyperframes.render','pptx.create','blender.import_asset','gemini.image','openai.image','openrouter.image','runway.image','runway.video') and Path(source['path']).suffix.lower() in ('.png','.jpg','.jpeg','.webp'):
                    item['media_type']={'.png':'image/png','.webp':'image/webp'}.get(Path(source['path']).suffix.lower(),'image/jpeg')
                elif e['capability'] in ('blender.animate','pptx.create') and Path(source['path']).suffix.lower()=='.zip':
                    item['media_type']='application/zip'
                elif e['capability'] in ('blender.import_asset','blender.animate','rhino.render') and source['sha256']==e.get('parameters',{}).get('manifest_sha256'):
                    item['media_type']='application/json'
                elif e['capability'] in SCRIPT_OPERATIONS and source['sha256']==e.get('parameters',{}).get('script_sha256'):
                    item['media_type']=native_profile(e['capability']).script_media
                elif e['capability'] in SCRIPT_OPERATIONS and source['sha256']==e.get('parameters',{}).get('checks_sha256'):
                    item['media_type']='application/json'
                else:
                    if Path(source['path']).suffix.lower() not in ('.txt','.md','.json','.csv','.py','.rb'):
                        raise ValueError('Selected binary source is incompatible with this registered operation.')
                    item['media_type']='text/plain'
            aliases=[i for i in declared_inputs if i.get('artifact')==aid]
            if not registered or not aliases:task['inputs'].append(item)
            for alias in aliases:
                if not registered and alias['path']==item['path']:continue
                if alias.get('media_type') and item.get('media_type') and alias['media_type']!=item['media_type']:
                    raise ValueError('Declared input type differs from its exact source type.')
                task['inputs'].append({**item,'path':alias['path'],'purpose':alias['purpose']})
        if not registered and any(i.get('visual_reference') for i in task['inputs']):
            if 'worker' in task:
                task['worker']['requires']=list(dict.fromkeys(task['worker'].get('requires',[])+['images.view']))
            task['instruction']+='\nVisually inspect the exact visual_reference image files using image viewing tools. Caption, filename, dimensions and pixel statistics alone are not visual inspection. Distinguish visible proportions from inferred hidden geometry and scale; keep assumptions explicit.'
        task['instruction']='Read request/USER-REQUEST.txt first. Preserve its exact constraints and current user decisions.\n\n'+task['instruction']
        if not registered:
            prefix='operation-support/sketchup.run_ruby/'
            if prefix+'validate.py' in {s['path'] for s in payload['sources']}:
                task['instruction']+=('\nRead '+prefix+'contract.json and sketchup_contract.py for the frozen authoritative SketchUp contract. '
                    'Prepare UTF-8 model.rb and checks.json, at most 100000 script bytes. Validate with python3 '+prefix+
                    'validate.py CHECKS_JSON SCRIPT_RB. This validates JSON and script bounds, not Ruby syntax or geometry. '
                    'Use SketchUp Ruby API; model is Sketchup.active_model. Internal lengths are inches; checks are millimeters. '
                    'Select script and checks together for independent review. Do not launch SketchUp during preparation. '
                    'Exact approved Ruby executes later in sketchup.run_ruby; Relay saves/reopens the native candidate.')
            for capability in ('blender.run_python','blender.import_asset','blender.animate'):
                prefix='operation-support/'+capability+'/'
                if not {prefix+'contract.json',prefix+'validate.py'} <= {s['path'] for s in payload['sources']}:continue
                task['instruction']+=('\n\nRead '+prefix+'contract.json. Validate prepared/reviewed checks or manifest JSON with python3 '+
                    prefix+'validate.py PATH_TO_JSON. It requires only the Python standard library. '
                    'Do not launch Blender or execute host scripts in an agent preparation/review assignment.')
            for capability in ('rhino.run_python','rhino.render'):
                prefix='operation-support/'+capability+'/'
                if not {prefix+'contract.json',prefix+'rhino_contract.py',prefix+'validate.py'} <= {s['path'] for s in payload['sources']}:continue
                task['instruction']+=('\n\nRead '+prefix+'contract.json and rhino_contract.py for the frozen authoritative '
                    'Rhino contract. Validate prepared or reviewed checks/manifest JSON with python3 '+prefix+
                    'validate.py PATH_TO_JSON. This uses only the Python standard library; it does not '
                    'validate native geometry. Do not launch Rhino or execute model.py in this preparation/review '
                    'assignment. Exact host script execution and rendering require later approved stages.')
                if capability=='rhino.run_python':
                    task['instruction']+='\nHost scripts must be at most 100000 UTF-8 bytes. Run the validator with BOTH checks JSON and script paths: python3 '+prefix+'validate.py CHECKS_JSON SCRIPT_PY. For a flat drawing prepare a saved orthographic named view and preview.named_view.'
                    from orchestrator.rhino_contract import DESCRIPTION
                    task['instruction']+='\n'+DESCRIPTION['output_checks']+' '+DESCRIPTION['dimension_warnings']
        if not registered and not task.get('browser') and 'operation-support/rhino3dm.run_python/validate.py' in {s['path'] for s in payload['sources']}:
            task['instruction']+=('\n\nRead operation-support/rhino3dm.run_python/contract.json and rhino3dm_script_contract.py. '
                'Validate BOTH checks JSON and Python with its validate.py; choose explicit file_version (7 for Rhino 7). '
                'The script has the full installed rhino3dm API and receives model, rhino3dm, input_paths and workspace. '
                'Prepare/review only; do not execute this modeling script here. Select script/checks together before '
                'separate exact-code Start. The runtime is standalone CPython, never Rhino 7 IronPython or RhinoCommon.')
        if not registered and not task.get('browser') and 'operation-support/rhino3dm.create/validate.py' in {s['path'] for s in payload['sources']}:
            task['instruction']+=('\n\nRead operation-support/rhino3dm.create/contract.json and rhino3dm_contract.py. '
                'Validate prepared/reviewed geometry JSON using its validate.py. This is data-only preparation; '
                'never launch Rhino or execute user modeling scripts. Library generation is a separate registered '
                'operation; its reopen checks do not establish native Rhino verification or visual/source fidelity.')
        if not registered and not task.get('browser') and 'operation-support/pptx.create/validate.py' in {s['path'] for s in payload['sources']}:
            task['instruction']+=('\n\nUse the supplied operation-support/pptx.create/validate.py schema checker, '
                'the same implementation as the PPTX creator. Run it with the slide JSON path followed by '
                'the exact declared image paths used in that JSON. In an isolated Python worker, execute '
                'the supplied validator module with runpy and call validate(load(text), image_paths). '
                'Do not invent another schema validator or launch a presentation application. '
                'Keep simple requests concise; make targeted corrections to prior candidates. '
                'Distinguish measured layout failures from assumptions; record uncertain fit estimates '
                'for review of the actual deck rather than presenting them as observed clipping.')
        if payload.get('previous_stage'):
            task['instruction']='Read previous-stage/CONTEXT.json and the exact selected outputs. Preserve prior relevant user constraints; the latest explicit request controls this stage.\n\n'+task['instruction']
        if type(task.get('max_attempts')) is not int or not 1<=task['max_attempts']<=options.get('max_attempts',1):
            raise ValueError('Planner exceeds the frozen attempt allowance.')
        if (registered or task.get('browser')) and task['max_attempts']!=1:
            raise ValueError('Registered operations and browser work permit one attempt.')
        task_limits=dict(options['limits'])
        if registered:
            # The default agent's file allowance is not the registered builder's
            # output contract. Both the saved and installed operation bound apply.
            frozen_operation=next((x for x in payload.get('graph_operations',[]) if x['id']==e['capability']),None)
            if frozen_operation:
                from orchestrator.handoff_contracts import operation
                task_limits['output_bytes']=operation(e['capability'],frozen_operation)['output_bytes']
        for key,maximum in task_limits.items():
            value=task.get('limits',{}).get(key)
            if type(value) is not int or not (0 if registered and key=='tool_calls' else 1)<=value<=maximum:
                raise ValueError(f"{task['id']}: planned {key}={value!r} exceeds or violates its frozen limit {maximum}.")
    complete_operation_wiring(plan['tasks'])
    input_path_bindings=bind_host_input_paths(plan['tasks'])
    from . import presentation_inputs
    presentation_inputs.bind(plan['tasks'])
    selected_operations=set(options.get('step_capabilities',[]))
    actual_operations={t.get('execution',{}).get('capability') for t in plan['tasks']}
    deferred=result.get('deferred_operations',{})
    if not isinstance(deferred,dict) or set(deferred)-selected_operations or set(deferred)&actual_operations:
        raise ValueError('Deferred operations must be selected, absent operations.')
    if deferred:
        from orchestrator.execution import REGISTRY
        if not any(REGISTRY.get(capability,{}).get('requires_registered_inputs') for capability in deferred):
            raise ValueError('Host deferral requires an exact-input operation awaiting prepared registered inputs.')
        for capability,reason in deferred.items():
            if (REGISTRY.get(capability,{}).get('kind')!='host' and capability!='hyperframes.render') or not isinstance(reason,str) or not 1<=len(reason)<=500:
                raise ValueError('Only selected host operations can share the deferred execution phase, each with an explicit preparation reason.')
        prepared=[t for t in plan['tasks'] if not t.get('execution') and not t.get('review_of') and t.get('user_gate') and t.get('selection_outputs')]
        if set(deferred)=={'hyperframes.render'}:
            prepared += [t for t in plan['tasks'] if t.get('execution',{}).get('capability')=='hyperframes.preview' and t.get('user_gate')
                         and set(t.get('selection_outputs',[]))==set(REGISTRY['hyperframes.preview']['outputs'])]
        if not prepared:raise ValueError('A deferral requires a gated preparation task with selected outputs.')
    missing_operations=selected_operations-actual_operations-set(deferred)
    if missing_operations:
        raise ValueError('The plan omitted selected operations: '+', '.join(sorted(missing_operations))+'. Include their steps or explicitly declare a preparation-only deferral; no outcome may disappear.')
    requested_deliverables=options.get('deliverables',{})
    coverage=result.get('deliverable_map',{})
    if not isinstance(coverage,dict) or set(coverage)!=set(requested_deliverables):
        raise ValueError('Map every requested deliverable exactly once; a deliverable cannot disappear.')
    for ident,binding in coverage.items():
        if isinstance(binding,dict) and set(binding)=={'deferred_operation'} and binding['deferred_operation'] in deferred:continue
        if not isinstance(binding,dict) or set(binding)!={'task','output'}:
            raise ValueError('Each deliverable must name a producing task/output or an explicitly deferred operation.')
        producer=next((t for t in plan['tasks'] if t['id']==binding['task'] and not t.get('review_of')),None)
        if not producer or not any(o['path']==binding['output'] for o in producer['outputs']):
            raise ValueError('A deliverable must resolve to an actual declared producer output.')
        if not any(r.get('review_of')==producer['id'] and any(i.get('from_task')==producer['id'] and i.get('output')==binding['output'] for i in r['inputs']) for r in plan['tasks']):
            raise ValueError('Every declared deliverable needs independent review of its exact output.')
    if coverage:plan['deliverables']={ident:{'description':requested_deliverables[ident],**binding} for ident,binding in coverage.items()}
    if deferred:
        plan['deferred_operations']=dict(deferred)
        plan['brief']+=' [Preparation only; pending: '+', '.join(sorted(deferred))+']'
    for host in plan['tasks']:
        capability=host.get('execution',{}).get('capability')
        if capability not in ('blender.scene','blender.mesh_scene'):continue
        prefix='operation-support/'+capability+'/'
        # Only advertise support actually frozen for this plan, including on
        # revisions. Old assignments are never repaired by changing their prompt.
        if not {prefix+'contract.json',prefix+'validate_scene.py'} <= {s['path'] for s in payload['sources']}:continue
        scene_input=next(i for i in host['inputs'] if i.get('media_type')=='application/json')
        producer_id=scene_input.get('from_task')
        for task in plan['tasks']:
            if task['id']!=producer_id and task.get('review_of')!=producer_id:continue
            candidate=scene_input['output'] if task['id']==producer_id else next(
                (i['path'] for i in task['inputs'] if i.get('from_task')==producer_id and i.get('output')==scene_input['output']),scene_input['output'])
            task['instruction']=('This is scene-data preparation/review only. Read '+prefix+'contract.json. '
                'Validate the scene JSON with the standalone Python script '+prefix+'validate_scene.py, '
                'passing '+candidate+' as its file argument. It needs only the Python standard library. '
                'Do not launch/probe Blender or look for an installed Relay executor. Relay runs the separate '
                'registered '+capability+' task '+host['id']+' after its dependencies are satisfied. '
                'A previous worker-shell startup failure is not a blocker for producing or validating this JSON.\n\n'+task['instruction'])
    producers=[t for t in plan['tasks'] if not t.get('review_of') and not t.get('execution')]
    if basis and basis['mode']=='modify_existing':
        production_inputs={i.get('artifact') for t in plan['tasks'] if not t.get('review_of') for i in t['inputs']}
        if not set(basis['artifacts']) <= production_inputs:
            raise ValueError('Every declared baseline must be an input to the producing step; conversation alone is insufficient.')
    reviewers=[t for t in plan['tasks'] if t.get('review_of')]
    for producer in producers:
        prepared=[o['path'] for o in producer['outputs'] if Path(o['path']).suffix.lower() in ('.py','.rb','.json')]
        if (set(options.get('step_capabilities',[])) & set(SCRIPT_OPERATIONS)
            and any(p.endswith(('.py','.rb')) for p in prepared) and any(p.endswith('.json') for p in prepared)
            and not set(prepared)<=set(producer.get('selection_outputs',[]))):
            raise ValueError('Host script preparation requires selection_outputs containing its script and checks together')
        for path in producer.get('selection_outputs',[]):
            if not any(i.get('from_task')==producer['id'] and i.get('output')==path
                       for r in reviewers if r['review_of']==producer['id'] for i in r['inputs']):
                raise ValueError('Every member of a selection set needs independent review')
    if (not producers and not any(REGISTRY.get(t.get('execution',{}).get('capability'),{}).get('kind')=='procedure' or t.get('execution',{}).get('capability') in ('pptx.create','gemini.image','openai.image','openrouter.image',*CLOUD_MEDIA,'blender.startup','blender.inspect','blender.run_python','blender.import_asset','blender.animate','rhino.startup','rhino.inspect','rhino.run_python','rhino.render','rhino3dm.run_python','sketchup.startup','sketchup.inspect','sketchup.run_ruby') for t in plan['tasks'])) or (not mixed and (len(producers)!=1 or len(reviewers)!=1)) or any(not any(r['review_of']==p['id'] for r in reviewers) for p in producers):
        raise ValueError('An independent reviewer is required for every agent producer.')
    # Independent verification needs the same source versions as production.
    for review in reviewers:
        producer=next((p for p in plan['tasks'] if p['id']==review['review_of']),None)
        if not producer:raise ValueError('Reviewer target does not exist.')
        existing={i.get('artifact') for i in review['inputs']}
        for item in producer['inputs']:
            if 'artifact' in item and item['artifact'] not in existing:
                review['inputs'].append(copy.deepcopy(item));existing.add(item['artifact'])
            elif ('from_task' in item and producer.get('execution',{}).get('capability') in ('pptx.create','gemini.image','openai.image','openrouter.image',*CLOUD_MEDIA)
                  and not any(i.get('from_task')==item['from_task'] and i.get('output')==item['output'] for i in review['inputs'])):
                source=copy.deepcopy(item)
                source['path']='source-inputs/'+producer['id']+'/'+item['path']
                review['inputs'].append(source)
                if item['from_task'] not in review['dependencies']:review['dependencies'].append(item['from_task'])
    for operation in plan['tasks']:
        if not operation.get('execution'):continue
        ceiling=REGISTRY[operation['execution']['capability']]['input_bytes']
        total=sum(known[i['artifact']]['bytes'] for i in operation['inputs'] if 'artifact' in i)
        if total>ceiling:
            raise ValueError(f"{operation['id']}: selected operation inputs total {total} bytes, exceeding {ceiling}; select only required inputs before Start.")
    if sum(known[aid]['bytes'] for aid in used)>MAX_INPUT_BYTES:raise ValueError('Selected inputs exceed 150 MB; select a smaller source set.')
    pipeline_stage=payload.get('pipeline_step')
    geometry_sources.bind(plan['tasks'],geometry,known)
    if pipeline_stage and not deferred:
        targets={}
        for binding in coverage.values():
            if 'task' in binding:targets.setdefault(binding['task'],set()).add(binding['output'])
        for task in plan['tasks']:
            if task.get('review_of'):continue
            if pipeline_stage['gate']=='selection' and task['id'] in targets:
                task['user_gate']='User selects the declared outputs for '+pipeline_stage['id']
                if len(targets[task['id']])>1:task['selection_outputs']=sorted(targets[task['id']])
                else:task.pop('selection_outputs',None)
            elif pipeline_stage['gate']=='none' and task.get('user_gate'):
                raise ValueError('This automatic workflow stage has no user selection gate; retain independent review without inventing acceptance.')
    from orchestrator import worker_capabilities
    from orchestrator import executors
    for task in plan['tasks']:
        if 'worker' in task:
            if 'worker_catalog' not in options:raise ValueError('This saved planning scope has no dynamic worker catalog.')
            worker_capabilities.resolve(task,options['worker_catalog'],options['backend'])
            chosen=task['worker']['backend']
            if chosen['type'] in executors.API_TYPES:
                # Composition may choose a narrower profile than the default.
                # Freeze its smaller bounds in the proposed plan, never expand
                # the model's requested limits or fail over to a shell for them.
                for key,limit in executors.limits_for(chosen).items():
                    task['limits'][key]=min(task['limits'][key],limit)
        if not task.get('execution') and not task.get('browser'):
            task['max_attempts']=options.get('max_attempts',1)
        if not task.get('execution') and 'worker_catalog' in options:
            if worker_capabilities.backend_for(task,options['backend'])['type'] in executors.API_TYPES:
                chosen=worker_capabilities.backend_for(task,options['backend'])
                supported_capture=chosen['type'] in executors.BROWSER_TYPES and worker_capabilities.matches(task,['browser.use'],chosen)
                if worker_capabilities.has_binary(task) and not supported_capture and chosen['type'] not in executors.CODE_TYPES:raise ValueError('Resolved API worker requires text or explicitly supported browser PNG files; other binary files need a compatible executor.')
                executors.validate_input_sizes([{**known[i['artifact']],**i} for i in task['inputs'] if 'artifact' in i],chosen)
    for task in plan['tasks']:
        if (not task.get('execution') and any(i.get('visual_reference') for i in task.get('inputs',[]))
            and 'images.view' not in worker_capabilities.abilities(worker_capabilities.backend_for(task,options['backend']))):
            raise ValueError('Selected image references require a worker that can inspect pixels (images.view); binary file access alone is insufficient.')
        executors.code_budgets(task,worker_capabilities.backend_for(task,options['backend']),options.get('response_budgets',False))
    if options.get('local_corrections') is True and options.get('max_attempts',1)>=2:
        from orchestrator.corrections import compile as compile_corrections
        compile_corrections(plan['tasks'])
    from orchestrator.handoff_contracts import bind_stage
    bind_stage(payload.get('pipeline_step'),plan,payload.get('handoff_sources',[]),source_catalog(payload))
    plan=c.plan(plan)
    for task in plan['tasks']:
        if task.get('execution',{}).get('capability') in ('images.collect','images.fetch'):
            if not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('Image sourcing needs independent review of subject coverage and candidate identity.')
        if task.get('execution',{}).get('capability') in ('hyperframes.preview','hyperframes.render'):
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('HyperFrames execution needs independent delivery review and human visual selection')
            if task['execution']['capability']=='hyperframes.preview':
                if set(task.get('selection_outputs',[]))!=set(REGISTRY['hyperframes.preview']['outputs']):
                    raise ValueError('Preview selection must preserve the complete source/project/frame/receipt set')
                manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
                if 'from_task' in manifest and not any(r['review_of']==manifest['from_task'] and r['id'] in task['dependencies'] for r in reviewers):
                    raise ValueError('HyperFrames preview must depend on independent review of its source project')
            else:
                for media,key in (('application/zip','project_sha256'),('application/json','preview_sha256')):
                    item=next(i for i in task['inputs'] if i['media_type']==media)
                    if known[item['artifact']]['sha256']!=task['execution']['parameters'][key]:raise ValueError('Render parameters must match the captured exact preview artifact hashes')
        if task.get('execution',{}).get('capability')=='media.compose':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('Reel composition requires independent delivery review and a human visual selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if 'from_task' in manifest and not any(r['review_of']==manifest['from_task'] and r['id'] in task['dependencies'] for r in reviewers):
                raise ValueError('Reel composition must depend on independent review of its scene specification')
        if task.get('execution',{}).get('capability')=='rhino3dm.create':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('Standalone 3DM creation needs independent output review and a candidate selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if 'from_task' in manifest and not any(r['review_of']==manifest['from_task'] and r['id'] in task['dependencies'] for r in reviewers):
                raise ValueError('Standalone 3DM creation must depend on independent review of its geometry specification')
        if task.get('execution',{}).get('capability')=='pptx.create':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] and any(
                i.get('from_task')==task['id'] and i.get('output')==task['outputs'][0]['path'] for i in r['inputs']) for r in reviewers):
                raise ValueError('PPTX creation needs independent review of the actual deck and a candidate selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if 'from_task' in manifest and not any(r['review_of']==manifest['from_task'] and r['id'] in task['dependencies'] for r in reviewers):
                raise ValueError('PPTX creation must depend on independent review of its slide specification')
        if task.get('execution',{}).get('capability') in ('gemini.image','openai.image','openrouter.image',*CLOUD_MEDIA):
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('Media generation needs independent review and a candidate selection gate')
        if task.get('execution',{}).get('capability')=='rhino.render':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):raise ValueError('Rhino render needs independent review and a candidate selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if known[manifest['artifact']]['sha256']!=task['execution']['parameters']['manifest_sha256']:raise ValueError('Rhino render manifest hash differs from selected artifact')
        if task.get('execution',{}).get('capability')=='blender.animate':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):raise ValueError('Animation needs independent review and a candidate selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if known[manifest['artifact']]['sha256']!=task['execution']['parameters']['manifest_sha256']:raise ValueError('Animation manifest hash does not match the selected version')
        if task.get('execution',{}).get('capability')=='blender.import_asset':
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):raise ValueError('Asset import needs independent review and a candidate selection gate')
            manifest=next(i for i in task['inputs'] if i['media_type']=='application/json')
            if known[manifest['artifact']]['sha256']!=task['execution']['parameters']['manifest_sha256']:raise ValueError('Asset manifest hash does not match the selected version')
        if task.get('execution',{}).get('capability') in SCRIPT_OPERATIONS:
            if not task.get('user_gate') or not any(r['review_of']==task['id'] for r in reviewers):
                raise ValueError('Host script requires independent output review and a candidate selection gate')
            adapter=native_profile(task['execution']['capability']);native=adapter.media
            for media,key in ((native,'scene_sha256'),(adapter.script_media,'script_sha256'),('application/json','checks_sha256')):
                if adapter.new_model and key=='scene_sha256' and task['execution']['parameters'][key] is None:continue
                item=next(i for i in task['inputs'] if i['media_type']==media)
                if known[item['artifact']]['sha256']!=task['execution']['parameters'][key]:raise ValueError('Proposed host code/input hash differs from its selected artifact')
    if not any(a.get('review_of') for a in plan['tasks']):raise ValueError('An independent reviewer is required.')
    plan['origin']=plan_origin(payload,supplied,row['request_id'])
    if builder_receipt:plan['origin']['operation_builder']=builder_receipt
    if binding_receipts:plan['origin']['artifact_bindings']=dict(version=1,tasks=binding_receipts)
    if field_bindings:plan['origin']['planner_field_bindings']=field_bindings
    if geometry:plan['origin']['geometry_basis']=geometry
    if input_path_bindings:plan['origin']['input_path_bindings']=input_path_bindings
    return result,plan


def notice(state,row,key,text):
    event='planner:'+row['id']+':'+key
    state.db.execute('INSERT OR IGNORE INTO outbox(id,text) VALUES (?,?)',(event,text))
    state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)',(event,row['channel']))
    return event


def attach_host_code(state,row,event,rt):
    from orchestrator import host_code
    repair=json.loads(row['context']).get('execution_recovery',{}).get('reviewed_repair')
    if repair:
        for key in ('diagnosis','review'):
            entry=repair['artifacts'][key];verify_artifact(rt,entry);artifact=rt.artifact(entry['artifact'])
            state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                (event+':repair-'+key,event,artifact['blob'],Path(entry['path']).name,'original',
                 'Reviewed repair '+key+' · SHA-256 '+entry['sha256']))
    for task in json.loads(row['plan'])['tasks']:
        if task.get('execution',{}).get('capability')=='blender.import_asset':
            from orchestrator.blender_assets import bind_registered
            bind_registered(rt,task)
            item=next(i for i in task['inputs'] if i['media_type']=='application/json');artifact=rt.artifact(item['artifact'])
            state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                (event+':asset-manifest:'+task['id'],event,artifact['blob'],task['id']+'-assets.json','original','Exact assets, paths, import modes and supplied provenance · SHA-256 '+artifact['sha256']))
        if task.get('execution',{}).get('capability')=='rhino.render':
            from orchestrator.rhino_render import bind_registered
            bind_registered(rt,task)
            item=next(i for i in task['inputs'] if i['media_type']=='application/json');artifact=rt.artifact(item['artifact'])
            state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                (event+':rhino-render-manifest:'+task['id'],event,artifact['blob'],task['id']+'-render.json','original','Exact Rhino renderer, named view and image resolution · SHA-256 '+artifact['sha256']))
        if task.get('execution',{}).get('capability')=='blender.animate':
            from orchestrator.blender_animation import bind_registered
            bind_registered(rt,task)
            item=next(i for i in task['inputs'] if i['media_type']=='application/json');artifact=rt.artifact(item['artifact'])
            state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                (event+':animation-manifest:'+task['id'],event,artifact['blob'],task['id']+'-animation.json','original','Exact frame range, quality, camera and transform tracks · SHA-256 '+artifact['sha256']))
        if not host_code.required(task):continue
        # Validate concrete code/checks before presenting an executable host card.
        host_code.binding(rt,task)
        adapter=native_profile(task['execution']['capability'])
        for media,suffix,filename in ((adapter.script_media,'script','edit'+adapter.script_suffix),('application/json','checks','edit-checks.json')):
            item=next(i for i in task['inputs'] if i['media_type']==media)
            artifact=rt.artifact(item['artifact'])
            state.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                (event+':host-'+suffix+':'+task['id'],event,artifact['blob'],task['id']+'-'+filename,'original',
                 'Exact host '+suffix+' for approval · SHA-256 '+artifact['sha256']))


def preview(row):
    from orchestrator import executors
    plan=json.loads(row['plan']);options=json.loads(row['options'])
    lines=['Proposed production: '+plan['brief'], 'Planning only.' if options['planning_only'] else 'Ready for your approval; no workers have started.']
    payload=json.loads(row['context'])
    geometry=plan.get('origin',{}).get('geometry_basis')
    if geometry:
        lines.append('Geometry basis: '+geometry['mode'])
        if geometry['checks']:
            lines.append('Proposed source error limits: '+', '.join(
                str(x['metric'])+' ≤ '+str(x['tolerance'])+' '+x['unit'] for x in geometry['checks']))
            lines.append('Preparation audits source use. Native output acceptance additionally requires measured source comparisons; unavailable measurements block review.')
    if payload.get('starter_workflow'):
        starter=payload['starter_workflow']
        lines.append('Starter: '+starter['definition']['id']+' v'+str(starter['definition']['version'])+
            ' · stage '+starter['stage']+' · '+starter['sha256'][:12]+'\nLater stages are not authorized by this plan.')
    for ident,binding in json.loads(row['result'] or '{}').get('deliverable_map',{}).items():
        target=('pending '+binding['deferred_operation']) if 'deferred_operation' in binding else binding['task']+' / '+binding['output']
        lines.append('Deliverable: '+options['deliverables'][ident]+' → '+target)
    for capability,reason in json.loads(row['result'] or '{}').get('deferred_operations',{}).items():
        lines.append('Not executed by this stage: '+capability+' — '+reason+' Separate approval required after preparation.')
    dynamic=any(t.get('worker') for t in plan['tasks'])
    lines.append(('Default executor: ' if dynamic else 'Executor: ')+c.encoded(plan['backend']))
    if dynamic:
        from orchestrator.worker_capabilities import needs_approval
        if needs_approval(plan):lines.append('This plan includes a different worker backend. Use Start to approve the displayed worker models and transfers; the workflow will not switch automatically.')
    if plan['backend']['type'] in executors.FILE_TYPES:
        lines.append('File tools only: declared UTF-8 inputs and text outputs. External transfer: assignment and read text go to '+executors.provider_for(plan['backend'])+'. Per worker: at most 8 API requests, 4096 output tokens per request, 512 KB inputs. Cancellation stops local work; an accepted remote request cannot be undone. Unknown cost stays unknown.')
    code_profiles=[plan['backend'],*(t['worker']['backend'] for t in plan['tasks'] if t.get('worker'))]
    if any(b['type'] in executors.CODE_TYPES for b in code_profiles):
        lines.append('Native Python code: exact input copies and declared outputs, no network or subprocesses. Up to 120 seconds per call within task limits; 100 MB input/output ceiling. Binary files stay local; code logs and extracted text can go to the selected provider. No package installation or native app access. Document checks do not certify visual layout or application import compatibility.')
    if plan['backend']['type'] in ('gemini-browser','openai-browser','qwen-browser'):
        lines.append('Browser and declared text file tools, plus explicitly granted viewport PNG captures and provenance. PNG reads return metadata only; pixels are not sent to the model and visual review remains separate. External transfer: instructions, read text, page observations and capture metadata go to the selected provider. Up to 10 MB outputs and 10 MB PNG inputs; 512 KB text inputs, 8 API requests, 4096 output tokens per request. Dedicated sessions; no shell or credential tools. Site/action scope is shown below. Cancellation cannot undo website actions; uncertain actions are never replayed.')
    if payload.get('previous_stage'):
        lines.append('Next stage after: '+payload['previous_stage']['run']+'; exact recorded selections and prior instructions are included.')
    if payload.get('review_correction_origin'):
        origin=payload['review_correction_origin']
        lines.append('Correction preparation for '+origin['run']+'. Existing files and receipts stay unchanged. This Start approves script/checks preparation and independent review only; native execution needs a separate exact-code Start.')
    if payload.get('registered_criteria_updates'):
        lines.append('Operation completion criteria refreshed for this app version. Historical receipts are unchanged; Start approves this new proposal.')
    if payload.get('execution_recovery'):
        recovery=payload['execution_recovery']
        lines.append('Repair of failed execution: '+recovery['baseline']['run']+'. Original attempts and files remain preserved.')
        if recovery.get('script_replacement'):lines.append('Script SHA-256: '+recovery['script_replacement']['sha256']+'. Start approves the new execution assignment.')
        elif recovery.get('kind')=='review_revision':lines.append('Correct the saved draft and repeat its independent review; downstream work has not started. No original attempts are reset.')
        elif recovery.get('kind')=='code_budget':lines.append('New bounded preparation with draft checkpoints and exact creator asset bindings. Completed work is retained; original attempts are not reset. Provider request limits are unchanged.')
        else:lines.append('Local operation input repair; completed preparation and exact source bytes are retained.')
        if recovery.get('runtime_changes'):lines.append('Implementation repair; script bytes unchanged. Updated: '+', '.join(sorted(recovery['runtime_changes'])))
        if recovery.get('assessment'):
            lines.append('Recovery: '+recovery['assessment']['reason']+' Exact inputs and limits are retained; a fresh Start is required.')
        # Previously saved proposals remain readable without rewriting history.
        if recovery.get('no_launch_receipt') or recovery.get('startup_failure_receipt'):
            lines.append('The prior attempt stopped before modeling. Exact script/checks are retained; a fresh Start is required.')
        if recovery.get('reviewed_repair'):
            diagnosis=recovery['reviewed_repair']['diagnosis']
            lines.extend(['Diagnosis: '+diagnosis['cause'][:600], 'Proposed correction: '+diagnosis['changes'][:600],
                          'Independent review passed. Attached diagnosis, review, script and unchanged checks define this Start.'])
        if recovery['reused_completed_tasks']:lines.append('Already completed; not repeated: '+', '.join(recovery['reused_completed_tasks']))
    for task in plan['tasks']:
        if task.get('review_correction'):
            lines.append('Automatic local correction: '+task['review_correction']['producer']+' can correct its draft once after specification review and once after deck failure/review. Re-review each version; build the deck at most twice. Per-attempt limits below apply to every attempt. No browser, host-app or external API operation is replayed.')
    used={i['artifact'] for t in plan['tasks'] for i in t['inputs'] if 'artifact' in i}
    selected=[s for s in source_catalog(payload) if s['artifact'] in used]
    lines += ['Project: '+(payload['project'] or 'Isolated production workspace'),
              'Inputs: '+', '.join(s['path'] for s in selected[:12])]
    if len(selected)>12:lines.append(f'{len(selected)-12} more inputs listed in the attached source manifest.')
    for task in plan['tasks']:
        if task.get('worker'):
            from orchestrator.worker_capabilities import entry
            binding=task['worker'];profile=entry(binding['backend'])
            lines.append('Worker '+task['id']+': '+c.encoded(binding['backend'])+' · requires '+', '.join(binding['requires'])+' · tools '+', '.join(profile['tools']))
            if binding['backend']['type'] in executors.API_TYPES:
                lines.append('External transfer: assignment and read text go to this worker provider; browser workers also send page observations, Python workers send code logs and extracted text. At most 8 API requests and 4096 output tokens per request. No shell; unknown costs remain unknown.')
        if task.get('browser'):lines.append('Browser scope for '+task['id']+': '+c.encoded(task['browser']))
        if task.get('execution'):
            e=task['execution']
            lines.append('Operation: '+e['capability']+' v'+str(e['version'])+' · '+c.encoded(e['parameters']))
            if e['capability'] in CLOUD_MEDIA:
                lines.append('External generation: the displayed prompt and supported image inputs go to '+e['capability'].split('.')[0]+'. One generation request; status polling and local output download. Provider credits may be charged. Stopping local waiting does not cancel remote work; uncertain submissions are never repeated.')
            if e['capability']=='blender.inspect':
                lines.append('Host inspection: open the exact selected .blend with embedded auto-execution disabled. Linked libraries may resolve on the host. No editing, rendering or asset import.')
            if e['capability'] in SCRIPT_OPERATIONS:
                lines.append('HOST CODE: Start authorizes the attached exact script with normal host filesystem and network access. No OS isolation is enforced. Scene/scripts/checks hashes and limits are fixed; changes require a new approval. Candidate output is not automatically selected.')
            if e['capability']=='rhino3dm.run_python':
                lines.append('Standalone rhino3dm Python, not a Rhino application. Full installed library API; target .3dm file version is fixed in the attached checks (7 means Rhino 7). Verification reopens with the library, not native Rhino.')
            if e['capability'].startswith('sketchup.'):
                lines.append('SketchUp 2025/2026 on macOS: owned desktop process, normal host permissions. Existing user sessions are not attached. Ruby modeling requires exact source/checks approval; the saved candidate is reopened and checked independently. No implicit selection.')
            if e['capability'].startswith('rhino.'):
                lines.append('Direct Rhino 7/8 on macOS: owned process or separate documents in connected Rhino 8, IronPython 2.7 on 7 or CPython 3 on 8, and RhinoCommon. Modeling creates a new .3dm candidate with independent reopen checks and a viewport preview. Startup/inspection use fixed code. Grasshopper is paused.')
            if e['capability']=='blender.import_asset':
                lines.append('Host asset import: append named meshes and pack selected image files using the attached exact manifest. Normal OS permissions; embedded scripts disabled. No downloads or persistent links. Candidate and retained source bundle remain unselected.')
            if e['capability']=='blender.animate':
                lines.append('Host animation/render: Start approves the attached exact frames, FPS, quality and numeric tracks. Blender and ffmpeg use normal host permissions. Checkpoints reuse verified completed frames; unresolved frame intents block. No automatic final render or candidate selection.')
            if e['capability'] in ('blender.startup','blender.scene','blender.mesh_scene'):
                lines.append('Host execution: Blender runs with normal OS permissions using fixed Relay code and validated data. No arbitrary scripts or agent shell escalation.')
            if e['capability']=='gemini.text':lines.append('External transfer: listed text inputs and instructions go to Gemini in one API request. Local cancellation cannot undo an accepted remote request; unknown cost remains unknown.')
            if e['capability']=='images.fetch':lines.append('Image downloads: public HTTPS images from the declared observed-source manifest. Source URLs and unknown rights are retained for review; no search API or generated image.')
            if e['capability']=='images.collect':lines.append('Image sourcing: only the displayed literal subject queries go to public Wikimedia Commons. No credentials or image generation model; exact downloads, source credits and missing matches are retained for review.')
            if e['capability']=='gemini.image':lines.append('External transfer: listed images, text and instructions go to the exact displayed image model in one API request. Cancellation cannot undo accepted work; uncertain submissions are never replayed.')
            if e['capability']=='openrouter.image':lines.append('External transfer: listed images, text and instructions go through OpenRouter to the selected model in one image request; provider fallbacks are disabled. Uncertain submissions are never replayed.')
            if e['capability']=='openai.image':lines.append('External transfer: listed images, text and instructions go to OpenAI in one image API request. Cancellation cannot undo accepted work; uncertain submissions are never replayed.')
        lines += ['\n'+task['role']+': '+task['objective'], 'Outputs: '+', '.join(o['path'] for o in task['outputs']),
                  'Checks: '+'; '.join(task['criteria']),f"Limits: {task['limits']['seconds']} seconds, {task['limits'].get('provider_requests',8)} provider requests (API workers), {task['limits']['tool_calls']} tool calls per attempt, {task['max_attempts']} attempt(s)."]
        if 'response_tokens' in task['limits']:
            lines.append(f"Response allowance: up to {task['limits']['response_tokens']:,} output tokens per provider response. Larger responses can consume more tokens; this is a ceiling, not estimated usage.")
        if task.get('user_gate'):lines.append('Next user decision: '+task['user_gate'])
        if task.get('selection_outputs'):lines.append('Select together: '+' + '.join(task['selection_outputs']))
    lines.append('\nInputs include your exact request, selected guides and named source versions. '+
                 ('Ask to execute this saved plan when ready.' if options['planning_only'] else 'Start approves this exact stage only.'))
    return '\n'.join(lines)


def publish_ready_files(s,current,event,rt,plan,payload):
    row=current
    attach_host_code(s,current,event,rt)
    # A rolled-back transaction may leave immutable files behind. Name each
    # prepared version by content so retrying never overwrites an earlier one.
    path=s.media_dir.parent/'production-planning'/row['id']/c.digest(plan)/'plan.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    def write_once(path,value):
        data=json.dumps(value,ensure_ascii=False,indent=2)
        if path.is_symlink():raise ValueError('Linked planning document is not allowed.')
        if path.exists():
            if path.read_text()!=data:raise ValueError('Immutable planning document changed.')
        else:
            with path.open('x') as stream:stream.write(data)
            path.chmod(0o400)
    write_once(path,plan)
    s.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                 (event+':file',event,str(path),'plan.json','original','Complete proposed plan; not started'))
    manifest=path.with_name('sources.json')
    used={i['artifact'] for t in plan['tasks'] for i in t['inputs'] if 'artifact' in i}
    write_once(manifest,[s for s in source_catalog(payload) if s['artifact'] in used])
    s.db.execute('INSERT OR IGNORE INTO media_outbox(id,event_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?)',
                 (event+':sources',event,str(manifest),'sources.json','original','Selected input versions, purposes and SHA-256 hashes'))


def rate_limited_plan(state, row):
    if not row or row['status']!='blocked' or row['run']:
        return False
    call=state.db.execute('SELECT response,error FROM production_plan_calls WHERE plan_id=? ORDER BY number DESC LIMIT 1', (row['id'],)).fetchone()
    # Older receipts have only the adapter's exact error, not HTTP metadata.
    # Do not treat a timeout, interrupted send, or arbitrary error as a rejection.
    return bool(call and call['response'] is None and call['error']==row['error'] and
                row['error']=='Gemini request failed (429)' and row['provider']=='gemini')


def recover_uploaded_sources(state, ident, ids):
    """Explicitly recover missing bindings in an unstarted plan from its upload snapshot.

    Caller selects the exact IDs from saved user context; this never guesses a
    latest file, accepts outputs, starts workers or edits the failed proposal.
    """
    if not state.db.in_transaction:raise ValueError('Upload recovery requires an atomic transaction.')
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    if (not row or row['status']!='needs_input' or row['run'] or row['plan']
        or row['channel']!=getattr(state,'channel','telegram')):
        raise ValueError('Only an unexecuted needs-input plan in this channel can receive missing uploads.')
    payload=json.loads(row['context'])
    if c.digest(payload)!=row['context_hash']:raise ValueError('Frozen planning request changed.')
    job=state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(row['request_id'],)).fetchone()
    from . import routing_inputs
    snapshot=json.loads(job['snapshot']) if job else {}
    routing_inputs.validate_upload_ids(ids,snapshot.get('uploaded_files',[]))
    if not ids or any(s.get('upload_id') in ids for s in payload['sources']):
        raise ValueError('Recovery must add missing explicitly selected uploads.')
    new_request=-int(c.digest({'missing_upload_plan':ident,'ids':ids})[:15],16)-1
    new_id='plan-'+str(new_request)
    previous=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    if previous:return new_id,json.loads(previous['context'])['upload_recovery']
    rt=Runtime(pc.root(state),connection=state.db)
    for source in payload['sources']:verify_artifact(rt,source)
    manifest=routing_inputs.freeze_uploads(state,{'id':new_request,'focus':job['focus']},ids)
    original={f['id']:f for f in snapshot['uploaded_files']}
    for item in manifest:
        captured=original[item['upload_id']]
        if item['sha256']!=captured['sha256'] or item['bytes']!=captured['bytes']:
            raise ValueError('Upload differs from the original request snapshot.')
        path='request-inputs/'+str(new_request)+'/'+str(item['upload_id'])+'/'+Path(item['name']).name
        aid=rt.register(item['path'],item['role'],run=new_id,path=path)
        source=source_entry(rt,aid,path,item['role'],'Exact user upload; source context, not new authorization.')
        source.update(upload_id=item['upload_id'],media_type=item['media_type'],caption=item['caption'])
        if item['media_type'].startswith('image/'):source['visual_reference']=True
        payload['sources'].append(source);payload['required_artifacts'].append(aid)
        payload['missing_text_artifacts'].append(aid)
    options=json.loads(row['options']);options['reference_ids']=ids
    from orchestrator import worker_capabilities
    # Same configured providers/models, current truthful capability labels.
    for entry in options.get('worker_catalog',[]):
        entry['capabilities']=worker_capabilities.abilities(entry['backend'])
    receipt={'plan_id':ident,'request_id':row['request_id'],'context_hash':row['context_hash'],
             'uploads':[{'id':m['upload_id'],'sha256':m['sha256'],'bytes':m['bytes']} for m in manifest]}
    payload.update(options=options,upload_recovery=receipt)
    payload['planner_instructions']+=UPLOAD_PLANNER_INSTRUCTIONS
    values=dict(row)
    values.update(id=new_id,request_id=new_request,parent_id=ident,options=c.encoded(options),
        context=c.encoded(payload),context_hash=c.digest(payload),status='queued',calls=0,
        result=None,plan=None,plan_hash=None,token=secrets.token_hex(12),event_id=None,
        expires=time.time()+86400,run=None,error=None,created=time.time())
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(new_request,row['channel']))
    from . import production_stages
    production_stages.replace_unexecuted_plan(state,rt,payload,ident,new_id,row['channel'])
    return new_id,receipt



def retry_rate_limited_plan(state, ident, request):
    """Queue one explicitly requested successor; preserve the failed call intact."""
    if not state.db.in_transaction:raise ValueError('Planning retry requires an atomic transaction.')
    c.nonempty(request,'Exact planning retry request')
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    if not rate_limited_plan(state,row) or row['channel']!=getattr(state,'channel','telegram'):
        raise ValueError('Only confirmed rate-limited, unexecuted planning in this channel can be retried.')
    payload=json.loads(row['context'])
    if c.digest(payload)!=row['context_hash']:raise ValueError('Frozen planning request changed.')
    rt=Runtime(pc.root(state),connection=state.db)
    for source in payload['sources']:verify_artifact(rt,source)
    receipt={'plan_id':ident,'call':row['calls'],'context_hash':row['context_hash'],
             'request':request,'provider':row['provider'],'model':row['model']}
    new_request=-int(c.digest({'rate_limited_plan':ident})[:15],16)-1
    new_id='plan-'+str(new_request)
    if state.db.execute('SELECT 1 FROM production_plans WHERE id=?',(new_id,)).fetchone():
        raise ValueError('This planning retry already exists; inspect its successor.')
    values=dict(row)
    # Keep parent_id: a host execution plan must retain its preparation lineage.
    values.update(id=new_id,request_id=new_request,status='queued',calls=0,result=None,
        plan=None,plan_hash=None,token=secrets.token_hex(12),event_id=None,
        expires=time.time()+86400,run=None,error=None,created=time.time())
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(new_request,row['channel']))
    from . import production_stages
    production_stages.replace_unexecuted_plan(state,rt,payload,ident,new_id,row['channel'])
    return new_id,receipt


def recover_validated_response(state,ident):
    """Explicit recovery of an unexecuted proposal; never call a provider or retry work."""
    if not state.db.in_transaction:raise ValueError('Plan recovery requires an atomic transaction.')
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    if not row or row['status']!='blocked' or row['run'] or row['channel']!=getattr(state,'channel','telegram'):
        raise ValueError('Only a blocked, unexecuted plan in this channel can be recovered.')
    payload=json.loads(row['context'])
    if c.digest(payload)!=row['context_hash']:raise ValueError('Frozen planning request changed.')
    rt=Runtime(pc.root(state),connection=state.db)
    for source in payload['sources']:verify_artifact(rt,source)
    from . import workflow_correction
    def candidates():
        yield payload,None
        binding=workflow_correction.stage_binding_recovery(state,row)
        if binding:yield binding[0],binding
    for payload,binding in candidates():
        for call in state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=? ORDER BY number DESC',(ident,)):
            if not call['response'] or not call['error']:continue
            candidate=dict(row);candidate['context']=c.encoded(payload);candidate['context_hash']=c.digest(payload)
            try:result,plan=validate_result(call['response'],candidate)
            except (ValueError,KeyError,TypeError):continue
            if not plan:continue
            used={i['artifact'] for t in plan['tasks'] for i in t['inputs'] if 'artifact' in i}
            for source in source_catalog(payload):
                if source['artifact'] in used:verify_artifact(rt,source)
            receipt={'plan_id':ident,'call':call['number'],'response_sha256':c.digest(call['response'])}
            if binding:receipt['stage_type_recovery']=binding[2]
            new_request=-int(c.digest(receipt)[:15],16)-1
            new_id='plan-'+str(new_request)
            if state.db.execute('SELECT 1 FROM production_plans WHERE id=?',(new_id,)).fetchone():
                raise ValueError('This saved proposal was already recovered; inspect its successor.')
            if binding:
                from . import pipelines
                _,spec,record=binding
                state.db.execute('UPDATE relay_pipelines SET spec=? WHERE id=?',(c.encoded(spec),record['pipeline']))
                pipelines.event(state,record['pipeline'],record['stage'],'registered_handoff_rebound',receipt)
            values=dict(row)
            context={**payload,'recovered_proposal':receipt}
            values.update(id=new_id,request_id=new_request,parent_id=ident,context=c.encoded(context),
                context_hash=c.digest(context),status='ready',calls=0,result=c.encoded(result),plan=c.encoded(plan),
                plan_hash=c.digest(plan),token=secrets.token_hex(12),event_id=None,expires=time.time()+86400,
                run=None,error=None,created=time.time())
            state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
            state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(new_request,row['channel']))
            from . import production_stages
            production_stages.replace_unexecuted_plan(state,rt,payload,ident,new_id,row['channel'])
            current=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
            event=notice(state,current,'ready',('Recovered saved proposal with registered output types; review and Start this plan.\n' if binding else 'Recovered saved proposal; no provider call was repeated.\n')+preview(current))
            state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
            publish_ready_files(state,current,event,rt,plan,context)
            return new_id,receipt
    raise ValueError('No saved proposal currently validates. A new explicit planning request is needed; no work was replayed.')


def prepare_local_input_repair(state,run,request):
    """Recover only a confirmed failed local procedure with corrected input paths."""
    from . import production_stages,pipelines
    if not state.db.in_transaction:raise ValueError('Input repair requires an atomic transaction.')
    c.nonempty(request,'Exact recovery request')
    channel=getattr(state,'channel','telegram');rt=Runtime(pc.root(state),connection=state.db)
    baseline=production_stages.failed_execution_snapshot(state,rt,run,channel,'local_inputs')
    parent=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not parent or parent['channel']!=channel:raise ValueError('Original execution plan is unavailable.')
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():raise ValueError('Recovery already exists.')
    payload=json.loads(parent['context'])
    if c.digest(payload)!=parent['context_hash']:raise ValueError('Original context changed.')
    for source in payload['sources']:verify_artifact(rt,source)
    failed=next(t for t in baseline['tasks'] if t['status']=='blocked')
    frozen=json.loads(state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(failed['latest'],)).fetchone()[0])
    result=json.loads(parent['result']);raw=next(t for t in result['plan']['tasks'] if t['id']==failed['id'])
    changes=[{'artifact':i['artifact'],'path':i['path']} for i in raw['inputs'] if 'artifact' in i
             and not any(j['artifact']==i['artifact'] and j['path']==i['path'] for j in frozen['inputs'])]
    if not changes:raise ValueError('No lost declared input path was identified; no replay proposed.')
    done={t['id']:t for t in baseline['tasks'] if t['status']=='completed'}
    result['plan']['tasks']=[t for t in result['plan']['tasks'] if t['id'] not in done]
    for task in result['plan']['tasks']:
        task['dependencies']=[d for d in task.get('dependencies',[]) if d not in done]
        for item in task.get('inputs',[]):
            if item.get('from_task') not in done:continue
            artifact=rt.output(run,item['from_task'],item['output'])
            output=next(o for o in rt.spec(done[item['from_task']])['outputs'] if o['path']==item['output'])
            if output.get('media_type'):item['media_type']=output['media_type']
            source=source_entry(rt,artifact['id'],'recovery/completed/'+item['from_task']+'/'+item['output'],item['purpose'],'Exact output of completed preparation; retain its independent review receipt.')
            verify_artifact(rt,source)
            payload['sources'].append(source)
            item.pop('from_task');item.pop('output');item['artifact']=artifact['id']
    ident=-int(c.digest({'run':run,'request':request,'input_paths':changes})[:15],16)-1
    new_id='plan-'+str(ident)
    payload['execution_recovery']={'kind':'local_inputs','baseline':baseline,'input_paths':changes,
        'reused_completed_tasks':sorted(done),'request':request}
    payload['recovery_origin']={'original_request':parent['request'],'previous_stage':payload.pop('previous_stage',None)}
    options=json.loads(parent['options']);options['step_capabilities']=sorted({t['execution']['capability'] for t in result['plan']['tasks'] if t.get('execution')})
    payload['options']=options
    prompt=parent['request']+'\n\n--- EXACT USER RECOVERY REQUEST ---\n'+request
    folder=state.media_dir.parent/'production-planning'/new_id;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'recovery-request.txt'
    if path.exists() and path.read_text()!=prompt:raise ValueError('Recovery request changed.')
    path.write_text(prompt);aid=rt.register(path,'Exact recovery request',run=new_id,path='recovery/REQUEST.txt')
    for source in payload['sources']:
        if source['path']=='recovery/REQUEST.txt':source['path']='recovery-history/'+run+'/'+source['artifact']+'/REQUEST.txt'
    payload['sources'].append(source_entry(rt,aid,'recovery/REQUEST.txt','Exact recovery request','Current user report and original request; preserve scope.'))
    payload['required_artifacts'].append(aid)
    result['message']='Restore declared input paths; reuse completed preparation and review without changing source bytes.'
    values=dict(parent);values.update(id=new_id,request_id=ident,parent_id=parent['id'],request=prompt,
        options=c.encoded(options),context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,
        token=secrets.token_hex(12),event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    result,plan=validate_recovery_result(result,values)
    operation=next(t for t in plan['tasks'] if t['id']==failed['id'])
    if operation['execution']['capability']=='pptx.create':
        from orchestrator import pptx_document
        manifest=next(i for i in operation['inputs'] if i['media_type']=='application/json')
        pptx_document.validate(pptx_document.load(Path(rt.artifact(manifest['artifact'])['blob']).read_text()),
            [i['path'] for i in operation['inputs'] if i['media_type'] in ('image/png','image/jpeg')])
    values.update(result=c.encoded(result),plan=c.encoded(plan),plan_hash=c.digest(plan))
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
    state.db.execute('INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)',(run,new_id))
    stage=state.db.execute("SELECT s.*,p.status AS workflow_status FROM relay_pipeline_steps s JOIN relay_pipelines p ON p.id=s.pipeline WHERE s.target_kind='plan_production' AND s.target=?",(parent['id'],)).fetchone()
    if stage:
        if stage['workflow_status'] not in ('active','blocked'):raise ValueError('Workflow is paused or cancelled.')
        state.db.execute("UPDATE relay_pipeline_steps SET target=?,status='running',error=NULL WHERE pipeline=? AND id=?",(new_id,stage['pipeline'],stage['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(stage['pipeline'],))
        pipelines.event(state,stage['pipeline'],stage['id'],'local_input_repair_planned',{'parent':run,'plan':new_id,'input_paths':changes})
    current=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    event=notice(state,current,'ready',preview(current));state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
    publish_ready_files(state,current,event,rt,plan,payload)
    return new_id


def host_recovery_assessment(rt,run,task):
    """Bind shared policy evidence to the exact latest registered receipt."""
    from orchestrator.native_recovery import assess
    capability=rt.spec(task).get('execution',{}).get('capability')
    artifact=rt.output(run,task['id'],'delivery/execution.json')
    if not artifact or artifact['attempt']!=task['latest']:return None
    if file_hash(artifact['blob'])!=artifact['sha256']:raise ValueError('Host receipt changed.')
    receipt=json.loads(Path(artifact['blob']).read_text())
    if (receipt.get('assignment')!=task['latest'] or receipt.get('capability')!=capability
        or receipt.get('passed') is not False):return None
    return artifact,receipt,assess(receipt,capability)


def prepare_host_launch_recovery(state,run,request):
    """Shared pre-execution recovery; exact-code Start remains mandatory."""
    from . import production_stages
    if not state.db.in_transaction:raise ValueError('Host recovery requires a transaction.')
    rt=Runtime(pc.root(state),connection=state.db)
    tasks=[t for t in rt.status(run)['tasks'] if t['status']=='blocked']
    if len(tasks)!=1:return None
    capability=rt.spec(tasks[0]).get('execution',{}).get('capability')
    # These are the native operations supported by the existing repair planner.
    if capability not in ('rhino.run_python','blender.run_python','rhino3dm.run_python'):return None
    assessment=host_recovery_assessment(rt,run,tasks[0])
    if not assessment:return None
    if assessment[2]['action']=='prepare_reviewed_repair' and capability=='rhino.run_python':
        # Older versions treated bounding-box differences as fatal. Re-evaluate
        # only registered, terminal verification evidence; never relabel the old
        # attempt or start modeling from here. Fresh exact-code Start is required.
        from orchestrator.rhino_contract import compare, dimension_warnings, validate_checks
        task=tasks[0];report=rt.output(run,task['id'],'delivery/checks.json')
        phases=assessment[1].get('runs',[])
        if (not report or report['attempt']!=task['latest'] or not phases or phases[-1]['mode']!='verify'):
            return None
        measured=verify_artifact(rt,source_entry(rt,report['id'],'failure/checks.json','Failure measurements','Historical evidence'))
        evidence=json.loads(measured.read_text())
        errors=evidence.get('errors')
        if not isinstance(errors,list) or not errors or any(not isinstance(e,str) or not e.startswith('Unexpected dimensions: ') for e in errors):return None
        spec=rt.spec(task)
        original=next(i for i in spec['inputs'] if i.get('media_type')=='application/json')
        entry=source_entry(rt,original['artifact'],original['path'],'Original input checks','Frozen input')
        if entry['sha256']!=spec['execution']['parameters']['checks_sha256']:raise ValueError('Original checks identity changed.')
        checks=validate_checks(json.loads(verify_artifact(rt,entry).read_text()))
        try:
            if compare(evidence['before'],evidence['after'],checks) or evidence['after'].get('dependencies') or not dimension_warnings(evidence['after'],checks):return None
        except (KeyError,TypeError,ValueError):return None
        script=next(i['artifact'] for i in spec['inputs'] if i.get('media_type')=='text/x-python')
        return prepare_host_repair(state,run,script,request,runtime_repair=True)
    if assessment[2]['action']!='retry_unchanged':return None
    production_stages.failed_execution_snapshot(state,rt,run,getattr(state,'channel','telegram'))
    script=next(i['artifact'] for i in rt.spec(tasks[0])['inputs'] if i.get('media_type')=='text/x-python')
    return prepare_host_repair(state,run,script,request,pre_execution_recovery=True)


def prepare_host_repair(state,run,script_artifact,request,runtime_repair=False,repair_evidence=None,pre_execution_recovery=False):
    """Propose one exact-script repair; never dispatch it or reset old attempts.

    The caller supplies the user's recovery request and a registered candidate.
    runtime_repair permits an unchanged script only with a recorded Rhino
    implementation change; the new exact Start is still required.
    Completed tasks become receipt-backed inputs; only unfinished work is planned.
    """
    from . import production_stages,pipelines
    if not state.db.in_transaction:raise ValueError('Host repair planning requires an atomic transaction.')
    c.nonempty(request,'recovery request')
    channel=getattr(state,'channel','telegram');rt=Runtime(pc.root(state),connection=state.db)
    baseline=production_stages.failed_execution_snapshot(state,rt,run,channel)
    if repair_evidence:
        from .production_repairs import verify
        verify(state,rt,repair_evidence)
        if repair_evidence['artifacts']['script']['artifact']!=script_artifact:raise ValueError('Repair script differs from its independent review.')
    parent=state.db.execute('SELECT * FROM production_plans WHERE run=?',(run,)).fetchone()
    if not parent or parent['channel']!=channel:raise ValueError('Original execution plan is unavailable in this channel.')
    if state.db.execute('SELECT 1 FROM production_stage_links WHERE parent=?',(run,)).fetchone():
        raise ValueError('A recovery already exists; inspect that plan instead of duplicating it.')
    payload=json.loads(parent['context'])
    if c.digest(payload)!=parent['context_hash']:raise ValueError('Original execution planning context changed.')
    failed=next(t for t in baseline['tasks'] if t['status']=='blocked')
    failed_spec=rt.spec(failed);old_script=next(i['artifact'] for i in failed_spec['inputs'] if i.get('media_type')=='text/x-python')
    candidate=source_entry(rt,script_artifact,'recovery/model.py','Proposed corrected host script',
                           'Proposed repair candidate; the new exact-code Start is required before execution.')
    verify_artifact(rt,candidate)
    from orchestrator.host_script import validate_script_bytes
    validate_script_bytes(Path(rt.artifact(script_artifact)['blob']).read_bytes())
    runtime_changes={}
    recovery_assessment=host_recovery_assessment(rt,run,failed) if pre_execution_recovery else None
    if pre_execution_recovery:
        from orchestrator.native_recovery import require_ready
        if (not recovery_assessment or recovery_assessment[2]['action']!='retry_unchanged'
            or script_artifact!=old_script):raise ValueError('Confirmed pre-execution stop and unchanged script required.')
        artifact,receipt,decision=recovery_assessment
        require_ready(receipt,failed_spec['execution']['capability'])
        payload['sources'].append(source_entry(rt,artifact['id'],'recovery/pre-execution-failure.json',
            'Confirmed pre-execution failure receipt','Historical evidence; no permission to replay work.'))
    elif candidate['sha256']==rt.artifact(old_script)['sha256']:
        if not runtime_repair or failed_spec['execution']['capability']!='rhino.run_python':
            raise ValueError('Script repair must name a changed candidate version.')
        artifact=rt.output(run,failed['id'],'delivery/execution.json')
        if not artifact or artifact['attempt']!=failed['latest']:raise ValueError('Current failed host receipt is unavailable.')
        receipt_source=source_entry(rt,artifact['id'],'recovery/failed-execution.json','Failed host receipt','Historical failure evidence, not approval.')
        verify_artifact(rt,receipt_source)
        receipt=json.loads(Path(artifact['blob']).read_text())
        for name in ('rhino_execution.py','rhino_contract.py','rhino_worker.py'):
            previous=receipt.get('runtime_sources',{}).get(name)
            current=file_hash(Path(__file__).parent.parent/'orchestrator'/name)
            if previous and previous!=current:runtime_changes[name]={'before':previous,'after':current}
        if not runtime_changes:raise ValueError('No recorded Rhino implementation change justifies a runtime repair.')
        payload['sources'].append(receipt_source)
    done={t['id']:t for t in baseline['tasks'] if t['status']=='completed'}
    result=json.loads(parent['result']);tasks=result['plan']['tasks']
    # Retain the original operation recipe, parameters, review and limits.
    result['plan']['tasks']=[t for t in tasks if t['id'] not in done]
    for t in result['plan']['tasks']:
        t['instruction']='Read recovery/REQUEST.txt for the exact recovery request. '+('Use the unchanged selected script and checks; the previous attempt never reached the approved script execution phase. ' if pre_execution_recovery else 'Use the unchanged script/checks with the disclosed runtime correction. ' if runtime_changes else 'Use the proposed corrected script version; ')+ 'Prior failed artifacts are history, not accepted outputs.\n\n'+t['instruction']
        if t.get('review_of') in done:raise ValueError('A completed producer with unfinished review needs separate recovery.')
        t['dependencies']=[d for d in t.get('dependencies',[]) if d not in done]
        for item in t.get('inputs',[]):
            if item.get('artifact')==old_script:item['artifact']=script_artifact
            if item.get('from_task') in done:
                previous=done[item['from_task']]
                artifacts=state.db.execute('SELECT id FROM production_artifacts WHERE run=? AND task=? AND attempt=? AND path=?',
                    (run,previous['id'],previous['latest'],item['output'])).fetchall()
                if len(artifacts)!=1:raise ValueError('Completed dependency output is missing or ambiguous.')
                aid=artifacts[0][0];entry=source_entry(rt,aid,'recovery/completed/'+previous['id']+'/'+item['output'],item['purpose'],'Recorded output of completed work; no repeated operation.')
                verify_artifact(rt,entry);payload['sources'].append(entry)
                item.pop('from_task');item.pop('output');item['artifact']=aid
        if t['id']==failed['id']:t['execution']['parameters']['script_sha256']=candidate['sha256']
    caps={t.get('execution',{}).get('capability') for t in result['plan']['tasks']}-{None}
    options=json.loads(parent['options']);options['step_capabilities']=sorted(caps)
    recovery={'baseline':baseline,'parent_plan':parent['id'],'parent_context_hash':parent['context_hash'],
              'script_replacement':{'old':old_script,'new':script_artifact,'sha256':candidate['sha256']},
              'reused_completed_tasks':sorted(done),'request':request}
    if runtime_changes:recovery['runtime_changes']=runtime_changes
    if recovery_assessment:
        artifact,receipt,decision=recovery_assessment
        recovery['assessment']={**decision,'artifact':artifact['id'],'sha256':artifact['sha256']}
    ident=-int(c.digest({'run':run,'script':script_artifact,'request':request})[:15],16)-1
    new_id='plan-'+str(ident)
    payload['recovery_origin']={'original_request':parent['request'],'previous_stage':payload.pop('previous_stage',None)}
    payload['execution_recovery']=recovery
    if repair_evidence:
        recovery['reviewed_repair']=repair_evidence
        for key in ('diagnosis','review'):
            entry=copy.deepcopy(repair_evidence['artifacts'][key])
            entry['path']='repair-review/'+run+'/'+Path(entry['path']).name
            payload['sources'].append(entry)
            payload['required_artifacts'].append(entry['artifact'])
    for source in payload['sources']:
        if source['path']==candidate['path'] and source['artifact']!=script_artifact:
            source['path']='recovery-history/'+run+'/'+source['artifact']+'/model.py'
    if not any(s['artifact']==script_artifact for s in payload['sources']):payload['sources'].append(candidate)
    pipeline=pipelines.context_for_run(state,run)
    if pipeline:payload['pipeline_step']=pipeline['stage']
    if script_artifact not in payload['required_artifacts']:payload['required_artifacts'].append(script_artifact)
    payload['options']=options
    prompt=parent['request']+'\n\n'+('--- SAVED WORKFLOW REPAIR POLICY ---' if repair_evidence else '--- EXACT USER RECOVERY REQUEST ---')+'\n'+request
    folder=state.media_dir.parent/'production-planning'/new_id;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'recovery-request.txt'
    if path.exists() and path.read_text()!=prompt:raise ValueError('Recovery request identity changed.')
    path.write_text(prompt)
    aid=rt.register(path,'Exact original and recovery requests',run=new_id,path='recovery/REQUEST.txt')
    for source in payload['sources']:
        if source['path']=='recovery/REQUEST.txt':
            source['path']='recovery-history/'+run+'/'+source['artifact']+'/REQUEST.txt'
    payload['sources'].append(source_entry(rt,aid,'recovery/REQUEST.txt','Original and exact recovery request','Current user request; preserve its limits.'))
    payload['required_artifacts'].append(aid)
    result['message']=('Updated runtime proposed with unchanged script and checks; Start approves a new execution attempt.' if runtime_changes else 'Corrected script proposed; completed tasks are retained. Start approves the attached new version.')
    if runtime_changes:result['message']='Corrected Rhino verification runtime proposed with the unchanged script and checks. Start approves the new execution assignment.'
    if recovery_assessment:result['message']='The prior attempt stopped before the approved script ran. Exact inputs and limits are retained; Start approves a fresh attempt after the host readiness check.'
    values=dict(parent);values.update(id=new_id,request_id=ident,parent_id=parent['id'],request=prompt,
        options=c.encoded(options),context=c.encoded(payload),context_hash=c.digest(payload),status='ready',calls=0,
        token=secrets.token_hex(12),event_id=None,expires=time.time()+86400,run=None,error=None,created=time.time())
    result,plan=validate_recovery_result(result,values)
    values.update(result=c.encoded(result),plan=c.encoded(plan),plan_hash=c.digest(plan))
    state.db.execute('INSERT INTO production_plans('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
    state.db.execute('INSERT INTO production_stage_links(parent,plan_id) VALUES (?,?)',(run,new_id))
    stage=state.db.execute('''SELECT s.*,p.status AS workflow_status FROM relay_pipeline_steps s
        JOIN relay_pipelines p ON p.id=s.pipeline WHERE s.target_kind='plan_production' AND s.target=?''',(parent['id'],)).fetchone()
    if stage:
        if stage['workflow_status'] not in ('active','blocked'):raise ValueError('The workflow is paused or cancelled; no repair was queued.')
        state.db.execute("UPDATE relay_pipeline_steps SET target=?,status='running',error=NULL WHERE pipeline=? AND id=?",(new_id,stage['pipeline'],stage['id']))
        state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(stage['pipeline'],))
        pipelines.event(state,stage['pipeline'],stage['id'],'execution_repair_planned',{'parent':run,'plan':new_id,'script_replacement':recovery['script_replacement']})
    current=state.db.execute('SELECT * FROM production_plans WHERE id=?',(new_id,)).fetchone()
    event=notice(state,current,'ready',preview(current))
    state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,new_id))
    publish_ready_files(state,current,event,rt,plan,payload)
    return new_id


class Worker:
    def __init__(self,state,generator=generate):self.state=state;self.generator=generator;self.started=False
    def tick(self):
        s=self.state
        if not self.started:
            with s.db:
                for row in s.db.execute("SELECT * FROM production_plans WHERE status='sending'").fetchall():
                    s.db.execute("UPDATE production_plans SET status='uncertain',error='Planner interrupted after submission; not replayed' WHERE id=?",(row['id'],))
                    notice(s,row,'uncertain','Planning was interrupted after submission. No workers started; inspect the saved request before trying again.')
            self.started=True
        row=s.db.execute("SELECT * FROM production_plans WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if not row:return
        payload=json.loads(row['context']);number=row['calls']+1
        if row['error']:
            previous=s.db.execute('SELECT response FROM production_plan_calls WHERE plan_id=? ORDER BY number DESC LIMIT 1',(row['id'],)).fetchone()
            response=previous[0] if previous else None
            try:response=json.loads(response)
            except (ValueError,TypeError):pass
            payload={**payload,'structural_correction':{'error':row['error'],'previous_response':response}}
            detail=s.get('planner-contract-error:'+row['id']+':'+str(number-1))
            if detail:payload['structural_correction']['detail']=detail
        try:
            if number>2:raise ValueError('The two-call planning budget is exhausted.')
            if len(c.encoded(payload))>MAX_CONTEXT:raise ValueError('Planning request including correction exceeds its frozen context limit.')
            if c.digest(json.loads(row['context']))!=row['context_hash']:raise ValueError('Frozen planning request changed.')
            rt=Runtime(pc.root(s),connection=s.db)
            for source in json.loads(row['context'])['sources']:verify_artifact(rt,source)
            with s.db:
                claimed=s.db.execute("UPDATE production_plans SET status='sending',calls=? WHERE id=? AND status='queued'",(number,row['id'])).rowcount
                if not claimed:return
                s.db.execute('INSERT INTO production_plan_calls VALUES (?,?,?,NULL,NULL,NULL,?)',(row['id'],number,c.encoded(payload),time.time()))
            raw,usage=self.generator(row,payload)
            with s.db:s.db.execute('UPDATE production_plan_calls SET response=?,usage=? WHERE plan_id=? AND number=?',(raw,c.encoded(usage),row['id'],number))
            try:
                result,plan=validate_result(raw,row)
                if plan:
                    used={i['artifact'] for t in plan['tasks'] for i in t['inputs'] if 'artifact' in i}
                    for source in source_catalog(payload):
                        if source['artifact'] in used:verify_artifact(rt,source)
            except (ValueError,KeyError,TypeError) as exc:
                with s.db:
                    from .operation_builders import ContractError
                    if isinstance(exc,ContractError):
                        s.put('planner-contract-error:'+row['id']+':'+str(number),exc.receipt())
                    s.db.execute('UPDATE production_plan_calls SET error=? WHERE plan_id=? AND number=?',(str(exc),row['id'],number))
                    s.db.execute('UPDATE production_plans SET status=?,error=? WHERE id=?',('queued' if number<2 else 'blocked',str(exc),row['id']))
                    if number>=2:notice(s,row,'invalid','Planning stopped after one structural correction: '+str(exc)+'. No workers started.')
                return
            with s.db:
                s.db.execute('UPDATE production_plans SET status=?,result=?,plan=?,plan_hash=?,error=NULL WHERE id=?',
                    (result['decision'],c.encoded(result),c.encoded(plan) if plan else None,c.digest(plan) if plan else None,row['id']))
                current=s.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone()
                text=preview(current) if plan else 'Planning '+result['decision']+': '+result['message']+'\nReply with the missing information; your original request is retained.'
                event=notice(s,current,'ready' if plan else result['decision'],text)
                s.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,row['id']))
                if plan:
                    publish_ready_files(s,current,event,rt,plan,payload)
        except Exception as exc:
            s.db.rollback()
            status='uncertain' if isinstance(exc,gemini.ProviderError) and exc.uncertain else 'blocked'
            with s.db:
                s.db.execute('UPDATE production_plans SET status=?,error=? WHERE id=?',(status,str(exc),row['id']))
                s.db.execute('UPDATE production_plan_calls SET error=? WHERE plan_id=? AND number=?',(str(exc),row['id'],number))
                notice(s,row,'error','Planning '+status+': '+str(exc)+'. No workers started; no automatic provider retry.')


def authorize(state,job,ident):
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    if not row or row['channel']!=relay_channels.request_channel(state,job['id']) or row['status']!='ready':
        raise ValueError('That saved plan is not ready in this channel.')
    options=json.loads(row['options']);options['planning_only']=False
    state.db.execute('UPDATE production_plans SET options=?,token=?,expires=? WHERE id=?',
                     (c.encoded(options),secrets.token_hex(12),time.time()+86400,ident))
    row=state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
    event=notice(state,row,'authorize-'+str(job['id']),preview(row))
    attach_host_code(state,row,event,Runtime(pc.root(state),connection=state.db))
    state.db.execute('UPDATE production_plans SET event_id=? WHERE id=?',(event,ident))
    return 'The saved plan is ready for your approval. No workers have started.'


def controls(state,event):
    row=state.db.execute("SELECT * FROM production_plans WHERE event_id=? AND status='ready' AND expires>?",(event,time.time())).fetchone()
    if not row:return None
    buttons=[]
    if not json.loads(row['options'])['planning_only']:buttons.append({'text':'Start preparation' if json.loads(row['context']).get('review_correction_origin') else 'Start this stage','callback_data':'plan:start:'+row['token']})
    buttons.append({'text':'Discard plan','callback_data':'plan:discard:'+row['token']})
    return {'inline_keyboard':[buttons]}


def apply(state,token,verb,reviewed_event=None,reviewed_attachments=None,followup_channel=None,pipeline_grant=None):
    if not state.db.in_transaction:raise ValueError('Plan approval requires a transaction.')
    row=state.db.execute("SELECT * FROM production_plans WHERE token=? AND status='ready' AND expires>?",(token,time.time())).fetchone()
    if not row:raise ValueError('That plan is expired, changed or already handled.')
    from . import pipelines
    if verb=='start':pipelines.verify_start(state,row,pipeline_grant)
    if row['channel']!=getattr(state,'channel','telegram'):raise ValueError('Use the plan card in its original channel.')
    if followup_channel is not None and (row['channel']!='desktop' or followup_channel!='telegram'):
        raise ValueError('Unsupported plan follow-up channel.')
    desktop_review = row['channel']=='desktop' and reviewed_event==row['event_id']
    sent=state.db.execute('SELECT sent FROM outbox WHERE id=?',(row['event_id'],)).fetchone()
    if not desktop_review and (not sent or not sent[0]):raise ValueError('Wait for the complete plan card before approving it.')
    def delivered(ident):
        if desktop_review:return ident in (reviewed_attachments or set())
        item=state.db.execute('SELECT status FROM media_outbox WHERE id=?',(ident,)).fetchone()
        return bool(item and item['status']=='sent')
    if verb=='discard':
        state.db.execute("UPDATE production_plans SET status='discarded' WHERE id=?",(row['id'],));return 'Plan discarded; no workers started.'
    if verb!='start' or json.loads(row['options'])['planning_only']:raise ValueError('This plan has no execution authorization.')
    if state.db.execute("SELECT 1 FROM production_plan_replies r JOIN orchestrator_chats c ON c.id=r.request_id WHERE r.plan_id=? AND c.status IN ('queued','sending','guides_pending')",(row['id'],)).fetchone():
        raise ValueError('A reply to this plan is still awaiting interpretation; wait for its result before starting.')
    payload=json.loads(row['context']);plan=json.loads(row['plan'])
    if c.digest(payload)!=row['context_hash'] or c.digest(plan)!=row['plan_hash']:raise ValueError('The saved plan or inputs changed.')
    if payload.get('review_correction_origin'):
        from . import production_review_corrections
        origin=payload['review_correction_origin']
        if production_review_corrections.snapshot(state,origin['run'])!=origin['baseline']:
            raise ValueError('The reviewed candidate or recovery state changed; request a new correction plan.')
    if payload.get('reference_pack'):
        from task_relay import reference_packs
        reference_packs.handoff(state,payload['reference_pack']['id'])
        if file_hash(Path(payload['reference_pack']['manifest']))!=payload['reference_pack']['sha256']:raise ValueError('Reference pack changed.')
    rt=Runtime(pc.root(state),connection=state.db)
    from task_relay import production_stages
    production_stages.verify(state,rt,payload,row['id'],row['channel'])
    if payload.get('execution_recovery',{}).get('reviewed_repair'):
        for key in ('diagnosis','review'):
            if not delivered(row['event_id']+':repair-'+key):raise ValueError('Wait for the complete repair diagnosis and independent review before Start.')
    used={i['artifact'] for t in plan['tasks'] for i in t['inputs'] if 'artifact' in i}
    from orchestrator.execution import available
    from orchestrator.executors import available as executor_available
    from orchestrator.worker_capabilities import backend_for
    for task in plan['tasks']:
        if not task.get('execution'):executor_available(backend_for(task,plan['backend']))
    for task in plan['tasks']:
        if task.get('execution'):available(task)
    if any(t.get('execution',{}).get('capability','').startswith('rhino.') for t in plan['tasks']):
        from . import host_apps,rhino_host
        rhino_host.require_available(host_apps.rhino()['executable'])
    for source in source_catalog(payload):
        if source['artifact'] in used:verify_artifact(rt,source)
    from orchestrator import host_code
    for task in plan['tasks']:
        if task.get('execution',{}).get('capability')=='rhino.render':
            from orchestrator.rhino_render import bind_registered
            bind_registered(rt,task)
            if not delivered(row['event_id']+':rhino-render-manifest:'+task['id']):raise ValueError('Wait for the complete Rhino render manifest before approving this render')
        if task.get('execution',{}).get('capability')=='blender.animate':
            from orchestrator.blender_animation import bind_registered
            bind_registered(rt,task)
            if not delivered(row['event_id']+':animation-manifest:'+task['id']):raise ValueError('Wait for the complete animation manifest before approving this render')
        if task.get('execution',{}).get('capability')=='blender.import_asset':
            from orchestrator.blender_assets import bind_registered
            bind_registered(rt,task)
            if not delivered(row['event_id']+':asset-manifest:'+task['id']):raise ValueError('Wait for the complete asset manifest before approving this import')
        if host_code.required(task):
            for suffix in ('script','checks'):
                if not delivered(row['event_id']+':host-'+suffix+':'+task['id']):raise ValueError('Wait for the complete editing script and checks documents before approving host code')
    validate_bound_worker_inputs(rt,plan,payload)
    rt.create(plan)
    if pipeline_grant:
        pipelines.event(state,pipeline_grant,None,'bounded_stage_started',{'plan_id':row['id'],'plan_hash':row['plan_hash']})
    for task in plan['tasks']:
        if host_code.required(task):host_code.authorize(rt,plan['id'],task['id'],
            {'source':'delivered_plan_start','plan_id':row['id'],'plan_hash':row['plan_hash'],
             'event_id':row['event_id'],'channel':row['channel'],'approved_at':time.time()})
    production_stages.register(state,rt,payload,row['id'],plan['id'])
    state.put('production-enabled:'+plan['id'],pc.runtime_digest(rt,plan['id']))
    state.db.execute("UPDATE production_plans SET status='started',run=? WHERE id=?",(plan['id'],row['id']))
    relay_channels.bind(state,'production',plan['id'],followup_channel or row['channel'])
    notice_state=getattr(state,'base',state) if followup_channel=='telegram' else state
    pc.notice(notice_state,plan['id'],'planner-started','Production scheduled: '+plan['brief']+'\n'+str(len(plan['tasks']))+' bounded steps with declared dependencies. Results and status will arrive here.')
    return 'Stage scheduled.'


def callback(bridge,update):
    q=update['callback_query'];raw=q.get('data','')
    if not raw.startswith('plan:'):return False
    s=bridge.state;user=q.get('from',{});chat=q.get('message',{}).get('chat',{})
    if user.get('is_bot') or user.get('id')!=s.get('user_id') or chat.get('id')!=s.get('chat_id') or chat.get('type')!='private':return True
    try:
        parts=raw.split(':')
        if len(parts)!=3:raise ValueError('Invalid plan choice.')
        with s.db:
            s.db.execute('BEGIN IMMEDIATE');message=apply(s,parts[2],parts[1])
    except (ValueError,OSError) as exc:message=str(exc)
    from task_relay.bridge import BridgeError
    try:bridge.telegram.call('answerCallbackQuery',callback_query_id=q['id'],text=message[:200],show_alert=True)
    except BridgeError:pass
    return True
