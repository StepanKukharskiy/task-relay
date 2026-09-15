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
PROVIDERS = ('gemini','openai','qwen','deepseek','openrouter')
FILE_TYPES = tuple(p+'-agent' for p in PROVIDERS)
CODE_TYPES = tuple(p+'-code' for p in PROVIDERS)
API_TYPES = (*FILE_TYPES, *BROWSER_TYPES, *CODE_TYPES)


def provider_for(backend):
    if backend.get('type') not in API_TYPES:raise ValueError('Not a registered API worker.')
    return backend['type'].split('-',1)[0]


def configured_worker(provider, kind='agent'):
    if provider not in PROVIDERS or kind not in ('agent','browser','code'):raise ValueError('Unsupported worker profile.')
    if provider=='gemini':config,base=configured()
    else:
        from task_relay import api_providers as api
        config=api.read_config(provider)
        if not config or not config.get('model'):raise ValueError('Connect '+provider+' and select its text model first.')
        base={'model':config['model']}
    backend={'type':provider+'-'+kind,'model':base['model']}
    if kind=='code':
        from task_relay.code_runtime import available
        backend['runtime']=available()['id']
    validate(backend)
    return config,backend


def verification_backend(provider, model):
    # Existing browser connection checks also verify the same text model/key.
    return {'type':provider+('-browser' if provider in ('openai','qwen') else '-agent'),'model':model}


def limits_for(backend):
    return {**GEMINI_LIMITS,**({'output_bytes':100000000} if backend['type'] in CODE_TYPES else {'output_bytes':10000000} if backend['type'] in BROWSER_TYPES else {})}


def validate_input_sizes(items,backend):
    if backend['type'] in CODE_TYPES:
        if sum(i['bytes'] for i in items)>100000000:raise ValueError('Code input pack exceeds 100 MB.')
        return
    from .browser_contract import png_input,MAX_PNG_BYTES
    images=[i for i in items if backend['type'] in BROWSER_TYPES and png_input(i)]
    if sum(i['bytes'] for i in images)>MAX_PNG_BYTES:raise ValueError('Browser PNG input pack exceeds 10 MB.')
    if sum(i['bytes'] for i in items if i not in images)>MAX_INPUT_BYTES:raise ValueError('API text input pack exceeds 512 KB.')


def validate(backend):
    if not isinstance(backend, dict):raise ValueError('Specify an execution backend.')
    if backend.get('type') in CODE_TYPES:
        if set(backend)!={'type','model','runtime'} or not isinstance(backend['runtime'],str) or not re.fullmatch('[a-f0-9]{64}',backend['runtime']):raise ValueError('Code workers require an exact model and verified native runtime identity.')
        validate({'type':backend['type'].replace('-code','-agent'),'model':backend['model']})
        return ['files','python']
    if backend.get('type') == 'codex-cli':
        if not isinstance(backend.get('model'),str) or not backend['model'].strip():raise ValueError('Specify a fixed model.')
        if backend.get('reasoning') not in ('low','medium','high','xhigh','max','ultra'):raise ValueError('Specify reasoning effort')
        return ['files','shell']
    if backend.get('type') in ('gemini-agent','gemini-browser'):
        if set(backend) != {'type','model'} or not isinstance(backend['model'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}',backend['model']):
            raise ValueError('Gemini execution requires an exact model and no unsupported backend options.')
        return ['files','browser'] if backend['type']=='gemini-browser' else ['files']
    if backend.get('type') in ('openai-browser','qwen-browser',*(p+'-agent' for p in PROVIDERS if p!='gemini')):
        from task_relay.api_providers import model_name
        if set(backend)!={'type','model'}:raise ValueError('API execution requires an exact model and no additional backend options.')
        model_name(backend['model'])
        if backend['type']=='openrouter-agent' and backend['model'] in ('openrouter/auto','openrouter/free'):
            raise ValueError('Choose an exact OpenRouter worker model; automatic model routing is disabled.')
        return ['files','browser'] if backend['type'] in BROWSER_TYPES else ['files']
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
    if provider_for(backend)!='gemini':
        from task_relay.api_providers import endpoint
        provider=provider_for(backend)
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
    if provider not in PROVIDERS:raise ValueError('Unsupported worker provider')
    atomic(receipt_path(provider),{'verified_at':0})
    if provider!='gemini':
        from task_relay import api_providers as api
        config,backend=configured(provider) if provider in ('openai','qwen') else configured_worker(provider)
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
    if backend['type'] in CODE_TYPES:
        from task_relay.code_runtime import available as runtime_available
        runtime_available(backend['runtime'])
        return available({'type':backend['type'].replace('-code','-agent'),'model':backend['model']})
    if backend['type'] in FILE_TYPES and backend['type']!='gemini-agent':
        provider=provider_for(backend);config,current=configured_worker(provider)
        if backend!=current:raise ValueError('Selected worker model changed; no fallback.')
        try:r=json.loads(receipt_path(provider).read_text())
        except (OSError,ValueError):raise ValueError('Verify the '+provider+' worker connection before use.') from None
        if r.get('backend')!=verification_backend(provider,backend['model']) or r.get('fingerprint')!=fingerprint(config,backend) or not 0<=time.time()-r.get('verified_at',0)<=VERIFICATION_SECONDS:
            raise ValueError(provider+' worker verification is stale; refresh its connection check.')
        return
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
    for provider in PROVIDERS[1:]:
        item={**entry,'id':provider+'-agent','backend':None,'available':False}
        item.pop('blocker',None)
        try:
            _,item['backend']=configured_worker(provider);available(item['backend']);item['available']=True
        except (ValueError,RuntimeError) as exc:item['blocker']=str(exc)
        result.append(item)
    browser={**entry,'id':'gemini-browser','backend':({'type':'gemini-browser','model':entry['backend']['model']} if entry['backend'] else None),
        'tools':['files','browser'],'available':False,
        'limits':limits_for({'type':'gemini-browser'}),
        'permissions':'Declared text files, metadata-only PNG inputs and explicitly granted viewport PNG captures in dedicated profiles. Exact origins, interaction scope and transfer grants required. Page text and capture metadata go to the model; screenshot pixels are saved locally, not sent to it. No visual reasoning, shell/cookie/credential tools.'}
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
    from .worker_capabilities import abilities
    for provider in PROVIDERS:
        item={'id':provider+'-code','backend':None,'tools':['files','python'],'limits':limits_for({'type':provider+'-code'}),'available':False,
              'permissions':'Native sandbox: exact input copies, declared outputs, no network/subprocesses or host apps. Unknown code does not run with normal host permissions.'}
        try:
            _,item['backend']=configured_worker(provider,'code');available(item['backend']);item['available']=True
            from task_relay.code_runtime import available as runtime_available
            item['runtime_tools']=runtime_available(item['backend']['runtime'])['tools']
        except (ValueError,RuntimeError,OSError) as exc:item['blocker']=str(exc)
        result.append(item)
    for item in result:
        item['capabilities']=abilities(item['backend']) if item.get('backend') else []
    return result


if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in tuple('verify-'+p for p in PROVIDERS):raise SystemExit('Use: python3 -m orchestrator.executors verify-PROVIDER')
    print(json.dumps(probe(sys.argv[1].removeprefix('verify-')),indent=2))
