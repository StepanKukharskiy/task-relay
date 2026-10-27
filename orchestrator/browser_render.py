"""Image-to-image browser operation using the existing Session and durable journal.

Site descriptions supply controls. The operation lifecycle owns dispatch; this
adapter never retries a submission or substitutes a page screenshot for a render.
"""
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .workers import atomic
from .runtime_outcomes import UncertainOperation
from .browser_contract import png_info

OUTPUTS={'delivery/render.png':'image/png','delivery/render.png.json':'application/json'}


def selected(url):
    u=urlsplit(url)
    ids=parse_qs(u.query).get('nodeId',[])
    if u.scheme!='https' or u.netloc!='app.xfigura.ai' or u.path!='/designer' or len(ids)!=1 or not ids[0] or len(ids[0])>256:
        raise ValueError('Choose an exact xFigura designer URL with one selected nodeId')
    return ids[0]


def policy(url,image):
    selected(url)
    return dict(profile='managed',session_source='settings',origins=['https://app.xfigura.ai'],
        interaction_scope='Upload the exact assigned PNG, fill the assigned prompt in the selected empty render node, generate once and download its new PNG. No purchases, settings changes or other nodes.',
        max_tabs=1,max_actions=60,uploads=[image],downloads=['delivery/render.png'],visual_inputs=[image],
        custom_actions=[dict(name='xFigura actions',mode='interact')])


def boundary(view,node):
    value=view.get('image_render')
    if not value or value.get('node')!=node:raise ValueError('Selected image-render node is not uniquely observable; no generation')
    if value.get('busy'):raise ValueError('Selected render node already has active work; no resubmission')
    return value


def control(view,role):
    matches=[c for c in view['controls'] if c.get('render_role')==role]
    if len(matches)!=1:raise ValueError('Expected one observed '+role+' control inside the selected node')
    return matches[0]['ref']


def transfer(session,url,prompt,image,deadline):
    """All mutations pass Session's fresh-observation and committed-intent checks."""
    node=selected(url)
    view=session.call('open','browser_open',dict(url=url))
    initial=boundary(view,node)
    if initial.get('output'):raise ValueError('Choose an empty xFigura render node; existing result is preserved')
    for role in ('upload','prompt','generate'):control(view,role)
    tab=view['tab']
    def act(ident,verb,role,**args):
        return session.call(ident,'browser_'+verb,dict(tab=tab,observation=view['observation'],ref=control(view,role),
                       purpose='Assigned image render: '+role,**args))
    view=act('upload','upload','upload',path=image)
    view=act('prompt','fill','prompt',text=prompt)
    b=boundary(view,node)
    if b.get('prompt')!=prompt or not b.get('input_ready'):raise ValueError('Image or exact prompt is not observable after transfer; no generation')
    # Intent is durable before this one Generate. A timeout never returns to it.
    view=act('generate','click','generate')
    for attempt in range(50):
        if time.monotonic()>=deadline:break
        b=view.get('image_render',{})
        if b.get('prompt')!=prompt:raise UncertainOperation('Prompt changed after Generate; no retry')
        if b.get('node')!=node:raise UncertainOperation('Selected node changed after Generate; no retry')
        if b.get('error'):raise UncertainOperation('xFigura reported an error after Generate: '+str(b['error'])[:1000])
        if not b.get('busy') and b.get('output'):
            output=b['output']
            view=act('download','download','download',path='delivery/render.png')
            final=view.get('image_render',{})
            if final.get('node')!=node or final.get('output')!=output:
                raise UncertainOperation('Render changed during download; keep the receipt without retry')
            return dict(node=node,output=output,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
        view=session.call('wait-'+str(attempt),'browser_wait',dict(tab=tab,seconds=2))
    raise UncertainOperation('Generation has no confirmed downloadable output within the original wait limit; no retry')


def available(assignment,spec):
    from .perplexity_search import setup
    state=setup()
    if state['error'] or not state['available'] or not state['enabled'] or state['manual_sign_in']:
        raise ValueError('Enable the saved Chrome profile and finish xFigura sign-in before running. No generation submitted.')
    selected(assignment['execution']['parameters']['url'])


def execute(ctx):
    from .operation_execution import Result
    from .agent_loop import Files
    from task_relay import general_browser
    from task_relay.browser_journal import Journal
    from task_relay.relay_paths import PATHS
    p=ctx.frozen['execution']['parameters']; image=p['image']
    item=next(i for i in ctx.frozen['inputs'] if i['path']==image)
    raw=(ctx.workspace/image).read_bytes();png_info(raw)
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Render input changed')
    frozen=dict(ctx.frozen,browser=policy(p['url'],image),tools=['files','browser'])
    files=Files(frozen)
    submitted=False;pending=False;touched=False
    try:
        available(ctx.frozen,ctx.spec)
        with closing(sqlite3.connect(PATHS.state,timeout=30)) as db:
            journal=Journal(db)
            if journal.pending('managed'):raise UncertainOperation('Managed browser has unresolved work; no interaction')
            with general_browser.browser(PATHS.data,frozen['browser']) as driver:
                session=general_browser.Session(db,ctx.frozen['assignment_id'],frozen['browser'],driver,files,
                                               cancelled=lambda:(ctx.control/'cancel.json').exists())
                try:binding=transfer(session,p['url'],p['prompt'],image,time.monotonic()+min(110,ctx.frozen['limits']['seconds']-10))
                finally:
                    rows=[dict(r) for r in db.execute('SELECT id,status,request,result FROM general_browser_actions WHERE job=? ORDER BY created,id',(ctx.frozen['assignment_id'],))]
                    submitted=any(r['id']=='generate' for r in rows)
                    pending=any(r['status'] in ('intent','uncertain') for r in rows)
                    touched=any(r['id'] in ('upload','prompt') and r['status']=='observed' for r in rows)
                    atomic(ctx.control/'browser-actions.json',rows)
        side=ctx.workspace/'delivery/render.png.json'
        provenance=json.loads(side.read_text());provenance.update(input_sha256=item['sha256'],render_binding=binding,usage=None,
            limitation='Browser transfer and selected-node association verified. Visual fidelity and geometry preservation are not established.')
        atomic(side,provenance)
        details=dict(outcome='completed',effect='confirmed',execution=ctx.frozen['execution'],usage=None,validation=provenance)
        atomic(ctx.control/'operation.json',details)
        atomic(ctx.workspace/'.relay/result.json',dict(assignment_id=ctx.frozen['assignment_id'],decision='delivered',instruction='',
            summary='Downloaded the selected node render; visual suitability remains a user decision.',checks=[dict(criterion=1,passed=True,evidence='delivery/render.png.json')]))
        return Result(receipt=details)
    except Exception as exc:
        details=dict(outcome='uncertain' if submitted or pending or isinstance(exc,UncertainOperation) else 'failed' if touched else 'rejected',effect='uncertain' if submitted or pending else 'confirmed' if touched else 'none',reason=str(exc),usage=None)
        atomic(ctx.control/'operation.json',details)
        if submitted or pending:raise UncertainOperation(str(exc)) from exc
        raise


def inspect(control,result,details):
    # Child death after an interaction must not become a harmless local failure.
    # operation_lifecycle already treats a missing terminal receipt as uncertain.
    if details.get('outcome')=='uncertain':result.update(status='uncertain',external_outcome='unknown',reason=details.get('reason'))


def register(registry,adapters):
    from .operation_adapters import Adapter,object_schema
    parameters=object_schema(dict(url=dict(type='string',minLength=1,maxLength=4000),prompt=dict(type='string',minLength=1,maxLength=4000),image=dict(type='string',minLength=1)))
    registry['xfigura.render']=dict(version=1,kind='procedure',input_types=['image/png'],min_inputs=1,max_inputs=1,input_bytes=10000000,
        output_type=None,outputs=OUTPUTS,output_bytes=11000000,seconds=180,external_requests=1,requires_paid_confirmation=True,
        parameters={'url':'Exact selected empty xFigura render node URL','prompt':'Exact architectural rendering prompt','image':'PNG view from an upstream node'},
        resources=['managed-perplexity-browser'],criteria=['Retain the original downloaded PNG, exact uploaded image hash, prompt and selected-node capture receipt; never resubmit uncertain generation.'],
        permissions='One xFigura generation in the saved browser account, which may spend credits. Requires explicit paid confirmation. No API key, subscription purchase or automatic retry.',
        cancellation='Retain all action intents and uncertain results. Never regenerate automatically.',
        description='Render an assigned PNG in a selected empty xFigura node using the existing browser adapter. Unsupported or ambiguous page controls stop before generation.',
        runtime_modules=['browser_render.py','browser_contract.py','browser_action_sets.py'],
        support_modules=['task_relay.general_browser','task_relay.browser_journal','task_relay.managed_browser','task_relay.host_managed_chrome','task_relay.browser_render_controls'],
        node_ui=dict(title='Render with xFigura',category='Images',connection='managed_browser',inputs={'url':'xFigura render node URL','prompt':'Render prompt','image':'Source image'},outputs={'render':'Architectural render','render_png':'Render provenance'}))
    adapters['xfigura.render']=Adapter(parameters=parameters,references={'image':'path'},reference_media={'image':dict(media_type='image/png',accepts=['image/png'])},
        handler='orchestrator.browser_render:execute',availability=('orchestrator.browser_render:available',),inspections=('orchestrator.browser_render:inspect',),handoffs=dict(version=1,ports=[]))
