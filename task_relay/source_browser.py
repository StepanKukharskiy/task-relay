"""Isolated public page rendering adapter; never adopts signed-in/user tabs."""
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from .host import HOST


def read_http(url,domains,control):
    """Existing public HTTP reader with exact durable intent/outcome, no search.

    Each call consumes one collector read, including a failed or empty capture.
    A crash between intent and outcome is uncertain and cannot be retried.
    """
    from . import orchestrator_web as web
    from orchestrator.source_fallback import exclusive
    from orchestrator.runtime_outcomes import UncertainOperation
    from orchestrator.workers import atomic
    from orchestrator.web_sources import allowed
    control=Path(control);control.mkdir(parents=True,exist_ok=True)
    url=web.public_url(url)
    if not allowed(url,domains):raise ValueError('HTTP read left permitted source domains')
    intent=control/'http-intent.json';outcome=control/'http-outcome.json'
    identity=dict(url=url,domains=domains,reader='http')
    if intent.is_symlink() or outcome.is_symlink():raise ValueError('HTTP read receipts cannot be symlinks')
    if intent.exists():
        if json.loads(intent.read_text())!=identity:raise ValueError('HTTP read grant changed; no replay')
        if not outcome.exists():raise UncertainOperation('Previous HTTP read has no confirmed outcome; no replay')
        value=json.loads(outcome.read_text())
        if value.get('identity')!=identity:raise ValueError('HTTP read identity changed')
        if value.get('error'):raise ValueError(value['error'])
        path=control/'http'/'page-1.json'
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=value['evidence_sha256']:
            raise ValueError('Saved HTTP evidence changed; no replay')
        return value['page']
    exclusive(intent,identity)
    try:
        page=web.Session(control/'http.json').fetch(url,0,web.MAX_CHARS,allowed_hosts=domains or None)
        if not allowed(page['url'],domains):raise ValueError('HTTP read left permitted source domains')
        status,reason=availability(page['title'],page['text'],200)
        page.update(capture_method='direct-public-http',retrieval_status=status,retrieval_reason=reason)
        atomic(outcome,dict(identity=identity,page=page,evidence_sha256=hashlib.sha256((control/'http'/'page-1.json').read_bytes()).hexdigest()))
        return page
    except (ValueError,OSError) as exc:
        atomic(outcome,dict(identity=identity,error=str(exc)))
        raise


def render(url,domains,control,seconds=45):
    from . import runtime_process
    from .relay_paths import PATHS
    from .orchestrator_web import public_url,public_addresses
    from orchestrator.workers import atomic
    from orchestrator.runtime_outcomes import UncertainOperation
    url=public_url(url)
    control=Path(control);control.mkdir(parents=True,exist_ok=True)
    intent=control/'render-intent.json';outcome=control/'render-outcome.json'
    if intent.is_symlink() or outcome.is_symlink():raise ValueError('Browser read receipts cannot be symlinks')
    if intent.exists():
        if not outcome.exists():raise UncertainOperation('Previous browser read has no confirmed outcome; no replay')
        prior=json.loads(intent.read_text())
        if prior.get('url')!=url or prior.get('domains')!=domains or prior.get('seconds')!=seconds:raise ValueError('Browser read grant changed; no replay')
        value=json.loads(outcome.read_text())
        if value.get('requested_url')!=url:raise ValueError('Browser read identity changed')
        if value.get('error'):raise ValueError(value['error'])
        return checked_page(value,control)
    from orchestrator.source_fallback import exclusive
    public_addresses(urlsplit(url).hostname)
    python=HOST.browser_python(PATHS.install,PATHS.data)
    exclusive(intent,dict(url=url,domains=domains,seconds=seconds,created=time.time()))
    env=runtime_process.environment({**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parent.parent)})
    with (control/'renderer.log').open('ab') as log:
        process=HOST.spawn(runtime_process.command(python,'-m','task_relay.source_browser',control),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        try:process.wait(timeout=seconds+10)
        except subprocess.TimeoutExpired:
            HOST.signal_tree(process)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                HOST.signal_tree(process,force=True);process.wait(timeout=5)
            if not outcome.exists():atomic(outcome,dict(requested_url=url,error='Browser read timed out; owned process stopped',finished=time.time()))
    if not outcome.exists():raise UncertainOperation('Browser renderer ended without an observed outcome; no replay')
    value=json.loads(outcome.read_text())
    if value.get('error'):raise ValueError(value['error'])
    return checked_page(value,control)


def execute(control):
    from . import general_browser,orchestrator_web as web
    from orchestrator.browser_contract import origin
    from orchestrator.workers import atomic
    control=Path(control);request=json.loads((control/'render-intent.json').read_text());url=request['url'];domains=request['domains']
    from orchestrator.web_sources import allowed
    policy=dict(profile='public-source',origins=[origin(url)],max_tabs=1,max_actions=2,
                interaction_scope='',uploads=[],downloads=[])
    driver=None
    try:
        with general_browser.browser(control,policy,headless=False,ephemeral=True) as driver:
            from .public_browser_navigation import open_page
            page,guard=open_page(driver,url,domains)
            responses=guard.responses
            observation=settle(page)
            if guard.errors:raise ValueError('Browser request guard failed')
            final=web.public_url(page.url)
            if not allowed(final,domains):raise ValueError('Rendered page left permitted source domains')
            html=page.content();raw=html.encode()
            if len(raw)>web.MAX_HTML_BYTES:raise ValueError('Rendered DOM exceeds public page byte limit')
            parser=web.PageText(final);parser.feed(html)
            text=page.locator('body').inner_text(timeout=5000)
            if parser.products:text='Observed product JSON-LD:\n'+json.dumps(parser.products,ensure_ascii=False,sort_keys=True)+'\nVisible page text:\n'+text
            total_characters=len(text)
            (control/'rendered-text.txt').write_text(text)
            text=text[:web.MAX_CHARS]
            value=dict(url=final,requested_url=url,title=page.title(),text=text,retrieved_at=time.time(),sha256=hashlib.sha256(raw).hexdigest(),
                       content_type='text/html',total_characters=total_characters,next_offset=web.MAX_CHARS if total_characters>web.MAX_CHARS else None,links=parser.links,images=parser.images,products=parser.products,alternatives=parser.alternatives,
                       capture_method='isolated-rendered-dom',navigation_transport='chromium-native',settlement=observation,navigation_responses=responses,raw_bytes=len(raw),raw_byte_limit=web.MAX_HTML_BYTES,
                       limitations=['Read-only rendered capture; no account, form interaction, stock or correspondence verification. Text may be truncated at the registered character bound.'])
            status,reason=availability(value['title'],text,responses[-1]['status'] if responses else None)
            value.update(retrieval_status=status,retrieval_reason=reason)
            # DOM/title reads can deliver more network events. Check the exact
            # final guard receipt, not only the state before those browser calls.
            guard_evidence=guard.evidence()
            if guard_evidence.get('errors'):raise ValueError('Browser request guard failed')
            (control/'rendered-dom.html').write_bytes(raw)
            atomic(control/'network-guard.json',guard_evidence)
            atomic(control/'render-outcome.json',dict(requested_url=url,page=value,finished=time.time(),
                evidence={name:hashlib.sha256((control/name).read_bytes()).hexdigest() for name in ('rendered-dom.html','rendered-text.txt','network-guard.json')}))
    except Exception as exc:
        # A later context cleanup failure cannot erase a confirmed observation.
        path=control/('render-cleanup-error.json' if (control/'render-outcome.json').exists() else 'render-outcome.json')
        if driver is not None and getattr(driver,'public_read_guard',None) is not None and not (control/'network-guard.json').exists():
            atomic(control/'network-guard.json',driver.public_read_guard.evidence())
        atomic(path,dict(requested_url=url,error=str(exc)[:1500],finished=time.time()))

def checked_page(value,control):
    for name,sha in value.get('evidence',{}).items():
        if name not in ('rendered-dom.html','rendered-text.txt','network-guard.json'):raise ValueError('Unknown browser evidence file')
        path=Path(control)/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Saved browser evidence changed; no replay')
    return value['page']


def availability(title,text,status):
    """Classify transport/access failure, never infer factual completeness."""
    if status is not None and status>=400:return 'blocked','Rendered navigation returned HTTP '+str(status)
    heading=title.strip() or next((line.strip() for line in text.splitlines() if line.strip()),'')
    if re.search(r'(?i)^(?:access denied|forbidden|just a moment|security check|verify (?:you|your)|sign in|log in)(?:\b|$)',heading):
        return 'blocked','Rendered page requires access, authentication or challenge resolution'
    # Conservative whole-heading signatures, not keyword scans of article prose.
    # A captured HTTP-200 error is evidence of a failed read, not usable content.
    headings=[heading]+[line.strip() for line in text.splitlines() if line.strip()][:3]
    if any(re.fullmatch(r'(?i)(?:(?:error\s*)?[45]\d\d\s*[-—:–]?\s*)?(?:something went wrong|internal server error|page not found|service unavailable)[.!]?',h) for h in headings):
        return 'blocked','Page displays an error heading despite a completed transport'
    # Navigation can precede a short error document. Require both an isolated
    # error code and a whole error-message line, never a keyword in normal prose.
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if len(text)<1000 and any(re.fullmatch(r'[45]\d\d',line) for line in lines) and any(
        re.fullmatch(r'(?i)(?:apologies,? but |sorry,? (?:but )?)?(?:something went wrong(?: on our end)?|internal server error|page not found|service unavailable)[.!]?',line) for line in lines):
        return 'blocked','Short page displays an error code and error message'
    if not text.strip():return 'empty','Rendered page contains no readable text'
    return 'captured',None


def settle(page,*,minimum=5,maximum=15,clock=time.monotonic):
    """Bounded DOM observation, not network-idle or semantic completion."""
    started=clock();previous=None;stable=0;samples=0;missing=0
    while True:
        elapsed=clock()-started
        # A navigation may have reached DOMContentLoaded before a body exists,
        # or replace it during hydration. A short locator timeout is not a
        # terminal read failure while the original observation window remains.
        try:
            text=page.locator('body').inner_text(timeout=1000)
        except Exception as exc:
            from playwright.sync_api import Error,TimeoutError
            transient=isinstance(exc,TimeoutError) or (isinstance(exc,Error) and
                any(word in str(exc) for word in ('Execution context was destroyed','Cannot find context')))
            if not transient or page.is_closed():raise
            missing+=1;stable=0
            if clock()-started>=maximum:raise ValueError('No readable document within the browser observation window') from exc
            page.wait_for_timeout(250);continue
        fingerprint=hashlib.sha256(text.encode()).hexdigest();samples+=1
        stable=stable+1 if fingerprint==previous else 0;previous=fingerprint
        elapsed=clock()-started
        if elapsed>=maximum or (elapsed>=minimum and stable>=2):
            return dict(samples=samples,seconds=round(elapsed,3),stable=stable>=2,transient_documents=missing,
                        interpretation='Bounded visible-text stability only; not evidence completeness')
        page.wait_for_timeout(500)


if __name__=='__main__':execute(sys.argv[1])
