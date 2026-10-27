"""Inline completion belongs only to the exact saved ungated text-result stage."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import Mock
from task_relay import request_contract as scope,orchestrator_files as files

STAGE=dict(id='report',route='conversation',gate='none',deliverables={'status':'Reviewed outcome'})
CONTRACT=dict(mode='existing_work',reason='Finish saved reporting stage',outcomes=[dict(id='status',description='Reviewed outcome',kind='result',count=1,format='',checks=[],validation=[])])
REPLY=dict(answer='Reviewed candidate; buyer checks remain and no acceptance is inferred.',action=None,work_status='respond')

class Tests(unittest.TestCase):
    def test_exact_explicit_inline_completion_compiles_without_changing_frozen_scope(self):
        raw=json.dumps(REPLY);sealed=scope.seal(raw,CONTRACT,STAGE);value=json.loads(sealed)
        self.assertEqual(value['request_contract'],CONTRACT)
        self.assertEqual(value['action'],dict(kind='pipeline_result',result=REPLY['answer'],choices=[]))
        scope.route(value)
        self.assertIsNone(json.loads(raw)['action'])
    def test_clarifications_choices_files_new_work_and_wrong_outcomes_are_not_completed(self):
        for change in ['missing_status','needs_input','blocked','choice','production','new_work','wrong_id','file']:
            stage=copy.deepcopy(STAGE);contract=copy.deepcopy(CONTRACT);reply=copy.deepcopy(REPLY)
            if change=='missing_status':reply.pop('work_status')
            elif change in ['needs_input','blocked']:reply['work_status']=change
            elif change=='choice':stage['gate']='choice'
            elif change=='production':stage['route']='production'
            elif change=='new_work':contract['mode']='new_work'
            elif change=='wrong_id':contract['outcomes'][0]['id']='unrequested'
            elif change=='file':contract['outcomes'][0].update(kind='file',format='.md',checks=['utf8'])
            value=scope.stage_response(dict(reply,request_contract=contract),stage)
            with self.subTest(change=change):self.assertIsNone(value['action'])
    def test_provider_journal_retains_original_reply_and_records_scoped_compilation(self):
        from tests.test_orchestrator_files import Tests as Fixtures
        fixture=Fixtures();fixture.setUp()
        try:
            response={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'text':json.dumps(REPLY)}]}}]}
            client=Mock();client.request.return_value=response
            out=files.run('gemini',client,'fixture',fixture.request('gemini'),[],fixture.receipt,frozen_intake=CONTRACT,pipeline_stage=STAGE)
            value=json.loads(out);self.assertEqual(value['action']['kind'],'pipeline_result')
            saved=json.loads(fixture.receipt.read_text());self.assertEqual(saved[0]['response'],response)
            self.assertEqual(saved[0]['stage_result_compilation']['action'],value['action'])
            client.request.assert_called_once()
        finally:fixture.tearDown()
