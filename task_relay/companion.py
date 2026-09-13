"""Small local companion views; no task dispatch or background usage scans."""
from contextlib import closing
import json
import re
import sqlite3
import time

from .relay_paths import PATHS
from .host import UnsupportedHost


def conversation(paths=PATHS):
    """Return only a validated bot address, never its credential or pairing code."""
    from . import onboarding
    try:
        username = onboarding.saved(paths.data / 'config.json').get('username')
    except (ValueError, OSError):
        username = None
    return {'url': f'https://t.me/{username}' if isinstance(username, str) and
            re.fullmatch(r'[A-Za-z0-9_]{5,32}', username) else None}


def approval_detail(task_id, paths=PATHS):
    from .desktop_approvals import pending
    from .desktop_tasks import _database, DesktopTaskError
    if not isinstance(task_id, str) or not task_id or len(task_id) > 180:
        raise DesktopTaskError('Choose a pending decision.')
    if not paths.state.is_file():
        raise DesktopTaskError('Saved decisions are unavailable.')
    with closing(_database(paths)) as db:
        task = db.execute('SELECT title FROM watched WHERE id=?', (task_id,)).fetchone()
        if not task:
            raise DesktopTaskError('This task is no longer available.')
        return {'task_id': task_id, 'title': task['title'] or task_id,
                'approvals': pending(db, task_id)}


def messages_state(paths=PATHS, clock=time.time):
    """Read the selected installation only; never initialize or repair its store."""
    result = {'paired': False, 'task_id': None, 'uncertain': 0, 'error': None,
              'health': None, 'fresh': False, 'paused': (paths.messages / 'paused').exists()}
    try:
        if paths.state.is_file():
            with closing(sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'messages_settings' in tables:
                    settings = {r[0]: json.loads(r[1]) for r in db.execute(
                        "SELECT key,value FROM messages_settings WHERE key IN ('chat','task_id')")}
                    result.update(paired=bool(settings.get('chat')), task_id=settings.get('task_id'))
                if 'messages_delivery' in tables:
                    result['uncertain'] = db.execute(
                        "SELECT count(*) FROM messages_delivery WHERE status='uncertain'").fetchone()[0]
        health_file = paths.messages / 'health.json'
        if health_file.is_file():
            health = json.loads(health_file.read_text())
            result['fresh'] = 0 <= clock() - float(health.get('updated_at', 0)) < 20
            result['health'] = health.get('status')
            result['health_detail'] = str(health.get('detail',''))[:1000]
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
        result['error'] = 'Messages status could not be read. Existing records were preserved.'
    return result


def status():
    from . import launcher
    from .desktop_macos import DesktopService
    from .desktop_messages import MessagesService
    from .desktop_approvals import inbox
    from .channel_policy import snapshot
    info = launcher.status()
    # No task catalog, conversation history, tool discovery beyond launcher status,
    # recursive storage scans, provider calls or mutable state initialization.
    folders = [
        {'name': 'Relay data', 'path': str(PATHS.data), 'purpose': 'Saved connections, task history and settings'},
        {'name': 'Task workspaces', 'path': str(PATHS.workspaces), 'purpose': 'Files created while working on tasks'},
        {'name': 'Generated files', 'path': str(PATHS.generated), 'purpose': 'Task outputs and exports'},
    ]
    project = info.get('project', {}).get('path')
    if project:
        folders.append({'name': 'Selected project', 'path': project, 'purpose': 'Default folder selected for new work'})
    result = {'setup': info, 'conversation': conversation(), 'folders': folders}
    from .managed_browser import status as browser_status
    result['browser'] = browser_status()
    from .cloud_providers import connections
    result['media_connections'] = connections()
    from .capability_defaults import snapshot as model_defaults
    try:
        result['model_defaults'] = model_defaults()
    except (OSError, ValueError, sqlite3.Error):
        result['model_defaults'] = {'error': 'Model settings could not be read. Saved choices were preserved.'}
    for name, operation in (('service', lambda: DesktopService().status()),
                            ('channels', snapshot),
                            ('messages', lambda: MessagesService().status()),
                            ('decisions', inbox)):
        try:
            result[name] = operation()
        except (OSError, ValueError, sqlite3.Error, UnsupportedHost):
            result[name] = {'error': f'{name.capitalize()} status is unavailable.'}
    return result
