"""A successful finish cannot silently discard a positive no-effect receipt."""
import copy,json,unittest
from contextlib import nullcontext
from orchestrator.computer_worker import run
from task_relay import computer_sessions as journal
from task_relay.computer_worker_session import Session
from tests import test_computer_worker as worker_fixture
from tests.test_computer_worker import DynamicHelper,policy
from tests.test_gemini_executor import CONFIG,report


class Model:
    def __init__(self,frozen,mode):self.frozen=frozen;self.mode=mode;self.calls=[];self.token=None
    def request(self,path,payload,**kwargs):
        self.calls.append(copy.deepcopy(payload));n=len(self.calls)
        if n==1:
            self.token=json.loads(payload['contents'][0]['parts'][0]['text'])['computer_observation']['token']
            name,args='computer_scroll',{'token':self.token,'direction':'down'}
        elif n==2:
            response=payload['contents'][-1]['parts'][0]['functionResponse']['response']
            assert response['refreshed'] and response['unexecuted_actions']
            self.token=response['token']
            name,args='file_write',{'path':self.frozen['outputs'][0]['path'],'text':'Synthetic saved evidence, with explicit action accounting.'}
        elif n==3:name,args='finish',{'report_json':json.dumps(report(self.frozen))}
        elif n==4:
            assert 'did not execute' in payload['contents'][-1]['parts'][0]['functionResponse']['response']['error']
            if self.mode=='complete':name,args='computer_scroll',{'token':self.token,'direction':'down'}
            else:
                r=report(self.frozen);r.update(decision='blocked',summary='The requested scroll did not execute; only refreshed text was captured.')
                r['checks'][0].update(passed=False,evidence=r['summary'])
                name,args='finish',{'report_json':json.dumps(r)}
        else:name,args='finish',{'report_json':json.dumps(report(self.frozen))}
        return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args}}]}}]}


class Tests(unittest.TestCase):
    setUp=worker_fixture.Tests.setUp
    tearDown=worker_fixture.Tests.tearDown
    prepare=worker_fixture.Tests.prepare

    def execute(self,mode):
        db=self.prepare();helper=DynamicHelper(db);model=Model(self.frozen,mode)
        result=run(self.frozen,self.control,db,client=model,config_reader=lambda:(CONFIG,self.frozen['backend']),helper=helper,lease_context=nullcontext())
        return db,helper,model,result

    def test_premature_success_is_rejected_then_explicit_matching_action_completes(self):
        db,helper,model,result=self.execute('complete')
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(model.calls),5)
        self.assertEqual([r['operation'] for r in helper.calls],['bind','scroll','scroll'])
        self.assertEqual(helper.calls[-1]['token'],'token-2')
        receipt=json.loads((self.control/'computer-result.json').read_text())
        self.assertEqual(receipt['unexecuted_actions'],[])
        self.assertIn('did not execute',json.loads((self.control/'tool-03-00.json').read_text())['result']['error'])

    def test_explicit_blocker_retains_action_gap_without_another_native_call(self):
        db,helper,model,result=self.execute('blocked')
        self.assertEqual(result['decision'],'blocked');self.assertEqual(len(helper.calls),2)
        receipt=json.loads((self.control/'computer-result.json').read_text())
        self.assertEqual(receipt['unexecuted_actions'][0]['operation'],'scroll')
        self.assertIn('did not execute',json.loads((self.ws/'.relay/result.json').read_text())['summary'])

    def test_observation_and_unrelated_navigation_do_not_satisfy_scroll(self):
        db=self.prepare();helper=DynamicHelper(db)
        ident=journal.approve(db,job='job',request_key='gaps',exact_request='Scroll',spec=policy()['spec'],helper=helper.identity,output_root=self.root/'evidence',actor='fixture')
        session=Session(db,ident,helper,self.control,'fixture')
        session.call('initial','computer_observe',{'token':''})
        session.call('scroll','computer_scroll',{'token':session.token,'direction':'down'})
        session.call('observe','computer_observe',{'token':session.token})
        session.call('navigate','computer_navigate',{'token':session.token,'url':'https://example.com/two'})
        session.call('different-page-scroll','computer_scroll',{'token':session.token,'direction':'down'})
        self.assertEqual(len(session.action_gaps()),1)
        self.assertEqual(session.action_gaps()[0]['source_url'],'https://example.com/one')
