"""Route frozen sessions to agents or trusted, supervised registered operations."""
import json
from pathlib import Path
import shutil
import sys
import time

from .workers import CodexFactory, SUPERVISOR, atomic, prepare_supervisor
from . import execution


class GeminiFactory(CodexFactory):
    """Shared process ownership; API file tools never invoke the Codex executable."""
    def create(self,control,workspace,frozen,backend):
        from . import executors
        executors.available(backend);config,_=executors.configured()
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('Gemini file executor; frozen assignment supplies scope.\n')
        command=[sys.executable,str(Path(__file__).with_name('gemini_worker.py')),str(control),str(workspace)]
        atomic(control/'launch.json',{'token':frozen['assignment_id'],'created':time.time(),'host_support_sha256':support_hash,'workspace':str(workspace),
            'limits':frozen['limits'],'registered_command':command,'backend':backend,
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
        result.update(backend=session['backend'],api_requests=len(list(control.glob('api-*.request.json'))),
                      external_outcome='unknown' if unknown else 'no_pending_response',pending_requests=unknown)
        if unknown and not (control/'cancel.json').exists():
            result.update(status='uncertain',local_terminal=True,reason='Gemini request outcome is unknown; stopped locally, never replayed or switched providers.')
        return result


class RegisteredFactory(CodexFactory):
    def create(self,control,workspace,frozen,backend):
        execution.available(frozen)
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('Registered operation; no agent prompt.\n')
        # This argv is service-owned. It cannot be supplied by a graph or model.
        command=[sys.executable,str(Path(__file__).with_name('step_runner.py')),str(control),str(workspace)]
        atomic(control/'launch.json',{'token':frozen['assignment_id'],'created':time.time(),'host_support_sha256':support_hash,
            'workspace':str(workspace),'limits':frozen['limits'],'registered_command':command,
            'execution':frozen['execution'],'kind':execution.REGISTRY[frozen['execution']['capability']]['kind']})
        return {'id':frozen['assignment_id'],'control':str(control),'adapter':'registered','execution':frozen['execution']}

    def inspect(self,session):
        result=super().inspect(session)
        if result['status']!='finished':return result
        control=Path(session['control']);operation=control/'operation.json'
        details=json.loads(operation.read_text()) if operation.exists() else {}
        result.update(execution=session['execution'],operation=details)
        if session['execution']['capability']=='gemini.text':
            sent=(control/'request.json').exists();received=(control/'response.json').exists()
            if received:
                response=json.loads((control/'response.json').read_text())
                details.update(upstream_id=response.get('responseId'),usage=response.get('usageMetadata',{}))
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
        elif backend['type']=='gemini-agent':adapter=self.gemini
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
