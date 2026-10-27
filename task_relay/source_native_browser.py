"""Native browser observations composed through the existing computer journal.

Explicit native authority, never an automatic downgrade of public-network policy.
No model calls, arbitrary page actions, site rules or new recovery controller.
"""
import hashlib,json,os,sqlite3,time
from pathlib import Path
from urllib.parse import urlsplit
from . import computer_contract as native,computer_sessions as journal
from .computer_worker_session import Session
from .browser_journal import UncertainAction
from orchestrator.source_fallback import exclusive,ReadCancelled
from orchestrator.runtime_outcomes import UncertainOperation
from orchestrator.workers import atomic

TRANSPORT='safari-visual'
POLICY='native-browser-same-origin-observation-scroll-v2'


def discover():
    from .host_computer import Observer,bundled_helper
    # Host configuration, not a model-supplied executable path. Observer checks
    # source/binary hashes and signing before any native request.
    helper=Observer(os.environ.get('TASK_RELAY_COMPUTER_HELPER') or bundled_helper())
    return dict(transport=TRANSPORT,policy=POLICY,helper=str(helper.app),identity=helper.identity)


def modules():
    from . import computer_worker_session,computer_use,host_computer,computer_sessions,computer_contract,source_native_browser
    return (source_native_browser,computer_worker_session,computer_use,host_computer,computer_sessions,computer_contract)


def verified(binding):
    from .host_computer import Observer
    if set(binding)!={'transport','policy','helper','identity'} or binding['transport']!=TRANSPORT or binding['policy']!=POLICY:
        raise ValueError('Unrecognized native browser authority')
    helper=Observer(binding['helper'])
    if helper.identity!=binding['identity']:raise ValueError('Native browser helper changed after binding')
    return helper


class RecordingDriver:
    def __init__(self,driver,root):self.driver,self.root,self.ordinal=driver,root,0
    def call(self,request):
        self.ordinal+=1
        base=self.root/('native-call-'+str(self.ordinal))
        exclusive(base.with_suffix('.request.json'),request)
        try:result=self.driver.call(request)
        except Exception as exc:
            atomic(base.with_suffix('.error.json'),dict(type=type(exc).__name__,error=str(exc)))
            if getattr(exc,'response',None) is not None:atomic(base.with_suffix('.response.json'),exc.response)
            raise
        atomic(base.with_suffix('.response.json'),result)
        return result


def saved(root,url,identity):
    if json.loads((root/'render-intent.json').read_text())!=identity:raise ValueError('Native read authority changed; no replay')
    path=root/'render-outcome.json'
    if not path.exists():raise UncertainOperation('Native browser read has no confirmed outcome; no replay')
    value=json.loads(path.read_text())
    if value.get('requested_url')!=url:raise ValueError('Native read identity changed')
    for name,sha in value.get('evidence',{}).items():
        if name not in ('native-receipts.json','rendered-text.txt'):raise ValueError('Unknown native browser evidence')
        p=root/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError('Native browser evidence changed; no replay')
    receipts=root/'native-receipts.json'
    if receipts.exists():
        for action in json.loads(receipts.read_text())['actions']:
            if action['receipt']:journal._verify_receipt(action['receipt'])
    if value.get('error'):
        if value.get('cancelled'):raise ReadCancelled(value['error'])
        raise ValueError(value['error'])
    return value['page']


def render(url,domains,control,*,binding,max_observations,helper=None,lease_context=None,wait=None,cancel_control=None):
    from .orchestrator_web import public_url,public_addresses,MAX_CHARS
    from .source_browser import availability
    from .host_computer import lease
    from orchestrator.web_sources import allowed
    url=public_url(url)
    wait=wait or time.sleep
    if not allowed(url,domains):raise ValueError('Native source URL outside the grant')
    if type(max_observations) is not int or not 2<=max_observations<=8:raise ValueError('Native reads require 2–8 bounded observations')
    root=Path(control);root.mkdir(parents=True,exist_ok=True)
    if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('Native evidence path cannot traverse symlinks')
    identity=dict(url=url,domains=domains,binding=binding,max_observations=max_observations)
    if cancel_control is not None:identity['cancel_control']=str(Path(cancel_control).resolve())
    for name in ('render-intent.json','render-outcome.json'):
        if (root/name).is_symlink():raise ValueError('Native receipt cannot be a symlink')
    if (root/'render-intent.json').exists():return saved(root,url,identity)
    if any((p/'cancel.json').exists() for p in (root,Path(cancel_control) if cancel_control is not None else root)):
        raise ValueError('Native source reading cancelled before dispatch')
    public_addresses(urlsplit(url).hostname)
    helper=helper or verified(binding)
    if helper.identity!=binding['identity']:raise ValueError('Native helper identity changed')
    # Permissions are checked without launching a window. The native contract
    # constrains agent actions, not all network traffic generated by the page.
    helper.require_ready()
    exclusive(root/'render-intent.json',identity)
    db=None;session=None
    try:
        with lease_context() if lease_context else lease():
            db=sqlite3.connect(root/'native-state.sqlite',isolation_level=None);db.row_factory=sqlite3.Row
            # An operation-owned journal reuses the computer session lifecycle;
            # it is not an owner pipeline or a scheduler and dispatches no model.
            db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)')
            db.execute("INSERT INTO relay_pipelines VALUES ('native-source-operation')")
            journal.initialize(db)
            spec=dict(target=native.NEW_WINDOW,url=url,allowed_urls=[url],actions=[],capture=False,local_fixture=False,max_seconds=40+25*max_observations,navigation_policy='same-origin-observed-v1')
            ident=journal.approve(db,job='native-source-operation',request_key='read',exact_request='Read the exact observed public source URL through the explicitly granted native browser; observe and scroll only.',spec=spec,helper=helper.identity,output_root=root/'evidence',actor='registered native-source operation')
            with helper.session() as driver:
                session=Session(db,ident,RecordingDriver(driver,root),root,'Relay source observation',cancel_control=cancel_control)
                observations=[]
                for index in range(max_observations):
                    if index==1:wait(3) # Let the acknowledged initial document load; no navigation replay.
                    name='computer_observe' if index<2 else 'computer_scroll'
                    args=dict(token=session.token or '')
                    if index>=2:args['direction']='down'
                    observation=session.call('source-'+str(index+1),name,args)
                    native.navigation_url(url,observation['url'],'same-origin-observed-v1')
                    observations.append(observation)
                    if index>=2 and not observation['scroll_available']:break
                session.close(completed=True)
                record=journal.inspect(db,ident);atomic(root/'native-receipts.json',record)
                text='\n\n'.join('Observation '+o['observation']+'\n'+o['text'] for o in observations)
                (root/'rendered-text.txt').write_text(text)
                status,reason=availability('',observations[-1]['text'],None)
                page=dict(url=observations[-1]['url'],requested_url=url,title='',text=text[:MAX_CHARS],retrieved_at=time.time(),sha256=hashlib.sha256(text.encode()).hexdigest(),
                    content_type='text/plain',total_characters=len(text),next_offset=MAX_CHARS if len(text)>MAX_CHARS else None,links=[],images=[],products=[],
                    capture_method='native-browser-observations',navigation_transport=binding['transport'],read_policy=binding['policy'],
                    retrieval_status=status,retrieval_reason=reason,observation_ids=[o['observation'] for o in observations],
                    limitations=['Native browser retains its session and page-generated networking; no network-method isolation is claimed.',
                        'Bounded visible text and scrolling only; no clicks, forms, login, downloads or complete-page guarantee.',
                        'Each observation is retained verbatim; changing or repeated visible content is not merged into verified facts.'])
                atomic(root/'render-outcome.json',dict(requested_url=url,page=page,finished=time.time(),evidence={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('native-receipts.json','rendered-text.txt')}))
    except BaseException as exc:
        pending=session.pending() if session else []
        if (root/'render-outcome.json').exists():
            atomic(root/'render-cleanup-error.json',dict(error=str(exc),finished=time.time()))
        else:
            stopped=False
            if db is not None and session:
                session.close()
                record=journal.inspect(db,session.ident)
                atomic(root/'native-receipts.json',record)
                stopped=record['assignment']['state'] in ('cancelled','paused')
            if pending or isinstance(exc,UncertainAction):
                atomic(root/'native-uncertain.json',dict(error=str(exc),pending=pending,finished=time.time()))
                raise UncertainOperation('Native browser action is uncertain; preserve receipts without replay') from exc
            error='Source reading cancelled by native ownership control' if stopped else str(exc)
            atomic(root/'render-outcome.json',dict(requested_url=url,error=error,cancelled=stopped,finished=time.time(),
                evidence={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('native-receipts.json',) if (root/name).exists()}))
            if stopped:raise ReadCancelled(error) from exc
            raise
    finally:
        if db is not None:db.close()
    return saved(root,url,identity)
