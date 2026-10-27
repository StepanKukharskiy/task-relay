"""Registered Codex search transport; uses the common source collector/reader."""
import copy
from dataclasses import replace
import time
import uuid
from task_relay.orchestrator_web import Session as PublicSession
from task_relay.gemini import ProviderError
from .codex_transport import Client, configuration, POLICY, Failure, SearchEvidenceError
from .workers import atomic


def backend(params):
    return dict(type='codex-agent',model=params['model'],reasoning=params['reasoning'],budget_semantics=POLICY)


def available(assignment, spec):
    from .executors import validate
    value=backend(assignment['execution']['parameters']);validate(value);configuration(value)


def freeze(frozen):
    config,_=configuration(backend(frozen['execution']['parameters']))
    frozen['codex_executor']=config


def describe(entry, context):
    from task_relay.host import HOST
    try:entry.update(available=bool(HOST.codex()),availability_evidence='CLI executable only; live search and source yield unverified. No Gemini fallback.')
    except (OSError,ValueError,RuntimeError) as exc:entry.update(available=False,availability_evidence=str(exc))


def register(registry, adapters):
    # Distinct transport IDs preserve captured Gemini contracts. Collection,
    # parsing, producer binding, page verification and downstream ports are shared.
    for original in ('web.sources','web.sources.prepared'):
        name=original+'.codex';spec=copy.deepcopy(registry[original])
        spec.update(search_provider='codex',source_mode=original,
            permissions='Codex CLI public web search turns and bounded HTTPS reads. CLI internal requests/usage may be unknown. No Gemini or shell fallback.')
        spec['parameters'].update(model='Exact Codex model',reasoning='Exact Codex reasoning effort')
        spec['support_modules']=list(dict.fromkeys(spec.get('support_modules',[])+['orchestrator.codex_transport','orchestrator.codex_gate','orchestrator.model_binding','orchestrator.codex_rejection','orchestrator.tool_authority','orchestrator.observation_outcomes','orchestrator.receipt_reconciliation']))
        adapter=adapters[original];schema=copy.deepcopy(adapter.parameters)
        schema['properties']['reasoning']=dict(type='string',enum=['low','medium','high','xhigh','max','ultra'])
        schema['required'].append('reasoning')
        adapted=replace(adapter,parameters=schema,backend_binding=dict(provider='codex',parameters=dict(model='model',reasoning='reasoning')),availability=('orchestrator.codex_sources:available',),
                        descriptions=('orchestrator.codex_sources:describe',),freeze_hooks=('orchestrator.codex_sources:freeze',))
        adapted.schema(spec);adapted.manifest()
        registry[name]=spec;adapters[name]=adapted


class Session(PublicSession):
    def search(self, query):
        self.root.mkdir(parents=True,exist_ok=True)
        path=self.root/('search-'+str(self.searches)+'.json')
        if path.exists():
            import json
            from .receipt_reconciliation import restore
            try:
                record=json.loads(path.read_text())
                if not isinstance(record,dict):raise ValueError('Invalid saved search')
            except (OSError,ValueError) as exc:raise Failure('Saved search receipt is unreadable; no new submission',uncertain=True) from exc
            if record.get('query')!=query or record.get('backend')!=self.config['backend']:raise Failure('Saved search belongs to a different request',uncertain=True)
            try:saved=restore(self.root/'codex')
            except (OSError,ValueError,KeyError) as exc:raise Failure('Saved CLI search has no verified response; reconcile without duplicate submission',uncertain=True) from exc
            if not record.get('request_id') or saved.get('scope')!=record['request_id']:raise Failure('Confirmed response belongs to a different submission',uncertain=True)
            result=saved['result']
            if result.get('query')==query and result.get('search_failure'):
                failure=result['search_failure']
                raise Failure(failure['message'],uncertain=False,status=failure['status'],detail=failure['detail'])
            if result.get('query')!=query or not result.get('ok'):raise Failure('Saved response differs from the requested search',uncertain=True)
            # Preserve the original submitted/uncertain record; append recovery.
            recovery=self.root/'search-reconciliation.json'
            if recovery.exists():
                try:
                    prior=json.loads(recovery.read_text())
                    if not isinstance(prior,dict):raise ValueError('Invalid reconciliation')
                except (OSError,ValueError) as exc:raise Failure('Saved reconciliation is unreadable; no new submission',uncertain=True) from exc
                if prior.get('request_id')!=saved['request_id'] or prior.get('original',{}).get('request_id')!=record['request_id']:
                    raise Failure('Reconciliation belongs to a different submission',uncertain=True)
            else:
                atomic(recovery,dict(version=1,original=record,request_id=saved['request_id'],replayed=False,acceptance=False))
            record.update(status='responded',result=result,retrieved_at=time.time())
            atomic(path,record)
            self.evidence.append(dict(kind='search',query=query,sources=result['sources'],summary=result['summary'],metadata=dict(observation_outcome=result.get('observation_outcome'))))
            self.report();return result
        selected=self.config['backend'];config,_=configuration(selected)
        if config!=self.config.get('cli_executor'):raise ValueError('CLI search executable changed after admission; no search dispatched')
        seconds=self.remaining_seconds(cap=None)
        from .provider_cooldown import search_gate,search_failure
        cooldown=search_gate(self.config,self.root,selected,seconds)
        seconds=self.remaining_seconds(cap=None)
        record=dict(request_id=uuid.uuid4().hex,query=query,backend=selected,submitted_at=time.time(),status='submitted',provider_requests=None,
                    transport_seconds=seconds,operation_deadline=self.config.get('operation_deadline'))
        atomic(path,record)
        try:
            with Client(config,selected,self.root/'codex',seconds) as client:
                client.operation_id=record['request_id']
                result=client.search(query)
        except SearchEvidenceError as exc:
            record.update(status='responded',evidence_error=str(exc));atomic(path,record)
            raise
        except ProviderError as exc:
            record.update(status='uncertain' if exc.uncertain else 'rejected',error=str(exc),provider_status=exc.status,detail=exc.detail)
            atomic(path,record)
            if not exc.uncertain and exc.detail.get('journals'):
                from .receipt_reconciliation import commit
                identity=exc.detail['thread']+':'+exc.detail['turn']
                commit(self.root/'codex',identity,dict(id=identity,status='rejected'),
                    dict(query=query,search_failure=dict(message=str(exc),status=exc.status,detail=exc.detail)),
                    evidence=[self.root/'codex'/name for name in exc.detail['journals']],scope=record['request_id'])
            search_failure(cooldown,query,exc,max(0,(self.config.get('operation_deadline') or time.time()+seconds)-time.time()))
            raise
        except (OSError,ValueError) as exc:
            if getattr(exc,'outcome',{}).get('code')=='tool_boundary_unqualified':
                record.update(status='not_submitted',submitted_at=None,error=str(exc),
                              boundary=exc.outcome)
                atomic(path,record)
                raise
            record.update(status='uncertain',error=str(exc));atomic(path,record)
            raise Failure('search: '+str(exc),uncertain=True) from exc
        record.update(status='responded',result=result,retrieved_at=time.time());atomic(path,record)
        self.evidence.append(dict(kind='search',query=query,sources=result['sources'],summary=result['summary'],metadata=dict(observation_outcome=result.get('observation_outcome'))))
        self.report();return result
