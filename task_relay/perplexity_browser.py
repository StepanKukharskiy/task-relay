"""Optional standalone Perplexity Search browser pilot; no model API or Telegram routing."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from .browser_jobs import Journal,conversation_url,execute,fingerprint
from .host import HOST,UnsupportedHost
from .relay_paths import PATHS

HOME_URL='https://www.perplexity.ai/'


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
        main=self.page.get_by_role('main')
        text=main.inner_text(timeout=5000)
        if len(text)>250000:raise ValueError('Conversation exceeds the bounded browser text limit')
        return {'url':self.page.url,'text':text,
                'queries':main.get_by_role('button',name='Edit query',exact=True).count(),
                'answers':main.get_by_role('button',name='Copy',exact=True).count(),
                'ready':main.get_by_role('textbox').count()==1 and
                        (self.page.url==HOME_URL or main.get_by_role('button',name='Submit',exact=True).count()==1)}

    def check_ready(self,snapshot):
        # Fail closed on logged-out, changed, busy or prefilled UI. Do not operate
        # login forms, CAPTCHAs, billing dialogs, files or Computer workflows.
        if self.page.get_by_role('button',name='Sign In',exact=True).count():
            raise ValueError('Start sign-in with /browser connect in Telegram or Messages first')
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
        current=self.snapshot();self.check_ready(current)
        if fingerprint(current)!=fingerprint(baseline):raise ValueError('Conversation changed before submission')
        box=self.page.get_by_role('textbox');box.fill(prompt)
        if box.inner_text()!=prompt:raise ValueError('Prompt text was not entered exactly; no Enter was sent')
        box.press('Enter',timeout=5000)

    def pause(self):self.page.wait_for_timeout(1000)


@contextmanager
def browser_page(root):
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


def main(argv=None):
    import sys
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv[:1]==['general']:
        from .browser_cli import main as general_main
        return general_main(argv[1:])
    parser=argparse.ArgumentParser(description=__doc__,epilog='For general websites: task-relay browser general --help')
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('login')
    p=sub.add_parser('send');p.add_argument('--receipt',required=True);p.add_argument('--prompt-file',type=Path,required=True);p.add_argument('--url')
    p=sub.add_parser('status');p.add_argument('receipt')
    p=sub.add_parser('reconcile');p.add_argument('receipt');p.add_argument('--url')
    args=parser.parse_args(argv)
    os.umask(0o077)
    try:
        with profile_lock(PATHS.data) as root:
            if args.action=='login':
                with browser_page(root) as driver:
                    driver.open()
                    input('Sign in to your Perplexity account in the dedicated browser, resolve any consent dialog, select Search, then press Enter here. ')
                    driver.check_ready(driver.snapshot())
                print('Browser session saved locally. No prompt was submitted.');return 0
            with sqlite3.connect(PATHS.state) as db:
                journal=Journal(db)
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
                        with browser_page(root) as driver:
                            result=execute(journal,args.receipt,driver,reconcile=args.action=='reconcile',url=args.url)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return 0 if result['status']=='completed' else 2
    except (OSError,ValueError,sqlite3.Error,UnsupportedHost) as exc:
        print(str(exc));return 2


if __name__=='__main__':raise SystemExit(main())
