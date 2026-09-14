"""Route frozen sessions to agents or trusted, supervised registered operations."""
import json
from pathlib import Path
import shutil
import sys
import time

from .workers import CodexFactory, SUPERVISOR, atomic, prepare_supervisor, supervisor_support
from . import execution, executors


class GeminiFactory(CodexFactory):
    """Shared process ownership; API file tools never invoke the Codex executable."""
    def create(self,control,workspace,frozen,backend):
        from . import executors
        executors.available(backend)
        provider=backend['type'].removesuffix('-browser') if backend['type'] in executors.BROWSER_TYPES else 'gemini'
        config,_=executors.configured() if provider=='gemini' else executors.configured(provider)
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('API executor; frozen assignment supplies scope.\n')
        python=sys.executable;worker='gemini_worker.py'
        if backend['type'] in executors.BROWSER_TYPES:
            from task_relay.host import HOST
            from task_relay.relay_paths import PATHS
            python=HOST.browser_python(PATHS.install,PATHS.data);worker='browser_worker.py'
        browser_support={}
        if backend['type'] in executors.BROWSER_TYPES:
            from .browser_worker import support_hashes
            browser_support=support_hashes()
        command=[python,str(Path(__file__).with_name(worker)),str(control),str(workspace)]
        atomic(control/'launch.json',{'token':frozen['assignment_id'],'created':time.time(),'host_support_sha256':support_hash,'host_support_files':supervisor_support(control),'workspace':str(workspace),
            'limits':frozen['limits'],'registered_command':command,'backend':backend,
            'browser_support':browser_support,
            'credential_fingerprint':executors.fingerprint(config,backend)})
        return {'id':frozen['assignment_id'],'control':str(control),'adapter':'gemini-agent','backend':backend}

    def inspect(self,session):
        result=super().inspect(session)
        if result['status']!='finished':return result
        control=Path(session['control']);unknown=[]
        for request in sorted(control.glob('api-*.request.json')):
            stem=request.name.removesuffix('.request.json');outcome=control/(stem+'.outcome.json')
            detail=json.loads(outcome.read_text()) if outcome.exists() else {}
            if not (control/(stem+'.response.json')).exists() and detail.get('outcome')!='rejected':unknown.append(stem)
        result.update(backend=session['backend'],api_requests=len(list(control.glob('api-*.request.json'))))
        browser_result=control/'browser-result.json'
        if session['backend']['type'] in executors.BROWSER_TYPES and browser_result.exists():
            try:
                detail=json.loads(browser_result.read_text())
                if not isinstance(detail,dict) or not isinstance(detail.get('actions'),list) or not isinstance(detail.get('uncertain_actions'),list) or not detail.get('profile') or not detail.get('job'):
                    raise ValueError('Incomplete browser receipt')
                if session.get('id') and detail['job']!=session['id']:raise ValueError('Browser receipt belongs to another assignment')
                result['browser']=detail
                if detail['uncertain_actions']:unknown.append('browser_actions')
            except (ValueError,OSError):unknown.append('invalid_browser_receipt')
        elif session['backend']['type'] in executors.BROWSER_TYPES:
            unknown.append('missing_browser_receipt')
        result.update(external_outcome='unknown' if unknown else 'no_pending_response',pending_requests=unknown)
        if unknown and not (control/'cancel.json').exists():
            result.update(status='uncertain',local_terminal=True,reason='Provider or browser outcome is unknown; stopped locally, never replayed or switched providers.')
        return result


class RegisteredFactory(CodexFactory):
    def create(self,control,workspace,frozen,backend):
        execution.available(frozen)
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('Registered operation; no agent prompt.\n')
        # This argv is service-owned. It cannot be supplied by a graph or model.
        command=[sys.executable,str(Path(__file__).with_name('step_runner.py')),str(control),str(workspace)]
        atomic(control/'launch.json',{'token':frozen['assignment_id'],'created':time.time(),'host_support_sha256':support_hash,'host_support_files':supervisor_support(control),
            'workspace':str(workspace),'limits':frozen['limits'],'registered_command':command,
            'execution':frozen['execution'],'kind':execution.REGISTRY[frozen['execution']['capability']]['kind']})
        return {'id':frozen['assignment_id'],'control':str(control),'adapter':'registered','execution':frozen['execution']}

    def inspect(self,session):
        result=super().inspect(session)
        if result['status']!='finished':return result
        control=Path(session['control']);operation=control/'operation.json'
        details=json.loads(operation.read_text()) if operation.exists() else {}
        result.update(execution=session['execution'],operation=details)
        if execution.REGISTRY[session['execution']['capability']]['kind']=='api':
            sent=(control/'request.json').exists();received=(control/'response.json').exists()
            if received:
                response=json.loads((control/'response.json').read_text())
                details.update(upstream_id=details.get('upstream_id') or response.get('responseId') or response.get('id') or response.get('request_id'),usage=response.get('usageMetadata',response.get('usage',{})))
            if (control/'remote.json').exists(): details['remote']=json.loads((control/'remote.json').read_text())
            uncertain=details.get('outcome')=='uncertain' or (sent and not received and details.get('outcome')!='rejected')
            if uncertain:
                result['external_outcome']='unknown'
                if not (control/'cancel.json').exists():
                    result.update(status='uncertain',reason='API submission outcome is unknown; no automatic retry. Local process has stopped.',local_terminal=True)
            elif received:result['external_outcome']='response_received'
            else:result['external_outcome']='rejected' if sent else 'not_submitted'
        return result


class ExecutionFactory:
    def __init__(self,agents=None,registered=None,gemini=None):
        self.agents=agents or CodexFactory();self.registered=registered or RegisteredFactory();self.gemini=gemini or GeminiFactory()

    def available(self,backend):
        from .executors import available
        available(backend)

    def create(self,control,workspace,frozen,backend):
        if frozen.get('execution'):adapter=self.registered
        elif backend['type'] in executors.API_TYPES:adapter=self.gemini
        elif backend['type']=='codex-cli':adapter=self.agents
        else:raise ValueError('Unsupported execution provider; no fallback.')
        return adapter.create(control,workspace,frozen,backend)

    def adapter(self,session):
        kind=session.get('adapter')
        if kind=='registered':return self.registered
        if kind=='gemini-agent':return self.gemini
        if kind is None:return self.agents  # Existing Codex sessions keep their adapter.
        raise ValueError('Unknown saved execution adapter; no fallback.')

    def submit(self,session):return self.adapter(session).submit(session)
    def inspect(self,session):return self.adapter(session).inspect(session)
    def cancel(self,session):return self.adapter(session).cancel(session)
