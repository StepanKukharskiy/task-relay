import copy,json,unittest
from task_relay import production_planning as planning
from orchestrator import execution
from tests import test_production_planning as fixture

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row

    def test_saved_manifest_binding_remains_json_and_exact_identity(self):
        row=dict(self.queue(action=self.action(step_capabilities=['images.fetch'])))
        payload=json.loads(row['context']);payload.pop('response_contract',None);payload.pop('artifact_binding_version',None)
        source={'artifact':'manifest-fixture','path':'saved/image-sources.json','purpose':'Observed image manifest','authority':'Prior candidate source; no acceptance','sha256':'a'*64,'bytes':100}
        payload['sources']=[source];payload['required_artifacts']=[]
        row['context']=json.dumps(payload)
        result=fixture.Tests.response(self);producer,reviewer=result['plan']['tasks']
        producer['limits']={'seconds':600,'tool_calls':1,'output_bytes':45000000};producer.pop('user_gate');producer.pop('tools');producer.pop('worker',None)
        producer.update(execution={'capability':'images.fetch','version':1,'parameters':{}},inputs=[{k:source[k] for k in ('artifact','path','purpose','authority')}],outputs=[{'path':'photos.zip','purpose':'Observed photographs','media_type':'application/zip'}],criteria=copy.deepcopy(execution.REGISTRY['images.fetch']['criteria']))
        reviewer['criteria']=copy.deepcopy(producer['criteria']);reviewer['inputs']=[{'from_task':producer['id'],'output':'photos.zip','path':'input/photos.zip','purpose':'Inspect exact bundle','authority':'Candidate','media_type':'application/zip'}]
        _,plan=planning.validate_result(json.dumps(result),row)
        bound=plan['tasks'][0]['inputs'];self.assertEqual(len(bound),1)
        self.assertEqual(bound[0]['artifact'],source['artifact']);self.assertEqual(bound[0]['media_type'],'application/json')
        execution.validate(plan['tasks'][0])
