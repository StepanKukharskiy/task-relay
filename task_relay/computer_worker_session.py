"""Model-selected Safari steps using the existing authoritative native journal."""
import json
import re
from pathlib import Path
import time
from orchestrator.storage import transaction
from . import computer_sessions as journal, computer_contract as native
from .browser_journal import UncertainAction


class Session:
    def __init__(self,db,ident,driver,control,label):
        self.db,self.ident,self.driver=db,ident,driver
        self.control=Path(control);self.label=label[:160]
        self.event=self.control/'computer-owner-event.json'
        self.token=None;self.failed=False;self.scroll_available=True;self.failure=None
        row=journal.get(db,ident);self.spec=json.loads(row['spec'])
        self.target=self.spec['target']
        with transaction(db):
            if row['state']!='approved' or journal.actions(db,ident):raise UncertainAction('Existing Safari attempt cannot be replayed.')
            db.execute("UPDATE relay_computer_assignments SET state='running',deadline=? WHERE id=?",(time.time()+self.spec['max_seconds'],ident))

    def check(self):
        if self.event.exists():
            event=json.loads(self.event.read_text())
            if event.get('kind') not in ('pause','stop','takeover'):raise ValueError('Invalid ownership control; session stopped.')
            with transaction(self.db):
                row=journal.get(self.db,self.ident)
                if row['state']=='running':
                    journal.decision(self.db,row,'owner_'+event['kind'],'local Safari owner','Visible session ownership control',event)
                    self.db.execute('UPDATE relay_computer_assignments SET state=? WHERE id=?',('paused' if event['kind']=='pause' else 'cancelled',self.ident))
        row=journal.get(self.db,self.ident)
        if (self.control/'cancel.json').exists() and row['state']=='running':
            journal.control(self.db,self.ident,'cancel',actor='worker supervisor',note='Production attempt cancelled.')
            row=journal.get(self.db,self.ident)
        if self.failed or row['state']!='running':raise ValueError('Safari session stopped; explicit recovery required.')
        if time.time()>=row['deadline']:raise ValueError('Safari session time budget expired.')

    def pending(self):
        return [a['id'] for a in journal.actions(self.db,self.ident) if a['state'] in ('claimed','uncertain') and not a['resolved']]

    def action_gaps(self):
        return action_gaps(journal.actions(self.db,self.ident))

    def call(self,call_id,name,args):
        self.check()
        fields={'computer_observe':{'token'},'computer_navigate':{'token','url'},'computer_scroll':{'token','direction'}}
        if name not in fields or not isinstance(args,dict) or set(args)!=fields[name]:raise ValueError('Invalid Safari tool arguments.')
        if args['token']!=(self.token or ''):raise ValueError('Stale observation token; use the last returned token.')
        operation=name.removeprefix('computer_')
        if operation=='scroll' and not self.scroll_available:
            raise ValueError('Safari scrolling requires Allow JavaScript from Apple Events; no scroll was attempted.')
        if self.token is None:
            if operation!='observe':raise ValueError('Observe the selected window before acting.')
            operation='launch' if native.managed_target(self.target) else 'bind'
        if operation=='navigate' and args['url'] not in self.spec['allowed_urls']:raise ValueError('URL not in the frozen exact grant.')
        if operation=='scroll' and args['direction'] not in ('up','down'):raise ValueError('Invalid scroll direction.')
        row=journal.get(self.db,self.ident)
        expected=args.get('url',row['current_url'])
        request={'protocol':native.PROTOCOL,'operation':operation,'token':self.token,
                 'observation_request':native.request(self.target,expected,row['exact_request'],False,self.spec['local_fixture'],launch=operation=='launch')}
        for key in ('url','direction'):
            if key in args:request[key]=args[key]
        if operation in ('bind','launch'):
            request.update(allow_refresh=True,allowed_urls=self.spec['allowed_urls'],max_seconds=max(1,int(row['deadline']-time.time())),
                           ownership={'label':self.label,'event_path':str(self.event),'cancel_path':str(self.control/'cancel.json')})
        action=journal._claim(self.db,self.ident,request,None)
        response=None;phase='native_dispatch'
        try:
            response=self.driver.call(request)
            phase='evidence_validation'
            if 'scroll_available' in response:
                if type(response['scroll_available']) is not bool:raise ValueError('Invalid Safari scroll capability receipt.')
                self.scroll_available=response['scroll_available']
            # A live-page refresh is a positive no-effect receipt. Navigation's
            # requested destination must not be mistaken for the observed URL.
            refreshed=response.get('refreshed') is True
            if refreshed:
                if response.get('action_executed') is not False or operation not in ('navigate','scroll'):raise ValueError('Invalid no-action refresh receipt.')
            receipt=journal._save(row,action,request,response,refresh_url=row['current_url'] if refreshed else None)
            receipt.update(refreshed=refreshed,action_executed=response.get('action_executed'),call_id=call_id)
            phase='evidence_commit'
            with transaction(self.db):
                total=receipt['files']['page.txt']['bytes']+sum(json.loads(a['receipt'])['files']['page.txt']['bytes'] for a in journal.actions(self.db,self.ident) if a['receipt'])
                if total>200000:raise ValueError('Safari evidence budget exceeded.')
                self.db.execute("UPDATE relay_computer_actions SET state='completed',receipt=? WHERE id=?",(journal.encoded(receipt),action))
                self.db.execute('UPDATE relay_computer_assignments SET current_url=? WHERE id=?',(receipt['url'],self.ident))
            self.token=receipt['token']
            self.target=receipt['target']
            self.check()
            return {'observation':action,'token':self.token,'url':receipt['url'],
                    'text':(Path(receipt['folder'])/'page.txt').read_text(),
                    'unexecuted_actions':self.action_gaps(),
                    'refreshed':refreshed,'scroll_available':self.scroll_available,'action_executed':response.get('action_executed',operation in ('navigate','scroll')),
                    'evidence':receipt['files']['page.txt'],'coverage':response['observation']['coverage']}
        except BaseException as exc:
            self.failed=True
            # Preserve only a bounded machine error code, never native diagnostic
            # text that could contain page contents or credentials.
            from .host_computer import NativeSessionError
            code=exc.code if isinstance(exc,NativeSessionError) else response.get('error') if isinstance(response,dict) else None
            code=code if isinstance(code,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,159}',code) else None
            self.failure={'operation':operation,'phase':phase,'code':code or 'diagnostic_unavailable'}
            detail='Safari '+operation+' failed during '+phase+'; outcome uncertain; no replay. Native error: '+self.failure['code']
            with transaction(self.db):
                self.db.execute("UPDATE relay_computer_actions SET state='uncertain',error=? WHERE id=? AND state='claimed'",(detail,action))
                self.db.execute("UPDATE relay_computer_assignments SET state='blocked' WHERE id=? AND state='running'",(self.ident,))
            if self.pending():raise UncertainAction(detail) from exc
            raise

    def close(self,completed=False):
        # Consume panel decisions even when a provider call failed/in flight.
        try:self.check()
        except ValueError:pass
        with transaction(self.db):
            self.db.execute("UPDATE relay_computer_assignments SET state=? WHERE id=? AND state='running'",('completed' if completed and not self.pending() else 'blocked',self.ident))


def action_gaps(history):
    """Track positive no-effect receipts; never dispatch or resolve uncertainty."""
    gaps=[]
    for action in history:
        request=json.loads(action['request']);operation=request['operation']
        if operation not in ('navigate','scroll') or action['state']!='completed':continue
        receipt=json.loads(action['receipt'])
        detail={k:request[k] for k in ('url','direction') if k in request}
        if operation=='scroll':detail['source_url']=request['observation_request']['expected_url']
        if receipt.get('action_executed') is False:
            gaps.append({'observation':action['id'],'operation':operation,**detail})
        elif receipt.get('action_executed') is True:
            # One later explicit model decision can satisfy the same deferred
            # operation, including repeated refreshes; unrelated actions cannot.
            gaps=[g for g in gaps if (g['operation'],{k:g[k] for k in ('url','direction','source_url') if k in g})!=(operation,detail)]
    return gaps
