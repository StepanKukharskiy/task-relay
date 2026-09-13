"""Optional standalone Perplexity Search browser pilot; no model API or Telegram routing."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import re
from urllib.parse import urlsplit,urljoin

from .browser_jobs import Journal,conversation_url,execute,fingerprint,SubmissionNotAttempted
from .host import HOST,UnsupportedHost
from .relay_paths import PATHS

HOME_URL='https://www.perplexity.ai/'


def same_submission_context(baseline, current):
    # The empty homepage has changing suggestions/labels during hydration. Its
    # whole-page prose is not conversation identity. Existing threads stay strict.
    if (baseline.get('url')==current.get('url')==HOME_URL
            and baseline.get('queries')==current.get('queries')==0
            and baseline.get('answers')==current.get('answers')==0
            and baseline.get('ready') is True and current.get('ready') is True):
        return True
    return fingerprint(current)==fingerprint(baseline)


@contextmanager
def profile_lock(data):
    # Native privacy/locking enforcement stays behind the host boundary.
    HOST.require_posix('Browser profile privacy and locking')
    data=Path(data).resolve();data.mkdir(parents=True,exist_ok=True,mode=0o700)
    root=data/'browser-perplexity'
    if root.is_symlink():raise ValueError('Browser profile directory must not be a symlink')
    root.mkdir(mode=0o700,exist_ok=True);os.chmod(root,0o700)
    lock=root/'profile.lock'
    if lock.is_symlink():raise ValueError('Browser lock must not be a symlink')
    with lock.open('a') as stream:
        HOST.lock(stream)
        yield root


class PerplexityPage:
    def __init__(self,page):self.page=page

    def open(self,url=None):
        self.page.goto(conversation_url(url) if url else HOME_URL,wait_until='domcontentloaded',timeout=30000)
        self.page.get_by_role('textbox').wait_for(state='visible',timeout=30000)

    def snapshot(self):
        # Submission can briefly show a same-site transitional URL before the
        # saved UUID appears. Observe that state without treating it as a saved
        # result; the journal validates the canonical conversation on completion.
        current=urlsplit(self.page.url)
        if current.scheme!='https' or current.netloc!='www.perplexity.ai':
            raise ValueError('Perplexity tab left its authorized origin; page text was not read.')
        main=self.page.get_by_role('main')
        text=main.inner_text(timeout=5000)
        if len(text)>250000:raise ValueError('Conversation exceeds the bounded browser text limit')
        return {'url':self.page.url,'text':text,
                'queries':main.get_by_role('button',name='Edit query',exact=True).count(),
                # Quoted text can also expose a Copy button. Count only the
                # answer action group observed with sibling Share/Fork controls.
                'answers':main.get_by_role('button',name='Copy',exact=True).locator('xpath=..')
                    .filter(has=self.page.get_by_role('button',name='Share',exact=True))
                    .filter(has=self.page.get_by_role('button',name='Fork',exact=True)).count(),
                'ready':main.get_by_role('textbox').count()==1 and
                        main.get_by_role('button',name='Stop response',exact=False).count()==0}

    def check_ready(self,snapshot):
        # Fail closed on logged-out, changed, busy or prefilled UI. Do not operate
        # login forms, CAPTCHAs, billing dialogs, files or Computer workflows.
        if self.page.get_by_role('button',name='Sign In',exact=True).count():
            raise ValueError('Sign in to Perplexity in the Relay browser before retrying. In Task Relay Settings, use Browser use → Open browser / sign in.')
        if not self.page.get_by_role('button',name='Profile avatar',exact=False).count():
            raise ValueError('Authenticated account UI has not been verified')
        if self.page.get_by_role('dialog').count():raise ValueError('Resolve the visible browser dialog manually')
        if not snapshot['ready'] or snapshot['queries']!=snapshot['answers']:
            raise ValueError('Conversation is busy or its controls are not recognized')
        if self.page.get_by_role('textbox').inner_text().strip():
            raise ValueError('The browser contains an existing draft; it was not overwritten')
        if not self.page.get_by_role('button',name='Search',exact=True).get_attribute('aria-pressed')=='true':
            raise ValueError('Select ordinary Search mode manually; other modes are outside this pilot')

    def submit(self,prompt,baseline):
        try:
            current=self.snapshot();self.check_ready(current)
            if not same_submission_context(baseline,current):
                changed=','.join(k for k in ('url','queries','answers','ready','text') if baseline.get(k)!=current.get(k))
                raise ValueError('Conversation changed before submission ('+changed+')')
            box=self.page.get_by_role('textbox');box.fill(prompt)
            # The empty composer exposes voice mode. Submit is rendered only
            # after its input handler processes the exact draft.
            submit=self.page.get_by_role('main').get_by_role('button',name='Submit',exact=True)
            try:submit.wait_for(state='visible',timeout=5000)
            except Exception as exc:
                raise ValueError('Search Submit button did not become uniquely visible after entering the draft; no click was sent') from exc
            current=self.snapshot()
            if any(current[k]!=baseline[k] for k in ('url','queries','answers')) or not current['ready']:
                raise ValueError('Conversation changed while entering the draft; no click was sent')
            if self.page.get_by_role('dialog').count() or self.page.get_by_role('button',name='Search',exact=True).get_attribute('aria-pressed')!='true':
                raise ValueError('Search mode or dialog changed; no click was sent')
            if box.inner_text()!=prompt:
                raise ValueError('Prompt text was not entered exactly; no Submit click was sent')
        except Exception as exc:
            # This boundary ends before the first potentially submitting action.
            raise SubmissionNotAttempted(str(exc)) from exc
        # Exactly one click; any exception from this point remains uncertain.
        submit.click(timeout=5000)

    def pause(self):self.page.wait_for_timeout(1000)

    def _login_origin(self):
        url=urlsplit(self.page.url)
        if url.scheme!='https' or url.netloc!='www.perplexity.ai':
            raise ValueError('Continue sign-in in the browser; this domain cannot receive chat credentials.')

    def begin_login(self):
        self.page.goto(HOME_URL,wait_until='domcontentloaded',timeout=30000)
        self._login_origin()
        button=self.page.get_by_role('button',name='Sign In',exact=True)
        if button.count()==1 and button.is_visible():button.click(timeout=5000)

    def _login_controls(self,kind):
        self._login_origin()
        selector={'email':'input[type="email"]:visible',
                  'code':'input[autocomplete="one-time-code"]:visible'}.get(kind)
        if not selector:raise ValueError('This website adapter does not support that login field.')
        field=self.page.locator(selector)
        if field.count()!=1:raise ValueError('Login field is not uniquely recognized.')
        form=field.locator('xpath=ancestor::form[1]')
        if form.count()!=1:raise ValueError('Login form needs browser interaction.')
        if (form.get_attribute('method') or '').lower()!='post':
            raise ValueError('Login submission transport needs site-specific qualification.')
        action=urlsplit(urljoin(self.page.url,form.get_attribute('action') or self.page.url))
        if action.scheme!='https' or action.netloc!='www.perplexity.ai':
            raise ValueError('Login form targets a different domain.')
        button=form.get_by_role('button',name=re.compile(r'^(Continue(?: with email)?|Sign in|Log in|Verify(?: code)?|Submit)$',re.I))
        if button.count()!=1 or not button.is_visible():raise ValueError('Login submission is not uniquely recognized.')
        return field,button

    def login_identity(self,kind):
        field,button=self._login_controls(kind)
        form=field.locator('xpath=ancestor::form[1]')
        return fingerprint({'url':self.page.url,'kind':kind,'action':form.get_attribute('action'),
                            'method':form.get_attribute('method'),'name':field.get_attribute('name'),
                            'button':button.inner_text()})

    def login_stage(self):
        try:self._login_origin()
        except ValueError:return 'manual'
        if 'just a moment' in self.page.title().lower():return 'manual'
        for kind in ('code','email'):
            try:field,_=self._login_controls(kind)
            except ValueError:continue
            if field.input_value():return 'manual'
            return kind
        try:self.check_ready(self.snapshot())
        except Exception:return 'manual'
        return 'ready'

    def login_submit(self,kind,value,expected=None):
        if kind=='email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('Invalid email input; restart sign-in.')
        if kind=='code' and not re.fullmatch(r'[0-9]{4,10}',value):
            raise ValueError('Invalid verification code format; restart sign-in.')
        if self.login_stage()!=kind:raise ValueError('Login page changed before input.')
        identity=self.login_identity(kind)
        if expected is not None and identity!=expected:raise ValueError('Login form changed after the prompt.')
        field,button=self._login_controls(kind)
        field.fill(value,timeout=5000)
        self._login_origin()
        field,button=self._login_controls(kind)
        if field.input_value()!=value:raise ValueError('Login input was not entered exactly.')
        if self.login_identity(kind)!=identity:raise ValueError('Login form changed before submission.')
        button.click(timeout=5000)


@contextmanager
def browser_page(root,endpoint=None,chrome=False):
    from . import managed_browser
    configured = managed_browser.preference(root.parent)
    if configured is not None and not endpoint and not chrome:
        if not configured['enabled']:
            raise ValueError('Browser use is off. Enable it in Task Relay Settings.')
        with managed_browser.page(root.parent) as page:yield PerplexityPage(page)
        return
    if endpoint or chrome:
        from .host_perplexity import attached_page
        with attached_page(endpoint,chrome=chrome) as page:yield PerplexityPage(page)
        return
    try:from playwright.sync_api import sync_playwright
    except ImportError:raise ValueError('Install the browser extra and Chromium; see docs/perplexity-browser.md') from None
    profile=root/'profile'
    if profile.is_symlink():raise ValueError('Browser profile must not be a symlink')
    with sync_playwright() as runtime:
        context=runtime.chromium.launch_persistent_context(str(profile),headless=False,
                    accept_downloads=False,permissions=[])
        try:
            # A fresh tab never overwrites a user's pending draft in an older tab.
            page=context.new_page()
            yield PerplexityPage(page)
        finally:context.close()


def inspect_controls(page, prompt, baseline=None):
    """Bounded visible composer diagnostics; never fill, click or read credentials."""
    if urlsplit(page.url).scheme!='https' or urlsplit(page.url).netloc!='www.perplexity.ai':
        raise ValueError('Only the authorized website can be inspected.')
    main=page.get_by_role('main')
    boxes=main.get_by_role('textbox')
    buttons=main.get_by_role('button')
    controls=[]
    for index in range(min(buttons.count(),60)):
        button=buttons.nth(index)
        if not button.is_visible():continue
        controls.append({**{name:button.get_attribute(name) for name in ('aria-label','title','type','data-testid')},
                         'text':button.inner_text()[:120], 'enabled':button.is_enabled()})
    comparison={}
    if baseline:
        saved=json.loads(baseline);current=PerplexityPage(page).snapshot()
        comparison={'matches_submission_context':same_submission_context(saved,current),
                    'changed_fields':[k for k in ('url','queries','answers','ready','text') if saved.get(k)!=current.get(k)]}
    return {**comparison,'url':page.url,'draft_matches_request':boxes.count()==1 and boxes.inner_text()==prompt,
            'draft_empty':boxes.count()==1 and not boxes.inner_text().strip(),
            'buttons':controls}


def inspect_open_pages(root, job):
    """Inspect only existing matching tabs in Relay's currently running Chrome."""
    from .host_managed_chrome import live_socket
    from .host_browser_accounts import attach
    from playwright.sync_api import sync_playwright
    socket=live_socket(root/'chrome-profile')
    if not socket:raise ValueError('Relay Chrome is not running; inspection did not launch a browser.')
    with sync_playwright() as runtime:
        remote=attach(runtime,socket)
        try:
            allowed={HOME_URL,job['url'],job['target']}-{None}
            pages=[p for context in remote.contexts for p in context.pages if p.url in allowed]
            return {'receipt':job['id'],'status':job['status'],
                    'observations':[inspect_controls(p,job['prompt'],job.get('baseline')) for p in pages[:10]],
                    'matching_tabs':len(pages),'read_only':True}
        finally:remote.close()


def main(argv=None):
    import sys
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:1]==['relay']:
        from .perplexity_native import main as native_main
        return native_main(argv[1:])
    if argv[:1]==['sites']:
        from .browser_sites import main as sites_main
        return sites_main(argv[1:])
    if argv[:1]==['general']:
        from .browser_cli import main as general_main
        return general_main(argv[1:])
    parser=argparse.ArgumentParser(description=__doc__,epilog='For general websites: task-relay browser general --help')
    sub=parser.add_subparsers(dest='action',required=True)
    def connection_options(p):
        group=p.add_mutually_exclusive_group()
        group.add_argument('--endpoint',help='Explicit local Chromium debugging server origin')
        group.add_argument('--chrome',action='store_true',help='Request access to existing signed-in Chrome (144+); remote debugging must be enabled in Chrome')
    p=sub.add_parser('login');connection_options(p)
    p=sub.add_parser('send');p.add_argument('--receipt',required=True);p.add_argument('--prompt-file',type=Path,required=True);p.add_argument('--url')
    connection_options(p)
    p=sub.add_parser('status');p.add_argument('receipt')
    p=sub.add_parser('inspect');p.add_argument('receipt')
    p=sub.add_parser('reconcile');p.add_argument('receipt');p.add_argument('--url')
    connection_options(p)
    args=parser.parse_args(argv)
    os.umask(0o077)
    try:
        with profile_lock(PATHS.data) as root:
            if args.action=='login':
                with browser_page(root,endpoint=args.endpoint,chrome=args.chrome) as driver:
                    if args.endpoint or args.chrome:driver.page.goto(HOME_URL,wait_until='domcontentloaded',timeout=30000)
                    else:driver.open()
                    input('Sign in to your Perplexity account in the dedicated browser, resolve any consent dialog, select Search, then press Enter here. ')
                    driver.check_ready(driver.snapshot())
                print('Browser session saved locally. No prompt was submitted.');return 0
            with sqlite3.connect(PATHS.state) as db:
                journal=Journal(db)
                if args.action=='inspect':
                    result=inspect_open_pages(root,journal.get(args.receipt))
                    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
                if args.action=='status':result=journal.get(args.receipt)
                else:
                    if args.action=='send':
                        with args.prompt_file.open('rb') as source:raw=source.read(48001)
                        if len(raw)>48000:raise ValueError('Prompt file exceeds 48000 bytes')
                        job=journal.prepare(args.receipt,raw.decode('utf-8'),args.url)
                    else:job=journal.get(args.receipt)
                    # Completed duplicate calls do not reopen or submit in the browser.
                    if job['status']=='completed':result=job
                    elif args.action=='send' and job['status'] in ('submitting','uncertain'):
                        raise ValueError('Use reconcile to inspect the uncertain turn; it will not be resent')
                    else:
                        with browser_page(root,endpoint=args.endpoint,chrome=args.chrome) as driver:
                            result=execute(journal,args.receipt,driver,reconcile=args.action=='reconcile',url=args.url)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return 0 if result['status']=='completed' else 2
    except (OSError,ValueError,sqlite3.Error,UnsupportedHost) as exc:
        print(str(exc));return 2


if __name__=='__main__':raise SystemExit(main())
