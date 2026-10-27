"""Node inspector projection over existing provider connections and adapters."""
import copy
from .relay_paths import PATHS
from . import credentials, capability_defaults
from orchestrator import executors, execution


def backend(choice):
    if not isinstance(choice,dict) or set(choice)-{'provider','id','reasoning'} or not {'provider','id'}<=set(choice):
        raise ValueError('Choose a provider and an exact model ID')
    provider=choice['provider']
    if provider=='codex':
        from orchestrator.codex_transport import POLICY
        result=dict(type='codex-agent',model=choice['id'],reasoning=choice.get('reasoning','high'),budget_semantics=POLICY)
    else:
        if provider not in executors.PROVIDERS or 'reasoning' in choice:raise ValueError('Unsupported model settings')
        result=dict(type=provider+'-agent',model=choice['id'])
    executors.validate(result)
    return result


def snapshot():
    rows=capability_defaults.snapshot()['capabilities']
    text=next(r for r in rows if r['capability']=='text')
    # No model discovery call here. Exact IDs may be entered and verified explicitly.
    providers=[dict(provider='codex',models=['gpt-6.1-sol','gpt-6-sol'],connected=None,authentication='Existing ChatGPT Codex login')]+text['options']
    from orchestrator.operation_definition import catalog
    operations={}
    for row in catalog():
        op=row['id'];family=op.split('.')[0]
        provider=family if family in ('gemini','openai','openrouter','runway','higgsfield','meshy') else 'gemini' if op in ('web.sources','web.sources.prepared','web.sources.coverage') else 'codex' if op.endswith('.codex') else None
        operations[op]=dict(worker=op not in execution.REGISTRY,provider=provider)
        connection=execution.REGISTRY.get(op,{}).get('node_ui',{}).get('connection')
        if connection:operations[op]['connection']=connection
    from orchestrator.perplexity_search import setup as browser_setup
    return dict(text=providers,capabilities=rows,operations=operations,browser=browser_setup(),credential_file=str(PATHS.data/'.env'),
                limitation='Connection checks read model metadata only. Running API nodes may incur provider charges.')


def connect(value):
    from .desktop_plans import DesktopPlanError
    if not isinstance(value,dict) or set(value)!={'provider','key','model'}:raise DesktopPlanError('Supply provider, key and model only')
    from . import api_providers,gemini,cloud_providers,onboarding
    provider=value['provider'];key=value['key'];model=value['model']
    if provider not in (*executors.PROVIDERS,*cloud_providers.PROVIDERS):raise DesktopPlanError('Choose an API provider')
    if not isinstance(model,str) or not model.strip():raise DesktopPlanError('Choose a model before connecting')
    if not isinstance(key,str) or not key.strip() or len(key)>4000 or any(c in key for c in '\r\n\0'):
        raise DesktopPlanError('Enter a nonempty single-line API key. Existing credentials are unchanged.')
    if provider in executors.PROVIDERS:
        try:backend(dict(provider=provider,id=model))
        except ValueError:raise DesktopPlanError('Choose a valid model ID for this provider before connecting.') from None
    if provider=='higgsfield' and (not isinstance(key,str) or key.count(':')!=1 or not all(key.split(':'))):
        raise DesktopPlanError('Higgsfield needs ID:SECRET')
    name=provider.upper()+'_API_KEY'
    with onboarding.setup_lock():
        path=PATHS.data/(provider+'.json')
        config=credentials.private_json(path) if path.exists() else {}
        credentials.save_dotenv(PATHS.data/'.env',name,key)
        config.pop('api_key',None)
        config.update(enabled=True,api_key_ref=dict(source='dotenv',path=str(PATHS.data/'.env'),name=name))
        if provider=='gemini':config.setdefault('models',{}).setdefault('text',model)
        elif provider in api_providers.SPECS:
            config.setdefault('model',model);config.setdefault('base_url',api_providers.endpoint(provider))
        else:
            for cap,names in cloud_providers.PROVIDERS[provider]['models'].items():config.setdefault('models',{}).setdefault(cap,names[0])
        credentials.save(path,config)
    return dict(message='Connection saved in the private .env file. No provider request was sent.')


def verify(value):
    if not isinstance(value,dict) or set(value)!={'provider','model'}:raise ValueError('Choose provider and model')
    if value['provider']=='codex':
        executors.available(backend(dict(provider='codex',id=value['model'])))
        return dict(message='Codex access and the qualified tool runtime are available. ChatGPT sign-in is checked when execution starts; no generation ran.')
    result=executors.probe(value['provider'],value['model'])
    return dict(message=result['limitation'])


def configure_codex(value):
    """Select existing proved runtime bytes; never build, execute or infer approval."""
    from pathlib import Path
    from orchestrator.codex_gate import selected
    from . import credentials
    if set(value)!={'path'} or not isinstance(value['path'],str):raise ValueError('Choose an existing qualified runtime receipt')
    source=Path(value['path'])
    if source.is_symlink() or source.stat().st_size>100000:raise ValueError('Choose a regular qualification receipt')
    checked=selected(source)
    import json,hashlib
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=checked['gate_receipt_sha256']:raise ValueError('Receipt changed during selection')
    credentials.save(PATHS.data/'codex-runtime/qualified.json',json.loads(raw))
    selected(PATHS.data/'codex-runtime/qualified.json')
    return dict(message='Qualified Codex runtime selected. No model call ran; ChatGPT sign-in is checked on execution.')
