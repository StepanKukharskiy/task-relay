"""Local browser attachment and human sign-in, isolated from orchestration."""
from contextlib import contextmanager
import json
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler

from .host import HOST


def local_endpoint(value,websocket=False):
    u=urlsplit(value)
    if (u.scheme!=('ws' if websocket else 'http') or u.hostname not in ('127.0.0.1','::1')
            or not u.port or u.username or u.password or u.query or u.fragment
            or '\\' in value or any(ord(c)<32 for c in value)):
        raise ValueError('Select a local debugging endpoint using a loopback IP and explicit port.')
    if websocket:
        if not u.path.startswith('/devtools/browser/'):raise ValueError('Expected a browser debugging endpoint.')
    elif u.path not in ('','/'):
        raise ValueError('Use the debugging server origin without a path.')
    return value


def resolve_endpoint(endpoint):
    """Bind to this browser instance, not a port which a later browser may reuse."""
    HOST.require_posix('Local browser attachment')
    local_endpoint(endpoint)
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=build_opener(ProxyHandler({}),NoRedirect())
    with opener.open(Request(endpoint.rstrip('/')+'/json/version'),timeout=5) as response:
        raw=response.read(16001)
    if len(raw)>16000:raise ValueError('Browser response is too large.')
    socket=json.loads(raw)['webSocketDebuggerUrl']
    local_endpoint(socket,True)
    if urlsplit(socket).netloc!=urlsplit(endpoint).netloc:raise ValueError('Browser endpoint identity changed.')
    return socket


def login_required(page):
    # Read only field types/visibility and challenge metadata; never values.
    if any(s in page.title().lower() for s in ('just a moment','verify you are human','security verification')):return True
    for frame in page.frames:
        u=urlsplit(frame.url)
        if u.hostname=='challenges.cloudflare.com':return True
        if frame.locator('input[type="password"]:visible,input[autocomplete="one-time-code"]:visible,input[autocomplete="current-password"]:visible,input[type="email"]:visible').count():return True
    return False


def attach(runtime,endpoint,*,timeout=10000):
    local_endpoint(endpoint,True)
    try:
        remote=runtime.chromium.connect_over_cdp(endpoint,timeout=timeout,no_defaults=True)
    except Exception:
        raise ValueError('The selected account browser is unavailable. Reattach it explicitly; saved site confirmations must be renewed.') from None
    if len(remote.contexts)!=1:
        remote.close()
        raise ValueError('Choose a browser with exactly one default context.')
    return remote


@contextmanager
def context(data,access,headless=False):
    from .general_browser import profile_lock
    from .browser_sites import PROFILE
    HOST.require_posix('Account browser sessions')
    from playwright.sync_api import sync_playwright
    with profile_lock(data,PROFILE) as root,sync_playwright() as runtime:
        if access.endpoint:
            remote=attach(runtime,access.endpoint)
            try:yield remote.contexts[0],True
            # For connect_over_cdp, Browser.close disconnects its transport;
            # it does not close the external Chrome process or context.
            finally:remote.close()
        else:
            owned=runtime.chromium.launch_persistent_context(str(root/'profile'),headless=headless,
                        accept_downloads=False,permissions=[],service_workers='block')
            try:yield owned,False
            finally:owned.close()


@contextmanager
def manual(data,access):
    with context(data,access) as (browser,_):
        page=browser.new_page()
        try:yield page
        finally:
            if not page.is_closed():page.close()


@contextmanager
def browser(data,policy,headless=False):
    from .browser_sites import Access
    from .general_browser import PlaywrightDriver
    access=Access(data)
    for site in policy['origins']:access.check(site)
    with context(data,access,headless) as (browser,attached):
        driver=PlaywrightDriver(browser,policy,access=access,attached=attached)
        try:yield driver
        finally:driver.detach()
