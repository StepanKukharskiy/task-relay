"""Free-form rejection -> typed preparation -> acquisition -> failed corrections/re-review."""
import json
from pathlib import Path
from tests.test_acquisition_render_lifecycle import AcquisitionRender
from tests.test_owner_intents import worker
from tests.test_visual_selection_lifecycle import VisualPath

class InventoryAcquisition(AcquisitionRender):
    def inventory_preflight(self):
        # An ordinary worker may produce useful prose/plans, as in the live
        # failure. The consumer must reject that shape BEFORE photo dispatch.
        self.submit('ordinary_plan',[worker('ordinary_plan',[{'artifact':self.inv['artifact']}],media='application/json')])
        raw=json.dumps(dict(schema='ordinary-plan/1',inventory=[dict(label=i['label']) for i in self.h.inventory['items']]))
        self.run_steps('ordinary_plan',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text=raw))])
        original=self.artifact('ordinary_plan');before=Path(original['blob']).read_bytes()
        bad=dict(id='bad_photos',objective='Try saved planning data',operation='images.products',parameters=dict(inventory_path={'artifact':original['id']},catalog_path=None,source_pack_path={'artifact':self.pack['artifact']},count_policy='target'))
        good=dict(id='typed_subjects',objective='Prepare exact subjects from saved plan; retain unknown details',content=dict(family='collection.subjects',sources=dict(source_path={'artifact':original['id']}),parameters=dict(max_records=11,fields=[])))
        result,script=self.invoke([('job_delegate',dict(request_id='bad_shape',tasks=[bad])),('job_delegate',dict(request_id='prepare_subjects',tasks=[good]))])
        self.assertEqual(result['outcome'],'yielded')
        self.assertIn('Inventory handoff needs an items projection',json.dumps(script.requests))
        self.assertNotIn('bad_photos',[t['id'] for t in self.rt.status('job')['tasks']])
        self.rt.tick('job')
        records=[dict(kind='item',slot=n+1,label=i['label'],attributes={},quote=i['label'],bbox=None,notes='Buying details unknown') for n,i in enumerate(self.h.inventory['items'])]+[dict(kind='end',count=11,notes='Complete scope')]
        VisualPath.run_worker(self,'typed_subjects',lambda f:[('operation_submit',dict(request_key='s'+str(n),revision=n,records=[v])) for n,v in enumerate(records)])
        rid=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')=='typed_subjects')
        VisualPath.run_worker(self,rid,lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs'] if i.get('media_type')=='application/json']+[('file_write',dict(path=f['outputs'][0]['path'],text='Exact source labels retained; gaps and unknowns disclosed.'))],decision='accept')
        typed=self.artifact('typed_subjects');self.inv={'artifact':typed['id']}
        self.h.inventory=json.loads(Path(typed['blob']).read_bytes())
        self.assertEqual(Path(original['blob']).read_bytes(),before)

    def test_inventory_acquisition_failed_correction_full_path(self):
        self.test_acquisition_failed_saved_section_restart_render_rereview_partial()

class Plants(InventoryAcquisition):schema='plants'
class Components(InventoryAcquisition):schema='components'
