"""Companion browser preference and setup, shared with the Perplexity worker."""
from contextlib import contextmanager

from . import credentials, host_managed_chrome as chrome
from .host import HOST, UnsupportedHost
from .relay_paths import PATHS


def preference(data):
    path = data/'browser-use.json'
    if not path.exists() and not path.is_symlink():
        return None
    value = credentials.private_json(path)
    if value.get('version') != 1 or type(value.get('enabled')) is not bool:
        raise ValueError('Browser settings need a compatible Task Relay version. Saved settings were preserved.')
    if type(value.get('manual_sign_in', False)) is not bool:
        raise ValueError('Browser sign-in state is invalid. Saved settings were preserved.')
    return value


def status(paths=PATHS):
    # Reading the companion never starts Chrome, connects to pages or claims login.
    result = {'enabled': False, 'available': False, 'manual_sign_in': False, 'error': None}
    try:
        saved = preference(paths.data)
        result['enabled'] = bool(saved and saved['enabled'])
        result['manual_sign_in'] = bool(saved and saved.get('manual_sign_in'))
        result['available'] = chrome.chrome_path() is not None
        if not result['available']:
            result['error'] = 'Google Chrome is required.'
        elif result['enabled']:
            result['error'] = saved.get('error')
    except (OSError, ValueError, UnsupportedHost) as exc:
        result['error'] = str(exc)
    return result


def configure(enabled, paths=PATHS):
    if type(enabled) is not bool:
        raise ValueError('Choose whether Browser use is on or off.')
    if enabled:
        return open_browser(paths, enable=True)
    with chrome.setup_lock(paths.data) as root:
        previous = preference(paths.data) or {'version': 1}
        # Persist the user's choice before launching. Failed/interrupted setup can
        # be resumed, without silently reverting to a different browser profile.
        saved = {**previous, 'enabled': enabled, 'error': None}
        credentials.save(paths.data/'browser-use.json', saved)
        if not enabled:
            return {'message': 'Browser use is off. New managed browser jobs are blocked. Running work can finish; saved sign-ins are retained.'}
        return _open(paths, root, saved)


def _open(paths, root, saved):
    try:
        HOST.browser_python(paths.install, paths.data)
        chrome.open_manual(root)
    except (OSError, ValueError, UnsupportedHost) as exc:
        saved['error'] = str(exc)
        credentials.save(paths.data/'browser-use.json', saved)
        return {'message': 'Browser setup needs attention: '+str(exc)}
    credentials.save(paths.data/'browser-use.json', {**saved, 'error': None})
    return {'message': 'Chrome is opening for manual sign-in. Open the websites you want Relay to use and sign in there, then choose Done signing in. Chrome Sync is unnecessary. Browser jobs are paused during sign-in.'}


def open_browser(paths=PATHS, *, enable=False):
    # Same lock order as jobs. Never close Chrome while a job is using its profile.
    with sign_in_lock(paths), chrome.setup_lock(paths.data) as root:
        saved = preference(paths.data) or {'version': 1, 'enabled': False}
        if not enable and not saved['enabled']:
            raise ValueError('Turn Browser use on first.')
        saved = {**saved, 'enabled': True, 'manual_sign_in': True, 'error': None}
        credentials.save(paths.data/'browser-use.json', saved)
        return _open(paths, root, saved)


def finish_sign_in(paths=PATHS):
    with sign_in_lock(paths), chrome.setup_lock(paths.data) as root:
        saved = preference(paths.data)
        if not saved or not saved['enabled']:
            raise ValueError('Turn Browser use on first.')
        if saved.get('manual_sign_in'):
            chrome.stop_owned(root)
            credentials.save(paths.data/'browser-use.json', {**saved, 'manual_sign_in': False, 'error': None})
    return {'message': 'Manual sign-in finished. Relay will reopen this saved profile for your next browser job and check the website session before submitting.'}


@contextmanager
def sign_in_lock(paths):
    from .perplexity_browser import profile_lock
    try:
        with profile_lock(paths.data):yield
    except BlockingIOError:
        raise ValueError('A browser job is using this profile. Wait for it to finish before opening sign-in.') from None


@contextmanager
def page(data):
    with chrome.setup_lock(data) as root:
        saved = preference(data)
        if not saved or not saved['enabled']:
            raise ValueError('Browser use is off. Enable it in Task Relay Settings.')
        if saved.get('manual_sign_in'):
            raise ValueError('Complete sign-in in Chrome, then choose Done signing in in Task Relay Settings. No research was submitted.')
        from playwright.sync_api import sync_playwright
        from .host_browser_accounts import attach
        socket = chrome.ensure(root)
    with sync_playwright() as runtime:
        remote = attach(runtime, socket)
        try:
            # Each job owns its new tab; its receipt controls any submission.
            yield remote.contexts[0].new_page()
        finally:
            remote.close()
