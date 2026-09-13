"""Capability choices shared by desktop setup and existing execution adapters.

Only preferences change here. Jobs retain their frozen inputs, models and receipts.
"""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import time

from .relay_paths import PATHS

CAPABILITIES = {'text': ('gemini', 'openai', 'qwen', 'deepseek', 'openrouter'),
                'image': ('gemini', 'openai', 'openrouter','runway','higgsfield'), 'video': ('gemini','runway','higgsfield'),
                'mesh': ('meshy',)}
INSTRUCTIONS = '''Use snapshot.capabilities.model_defaults for new work when the user
has not chosen a provider/model. Explicit request choices and an existing task's
model take precedence. Defaults never change approved plans or queued jobs.
For images, a Gemini default uses generate_image; other providers use their
registered production image operation. Do not silently switch a disconnected
default to another provider. Gemini video clips use the existing task /video path;
Runway/Higgsfield use registered video operations. Meshy uses meshy.mesh for a
text-to-3D untextured GLB. Texturing and image-to-3D are not implemented. Editable
modeling/rendering uses available Blender/Rhino operations. Cloud media parameters
include a self-contained generation prompt: preserve the user's scope without
Relay controls. Runway reference images use @ref1, @ref2, @ref3 in input order.
Higgsfield and Meshy currently support text inputs only; never drop requested images.
Never treat text credentials as proof of image, video or 3D generation support.
For media/modeling status, use snapshot.generation_jobs and the existing production
records. They expose the original receipt IDs and frozen models across execution
paths. A completed attempt is not user acceptance or proof of messenger delivery.
'''


def read(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_model_defaults'").fetchone():
        return {'version': 1, 'revision': 0, 'choices': {}}
    row = db.execute('SELECT value FROM relay_model_defaults WHERE id=1').fetchone()
    try:
        value = json.loads(row[0])
        if (set(value) != {'version', 'revision', 'choices'} or value['version'] != 1
                or type(value['revision']) is not int or value['revision'] < 0 or not isinstance(value['choices'], dict)):
            raise ValueError
        for cap, choice in value['choices'].items():
            if (cap not in CAPABILITIES or set(choice) != {'provider', 'model'}
                    or choice['provider'] not in CAPABILITIES[cap] or not isinstance(choice['model'], str) or not choice['model']):
                raise ValueError
    except (TypeError, KeyError, ValueError):
        raise ValueError('Saved model defaults need repair. Existing settings were preserved.') from None
    return value


def load(path):
    path = Path(path)
    if not path.exists():
        return {'version': 1, 'revision': 0, 'choices': {}}
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        return read(db)


def overlay(provider, config, path):
    if not config:
        return config
    result = copy.deepcopy(config)
    for cap, choice in load(path)['choices'].items():
        if choice['provider'] == provider:
            if cap == 'text' and provider != 'gemini':
                result['model'] = choice['model']
            else:
                result.setdefault('models', {})[cap] = choice['model']
    return result


def write(db, value):
    value['revision'] += 1
    db.execute('CREATE TABLE IF NOT EXISTS relay_model_defaults(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS relay_model_default_changes(revision INTEGER PRIMARY KEY,created REAL NOT NULL,value TEXT NOT NULL)')
    raw = json.dumps(value, sort_keys=True)
    db.execute('INSERT OR REPLACE INTO relay_model_defaults VALUES (1,?)', (raw,))
    db.execute('INSERT INTO relay_model_default_changes VALUES (?,?,?)', (value['revision'], time.time(), raw))


def update_selected(db, cap, provider, model):
    """Keep /providers changes coherent with a selected desktop default."""
    value = read(db)
    if value['choices'].get(cap, {}).get('provider') != provider:
        return False
    value['choices'][cap]['model'] = model
    write(db, value)
    return True


def clear_text(db, provider=None):
    value = read(db)
    if provider and value['choices'].get('text', {}).get('provider') == provider:
        return
    if value['choices'].pop('text', None):
        write(db, value)


def models(provider, cap, config):
    from . import gemini, api_providers as api
    from .providers import CANDIDATES
    from .cloud_providers import PROVIDERS
    if provider in PROVIDERS: return PROVIDERS[provider]['models'].get(cap, [])
    current = (config.get('model', api.SPECS[provider]['model']) if cap == 'text' and provider != 'gemini'
               else config.get('models', {}).get(cap, gemini.DEFAULT_MODELS.get(cap) if provider == 'gemini' else None))
    if provider == 'gemini':
        def compatible(name):
            if cap == 'image': return 'image' in name
            if cap == 'video': return name.startswith('veo-')
            return name.startswith('gemini-') and not any(x in name for x in ('image', 'tts', 'robotics', 'embedding'))
        available = config.get('catalog', [])
        names = [m for m in available if isinstance(m, str) and compatible(m)]
        if not available: names += CANDIDATES[cap]
    elif cap == 'image':
        names = config.get('image_catalog', config.get('catalog', []) if provider == 'openai' else [])
        if provider == 'openai': names = [m for m in names if m.startswith('gpt-image-')]
    else:
        names = config.get('catalog', [])
    # Retain a previously selected exact ID even when catalog discovery is stale.
    return list(dict.fromkeys(([current] if current else []) + names))


def snapshot(paths=PATHS):
    from . import credentials
    value = load(paths.state)
    chosen_text = None
    if paths.state.is_file():
        with closing(sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='kv'").fetchone():
                row = db.execute("SELECT value FROM kv WHERE key='orchestrator_provider'").fetchone()
                chosen_text = json.loads(row[0]) if row else None
    configs = {}
    for name in dict.fromkeys(p for providers in CAPABILITIES.values() for p in providers):
        try:
            config = credentials.configuration(paths.data / (name + '.json'))
        except credentials.CredentialError:
            config = None
        if config: configs[name] = overlay(name, config, paths.state)
    rows = []
    for cap, providers in CAPABILITIES.items():
        options = [dict(provider=p, models=models(p, cap, configs[p])) for p in providers if p in configs]
        options = [x for x in options if x['models']]
        choice = value['choices'].get(cap)
        inherited = choice is None
        if inherited:
            provider = (chosen_text or next((p for p in CAPABILITIES['text'] if p in configs), None)) if cap == 'text' else 'gemini'
            option = next((x for x in options if x['provider'] == provider), None)
            if option: choice = dict(provider=provider, model=option['models'][0])
            elif cap == 'text' and chosen_text: choice = dict(provider=chosen_text, model=None)
        rows.append(dict(capability=cap, selected=choice, inherited=inherited, options=options,
                         available=bool(options), selected_available=not choice or choice['provider'] in configs))
    return dict(**value, capabilities=rows,
                limitation='Saved connections and adapter candidates; generation access and quota are checked when used.')


def update(value, paths=PATHS):
    if not isinstance(value, dict) or set(value) != {'revision', 'capability', 'provider', 'model'}:
        raise ValueError('Choose a capability, connected provider and model.')
    cap, provider, model = (value[k] for k in ('capability', 'provider', 'model'))
    if (not isinstance(cap, str) or cap not in CAPABILITIES or provider not in CAPABILITIES[cap]
            or not isinstance(model, str) or type(value['revision']) is not int):
        raise ValueError('This provider does not support the selected capability.')
    if not paths.state.is_file():
        raise ValueError('Complete Relay setup before choosing task models.')
    from . import gemini, api_providers as api
    (gemini.model_name if provider == 'gemini' else api.model_name)(model)
    with closing(sqlite3.connect(paths.state.as_uri() + '?mode=rw', uri=True, timeout=5)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            current = read(db)
            if current['revision'] != value['revision']:
                raise ValueError('Model defaults changed. Refresh before saving again.')
            options = next(x['options'] for x in snapshot(paths)['capabilities'] if x['capability'] == cap)
            if not any(x['provider'] == provider and model in x['models'] for x in options):
                raise ValueError('Connect this provider and choose one of its available model candidates.')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='provider_jobs'").fetchone() and db.execute(
                    "SELECT 1 FROM provider_jobs WHERE provider=? AND operation!='browser_research' AND status IN ('queued','running')", (provider,)).fetchone():
                raise ValueError('Finish provider setup before changing models.')
            current['choices'][cap] = dict(provider=provider, model=model)
            write(db, current)
            if cap == 'text':
                db.execute('CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT)')
                db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('orchestrator_provider', json.dumps(provider)))
    return {'message': 'Default saved for future work. Existing tasks and approved jobs retain their models.'}
