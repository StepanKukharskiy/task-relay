"""Execution profiles and credential-bound, read-only connection verification."""
import hashlib
import json
import re
import time
from pathlib import Path

GEMINI_LIMITS = {'seconds': 1800, 'tool_calls': 24, 'output_bytes': 200000}
MAX_INPUT_BYTES = 512000
MAX_ROUNDS = 8
MAX_OUTPUT_TOKENS = 4096
VERIFICATION_SECONDS = 900
BROWSER_TYPES = ('gemini-browser', 'openai-browser', 'qwen-browser')
API_TYPES = ('gemini-agent', *BROWSER_TYPES)


def validate(backend):
    if not isinstance(backend, dict):raise ValueError('Specify an execution backend.')
    if backend.get('type') == 'codex-cli':
        if not isinstance(backend.get('model'),str) or not backend['model'].strip():raise ValueError('Specify a fixed model.')
        if backend.get('reasoning') not in ('low','medium','high','xhigh','max','ultra'):raise ValueError('Specify reasoning effort')
        return ['files','shell']
    if backend.get('type') in ('gemini-agent','gemini-browser'):
        if set(backend) != {'type','model'} or not isinstance(backend['model'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}',backend['model']):
            raise ValueError('Gemini execution requires an exact model and no unsupported backend options.')
        return ['files','browser'] if backend['type']=='gemini-browser' else ['files']
    if backend.get('type') in ('openai-browser','qwen-browser'):
        from task_relay.api_providers import model_name
        if set(backend)!={'type','model'}:raise ValueError('Browser execution requires an exact model and no additional backend options.')
        model_name(backend['model'])
        return ['files','browser']
    raise ValueError('Unsupported execution provider; no fallback is allowed.')


def configured(provider='gemini'):
    if provider in ('openai','qwen'):
        from task_relay import api_providers as api
        config=api.read_config(provider)
        if not config or not config.get('model'):raise ValueError('Connect '+provider+' and select its text model first.')
        backend={'type':provider+'-browser','model':config['model']};validate(backend)
        return config,backend
    if provider!='gemini':raise ValueError('Unsupported browser provider; no fallback.')
    from task_relay import gemini
    config=gemini.read_config()
    model=(config or {}).get('models',{}).get('text')
    if not config or not model:raise ValueError('Connect Gemini and select its text model first.')
    backend={'type':'gemini-agent','model':model};validate(backend)
    return config,backend


def fingerprint(config,backend):
    if backend['type'] in ('openai-browser','qwen-browser'):
        from task_relay.api_providers import endpoint
        provider=backend['type'].removesuffix('-browser')
        return hashlib.sha256(json.dumps([provider,config['api_key'],backend['model'],endpoint(provider,config.get('base_url'))]).encode()).hexdigest()
    return hashlib.sha256((config['api_key']+'\0'+backend['model']).encode()).hexdigest()


def receipt_path(provider='gemini'):
    from task_relay import gemini
    return gemini.DATA/(provider+'-executor-verification.json')


def probe(provider='gemini'):
    """GET model metadata only; no content generation and no credential output."""
    from task_relay import gemini
    from .workers import atomic
    # A failed refresh must not leave an older success advertising availability.
    if provider not in ('gemini','openai','qwen'):raise ValueError('Unsupported browser provider')
    atomic(receipt_path(provider),{'verified_at':0})
    if provider!='gemini':
        from task_relay import api_providers as api
        config,backend=configured(provider)
        names=api.catalog(provider,config['api_key'],config.get('base_url'))
        if backend['model'] not in names:raise ValueError('Selected model is absent from the provider catalog.')
        receipt={'backend':backend,'fingerprint':fingerprint(config,backend),'verified_at':time.time(),
                 'method':'models.list','limitation':'Model listing verified only; tool calling and quota are checked during execution.'}
        atomic(receipt_path(provider),receipt)
        return {k:v for k,v in receipt.items() if k!='fingerprint'}
    config,backend=configured()
    value=gemini.Client(config['api_key']).request('models/'+backend['model'],timeout=20,max_response_bytes=100000)
    if value.get('name')!='models/'+backend['model'] or 'generateContent' not in value.get('supportedGenerationMethods',[]):
        raise ValueError('The configured model did not confirm generateContent eligibility.')
    receipt={'backend':backend,'fingerprint':fingerprint(config,backend),'verified_at':time.time(),
             'method':'models.get','generation_methods':value['supportedGenerationMethods'],
             'limitation':'Connection/model metadata verified; generation quota is checked by execution.'}
    atomic(receipt_path(),receipt)
    return {k:v for k,v in receipt.items() if k!='fingerprint'}


def available(backend):
    validate(backend)
    if backend['type']=='codex-cli':return
    if backend['type']=='gemini-browser':
        from task_relay.host import HOST
        from task_relay.relay_paths import PATHS
        HOST.browser_python(PATHS.install,PATHS.data)
        return available({'type':'gemini-agent','model':backend['model']})
    if backend['type'] in ('openai-browser','qwen-browser'):
        from task_relay.host import HOST
        from task_relay.relay_paths import PATHS
        provider=backend['type'].removesuffix('-browser')
        config,current=configured(provider)
        if backend!=current:raise ValueError('Selected browser model changed; no fallback.')
        HOST.browser_python(PATHS.install,PATHS.data)
        try:r=json.loads(receipt_path(provider).read_text())
        except (OSError,ValueError):raise ValueError('Verify the '+provider+' browser connection before use.') from None
        if r.get('backend')!=backend or r.get('fingerprint')!=fingerprint(config,backend) or not 0<=time.time()-r.get('verified_at',0)<=VERIFICATION_SECONDS:
            raise ValueError(provider+' browser verification is stale; refresh its connection check.')
        return
    config,current=configured()
    if backend!=current:raise ValueError('The selected Gemini model changed; no fallback is allowed.')
    try:r=json.loads(receipt_path().read_text())
    except (OSError,ValueError):raise ValueError('Verify the Gemini executor connection before use.') from None
    if r.get('backend')!=backend or r.get('fingerprint')!=fingerprint(config,backend) or not 0<=time.time()-r.get('verified_at',0)<=VERIFICATION_SECONDS:
        raise ValueError('Gemini executor verification is stale; refresh its connection check.')


def catalog(state=None):
    result=[]
    codex=(state.get('production-planner-policy',{}) or {}).get('backend') if state else None
    if state and (not codex or codex.get('type')!='codex-cli'):
        for row in state.db.execute('SELECT plan FROM production_runs ORDER BY rowid DESC'):
            candidate=json.loads(row['plan'])['backend']
            if candidate.get('type')=='codex-cli':codex=candidate;break
    if codex and codex.get('type')=='codex-cli':
        from task_relay.host import HOST, UnsupportedHost
        try:executable=HOST.codex()
        except UnsupportedHost:executable=None
        result.append({'id':'codex-cli','backend':codex,'tools':['files','shell'],'available':executable is not None,
                       'grant_boundary':'Native workspace-write sandbox only; exact read/edit grants unavailable for shell execution',
                       'limits':{'seconds':1800,'tool_calls':60,'output_bytes':100000000}})
    entry={'id':'gemini-agent','backend':None,'tools':['files'],'limits':GEMINI_LIMITS.copy(),'available':False,
           'permissions':'Read declared UTF-8 inputs; write declared text outputs only. No shell, web, apps or other file access.',
           'request_bounds':{'rounds':MAX_ROUNDS,'max_output_tokens_per_round':MAX_OUTPUT_TOKENS,'input_bytes':MAX_INPUT_BYTES}}
    try:
        _,entry['backend']=configured();available(entry['backend']);entry['available']=True
    except ValueError as exc:entry['blocker']=str(exc)
    result.append(entry)
    browser={**entry,'id':'gemini-browser','backend':({'type':'gemini-browser','model':entry['backend']['model']} if entry['backend'] else None),
        'tools':['files','browser'],'available':False,
        'permissions':'Declared text files and general browser tools in dedicated profiles. Exact origins, interaction scope and transfer grants required. Website contents go to the selected model; no shell/cookie/credential tools.'}
    try:
        if browser['backend'] is None:raise ValueError('Connect and verify Gemini first')
        available(browser['backend']);browser['available']=True
    except (ValueError,RuntimeError) as exc:browser['blocker']=str(exc)
    result.append(browser)
    for provider in ('openai','qwen'):
        item={**browser,'id':provider+'-browser','backend':None,'available':False}
        item.pop('blocker',None)
        try:
            _,item['backend']=configured(provider);available(item['backend']);item['available']=True
        except (ValueError,RuntimeError) as exc:item['blocker']=str(exc)
        result.append(item)
    return result


if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in ('verify-gemini','verify-openai','verify-qwen'):raise SystemExit('Use: python3 -m orchestrator.executors verify-{gemini|openai|qwen}')
    print(json.dumps(probe(sys.argv[1].removeprefix('verify-')),indent=2))
