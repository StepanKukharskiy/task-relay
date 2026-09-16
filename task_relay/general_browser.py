"""Site-neutral, bounded browser actions. Playwright stays inside this host adapter."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urljoin

from orchestrator.browser_contract import validate,origin,profile_name
from orchestrator.contracts import encoded
from .browser_journal import Journal,UncertainAction
from .host import HOST

INTERACTIVE={'click','fill','select','press','upload','download'}
FIELDS="""el => {const secret=el.type==='password'||['one-time-code','current-password','new-password'].includes(el.autocomplete);
 const value=el.value||((el.isContentEditable||el.getAttribute('role')==='textbox')?el.textContent:'')||'';
 return {tag:el.tagName,role:el.getAttribute('role'),
 label:(el.getAttribute('aria-label')||el.labels?.[0]?.innerText||el.innerText||el.getAttribute('placeholder')||'').slice(0,300),
 type:el.getAttribute('type')||'',autocomplete:el.getAttribute('autocomplete')||'',
 href:el.tagName==='A'?el.href:null,connected:el.isConnected,
 value_present:!!value,_value:secret?null:value,
 options:el.tagName==='SELECT'?Array.from(el.options).slice(0,100).map(o=>({value:o.value,label:o.label})):[],
 options_truncated:el.tagName==='SELECT'&&el.options.length>100};}"""
CONTROLS='a[href],button,input,textarea,select,[role="button"],[role="textbox"],[contenteditable="true"]'


def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()


class NavigationBlocked(ValueError):
    """A recorded policy rejection, distinct from an unknown submitted action."""
    def __init__(self,detail):
        self.detail=detail
        super().__init__('Navigation stopped ('+detail['reason']+'): '+detail['url'])


@contextmanager
def profile_lock(data,profile):
    profile_name(profile);HOST.require_posix('Browser profile ownership')
    root=Path(data)/'browser-general'/profile
    for p in (root.parent,root,root/'profile',root/'profile.lock'):
        if p.is_symlink():raise ValueError('Browser profile paths cannot be symlinks')
    root.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(root,0o700)
    with (root/'profile.lock').open('a') as stream:
        HOST.lock(stream)
        yield root


class PlaywrightDriver:
    def __init__(self,context,policy,access=None,attached=False):
        self.context=context;self.policy=policy;self.pages={};self.dialogs=[];self.navigation_blocks={};self.redirects={}
        self.access=access;self.attached=attached
        context.route('**/*',self.route)
        # Unexpected popup tabs are not given implicit assignment ownership.
        if not attached:context.on('page',self.new_page)

    def detach(self):
        self.context.unroute('**/*',self.route)
        if not self.attached:self.context.remove_listener('page',self.new_page)
        for page in self.pages.values():
            if not page.is_closed():page.close()

    def new_page(self,page):
        page.on('dialog',lambda dialog:self.dismiss(dialog))
        if len(self.context.pages)>self.policy['max_tabs']+1:page.close()

    def dismiss(self,dialog):
        self.dialogs.append({'type':dialog.type,'message':dialog.message[:500]})
        dialog.dismiss()

    def route(self,route):
        request=route.request
        if self.attached:
            try:owner=request.frame.page
            except Exception:return route.fallback()
            if owner not in self.pages.values():
                # Only popups from Relay-owned tabs are blocked. Unrelated tabs
                # and user-created tabs retain their existing handlers.
                if owner.opener in self.pages.values():return route.abort()
                return route.fallback()
        main=request.is_navigation_request() and request.frame==request.frame.page.main_frame
        def block(url,reason='outside permitted website origins'):
            if main:
                self.navigation_blocks[request.frame.page]={'url':url,'requested_url':request.url,'reason':reason}
                # Settle this document without Chrome's delayed error-page
                # navigation interrupting a subsequent permitted URL. This blank
                # transport response is never exposed as website evidence.
                return route.fulfill(status=200,content_type='text/plain',body='')
            return route.abort()
        try:
            if main and origin(request.url) not in self.policy['origins']:return block(request.url)
            if main and self.access:
                try:self.access.check(request.url)
                except ValueError:return block(request.url,'manual site verification required')
            if not self.policy['interaction_scope'] and request.method not in ('GET','HEAD','OPTIONS'):
                return route.abort()
        except ValueError:return block(request.url)
        if main:
            # continue_ follows HTTP redirects without invoking routing again.
            # Fetch one hop and check Location. Follow permitted GET redirects
            # through a fresh goto so every hop is intercepted and the final URL
            # remains the real document URL (including relative-link behavior).
            # No transport retries: a POST may already have reached the site.
            try:
                response=route.fetch(max_redirects=0,max_retries=0,timeout=15000)
                try:
                    location=response.headers.get('location')
                    if 300<=response.status<400 and location:
                        target=urljoin(request.url,location)
                        try:allowed=origin(target) in self.policy['origins']
                        except ValueError:allowed=False
                        if not allowed:return block(target)
                        if request.method not in ('GET','HEAD') and response.status not in (301,302,303):
                            return block(target,'redirect would repeat a submitted request')
                        self.redirects[request.frame.page]=target
                        return route.fulfill(status=200,content_type='text/plain',body='')
                    return route.fulfill(response=response)
                finally:response.dispose()
            except Exception:
                # Do not repeat a transport call whose outcome may be unknown.
                return route.abort()
        route.continue_()

    def open(self,tab,url):
        page=self.context.new_page();self.pages[tab]=page
        if self.attached:
            page.on('dialog',lambda dialog:self.dismiss(dialog))
            page.on('popup',lambda popup:popup.close())
        if self.access:
            page.on('download',lambda download:download.cancel() if not self.policy['downloads'] else None)
        self.goto(page,url)

    def goto(self,page,url):
        for _ in range(10):
            self.navigation_blocks.pop(page,None);self.redirects.pop(page,None)
            try:page.goto(url,wait_until='domcontentloaded',timeout=15000)
            except Exception as exc:
                if page in self.navigation_blocks:raise NavigationBlocked(self.navigation_blocks[page]) from exc
                if page not in self.redirects:raise
            if page in self.navigation_blocks:raise NavigationBlocked(self.navigation_blocks[page])
            target=self.redirects.pop(page,None)
            if target is None:return
            url=target
        detail={'url':url,'requested_url':url,'reason':'redirect limit reached'}
        self.navigation_blocks[page]=detail
        raise NavigationBlocked(detail)

    def managed_page(self,tab):
        page=self.pages.get(tab)
        if not page or page.is_closed():raise ValueError('Tab is detached or closed; open a URL explicitly, never retarget an old action')
        return page

    def page(self,tab):
        page=self.managed_page(tab)
        if page in self.navigation_blocks:raise NavigationBlocked(self.navigation_blocks[page])
        if origin(page.url) not in self.policy['origins']:raise ValueError('Tab left its permitted website')
        if self.access:
            self.access.check(page.url)
            from .host_browser_accounts import login_required
            if login_required(page):self.access.require_manual(page.url)
        return page

    def snapshot(self,tab):
        page=self.page(tab);handles=[];controls=[]
        for element in page.locator(CONTROLS).element_handles()[:150]:
            if not element.is_visible():continue
            descriptor=element.evaluate(FIELDS)
            value=descriptor.pop('_value')
            if value is not None:
                descriptor['value']=value[:1000]
                descriptor['value_sha256']=hashlib.sha256(value.encode()).hexdigest()
                descriptor['value_truncated']=len(value)>1000
            handles.append(element);controls.append(descriptor)
        text=page.locator('body').inner_text(timeout=5000)
        return {'url':page.url,'title':page.title()[:500],'text':text[:24000],
                'text_truncated':len(text)>24000,'controls':controls,'dialogs_dismissed':self.dialogs[-3:]},handles

    def navigate(self,tab,url):self.goto(self.managed_page(tab),url)
    def close(self,tab):
        page=self.managed_page(tab);page.close();self.navigation_blocks.pop(page,None);del self.pages[tab]
    def wait(self,tab,seconds):self.page(tab).wait_for_timeout(seconds*1000)

    def screenshot(self,tab):
        page=self.page(tab);url=page.url
        size=page.viewport_size or page.evaluate('() => ({width:innerWidth,height:innerHeight})')
        if not size or not 1<=size['width']<=4096 or not 1<=size['height']<=4096 or size['width']*size['height']>8000000:
            raise ValueError('Screenshot requires a bounded viewport')
        raw=page.screenshot(type='png',full_page=False,scale='css',timeout=5000)
        if self.page(tab).url!=url:raise ValueError('Tab navigated during screenshot capture')
        return raw

    def act(self,tab,element,operation,args,files):
        self.page(tab)
        try:return self.interact(tab,element,operation,args,files)
        except Exception:
            page=self.managed_page(tab)
            if page in self.navigation_blocks:raise NavigationBlocked(self.navigation_blocks[page])
            target=self.redirects.pop(page,None)
            if target is None:raise
            # The original submission has a response. Follow its permitted GET
            # redirect; never reissue the POST or replay the original interaction.
            self.goto(page,target)
            return {'driver_action_returned':True,'remote_outcome':'not_independently_verified'}

    def interact(self,tab,element,operation,args,files):
        if not element.evaluate('el => el.isConnected'):raise ValueError('Observed element was replaced')
        if operation=='click':element.click(timeout=5000)
        elif operation=='fill':
            if element.evaluate(FIELDS)['value_present']:raise ValueError('Existing field content must be preserved')
            element.fill(args['text'],timeout=5000)
        elif operation=='select':element.select_option(args['value'],timeout=5000)
        elif operation=='press':element.press(args['key'],timeout=5000)
        elif operation=='upload':
            raw=files.read_bytes(args['path'])
            if hashlib.sha256(raw).hexdigest()!=files.inputs[args['path']]['sha256']:raise ValueError('Upload input version changed')
            element.set_input_files({'name':Path(args['path']).name,'mimeType':'text/plain','buffer':raw},timeout=5000)
        elif operation=='download':
            with self.page(tab).expect_download(timeout=15000) as event:element.click(timeout=5000)
            download=event.value
            temporary=download.path()
            if temporary is None:raise ValueError('Download failed')
            with Path(temporary).open('rb') as f:raw=f.read(files.frozen['limits']['output_bytes']+1)
            if len(raw)>files.frozen['limits']['output_bytes']:raise ValueError('Download exceeds declared output budget')
            result=files.call('file_write',{'path':args['path'],'text':raw.decode('utf-8')})
            download.delete()
            return result
        page=self.managed_page(tab)
        if page in self.navigation_blocks:raise NavigationBlocked(self.navigation_blocks[page])
        target=self.redirects.pop(page,None)
        if target:self.goto(page,target)
        return {'driver_action_returned':True,'remote_outcome':'not_independently_verified'}


@contextmanager
def browser(data,policy,*,headless=False):
    validate(policy)
    from .browser_sites import PROFILE
    if policy.get('session_source')=='settings':
        from .managed_browser import context as managed_context
        from .perplexity_browser import profile_lock as managed_lock
        # Settings sign-in and standalone jobs use this same lock/profile.
        with managed_lock(data),managed_context(data) as context:
            driver=PlaywrightDriver(context,policy,attached=True)
            try:yield driver
            finally:driver.detach()
        return
    if policy['profile']==PROFILE:
        from .host_browser_accounts import browser as accounts_browser
        with accounts_browser(data,policy,headless) as driver:yield driver
        return
    with profile_lock(data,policy['profile']) as root:
        try:from playwright.sync_api import sync_playwright,Error
        except ImportError:raise ValueError('Install the browser extra and Chromium; see docs/general-browser.md') from None
        try:
            with sync_playwright() as runtime:
                context=runtime.chromium.launch_persistent_context(str(root/'profile'),headless=headless,
                            accept_downloads=bool(policy['downloads']),permissions=[],service_workers='block')
                try:
                    # No restored page is adopted by position; tab IDs are assigned explicitly.
                    yield PlaywrightDriver(context,policy)
                finally:context.close()
        except Error as exc:raise ValueError('Browser operation failed: '+str(exc)[:1000]) from None


class Session:
    def __init__(self,db,job,policy,driver,files=None,cancelled=None):
        self.policy=validate(policy);self.profile=policy['profile'];self.job=job
        self.journal=Journal(db);self.driver=driver;self.files=files;self.observations={}
        self.tabs=set();self.cancelled=cancelled or (lambda:False)

    def url(self,url):
        if origin(url) not in self.policy['origins']:raise ValueError('URL is outside the authorized website origins')
        return url

    def inspect(self,tab):
        raw,handles=self.driver.snapshot(tab);self.url(raw['url'])
        ident=secrets.token_hex(12);fingerprint=digest(raw)
        self.observations[tab]={'id':ident,'fingerprint':fingerprint,'raw':raw,'handles':handles}
        result=json.loads(encoded(raw));result['tab']=tab;result['observation']=ident
        for i,element in enumerate(result['controls']):element['ref']=str(i)
        self.journal.tab(self.profile,tab,raw['url'])
        return result

    def target(self,args):
        observation=self.observed(args)
        ref=args.get('ref')
        if not isinstance(ref,str) or not ref.isdigit() or int(ref)>=len(observation['handles']):raise ValueError('Unknown element ref')
        return observation['handles'][int(ref)],observation['raw']['controls'][int(ref)]

    def observed(self,args):
        tab=args['tab'];observation=self.observations.get(tab)
        if not observation or args.get('observation')!=observation['id']:raise ValueError('Inspect this tab before acting; stale observation')
        raw,_=self.driver.snapshot(tab)
        if digest(raw)!=observation['fingerprint']:raise ValueError('Page changed; inspect again before acting')
        return observation

    def call(self,ident,name,args):
        from orchestrator.browser_contract import definitions
        schema=next((d for d in definitions() if d['name']==name),None)
        if not schema or not isinstance(args,dict) or set(args)!=set(schema['parameters']['required']):raise ValueError('Invalid browser tool arguments')
        for key,value in args.items():
            expected=schema['parameters']['properties'][key]['type']
            if expected=='string' and (not isinstance(value,str) or len(value)>12000):raise ValueError('Invalid browser string argument')
            if expected=='integer' and type(value) is not int:raise ValueError('Invalid browser integer argument')
        old=self.journal.lookup(self.profile,self.job,ident,name,args)
        if old is not None:return old
        if self.cancelled():raise ValueError('Cancelled before browser action')
        op=name.removeprefix('browser_');tab=args.get('tab');element=None;anchor=None
        if tab and tab not in self.tabs:raise ValueError('Unknown or detached tab; no implicit retargeting')
        if op in ('open','navigate'):self.url(args['url'])
        if op=='open' and len(self.tabs)>=self.policy['max_tabs']:raise ValueError('Tab budget exhausted')
        if op=='wait' and not 0<=args['seconds']<=5:raise ValueError('Wait must be 0–5 seconds')
        interactive=op in INTERACTIVE
        if op=='screenshot':
            if not args['purpose'].strip():raise ValueError('State the screenshot purpose')
            if args['path'] not in self.policy.get('screenshots',[]) or self.files is None:raise ValueError('No exact screenshot grant')
            self.files.capture_ready(args['path'])
            capture_observation=self.observed(args)
        if interactive:
            if not args['purpose'].strip():raise ValueError('State this action purpose within the assignment')
            element,descriptor=self.target(args)
            if op=='click' and descriptor.get('tag')=='A' and descriptor.get('href'):
                anchor=self.url(descriptor['href']);interactive=False
            if interactive and not self.policy['interaction_scope'].strip():raise ValueError('This job authorizes reading/navigation only')
            if descriptor.get('type','').lower()=='password' or descriptor.get('autocomplete','').lower() in ('one-time-code','current-password','new-password'):
                raise ValueError('Credentials and verification require the user in the browser')
            if op=='fill' and descriptor.get('value_present'):raise ValueError('Existing field content must be preserved; use a fresh empty field')
            if op=='press' and args['key'] not in ('Enter','Tab','Escape','ArrowDown','ArrowUp'):
                raise ValueError('Unsupported key')
            if op in ('upload','download'):
                if args['path'] not in self.policy[op+'s'] or self.files is None:raise ValueError('No exact file transfer grant')
        old=self.journal.claim(self.profile,self.job,ident,name,args,self.policy['max_actions'],interactive or op=='screenshot')
        if old is not None:return old
        # No external interaction occurs before the committed intent above.
        try:
            if self.cancelled():raise ValueError('Cancelled after claim; no automatic retry')
            if op=='tabs':
                result={'tabs':[dict(t,attached=t['id'] in self.tabs) for t in self.journal.tabs(self.profile)],
                        'uncertain':[r for r in self.journal.pending(self.profile) if (r['job'],r['id'])!=(self.job,ident)]}
            elif op=='open':
                tab=secrets.token_hex(12);self.tabs.add(tab)
                self.journal.tab(self.profile,tab,args['url'],'opening')
                self.driver.open(tab,args['url']);result=self.inspect(tab)
            elif op=='read':result=self.inspect(tab)
            elif op=='screenshot':
                from datetime import datetime,timezone
                raw=self.driver.screenshot(tab)
                # Capture does not freeze a dynamic canvas. Recheck DOM identity
                # and URL; retain that limitation in the provenance record.
                self.observed(args)
                metadata={'schema':'relay.browser-screenshot.v1','tab':tab,'observation':args['observation'],
                          'url':capture_observation['raw']['url'],'title':capture_observation['raw']['title'],
                          'captured_at':datetime.now(timezone.utc).isoformat(),'mode':'viewport',
                          'purpose':args['purpose'],'job':self.job,'action_id':ident,
                          'limitation':'Capture does not establish page completeness, map accuracy or visual acceptance.'}
                result={**metadata,'capture':self.files.write_capture(args['path'],raw,metadata)}
            elif op=='close':
                self.driver.close(tab);self.tabs.remove(tab)
                previous=self.observations.pop(tab,None)
                self.journal.tab(self.profile,tab,previous['raw']['url'] if previous else '', 'closed')
                result={'tab':tab,'closed':True}
            else:
                if op=='navigate' or anchor:self.driver.navigate(tab,anchor or args['url'])
                elif op=='wait':self.driver.wait(tab,args['seconds'])
                else:self.driver.act(tab,element,op,args,self.files)
                self.observations.pop(tab,None)
                result=self.inspect(tab)
                result['action_observed']=True;result['remote_outcome']='not_independently_verified'
            self.journal.finish(self.profile,self.job,ident,'observed',result)
            return result
        except Exception as exc:
            self.observations.pop(tab,None)
            from .browser_sites import VerificationRequired
            if isinstance(exc,VerificationRequired) and not interactive:
                result={'error':str(exc),'outcome':'manual_verification_required','tab':tab,
                        'next_step':str(exc)+' Continue only after explicit manual confirmation; do not replay prior submissions.'}
                self.journal.finish(self.profile,self.job,ident,'observed',result)
                return result
            if isinstance(exc,NavigationBlocked) and not interactive:
                result={'error':str(exc),'outcome':'blocked','tab':tab,'blocked_navigation':exc.detail,
                        'next_step':'Use another permitted URL or report the missing website scope; do not repeat this blocked navigation.'}
                self.journal.tab(self.profile,tab,exc.detail['requested_url'],'blocked')
                self.journal.finish(self.profile,self.job,ident,'observed',result)
                return result
            self.journal.finish(self.profile,self.job,ident,'uncertain',{'error':str(exc)[:1000],'tab':tab})
            raise UncertainAction('Browser action outcome is uncertain; inspect receipt '+ident+'; do not repeat it') from exc
