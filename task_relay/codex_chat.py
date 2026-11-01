"""ChatGPT-authenticated Codex selection for the existing conversation loop.

No credentials are read here. The shared transport checks account type and the
qualified tool boundary before inference; received fragments use normal routing.
"""
from contextlib import contextmanager, closing, ExitStack
import json
import sqlite3

from . import credentials
from .relay_paths import PATHS

MODELS = ('gpt-6.1-sol', 'gpt-6-sol')


class SetupError(ValueError):
    """Local pre-inference setup failure safe to show in the saved conversation."""


def read_config(paths=PATHS):
    path = paths.data / 'codex-chat.json'
    if not path.exists(): return None
    value = credentials.private_json(path)
    if set(value) != {'version', 'model'} or value['version'] != 1:
        raise ValueError('Codex chat settings need repair; saved settings were retained.')
    from .api_providers import model_name
    model_name(value['model'])
    from .capability_defaults import overlay
    return overlay('codex', value, paths.state)


def select(model='', paths=PATHS):
    from .desktop_node_setup import backend
    from orchestrator.codex_transport import configuration
    model = model.strip() or MODELS[0]
    configuration(backend(dict(provider='codex', id=model)))
    credentials.save(paths.data / 'codex-chat.json', dict(version=1, model=model))
    from .capability_defaults import clear_text
    with closing(sqlite3.connect(paths.state)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        clear_text(db)
        db.execute('CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT)')
        db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('orchestrator_provider', json.dumps('codex')))
    return {'message': 'Codex selected. Uses ChatGPT sign-in and account limits, without API billing. Sign-in is checked on the first chat request.'}


@contextmanager
def client(model, receipt):
    from .desktop_node_setup import backend
    from orchestrator.codex_transport import Client, configuration
    selected = backend(dict(provider='codex', id=model))
    try: config, selected = configuration(selected)
    except ValueError as exc: raise SetupError(str(exc)) from None
    control = receipt.with_suffix('.codex')
    # An interrupted conversation is inspected, never silently started again.
    if control.exists():
        raise SetupError('This Codex conversation already has an execution receipt; inspect its saved outcome before a new attempt.')
    with ExitStack() as stack:
        try: transport = stack.enter_context(Client(config, selected, control, 300))
        except ValueError as exc: raise SetupError(str(exc)) from None
        yield transport
