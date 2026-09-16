"""Shared capability descriptions and adapters over existing execution receipts.

The catalog describes configured execution paths, not inferred model powers.
Native workers still enforce their own permissions and record actual execution.
"""
import copy
import hashlib
import json
from pathlib import Path
import secrets
import time

from task_relay import file_tools

READ = ('file_list', 'file_read', 'file_search', 'pdf_read')
WORKER_CAPABILITIES = (*READ, 'file_write', 'shell', 'web_search', 'web_fetch')
CLAUDE_TOOLS = ['Read', 'Glob', 'Grep', 'Edit', 'Write', 'Bash', 'WebSearch', 'WebFetch']
EXECUTION_ROUTING = '''Execution routing check before your final response:
Interpret the current user's intent in its conversational context. Requests such as
"we need a desktop launcher" or "let's continue with O13 then" can ask for work,
even without a slash command or the word Codex. Resolve the referenced work from
the user's earlier messages and the current roadmap; do not expand it to the whole
milestone. When the user asks to proceed, select a suitable existing task, use the
linked workflow control, or propose a bounded production stage as appropriate.
If the execution destination is unclear, ask where to run it, or use choose_task
for relevant Codex destinations. An idea that is genuinely exploratory can stay
conversational; ask a concrete scope question when intent is ambiguous. Do not end
an actionable request with a generic offer to act later. History helps resolve
references but does not supply new authorization. General questions remain answers.

Desktop browser routing: the Codex files/shell catalog is a baseline, not a complete
inventory of the desktop task's installed plugins. Unverified Browser or Computer
Use support is not evidence that those tools are absent. For an explicit request
to use a named existing Codex task for website interaction, use route_task after
checking that exact destination's status. The destination must inspect its current
tools and permissions before acting and report a concrete blocker if unavailable.
Do not require gemini-browser or a Relay-managed account profile for a request to
use that desktop task's own signed-in browser. Do not advertise plugin availability
or successful browser execution from the baseline catalog alone.
Honor the requested website: research IN Perplexity means submitting the research
there and returning its answer and conversation URL. Do not silently replace that
with your own web search or a manual copy/paste task. Resolve the research question
from the user/context; if missing, ask for it before dispatch. Existing login or
verification blockers require user help only when actually encountered by the
selected browser worker. Questions about browser capabilities still have action=null.

For an explicit request to research in Perplexity, first inspect the browser_research
operation. When available, use {"kind":"browser_research","site":"perplexity","query":"the research question for the website"}.
It uses the app-managed Chrome profile without gemini-browser/openai-browser/qwen-browser,
an extension or Codex. Their stale checks and browser_account_sites verification
belong to a different profile and do not block this operation. The worker checks
actual login and website verification before submitting once. Do not claim sign-in
or universal website compatibility from Browser use being enabled.
Write query as a self-contained research task addressed to the website. Remove
Relay/browser routing language such as "use browser", "search Perplexity for", and
"send the result back". For "use browser and search perplexity for rebar contractors",
query is "Find rebar contractors." Do not ask the website how to operate Perplexity.
Preserve all substantive requirements: topic, named entities, geography, dates,
exclusions, language, requested output and source requirements. Do not invent a
location, budget, deadline, result count, or new research goal. A general search
without a location stays general; an optional preference is not a prerequisite.
Resolve references only from unambiguous user-provided conversation context. If
essential scope is missing or conflicting, ask with action=null. Do not send a
bare "do it", invent context, or re-run earlier work merely to answer a status
question. Questions actually ABOUT using Perplexity keep that meaning; the example
above is not a rule to remove Perplexity as a genuine research subject.
Relay retains the original message unchanged alongside the frozen query and
receipt, and submits the query exactly once. Rephrasing is scope-preserving task
translation, not permission to expand work. Honor provider choices. Capability and
status questions have action=null; inspect recent_requests. Other sites still use
their supported browser executors.

General browser workers also support
browser_screenshot for explicitly granted viewport PNG outputs plus .png.json
provenance. For capture requests use plan_production with a supported browser worker,
exact website origins and browser.screenshots PNG paths. No Codex or GIS adapter is
required. PNG reads return metadata only; screenshot capture does not add visual
reasoning, canvas clicking or verification that map tiles loaded. Do not promise
visual acceptance; preserve a user review gate for that. Screenshot grants and PNG
outputs must be shown in the exact plan before Start.
For a presentation requiring both subject photos and a location map, propose the
requested image sourcing, browser capture and deck creation together. Use the exact
named map service and project area; keep URL/time provenance and visible attribution.
The PNG can feed pptx.create alongside a sourced image bundle. Do not omit the map,
silently switch services or replace a website screenshot with a generated image.

Editable presentation creation uses plan_production with step_capabilities=["pptx.create"]
when the operation catalog reports it available. An agent prepares a bounded slide
JSON specification, independent review checks it, then the local operation creates
native editable PPTX text, shapes, tables, charts and selected PNG/JPEG images.
Use a separate reviewer for the actual deck and a user selection gate. This needs
no Google login or PowerPoint installation. PPTX can be opened in Keynote, but
creation/reopen checks do not establish Keynote import fidelity or visual layout.
Native .key output, arbitrary existing-template editing and PDF/previews are not
outputs of this operation; preserve those requirements as explicit separate work.
For real photos of specified subjects, include images.collect in step_capabilities.
It searches public Wikimedia Commons without an image-generation model, returns an
exact attributed image bundle and records missing matches. Review subject identity
and coverage before using the bundle in pptx.create. Preserve all named subjects,
scientific names when supplied, captions and source credits. Missing images require
an explicit gap or further sourcing; do not silently replace search with generation.

Direct Rhino support uses rhino.startup, rhino.inspect and rhino.run_python.
Select exact .3dm artifacts for inspection. For modeling, first prepare/review
interpreter-compatible model.py (IronPython 2.7 for Rhino 7, CPython 3 for Rhino 8) and checks JSON using the rhino.run_python catalog schema.
Then propose a separate exact-code approved host stage with registered script,
checks and optional source .3dm. scene_sha256=null means create a new model;
edits bind the exact source hash. Return candidate.3dm, viewport preview and
independent reopen checks for user selection. Scripts use RhinoCommon and the
supplied doc/scriptcontext.doc. Current adapter: Rhino 7/8 on macOS. rhino.render uses an exact manifest to render
an existing named view through built-in Rhino Render, with review and selection. Grasshopper
definitions, GH scripts and GH component execution are paused; do not route them
through direct Rhino modeling or claim they are supported.

For an existing Blender scene, blender.inspect can inventory its objects, materials,
cameras and dependencies. Select the exact .blend artifact_ids in plan_production
and step_capabilities=["blender.inspect"], or ask which scene if the version is
missing. Inspection is not editing. To edit, first prepare and independently review
edit.py and edit-checks.json using the blender.run_python checks schema, then stop.
Once exact scene/script/checks artifacts exist, propose a separate stage with
step_capabilities=["blender.run_python"] and those artifact_ids. It executes only
after an explicit delivered plan-card approval of that exact host Python, with
normal host filesystem/network permissions (no OS isolation). No future-script
approval or script execution through the restricted agent shell. The v1 route
preserves other objects/cameras/materials and supports self-contained scenes,
candidate save/reopen, bounded dimension checks and matching-camera previews.
For selected assets, blender.import_asset can append exact named meshes from a
registered .blend library and pack PNG/JPEG dependencies into a portable candidate.
First prepare/review an asset manifest using its catalog schema if none exists.
Then select the exact manifest/scene/library/image artifact_ids and use
step_capabilities=["blender.import_asset"]. The manifest preserves relative layout,
hashes, supplied provenance and explicit import choices. No downloads, persistent
links or unknown future inputs. The user reviews/selects the candidate after bundle
relocation verification. Numeric animation and rendering use blender.animate with an
exact manifest; other object additions/removals, simulation and UI remain deferred.

For Blender startup use plan_production with step_capabilities=["blender.startup"].
For primitive-based modeling (including a twisting tower), use step_capabilities=
["blender.scene"] with a scene-data producer and review. These host operations
are in snapshot.capabilities.graph_operations and avoid the restricted worker-shell
startup failure without changing agent permissions. Do not use that failed shell
path again. For unfamiliar shapes (gyroids, custom surfaces, generated topology), choose
step_capabilities=["blender.mesh_scene"]. An agent writes code in its sandbox to
compute numeric vertices/faces and scene JSON; the reusable host operation builds
and renders that exact geometry. Do not translate unknown shapes into primitives
or reject them merely because blender.scene is primitive-only.
Arbitrary host Blender scripts/imported scenes are outside this bounded
capability; use a suitable existing desktop task with its approval flow instead.

An explicit request to run a command, execute a script, or perform a diagnostic is
work to delegate. Direct conversation tools being read-only is not a reason to
send the user to Terminal when a compatible worker is available. Inspect the
current target and graph executor catalog. Use delegate_task for a relevant idle
task, or plan_production with template="custom", project=null and an available
files/shell executor for a standalone bounded diagnosis. Preserve explicit project
and provider choices; never route to an unrelated task. If neither path exists,
identify that exact unavailable path rather than claiming the whole system cannot
execute. An informational "how do I" question can still be answered without action.
For a startup check, scope the new plan to the requested probe, recorded exit code,
stdout/stderr and environment evidence. Do not generate/render an artifact, alter
permissions, reinstall software, or retry the previous exhausted production.
Terminal success does not qualify a different worker environment. Do not infer a
GPU cache, driver or permissions root cause from a crash location alone. A startup
failure in that environment is a valid diagnostic finding, not permission to fix
the host. Use the existing plan approval; do not claim execution before receipts.
'''
from orchestrator.browser_contract import WEBSITE_TASK_INSTRUCTIONS
EXECUTION_ROUTING += '\n'+WEBSITE_TASK_INSTRUCTIONS
from .capability_defaults import INSTRUCTIONS as MODEL_DEFAULT_INSTRUCTIONS
EXECUTION_ROUTING += '\n' + MODEL_DEFAULT_INSTRUCTIONS

IMMEDIATE = ('discover_opportunities','draft_procedure','run_procedure','plan_pipeline','pipeline_result','pipeline_decision','pipeline_control','browser_research', 'generate_image', 'continue_production', 'collect_references',
             'resume_production',
             'route_task', 'choose_task', 'create_codex_task', 'create_production_folder',
             'import_production_research', 'delegate_task', 'plan_production', 'authorize_production_plan','replace_selection')
GATED = ('plan', 'run', 'pause', 'resume', 'stop', 'start_production', 'revise_production')


class CapabilityError(ValueError):
    """A concrete unavailable execution path, safe to explain to the user."""


DELEGATE_SCHEMA = {
    'type':'object','additionalProperties':False,
    'required':['kind','task_id','provider','required_capabilities'],
    'properties':{
        'kind':{'const':'delegate_task'},
        'task_id':{'type':'string'},
        'provider':{'enum':['codex','claude','gemini','openai','qwen','deepseek','openrouter']},
        'artifact_ids':{'type':'array','minItems':0,'maxItems':10,'uniqueItems':True,'items':{'type':'string'}},
        'research_ids':{'type':'array','minItems':0,'maxItems':10,'uniqueItems':True,'items':{'type':'integer'}},
        'required_capabilities':{'type':'array','minItems':1,'uniqueItems':True,
                                 'items':{'enum':list(WORKER_CAPABILITIES)}}}}

INSTRUCTIONS = '''Use snapshot.capabilities as the current capability and executor catalog.
For an explicit request to replace a selected version, return
{"kind":"replace_selection","old_decision":"exact saved decision ID","new_decision":"exact saved decision ID"}.
Use production_runs.selections and artifact_replacements; never infer replacements
from names, dates or matching hashes. Both versions must already have saved selections
in the same recorded job and exact decision purpose. Ask which versions if ambiguous.
This action prepares a concrete replacement card; the user confirms that card. It
does not start workers. Existing decisions remain historical; outdated outputs are
conservative dependency flags, not proof of semantic use or permission to rebuild.
After an explicit request to update affected outputs, use plan_production with exact
current versions and a bounded scope. Include affected outputs/replacement decisions
as context. Preserve job identity through previous_run when eligible; do not bypass
stage eligibility or mutate old assignments. Never promise an automatic rebuild.
Distinguish direct tools from delegated worker capabilities. Missing direct shell/web
tools does not mean the whole system cannot help: inspect the eligible worker targets.
For an explicit request to do work in an EXISTING suitable task, you may return
{"kind":"delegate_task","task_id":"exact target id","provider":"exact provider",
 "required_capabilities":["web_search","web_fetch"],"artifact_ids":[],"research_ids":[]}.
For Codex, fill the source lists from the exact requested versions; empty means
none are needed. Omit these source lists for non-Codex providers.
Choose only capabilities actually needed and a target in the same relevant project.
Honor the user's explicit provider choice; do not silently fall back to another provider.
For multiple plausible tasks ask which one; never choose by capability alone. Prefer
existing workflow/production controls for work belonging to those stages. Never route
production feedback to an unrelated worker or bypass a frozen stage's bounds.
For delegate_task, the original user message is sent verbatim, not a model-generated
execution prompt. browser_research instead uses its separately frozen research query.
Capability availability is configuration evidence, not proof of authentication or
success; queue receipts prove queueing only. Actual status comes from worker records.
Focused production snapshots include artifact_lineage: exact registered inputs supplied
to recorded attempts and their outputs, with saved selection purposes. Use these
IDs/hashes when explaining which sources produced a draft. Declared context may not
have been used semantically. Respect truncation/gaps; do not infer that equal names or
hashes mean the same selection, or that a newer candidate supersedes an older choice.
Lineage does not authorize replacements or downstream rebuilds.
blender.animate supports bounded transform/camera keyframes and rendering of selected
native animation. A registered manifest fixes frames, FPS, preview/final quality and
tracks. Prepare missing manifests with an agent first, then propose the exact render
stage. It returns a native candidate, MP4, preview and frame/checkpoint receipts.
Continuation needs an exact checkpoint from a confirmed stopped attempt with the same
manifest; uncertain frame work is never silently replayed. Simulation/UI work remains unsupported.
plan_production can propose a bounded producer/reviewer stage using graph_executors
and the optional executor field. Honor exact provider choice; unavailable or
unsupported work is blocked without fallback. Gemini/OpenAI/Qwen/DeepSeek/OpenRouter
-agent profiles support declared text file tools. Their -code profiles use verified
native Python with exact inputs/outputs and no network, subprocesses or app access.
Check runtime_tools for usable document libraries; no package installation. Native
code is currently macOS only; Windows requires its native isolation adapter.
gemini-browser, openai-browser and qwen-browser add the same general
website tools under an exact approved profile, origin list, interaction scope and
file-transfer grants. Honor the requested provider and use its available browser
executor for website control. An OpenAI/Qwen browser executor does not need Gemini
or Codex. Never switch providers when the requested one is disconnected. Login is performed by the
user locally; no universal site compatibility is implied. API executor profiles
require a recent connection/model metadata check; listing a model does not prove
its tool-calling behavior has been qualified.
It can also propose explicitly
requested mixed text steps using graph_operations and step_capabilities. API steps
require the exact plan approval and have no agent tools.
Arbitrary tool installation and arbitrary graph steps are not exposed. If no eligible target exists, explain the specific missing path.
General questions about capabilities require action null, not a worker dispatch.
snapshot.capabilities.host_applications lists detected local applications. They
distinguish the preferred Rhino version from installed_versions. Never say Rhino 7
is absent merely because Rhino 8 is preferred, or call a detected app active.
For another installed Rhino version, direct the user to Settings → Models by task
to select it before planning interpreter-specific code. Do not silently run a
request for Rhino 7 in Rhino 8 or change already approved runtime assignments.
Detected applications
have registered host operations as well as agent task routes. The mesh operation
accepts geometry computed by a files/shell agent; the agent need not launch Blender. For a new standalone application job use plan_production with project=null,
template=custom and an available Codex executor when no relevant existing task
exists. Include the actual native file and preview as declared outputs. Follow
the existing plan authorization; do not invent a missing-destination blocker when
a standalone production is available. Execution receipts establish completion.
Read execution_environments separately. agent_shell historical failures apply only
to that shell, never to registered_host. Use registered_host startup_status and
latest_check for host evidence. Unverified means no matching current receipt; it
is not a failure. Never describe an old sandbox crash as a host startup blocker.
A reported failure warrants recovery only for its actual execution environment. Do not expand permissions or repeat spent attempts.
Requests to create an artifact in an application (for example, model a tower in
Blender) are execution requests. Inspect suitable worker/project paths before
substituting a script for the user to run. A code-only answer does not complete
such a request. If no suitable execution destination is available, explain the
specific missing path and ask for the destination; do not select an unrelated
task, claim execution, or invent an application adapter.
'''


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS capability_dispatches (
      job_id INTEGER PRIMARY KEY, action TEXT NOT NULL, executor TEXT NOT NULL,
      receipt_id TEXT, result TEXT NOT NULL, thread_id TEXT, created REAL NOT NULL)''')


def file_definitions(roots):
    result = copy.deepcopy(file_tools.DEFINITIONS)
    for definition in result:
        params = definition['parameters']
        params['properties']['project'] = {'type':'string', 'enum':sorted(roots),
                                           'description':'Exact known project folder.'}
        params['required'].append('project')
    return result


def read(roots, call):
    from task_relay import gemini
    try:
        args = json.loads(call['arguments'])
        if not isinstance(args, dict):
            raise ValueError()
        project = args.pop('project', None)
        if project not in roots:
            return {'ok':False, 'error':'Choose a known project from the offered tool schema.'}
        return file_tools.execute(project, call['name'], json.dumps(args), (gemini.DATA,))
    except (TypeError, ValueError):
        return {'ok':False, 'error':'Invalid file-tool arguments.'}


def backend_targets(state):
    from task_relay import backends
    from task_relay import api_providers as api
    from task_relay import gemini
    from task_relay import task_routing
    result=[]
    for row in state.db.execute('''SELECT b.*,w.title,w.status FROM backend_tasks b
            JOIN watched w ON w.id=b.id ORDER BY w.updated_at DESC,b.id LIMIT 51'''):
        if len(result)==50:
            break
        provider=row['backend']
        if provider=='claude':
            configured=bool(backends.claude_config() and backends.CLAUDE_PYTHON.is_file())
            caps=list(WORKER_CAPABILITIES)
            limits={'turns':100,'seconds':3600}
        elif provider=='gemini' or provider in api.SPECS:
            configured=bool(gemini.read_config() if provider=='gemini' else api.read_config(provider))
            caps=list(READ)
            limits={'tool_rounds':8,'tool_calls':24}
        else:
            continue
        blocker=(None if configured else 'Provider setup is missing.')
        if not Path(row['cwd']).is_dir():
            blocker='Project folder is missing.'
        if row['status']!='idle':
            blocker='Task is '+row['status']+'; inspect its current job before dispatch.'
        blocker=task_routing.task_conflict(state,row['id']) or blocker
        identity={k:row[k] for k in ('id','backend','cwd','model','session_id','initialized')}
        result.append(dict(id=row['id'],provider=provider,title=row['title'],cwd=row['cwd'],
            capabilities=caps,available=not blocker,blocker=blocker,limits=limits,
            fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
            permissions='Native worker permissions; no approval is granted by routing.',
            verification='Configured locally; authentication and model tool support verified during execution.'))
    return result


def catalog(state, snapshot):
    from task_relay import gemini
    enabled=bool(state.get('orchestrator_routing_enabled',False))
    targets=[]
    if enabled:
        for task in snapshot.get('codex_tasks',[]):
            if not all(k in task for k in ('id','title','cwd','status','fingerprint')):
                continue
            targets.append(dict(id=task['id'],provider='codex',title=task['title'],cwd=task['cwd'],
                capabilities=[*READ,'file_write','shell'],
                available=task['status']=='idle' and not task.get('routing_blocker'),
                blocker=task.get('routing_blocker') or (None if task['status']=='idle' else task['status']),
                fingerprint=task['fingerprint'],permissions='Existing desktop task permissions and approvals.',
                limits='Existing task configuration; this routes one turn, not a bounded production assignment.',
                verification='Desktop task observed. Listed capabilities are the baseline; installed Browser/Computer Use plugins are unverified, not known absent. An explicitly requested desktop task can check its own tools through route_task.'))
        targets.extend(backend_targets(state))
    specs=[]
    for d in file_tools.DEFINITIONS:
        limits = {'file_bytes':file_tools.MAX_FILE_BYTES,'response_chars':file_tools.MAX_CHARS}
        if d['name'] == 'pdf_read':
            limits.update(file_bytes=20_000_000, document_pages=500, pages_per_read=8, seconds=15)
        specs.append(dict(id=d['name'],executor='relay.files',input_schema=d['parameters'],
            permissions='Read-only known project folders; file policy enforced on every call.',
            limits=limits,
            evidence='Read result, path/offset and private tool-call journal.'))
    from task_relay import orchestrator_web
    for definition in (orchestrator_web.FETCH,orchestrator_web.SEARCH):
        specs.append(dict(id=definition['name'],executor='relay.web',input_schema=definition['parameters'],
            available=definition['name']=='web_fetch' or bool(gemini.read_config()),
            permissions='Public read-only web research; no private network or authenticated sessions.',
            limits={'search_requests':2,'page_downloads':6,'page_bytes':1000000},
            evidence='Timestamped source URLs, page hashes and saved research receipts.'))
    from . import browser_research
    specs.append(browser_research.catalog(state))
    for kind in (*IMMEDIATE,*GATED):
        if kind=='browser_research':continue
        specs.append(dict(id=kind,executor='relay.'+kind,
            inputs=('task_id, provider, required_capabilities' if kind=='delegate_task' else
                    'no parameters; local history analysis only' if kind=='discover_opportunities' else
                    'pipeline_id, name, parameters; optional opportunity_id' if kind=='draft_procedure' else
                    'procedure_id, bindings' if kind=='run_procedure' else
                    'title, planning_only, stages' if kind=='plan_pipeline' else
                    'result, choices' if kind=='pipeline_result' else
                    'pipeline_id, stage_id, choice_id' if kind=='pipeline_decision' else
                    'pipeline_id, verb' if kind=='pipeline_control' else
                    'template, project, reference_pack_id, research_ids, planning_only; optional parent_id or previous_run' if kind=='plan_production' else
                    'plan_id' if kind=='authorize_production_plan' else
                    'old_decision, new_decision' if kind=='replace_selection' else
                    'reference_ids, optional artifact_ids from production_artifacts' if kind=='generate_image' else 'project' if kind=='collect_references' else
                    'task_id/task_ids, optional reference_pack_id' if kind in ('route_task','choose_task') else
                    'workflow, items, direction'),
            permissions='Existing action card and scope checks.' if kind in GATED else 'Explicit user request; existing adapter checks.',
            limits='Existing adapter budgets and destination state checks.',
            evidence='Durable queue/control receipt; consult the underlying worker for completion.'))
        if kind=='delegate_task':
            specs[-1]['input_schema']=copy.deepcopy(DELEGATE_SCHEMA)
        if kind=='create_codex_task':
            from .task_creation import SCHEMA
            from .host import HOST
            specs[-1]['input_schema']=copy.deepcopy(SCHEMA)
            specs[-1]['inputs']='project, title, start_work, research_ids, artifact_ids'
            try:
                HOST.require_posix('Codex task creation'); HOST.codex()
                blocker=None if enabled else 'Task routing is disabled.'
            except (OSError,ValueError,RuntimeError) as exc:
                blocker=str(exc)
            specs[-1].update(available=not blocker,blocker=blocker,
                limits='One local task; optionally one first turn. No implicit worktree, model override or retry.')
        if kind=='replace_selection':
            from task_relay.production_replacements import SCHEMA
            specs[-1]['input_schema']=copy.deepcopy(SCHEMA)
    specs.append(dict(id='discover_guides',executor='relay.guides',
        input_schema={'type':'object','properties':{'kind':{'const':'discover_guides'},
                      'query':{'type':'string','minLength':1,'maxLength':2000}},
                      'required':['kind'],'additionalProperties':False},
        permissions='Read-only discovery; user chooses saved guides before use.',
        limits='One search per request, at most 20 known project folders and six guide matches.',
        evidence='Saved search result and guide selection receipt.'))
    receipts=[]
    for row in state.db.execute('SELECT job_id,executor,receipt_id,thread_id,created FROM capability_dispatches ORDER BY created DESC LIMIT 5'):
        entry=dict(row)
        if row['executor'] in ('backend_jobs','task_routes','task_creations','production_continuations','production_plans'):
            record=state.db.execute('SELECT status FROM '+row['executor']+' WHERE id=?',(row['receipt_id'],)).fetchone()
            entry['status']=record['status'] if record else 'receipt target missing'
        else:
            entry['status']='dispatched; inspect the corresponding action records'
        receipts.append(entry)
    from orchestrator.execution import catalog as graph_catalog
    from orchestrator.executors import catalog as executor_catalog
    from task_relay.host_apps import catalog as app_catalog
    from task_relay.browser_sites import catalog as site_catalog
    from .managed_browser import status as managed_browser_status
    from .capability_defaults import read as model_defaults
    from orchestrator.worker_capabilities import CAPABILITIES
    return dict(version=1,operations=specs,graph_operations=graph_catalog(),graph_executors=executor_catalog(state),targets=targets,routing_enabled=enabled,dispatches=receipts,
        worker_capabilities=CAPABILITIES.copy(),
        model_defaults=model_defaults(state.db)['choices'],
        browser_account_sites=site_catalog(state.db),
        managed_browser=managed_browser_status(),
        host_applications=app_catalog(state),
        backend_catalog_limit=50,backend_catalog_truncated=enabled and state.db.execute('SELECT count(*) FROM backend_tasks').fetchone()[0]>50,
        image_configured=bool(gemini.read_config()),
        direct_unavailable=['shell','file_write']+([] if gemini.read_config() else ['web_search']),
        web={'web_fetch':'Public HTTPS text reader; no login/JavaScript/PDF.',
             'web_search':'Gemini/Google Search; configured' if gemini.read_config() else 'Connect Gemini to enable search.'},
        production_worker='Task-specific roles resolve required worker_capabilities to captured executor profiles. Each approved task freezes its model and tools; explicit executor choice has no fallback. Registered operations remain separate. Workers are not free routing targets.')


def validate_delegate(action, snapshot):
    if set(action)-{'research_ids','artifact_ids'}!={'kind','task_id','provider','required_capabilities'}:
        raise CapabilityError('Delegation requires an exact task, provider and required capabilities.')
    caps=action['required_capabilities']
    if not isinstance(caps,list) or not caps or any(not isinstance(c,str) or c not in WORKER_CAPABILITIES for c in caps) or len(set(caps))!=len(caps):
        raise CapabilityError('Choose distinct supported worker capabilities.')
    target=next((t for t in snapshot.get('capabilities',{}).get('targets',[]) if t['id']==action['task_id']),None)
    if not target or not target['available']:
        raise CapabilityError('The selected worker is unavailable'+(': '+str(target['blocker']) if target else '.'))
    if target['provider']!=action['provider']:
        raise CapabilityError('The selected worker does not match the requested provider.')
    missing=set(caps)-set(target['capabilities'])
    if missing:
        raise CapabilityError('The selected worker cannot provide: '+', '.join(sorted(missing)))
    if 'research_ids' in action:
        from task_relay import routing_inputs
        if target['provider']!='codex':raise CapabilityError('Registered research handoff currently requires a Codex task.')
        routing_inputs.validate_ids(action['research_ids'],snapshot.get('research_documents',[]))
    if 'artifact_ids' in action:
        from task_relay import routing_inputs
        if target['provider']!='codex':raise CapabilityError('Generated artifact handoff currently requires a Codex task.')
        routing_inputs.validate_artifact_ids(action['artifact_ids'],snapshot.get('production_artifacts',[]))
    if target['provider']=='codex':
        from task_relay import routing_inputs
        routing_inputs.require_source_selections(action,snapshot)
    return target


def delegate(state, job, action, snapshot):
    from task_relay import task_routing
    from task_relay import backends
    target=validate_delegate(action,snapshot)
    if not state.get('orchestrator_routing_enabled',False):
        raise CapabilityError('Task routing has been disabled.')
    if target['provider']=='codex':
        candidate=next(t for t in snapshot['codex_tasks'] if t['id']==target['id'])
        text=task_routing.register(state,job,[candidate],False,research_ids=action.get('research_ids'),artifact_ids=action.get('artifact_ids'))
        return text,target['id'],'task_routes',str(job['id'])
    current=next((t for t in backend_targets(state) if t['id']==target['id']),None)
    if not current or not current['available'] or current['fingerprint']!=target['fingerprint']:
        raise CapabilityError('The worker changed or became unavailable; no job was queued.')
    # Distinct from Telegram update IDs and other internal analytical/media jobs.
    internal_id=-secrets.randbits(62)-1
    from task_relay import orchestrator_guides
    ident=backends.enqueue(state,target['id'],job['prompt']+orchestrator_guides.handoff(state,job),internal_id,'text',transaction=False)
    return ('Queued for '+target['provider'].capitalize()+': '+target['title']+
            '\nYour complete original request was sent to this existing task. '+
            'Native tool permissions still apply.'),target['id'],'backend_jobs',ident


def dispatch(state, job, action, snapshot):
    """Immediate adapters only; card-gated operations stay in the control path.

    Caller owns one transaction for the queue, receipt and user-facing answer.
    An uncertain native submission is never retried or switched to another provider.
    """
    if not action or action['kind'] not in IMMEDIATE:
        return None
    if not state.db.in_transaction:
        raise ValueError('Capability dispatch requires an outer transaction.')
    old=state.db.execute('SELECT * FROM capability_dispatches WHERE job_id=?',(job['id'],)).fetchone()
    if old:
        if json.loads(old['action'])!=action:
            raise ValueError('This request already dispatched a different action.')
        return old['result'],old['thread_id']
    from task_relay import production_continuations; from task_relay import production_folders; from task_relay import reference_packs; from task_relay import task_routing; from task_relay import orchestrator_images
    kind=action['kind'];tid=None;receipt=str(job['id']);executor=kind
    if kind in ('plan_pipeline','pipeline_result','pipeline_decision','pipeline_control'):
        from . import pipelines
        from .relay_channels import ScopedState, request_channel
        text,tid=pipelines.dispatch(ScopedState(state,request_channel(state,job['id'])),job,action,snapshot)
        executor='relay_pipelines'
    elif kind=='discover_opportunities':
        from . import opportunities
        from .relay_channels import ScopedState, request_channel
        if set(action)!={'kind'}:raise CapabilityError('History discovery takes no execution parameters.')
        scoped=ScopedState(state,request_channel(state,job['id']))
        text=opportunities.listing(opportunities.scan(scoped,job['id'],job['prompt']))
        executor='relay_opportunities'
    elif kind in ('draft_procedure','run_procedure'):
        from . import procedures
        from .relay_channels import ScopedState, request_channel
        try:text,tid=procedures.dispatch(ScopedState(state,request_channel(state,job['id'])),job,action,snapshot)
        except ValueError as exc:raise CapabilityError(str(exc)) from exc
        executor='relay_procedures'
    elif kind=='browser_research':
        from . import browser_research
        try:text,receipt=browser_research.dispatch(state,job,action)
        except ValueError as exc:raise CapabilityError(str(exc)) from exc
        executor='browser_research_requests'
    elif kind=='delegate_task':
        text,tid,executor,receipt=delegate(state,job,action,snapshot)
    elif kind=='create_codex_task':
        from . import task_creation
        text=task_creation.enqueue(state,job,action,snapshot)
        executor='task_creations'
    elif kind=='resume_production':
        from task_relay import production_control
        text=production_control.resume_review(state,action['workflow'],legacy=True)
        executor='production_runs';receipt=action['workflow']
    elif kind=='plan_production':
        from task_relay import production_planning
        text=production_planning.enqueue(state,job,action,snapshot)
        executor='production_plans';receipt='plan-'+str(job['id'])
    elif kind=='replace_selection':
        from task_relay import production_replacements
        text=production_replacements.propose(state,job,action)
        executor='production_replacement_cards';receipt=str(job['id'])
    elif kind=='authorize_production_plan':
        from task_relay import production_planning
        text=production_planning.authorize(state,job,action['plan_id'])
        executor='production_plans';receipt=action['plan_id']
    elif kind=='generate_image':
        tid,text=orchestrator_images.queue(state,job,action['reference_ids'],action.get('artifact_ids',[]),action.get('provider','gemini'),action.get('model'))
        executor='orchestrator_image_requests'
    elif kind=='continue_production':
        from task_relay import orchestrator_guides
        orchestrator_guides.production_inputs(state,job['id'],action['workflow'])
        text=production_continuations.enqueue(state,job,action['workflow'])
        executor='production_continuations'
    elif kind=='collect_references':
        text=reference_packs.enqueue(state,job,action['project'])
    elif kind in ('route_task','choose_task'):
        ids=[action['task_id']] if kind=='route_task' else action['task_ids']
        candidates=[next(t for t in snapshot['codex_tasks'] if t['id']==i) for i in ids]
        text=task_routing.register(state,job,candidates,kind=='choose_task',reference_pack_id=action.get('reference_pack_id'),research_ids=action.get('research_ids'),artifact_ids=action.get('artifact_ids'))
        executor='task_routes'
    else:
        operation=production_folders.create if kind=='create_production_folder' else production_folders.import_research
        text=operation(state,action['workflow'])
    if kind in ('continue_production','create_production_folder','import_production_research'):
        state.db.execute('UPDATE orchestrator_chats SET focus=? WHERE id=?',(action['workflow'],job['id']))
    state.db.execute('INSERT INTO capability_dispatches VALUES (?,?,?,?,?,?,?)',
        (job['id'],json.dumps(action),executor,receipt,text,tid,time.time()))
    return text,tid
