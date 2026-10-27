"""Existing full failed-correction graph through prospective node declarations."""
import json
from unittest.mock import patch
from orchestrator import job_owner
from tests import test_inventory_acquisition_lifecycle as existing

class NodeLifecycle(existing.InventoryAcquisition):
    def setUp(self):
        create=job_owner.create
        def nodes(rt,run,request,backend,inputs,grant,**kw):
            grant['execution_policy']=dict(version=2,review='independent',public_read=False)
            return create(rt,run,request,backend,inputs,grant,**kw)
        with patch.object(job_owner,'create',side_effect=nodes):super().setUp()

    def invoke(self,steps,run='job'):
        calls=[]
        for name,args in steps:
            name=next((n for n,old in job_owner.NODE_NAMES.items() if old==name),name)
            if name=='node_read':args={**{k:v for k,v in args.items() if k!='artifact'},'reference':{'artifact':args['artifact']}}
            if name=='node_run':args={'tasks':args['tasks']}
            elif name=='node_result':args=dict(outputs={key:{'artifact':v} for key,v in json.loads(args['deliverables_json']).items()},summary=args['summary'])
            calls.append((name,args))
        return super().invoke(calls,run)

    def test_node_failed_correction_render_review_partial(self):
        self.test_inventory_acquisition_failed_correction_full_path()
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['execution_policy']['version'],2)
