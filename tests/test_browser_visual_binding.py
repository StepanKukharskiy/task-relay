"""Mixed browser/vision plans retain exact explicit image review scope."""
import copy,json,unittest
from orchestrator import worker_capabilities
from task_relay import production_planning as planning
from tests import test_production_planning as fixture
from tests.test_general_browser import policy

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row

    def case(self):
        row=dict(self.queue());payload=json.loads(row['context']);payload.pop('response_contract',None);payload.pop('artifact_binding_version',None)
        source={'artifact':'photo-fixture','path':'saved/photo.jpg','purpose':'Selected original image','authority':'Source context','sha256':'a'*64,'bytes':100,'media_type':'image/jpeg','visual_reference':True}
        payload['sources']=[source];payload['required_artifacts']=['photo-fixture'];payload['browser_input_policy_version']=2;row['context']=json.dumps(payload)
        options=json.loads(row['options']);browser={'type':'gemini-browser','model':'fixture-model'}
        options['worker_catalog'].append(worker_capabilities.entry(browser));row['options']=json.dumps(options)
        result=fixture.Tests.response(self);producer,reviewer=result['plan']['tasks']
        producer.pop('tools');producer.update(browser=policy(),worker={'requires':['files.text','browser.use'],'executor':'gemini-browser'},limits={'seconds':600,'tool_calls':24,'output_bytes':200000},max_attempts=1)
        producer['browser']['interaction_scope']='';producer['browser']['uploads']=[];producer['browser']['downloads']=[]
        reviewer.pop('tools');reviewer['worker']={'requires':['files.text','files.binary','code.execute','images.view'],'executor':'codex-cli'}
        reviewer['inputs'].append({k:source[k] for k in ('artifact','path','purpose','authority','media_type')})
        return row,result,source

    def test_browser_text_research_and_pixel_reviewer_compile_together(self):
        row,result,source=self.case();_,plan=planning.validate_result(json.dumps(result),row)
        producer,reviewer=plan['tasks']
        self.assertNotIn(source['artifact'],[i.get('artifact') for i in producer['inputs']])
        image=next(i for i in reviewer['inputs'] if i.get('artifact')==source['artifact'])
        self.assertTrue(image['visual_reference']);self.assertEqual(image['path'],source['path'])
        self.assertEqual(producer['worker']['executor'],'gemini-browser');self.assertEqual(reviewer['worker']['executor'],'codex-cli')

    def test_explicit_browser_image_binding_still_requires_vision(self):
        row,result,source=self.case();result['plan']['tasks'][0].setdefault('inputs',[]).append({k:source[k] for k in ('artifact','path','purpose','authority','media_type')})
        with self.assertRaisesRegex(ValueError,'No eligible worker'):
            planning.validate_result(json.dumps(result),row)

    def test_historical_plan_keeps_implicit_visual_scope(self):
        row,result,_=self.case();payload=json.loads(row['context']);payload.pop('browser_input_policy_version');row['context']=json.dumps(payload)
        with self.assertRaisesRegex(ValueError,'No eligible worker'):
            planning.validate_result(json.dumps(result),row)
