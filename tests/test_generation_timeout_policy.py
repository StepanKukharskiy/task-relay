"""Actual worker loop and supervisor reconciliation, scripted transports only."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from orchestrator import executors,provider_recovery
from orchestrator.adapters import GeminiFactory
from orchestrator.workers import CodexFactory,atomic
from orchestrator.gemini_worker import execute
from task_relay import gemini
from tests import test_generation_recovery as fixtures
from tests import test_shared_code_workers as shared


class Tests(unittest.TestCase):
    setUp=shared.Tests.setUp
    backend=shared.Tests.backend
    setup_worker=fixtures.Tests.setup_worker

    def run_worker(self,control=None,provider='gemini',failures=1):
        control=control or self.control;reader=self.setup_worker(provider,code=False,control=control)
        transport=shared.Transport(provider,self.frozen);seen=[]
        def request(*a,**kw):
            seen.append(copy.deepcopy(a[1]))
            if len(seen)<=failures:raise gemini.ProviderError('timeout',uncertain=True,detail={'failure_kind':'timeout'})
            return transport.request(*a,**kw)
        return execute(self.frozen,control,type('Client',(),{'request':staticmethod(request)})(),reader),seen

    def inspect(self,control=None):
        session=dict(control=str(control or self.control),id=self.frozen['assignment_id'],backend=self.frozen['backend'],
            generation_recovery=self.frozen.get('generation_recovery'),provider_requests=executors.request_limit(self.frozen))
        with patch.object(CodexFactory,'inspect',return_value=dict(status='finished',exit_code=0)):
            return GeminiFactory().inspect(session)

    def test_authorized_timeouts_complete_without_replaying_tools_and_keep_unknown_usage(self):
        self.frozen['generation_recovery']=dict(version=1,max_retries=2)
        for provider in executors.PROVIDERS:
            with self.subTest(provider=provider),tempfile.TemporaryDirectory(dir=self.root) as temp:
                control=Path(temp);result,seen=self.run_worker(control,provider,failures=2)
                self.assertEqual(result['decision'],'delivered');self.assertEqual(len(seen),4)
                self.assertEqual(len(list(control.glob('tool-*.json'))),2)
                self.assertEqual(json.loads((control/'api-01.outcome.json').read_text())['outcome'],'uncertain')
                status=self.inspect(control)
                self.assertEqual(status['status'],'finished');self.assertEqual(status['pending_requests'],[])
                self.assertEqual(status['unknown_provider_usage'],['api-01','api-02'])
                self.assertEqual(status['api_requests'],4)
                # Journal changes invalidate the exemption; no implicit reconciliation.
                atomic(control/'api-01.outcome.json',dict(outcome='uncertain',http_status=None,provider_error={'failure_kind':'connection'}))
                self.assertEqual(self.inspect(control)['status'],'uncertain')

    def test_missing_grant_exhaustion_and_pending_external_work_stay_uncertain(self):
        for mode in ('no_grant','retry_limit','request_limit','pending_code','cancel'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as temp:
                control=Path(temp);self.frozen.pop('generation_recovery',None)
                self.frozen['limits']['provider_requests']=8
                if mode!='no_grant':self.frozen['generation_recovery']=dict(version=1,max_retries=2)
                if mode=='request_limit':self.frozen['limits']['provider_requests']=1
                if mode=='pending_code':
                    (control/'code-pending').mkdir();atomic(control/'code-pending/intent.json',{})
                if mode=='cancel':atomic(control/'cancel.json',{})
                with self.assertRaises((gemini.ProviderError,ValueError)):self.run_worker(control,failures=3)
                requests=list(control.glob('api-*.request.json'))
                self.assertEqual(len(requests),3 if mode=='retry_limit' else 0 if mode=='cancel' else 1)
                if mode!='cancel':self.assertEqual(self.inspect(control)['status'],'uncertain')
                self.assertFalse(list(control.glob('tool-*.json')))

    def test_hosted_tools_billing_and_unsupported_workers_cannot_gain_retry(self):
        backend=self.backend('gemini');request=dict(provider='gemini',model=backend['model'],endpoint='models/'+backend['model']+':generateContent',payload={'tools':[{'functionDeclarations':[]}]})
        outcome=dict(outcome='uncertain',http_status=None,provider_error={'failure_kind':'timeout'})
        self.assertTrue(provider_recovery.eligible(backend,request,outcome))
        for tools in ([{'googleSearch':{}}],[{'functionDeclarations':[],'codeExecution':{}}]):
            edited=copy.deepcopy(request);edited['payload']['tools']=tools
            self.assertFalse(provider_recovery.eligible(backend,edited,outcome))
        self.assertFalse(provider_recovery.eligible(backend,request,{**outcome,'http_status':402}))
        self.assertFalse(provider_recovery.eligible({**backend,'type':'gemini-browser'},request,outcome))

    def test_receipt_cannot_expand_dispatch_grant_or_survive_changed_request(self):
        self.frozen['generation_recovery']=dict(version=1,max_retries=2);self.run_worker()
        self.frozen['generation_recovery']['max_retries']=1
        self.assertEqual(self.inspect()['status'],'uncertain')
        self.frozen['generation_recovery']['max_retries']=2
        request=self.control/'api-01.request.json';data=json.loads(request.read_text());data['payload']['tools'].append({'googleSearch':{}});atomic(request,data)
        self.assertEqual(self.inspect()['status'],'uncertain')


if __name__=='__main__':unittest.main()
