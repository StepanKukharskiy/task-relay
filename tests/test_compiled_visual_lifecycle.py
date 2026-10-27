"""Public intent -> automatic partitions -> real merge -> full visual lifecycle.

Eleven subjects cross the unchanged 24-request partition threshold. Six synthetic
leads for S0 permit three designs; other subjects remain explicit target gaps.
"""
import copy,json
from pathlib import Path
from unittest.mock import patch
from tests import test_visual_selection_lifecycle as visual
from tests import test_correction_handoff_lifecycle as chain
from orchestrator import operation_contracts as c

class Compiled(visual.VisualPath):
    def setUp(self):
        harness=chain.Harness
        create=chain.job_owner.create
        def allowed(rt,run,request,backend,inputs,grant,*a,**kw):
            grant["operations"].append("records.merge")
            self.initial=copy.deepcopy(grant)
            return create(rt,run,request,backend,inputs,grant,*a,**kw)
        with patch.object(chain,'Harness',side_effect=lambda *a,**kw:harness(*a,**kw,count=11)), patch.object(chain.job_owner,'create',side_effect=allowed):
            super().setUp()
        self.params['max_records']=11
    def repair(self,ident,base,fragment,source,blocked=False):
        self.assertFalse(blocked)
        task=self.content(ident,source,base)
        old=json.loads(Path(base['blob']).read_text());digest=old['source_versions']['source_pack_sha256']
        parent=next(dict(a) for a in self.rt.db.execute('select * from production_artifacts where sha256=?',(digest,)))
        task['inputs'].append({'artifact':parent['id']})
        self.submit(ident,[task])
        self.run_worker(ident,lambda f:[('operation_amend',dict(request_key='correct',revision=0,expected_record_sha256=c.digest(old['records'][0]),record=fragment))])
        catalog=self.artifact(ident);pack=self.artifact(ident,'delivery/retained-sources.json')
        doc=json.loads(Path(catalog['blob']).read_text());self.assertEqual(doc['source_versions']['source_pack_sha256'],pack['sha256'])
        self.assertNotEqual(doc['items'][0]['options'][0]['option_id'],old['items'][0]['options'][0]['option_id'])
        self.review(ident);return catalog,pack

    def is_merge(self,ident):
        return self.rt.spec(self.rt.task('job',ident)).get('execution',{}).get('capability')=='records.merge'

    def artifact(self,task,path='outputs/result.json'):
        if self.is_merge(task):path={'outputs/result.json':'delivery/catalog.json','delivery/retained-sources.json':'delivery/source-pack.json'}.get(path,path)
        return super().artifact(task,path)

    def review(self,ident):
        if self.is_merge(ident):
            self.assertEqual(self.rt.task('job',ident)['status'],'completed');return
        return super().review(ident)

    def run_worker(self,ident,steps,decision='delivered'):
        if not self.is_merge(ident):return super().run_worker(ident,steps,decision)
        specs=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id'].startswith(ident+'_batch_') and not self.rt.spec(t).get('review_of')]
        self.assertEqual(len(specs),2)
        for chunk in specs:
            bounds=chunk['operation_contract']['parameters']['record_range']
            def actions(f):
                original=steps(f) if bounds[0]==0 else []
                # Empty submissions retain exact baseline records during corrections.
                for n in ([] if f['operation_contract']['parameters'].get('allow_baseline_amend') else range(max(1,bounds[0]),bounds[1])):
                    original.append(('operation_submit',dict(request_key='retain'+str(n),revision=len(original),records=[dict(item=self.h.inventory['items'][n]['id'],options=[],gap='No observed candidate; explicit target shortfall.')])) )
                if ident in ('repair','repair_again'):
                    # Visual wrapper supplies one benchmark and two photo observations.
                    original += [('file_read',dict(path=f['inputs'][0]['path'],offset=0,limit=100))]*(19-len(original))
                    original += [('file_read',dict(path=f['operation_contract']['output'],offset=0,limit=24000))]
                return original
            result=super().run_worker(chunk['id'],actions,decision)
            if ident in ('repair','repair_again'):
                self.assertEqual(len(result[1].requests),24)
                control=Path(self.factory.sessions[result[0]['assignment_id']]['session']['control'])
                self.assertFalse((control/'api-23.validation.json').exists())
            super().review(chunk['id'])
        self.native(ident)

    def test_compiler_partition_to_visual_correction_review_partial(self):
        self.test_broad_pool_unknown_buying_three_visual_designs_restart_correct_review_partial()
        catalog=json.loads(Path(self.artifact('final_repair')['blob']).read_text())
        self.assertEqual(len(catalog['items']),11)
        self.assertEqual([i['coverage']['suitable'] for i in catalog['items']],[3]+[0]*10)

class Plants(Compiled):
    schema="plants"

class Components(Compiled):
    schema="components"
