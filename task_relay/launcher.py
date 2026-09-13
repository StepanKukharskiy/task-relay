"""Loopback-only setup page backed by the existing local setup services."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import shlex
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from . import api_providers, credentials, diagnostics, host_apps, onboarding, releases
from .host import HOST, UnsupportedHost
from .relay_paths import ASSETS, PATHS


class LauncherError(ValueError):
    """A safe, user-facing validation error."""


def _require_host(operation):
    try:
        HOST.require_posix(operation)
    except UnsupportedHost:
        raise LauncherError('Setup controls are not supported on this host yet. See task-relay doctor.') from None


def _settings():
    path = PATHS.data / 'onboarding.json'
    value = onboarding.saved(path)
    if value.get('version', 1) != 1:
        raise LauncherError('This setup record needs a newer Task Relay version; it was preserved.')
    return value


def _save_settings(**values):
    value = _settings()
    value.update(version=1, **values)
    credentials.save(PATHS.data / 'onboarding.json', value)


def set_project(value):
    _require_host('Project setup')
    if not isinstance(value, str):
        raise LauncherError('Choose an existing absolute project directory.')
    try:
        project = diagnostics.project_folder(value, PATHS)
    except ValueError as exc:
        raise LauncherError(str(exc)) from None
    with onboarding.setup_lock():
        _save_settings(project=str(project))
    return {'project': str(project), 'message': 'Project saved. Existing tasks and file grants were not changed.'}


def set_provider(name, key='', model='', endpoint=''):
    _require_host('Provider setup')
    if name not in ('gemini', *api_providers.SPECS, 'later'):
        raise LauncherError('Choose one of the listed providers or Later.')
    if any(not isinstance(x, str) for x in (key, model, endpoint)):
        raise LauncherError('Provider fields must be text.')
    with onboarding.setup_lock():
        if name != 'later':
            if (PATHS.data / (name + '.json')).exists() and any(field.strip() for field in (key, model, endpoint)):
                raise LauncherError('This provider is already configured. New settings were not saved; use the CLI or /providers to change them.')
            def answer(prompt):
                return endpoint if prompt.startswith('Qwen regional') else model
            try:
                onboarding.setup_provider(name, ask=answer, hidden=lambda _: key)
            except ValueError as exc:
                # Setup owns these local validation messages; transport failures are
                # handled by the HTTP boundary without echoing exception payloads.
                raise LauncherError(str(exc)) from None
        _save_settings(provider=name)
    return {'provider': name, 'message': ('Provider selection saved.' if name == 'later'
            else 'Provider saved. Catalog access does not verify generation or quota.')}


def set_telegram(token=''):
    _require_host('Telegram setup')
    if not isinstance(token, str):
        raise LauncherError('Bot token must be text.')
    path = PATHS.data / 'config.json'
    with onboarding.setup_lock():
        existing = onboarding.saved(path)
        if path.exists():
            if token.strip():
                raise LauncherError('A bot is already configured. Use the CLI to change its credential deliberately.')
            if not credentials.configuration(path, 'token', enabled=False):
                raise LauncherError('Saved Telegram credential is unavailable. Diagnose it with task-relay credentials telegram.')
            username = existing.get('username')
            if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
                raise LauncherError('Saved bot username is invalid. Run task-relay telegram configure.')
        else:
            token = token.strip()
            if not token:
                raise LauncherError('Enter the token for a dedicated Telegram bot.')
            from .bridge import Telegram
            bot = Telegram(token)
            identity = bot.call('getMe')
            if bot.call('getWebhookInfo').get('url'):
                raise LauncherError('This bot already has a webhook. Use a new dedicated bot.')
            username = identity.get('username') if isinstance(identity, dict) else None
            if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
                raise LauncherError('Telegram did not return a valid bot username.')
            existing = {'token': token, 'username': username}
        try:
            paired = diagnostics.pairing(PATHS.state)
        except Exception:
            raise LauncherError('Saved pairing state is unreadable. Preserve it and run task-relay doctor.') from None
        if not paired and (not existing.get('pair_code') or existing.get('pair_expires', 0) <= time.time()):
            existing.update(pair_code=secrets.token_urlsafe(24), pair_expires=time.time() + 3600)
            credentials.save(path, existing)
        elif not path.exists():
            credentials.save(path, existing)
    return {'username': username, 'paired': paired,
            'pairing_url': None if paired else f"https://t.me/{username}?start={existing['pair_code']}",
            'message': 'Bot saved. Pairing and message delivery remain unverified.' if not paired
                       else 'Existing Telegram pairing retained; delivery remains unverified.'}


def update_check():
    _require_host('Release check')
    store = releases.Store(PATHS.data)
    try:
        store.check(force=True)
    finally:
        store.close()
    return {'message': 'Release metadata checked. No update was downloaded or installed.'}


def status():
    try:
        settings = _settings()
        saved_error = None
    except (ValueError, OSError):
        settings, saved_error = {}, 'Saved setup is unreadable; use task-relay doctor.'
    project = settings.get('project')
    project_info = {'name': None, 'path': None, 'available': False}
    if isinstance(project, str) and project:
        project_info.update(name=Path(project).name, path=project)
        try:
            diagnostics.project_folder(project, PATHS)
            project_info['available'] = True
        except (ValueError, OSError):
            pass
    providers = {name: credentials.status(PATHS.data / (name + '.json'))['available']
                 for name in ('gemini', *api_providers.SPECS)}
    selected = settings.get('provider')
    first_task = (f'/new {selected} {shlex.quote(project)} First task'
                  if selected in providers and providers[selected] and project_info['available'] else None)
    telegram = credentials.status(PATHS.data / 'config.json', 'token')['available']
    try:
        paired = diagnostics.pairing(PATHS.state)
    except Exception:
        paired = False
    try:
        report = diagnostics.inspect(PATHS, HOST)
    except Exception:
        report = {'ok': False, 'checks': [], 'scope': 'Local diagnostics unavailable; run task-relay doctor.'}
    try:
        cache = releases.cached(PATHS.data)
    except Exception:
        cache = {'checked': None, 'release': None, 'error': 'Release cache is unreadable.'}
    return {'version': releases.VERSION, 'platform': HOST.platform,
            'setup_error': saved_error, 'project': project_info,
            'selected_provider': selected, 'providers': providers,
            'first_task_command': first_task,
            'telegram': {'configured': telegram, 'paired': paired},
            'update': {'checked': cache.get('checked'), 'latest': (cache.get('release') or {}).get('version'),
                       'url': (cache.get('release') or {}).get('url'), 'error': cache.get('error')},
            'tools': host_apps.launcher_tools(HOST),
            'doctor': report}


class Handler(BaseHTTPRequestHandler):
    server_version = 'TaskRelayLauncher/1'
    sys_version = ''

    def log_message(self, *_):
        pass  # Never log URLs or submitted configuration.

    def _path(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            return None
        parsed = urlsplit(self.path)
        prefix = f'/l/{self.server.launcher_token}/'
        if parsed.query or parsed.fragment or not parsed.path.startswith(prefix):
            return None
        return parsed.path[len(prefix):]

    def _reply(self, code, body, mime='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, value):
        self._reply(code, json.dumps(value, separators=(',', ':')).encode())

    def do_GET(self):
        path = self._path()
        if path is None:
            return self._json(403, {'error': 'Unavailable launcher address.'})
        if path == 'api/status':
            try:
                return self._json(200, status())
            except Exception:
                return self._json(500, {'error': 'Local status is unavailable. Run task-relay doctor.'})
        assets = {'': ('launcher.html', 'text/html; charset=utf-8'),
                  'launcher.css': ('launcher.css', 'text/css; charset=utf-8'),
                  'launcher.js': ('launcher.js', 'text/javascript; charset=utf-8'),
                  'messages-icon.png': ('messages-icon.png', 'image/png')}
        for script in ('rich-text.js', 'vendor/marked.umd.js', 'vendor/purify.min.js', 'vendor/highlight.min.js'):
            assets[script] = (script, 'text/javascript; charset=utf-8')
        if path not in assets:
            return self._json(404, {'error': 'Not found.'})
        name, mime = assets[path]
        self._reply(200, (ASSETS / name).read_bytes(), mime)

    def do_POST(self):
        path = self._path()
        if path is None or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
            return self._json(403, {'error': 'Unavailable launcher origin.'})
        if self.headers.get('Content-Type') != 'application/json':
            return self._json(415, {'error': 'Expected JSON.'})
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            length = -1
        if not 0 <= length <= 16384:
            return self._json(413, {'error': 'Request is too large.'})
        try:
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            return self._json(400, {'error': 'Invalid JSON object.'})
        try:
            if path == 'api/project':
                result = set_project(value.get('path'))
            elif path == 'api/provider':
                result = set_provider(value.get('name'), value.get('key', ''),
                                      value.get('model', ''), value.get('endpoint', ''))
            elif path == 'api/telegram':
                result = set_telegram(value.get('token', ''))
            elif path == 'api/update-check':
                result = update_check()
            else:
                return self._json(404, {'error': 'Not found.'})
            return self._json(200, result)
        except LauncherError as exc:
            return self._json(400, {'error': str(exc)})
        except Exception:
            return self._json(500, {'error': 'Action could not finish. Saved steps remain; run task-relay doctor for details.'})


def make_server(port=0):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.launcher_token = secrets.token_urlsafe(32)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-open', action='store_true', help='Print the local URL without opening a browser')
    parser.add_argument('--port', type=int, default=0, help='Loopback port; defaults to an available port')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535.')
    with make_server(args.port) as server:
        url = f'http://127.0.0.1:{server.server_port}/l/{server.launcher_token}/'
        print('Task Relay launcher: ' + url, flush=True)
        print('This page runs on this computer only. Press Ctrl+C to close it.', flush=True)
        if not args.no_open:
            threading.Timer(0.1, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
