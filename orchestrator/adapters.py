"""Route frozen sessions to agents or trusted, supervised registered operations."""
import json
from pathlib import Path
import shutil
import sys
import time

from .workers import CodexFactory, SUPERVISOR, atomic, prepare_supervisor, supervisor_support
from . import execution, executors
from task_relay.runtime_process import command as python_command


def unresolved_operations(control):
    """Read durable local operation intents without dispatching or reconciling."""
    control=Path(control);unknown=[]
    for intent in control.glob('work-operations/*/intent.json'):
        outcome=intent.with_name('outcome.json')
        try:
            if not outcome.exists() or json.loads(outcome.read_text()).get('status') not in ('completed','failed'):
                unknown.append('work-operations/'+intent.parent.name)
        except (ValueError,OSError):unknown.append('work-operations/'+intent.parent.name)
    for intent in control.glob('code-*/intent.json'):
        if not intent.with_name('outcome.json').exists():unknown.append(intent.parent.name)
    return unknown


class AgentFactory(CodexFactory):
    """Shared agent process ownership; the selected provider owns its transport."""
    def create(self,control,workspace,frozen,backend):
        from . import executors
        executors.available(backend)
        provider=executors.provider_for(backend)
        if provider=='codex':
            from .codex_transport import configuration
            config,_=configuration(backend)
        else:config,_=executors.configured_worker(provider,'code' if backend['type'] in executors.CODE_TYPES else 'computer' if backend['type'] in executors.COMPUTER_TYPES else 'browser' if backend['type'] in executors.BROWSER_TYPES else 'agent')
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('API executor; frozen assignment supplies scope.\n')
        python=sys.executable;worker='agent_loop.py'
        if backend['type'] in executors.CODE_TYPES:
            from task_relay import code_runtime
            python=code_runtime.available(backend['runtime'])['runtime']['python']
        if backend['type'] in executors.BROWSER_TYPES:
            from task_relay.host import HOST
            from task_relay.relay_paths import PATHS
            python=HOST.browser_python(PATHS.install,PATHS.data);worker='browser_worker.py'
        browser_support={}
        if backend['type'] in executors.BROWSER_TYPES:
            from .browser_worker import support_hashes
            browser_support=support_hashes()
        computer_support={}
        if backend['type'] in executors.COMPUTER_TYPES:
            from .computer_worker import support_hashes
            worker='computer_worker.py';computer_support=support_hashes()
        command=python_command(python,Path(__file__).with_name(worker),control,workspace)
        atomic(control/'launch.json',{'token':frozen['assignment_id'],'created':time.time(),'host_support_sha256':support_hash,'host_support_files':supervisor_support(control),'workspace':str(workspace),
            'limits':frozen['limits'],'registered_command':command,'backend':backend,
            'browser_support':browser_support,'computer_support':computer_support,
            'credential_fingerprint':executors.fingerprint(config,backend)})
        return {'id':frozen['assignment_id'],'control':str(control),'adapter':'agent-session','backend':backend,'generation_recovery':frozen.get('generation_recovery'),
                'provider_requests':executors.request_limit(frozen)}

    def inspect(self,session):
        result=super().inspect(session)
        if result['status']!='finished':return result
        control=Path(session['control']);unknown=[];provider_failures=[];abandoned=[]
        for request in sorted(control.glob('api-*.request.json')):
            stem=request.name.removesuffix('.request.json');outcome=control/(stem+'.outcome.json')
            detail=json.loads(outcome.read_text()) if outcome.exists() else {}
            if not (control/(stem+'.response.json')).exists() and executors.synchronous_unavailable(session['backend'],json.loads(request.read_text()),detail):
                provider_failures.append({'request':stem,'http_status':503,'kind':'synchronous_service_unavailable'})
                continue
            if not (control/(stem+'.response.json')).exists() and detail.get('outcome')!='rejected':
                from .provider_recovery import abandoned as verified_abandonment
                if verified_abandonment(control,stem,session,len(abandoned)+1):abandoned.append(stem)
                else:unknown.append(stem)
        unknown.extend(unresolved_operations(control))
        result.update(backend=session['backend'],api_requests=len(list(control.glob('api-*.request.json'))))
        if session['backend']['type'] in ('codex-agent','codex-code'):
            count=result['api_requests']
            result.update(decision_exchanges=count,api_requests=None if count else 0,budget_semantics='cli-exchanges-v1')
            if (control/'codex-usage.json').is_file():result['cli_usage']=json.loads((control/'codex-usage.json').read_text())
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
        if session['backend']['type'] in executors.COMPUTER_TYPES:
            try:
                native=json.loads((control/'computer-result.json').read_text())
                if native['worker']!=session['id'] or not isinstance(native['uncertain_actions'],list):raise ValueError('Wrong computer receipt')
                result['computer']=native
                if native['uncertain_actions']:unknown.append('computer_actions')
                failure=native.get('failure')
                if native['uncertain_actions'] and isinstance(failure,dict):
                    import re
                    code=failure.get('code');operation=failure.get('operation');phase=failure.get('phase')
                    if (isinstance(code,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,159}',code)
                        and operation in ('launch','bind','observe','navigate','scroll')
                        and phase in ('native_dispatch','evidence_validation','evidence_commit')):
                        result['reason']=f'Safari {operation}: {code} ({phase}).'
            except (OSError,ValueError,KeyError,TypeError):unknown.append('missing_or_invalid_computer_receipt')
        result.update(external_outcome='unknown' if unknown else 'no_pending_response',pending_requests=unknown)
        if abandoned:result.update(abandoned_generations=abandoned,unknown_provider_usage=abandoned)
        if provider_failures:
            result['provider_failures']=provider_failures
            if result.get('exit_code') and not unknown and provider_failures[-1]['request']==stem:
                result['reason']='Model service unavailable (HTTP 503); no tool response was returned. Saved local work is retained.'
        agent_result=control/'agent-result.json'
        if result.get('exit_code') and not result.get('reason') and agent_result.is_file() and not agent_result.is_symlink() and agent_result.stat().st_size<=200000:
            try:
                detail=json.loads(agent_result.read_text())
                if detail.get('outcome')=='failed' and isinstance(detail.get('reason'),str):
                    result['reason']=detail['reason'][:1800]
            except (ValueError,OSError,AttributeError):pass
        if unknown and not (control/'cancel.json').exists():
            reason=result.get('reason')
            result.update(status='uncertain',local_terminal=True,reason='Provider, browser, code or registered work outcome is unknown; stopped locally, never replayed or switched providers.'+(' '+reason if reason else ''))
        return result


class RegisteredFactory(CodexFactory):
    def create(self,control,workspace,frozen,backend):
        execution.available(frozen)
        control=Path(control);control.mkdir(parents=True,exist_ok=False)
        support_hash=prepare_supervisor(control,frozen)
        (control/'prompt.txt').write_text('Registered operation; no agent prompt.\n')
        # This argv is service-owned. It cannot be supplied by a graph or model.
        command=python_command(sys.executable,Path(__file__).with_name('step_runner.py'),control,workspace)
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
        execution.adapter(session['execution']['capability']).inspect(control,result,details)
        return result


GeminiFactory = AgentFactory  # Compatibility import for captured integrations.


class ExecutionFactory:
    def __init__(self,agents=None,registered=None,gemini=None,agent_session=None):
        self.agents=agents or CodexFactory();self.registered=registered or RegisteredFactory();self.agent_session=agent_session or gemini or AgentFactory();self.gemini=self.agent_session

    def available(self,backend):
        from .executors import available
        available(backend)

    def create(self,control,workspace,frozen,backend):
        if frozen.get('execution'):adapter=self.registered
        elif backend['type'] in executors.API_TYPES:adapter=self.agent_session
        elif backend['type']=='codex-cli':adapter=self.agents
        else:raise ValueError('Unsupported execution provider; no fallback.')
        return adapter.create(control,workspace,frozen,backend)

    def adapter(self,session):
        kind=session.get('adapter')
        if kind=='registered':return self.registered
        if kind in ('agent-session','gemini-agent'):return self.agent_session
        if kind is None:return self.agents  # Existing Codex sessions keep their adapter.
        raise ValueError('Unknown saved execution adapter; no fallback.')

    def submit(self,session):return self.adapter(session).submit(session)
    def inspect(self,session):return self.adapter(session).inspect(session)
    def cancel(self,session):return self.adapter(session).cancel(session)
