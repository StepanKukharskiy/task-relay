"""Code owns complete subject inventory; browser batches only discover their subset."""
import copy
import unittest
from orchestrator import image_sources
from tests.test_photo_recovery import bundle
from tests.test_image_sources import subject
from task_relay.source_batches import validate
from tests import test_mixed_planning as mixed
from tests.test_mixed_execution import operation
from task_relay import production_planning as planning
from task_relay import text_evidence_planning
import json


class Tests(unittest.TestCase):
    def test_disjoint_feasible_batches_merge_into_complete_code_inventory(self):
        subjects=[subject('one'),subject('two')];original=copy.deepcopy(subjects)
        raw=image_sources.subject_base_bundle(subjects,'a'*64)
        from unittest.mock import patch
        with patch('zipfile.time.localtime',return_value=(2026,10,8,0,0,0)):
            self.assertEqual(image_sources.subject_base_bundle(subjects,'a'*64),raw)
        images,_,base=image_sources.unpack(raw)
        self.assertEqual(images,{})
        self.assertEqual(base['provider'],'code-subject-inventory')
        self.assertEqual(base['source_catalog_sha256'],'a'*64)
        self.assertFalse(base['complete'])
        self.assertEqual(subjects,original)
        result,manifest=image_sources.merge_bundles([raw,bundle(['one'],['one']),bundle(['two'],['two'])])
        self.assertTrue(manifest['complete']);self.assertEqual(manifest['coverage']['found'],2)
        self.assertEqual(len(image_sources.unpack(result)[0]),2)
        self.assertEqual(manifest['source_catalog_sha256'],'a'*64)

    def test_large_inventory_does_not_expand_each_browser_batch(self):
        subjects=[subject('s'+str(i)) for i in range(7)]
        raw=image_sources.subject_base_bundle(subjects,'b'*64)
        self.assertEqual(image_sources.unpack(raw)[2]['coverage']['missing'],7)
        for batch in (subjects[:3],subjects[3:]):
            validate({'tasks':[dict(browser=dict(image_sources=[dict(subjects=batch)]),
                                    limits=dict(tool_calls=24,provider_requests=24))]})

    def test_base_cannot_claim_photos_or_omit_source_identity(self):
        for subjects,digest in [([{**subject('one'),'status':'found'}],'a'*64),
                                ([subject('one')],'invented'),([], 'a'*64)]:
            with self.subTest(subjects=subjects,digest=digest),self.assertRaises(ValueError):
                image_sources.subject_base_bundle(subjects,digest)


class PlanningTests(unittest.TestCase):
    setUp=mixed.Tests.setUp
    tearDown=mixed.Tests.tearDown
    request=mixed.Tests.request
    action=mixed.Tests.action
    queue=mixed.Tests.queue
    row=mixed.Tests.row
    response=mixed.Tests.response

    def test_registered_merge_accepts_only_selected_frozen_zip_sources(self):
        row=dict(self.queue(action=self.action(step_capabilities=['images.merge'])))
        payload=json.loads(row['context']);inputs=[]
        for ident in ('base','recovery','unrelated'):
            path=self.rt.root/(ident+'.zip');path.write_bytes(image_sources.subject_base_bundle([subject('one')],'a'*64))
            aid=self.rt.register(path,'Small code-owned subject ZIP')
            source=planning.source_entry(self.rt,aid,path.name,'Subject inventory','No image evidence')
            payload['sources'].append(source)
            if ident!='unrelated':inputs.append(dict(artifact=aid,path=path.name,purpose='Exact subject ZIP',authority='No image evidence',media_type='application/zip'))
        row['context']=json.dumps(payload)
        from orchestrator.contracts import assignment
        result=self.response();merge=operation('merge','images.merge',inputs,['review'])
        payload['planner_budget_binding_version']=2;row['context']=json.dumps(payload)
        for t in result['plan']['tasks']:t['max_attempts']=1
        merge['outputs']=[dict(path='delivery/photos.zip',purpose='Merged subject inventory',media_type='application/zip')]
        merge=assignment(merge)
        result['plan']['tasks'].append(merge)
        review=copy.deepcopy(result['plan']['tasks'][1]);review.update(id='review-merge',review_of='merge',dependencies=['merge'],criteria=copy.deepcopy(merge['criteria']))
        review['inputs']=[dict(from_task='merge',output='delivery/photos.zip',path='photos.zip',purpose='Review exact ZIP',authority='Unaccepted bytes',media_type='application/zip')]
        review['outputs']=[dict(path='photos-review.md',purpose='Independent source review')]
        result['plan']['tasks'].append(review)
        _,plan=planning.validate_result(json.dumps(result),row)
        self.assertTrue(all(t['max_attempts']==1 for t in plan['tasks']))
        merge=next(t for t in plan['tasks'] if t['id']=='merge')
        self.assertEqual({i['artifact'] for i in merge['inputs']},{i['artifact'] for i in inputs})
        self.assertTrue(all(i['media_type']=='application/zip' for i in merge['inputs']))

    def test_selected_base_remains_first_when_an_upstream_zip_is_also_bound(self):
        row=dict(self.queue(action=self.action(step_capabilities=['images.merge'])))
        payload=json.loads(row['context']);inputs=[]
        for ident in ('base','recovery','seed'):
            path=self.rt.root/(ident+'.zip');path.write_bytes(image_sources.subject_base_bundle([subject('one')],'a'*64))
            aid=self.rt.register(path,'Tiny code-owned subject ZIP')
            payload['sources'].append(planning.source_entry(self.rt,aid,path.name,'Subject inventory','No photo evidence'))
            inputs.append(dict(artifact=aid,path=path.name,purpose='Exact ZIP',authority='No photo evidence',media_type='application/zip'))
        row['context']=json.dumps(payload);result=self.response()
        from orchestrator.contracts import assignment
        recovery=operation('recovery','images.merge',inputs[1:],['review'])
        recovery['outputs']=[dict(path='recovered.zip',purpose='Recovered source ZIP',media_type='application/zip')]
        recovery=assignment(recovery)
        review=copy.deepcopy(result['plan']['tasks'][1]);review.update(id='review-recovery',review_of='recovery',dependencies=['recovery'],criteria=copy.deepcopy(recovery['criteria']))
        review['inputs']=[dict(from_task='recovery',output='recovered.zip',path='recovered.zip',purpose='Review exact recovery',authority='Unaccepted',media_type='application/zip')]
        review['outputs']=[dict(path='review-recovery.md',purpose='Independent review')]
        merge=operation('merge','images.merge',[inputs[0],dict(from_task='recovery',output='recovered.zip',path='upstream/recovered.zip',purpose='Exact recovery ZIP',authority='Reviewed candidate',media_type='application/zip')],['recovery','review-recovery'])
        merge['outputs']=[dict(path='photos.zip',purpose='Merged ZIP',media_type='application/zip')]
        merge=assignment(merge)
        final=copy.deepcopy(review);final.update(id='review-merge',review_of='merge',dependencies=['merge'])
        final['inputs']=[dict(from_task='merge',output='photos.zip',path='photos.zip',purpose='Review exact merge',authority='Unaccepted',media_type='application/zip')]
        final['outputs']=[dict(path='review-merge.md',purpose='Independent review')]
        result['plan']['tasks'] += [recovery,review,merge,final]
        _,compiled=planning.validate_result(json.dumps(result),row)
        bound=next(t for t in compiled['tasks'] if t['id']=='merge')['inputs']
        self.assertEqual(len(bound),2)
        self.assertEqual(bound[0]['artifact'],inputs[0]['artifact'])
        self.assertEqual(bound[1]['from_task'],'recovery')

    def test_image_only_grant_preserves_no_new_factual_research_choice(self):
        task=dict(id='photos',browser=dict(image_sources=[dict(path='images.json')]),
                  outputs=[dict(path='images.json',media_type='application/json')])
        payload=dict(text_evidence_policy_version=2,research_choice_version=1,research_mode='none',
                     options=dict(research_mode='none',step_capabilities=['images.fetch']),sources=[])
        text_evidence_planning.bind(dict(tasks=[task]),payload)
        for kind in ('no_capability','extra_report','new_research'):
            p=copy.deepcopy(payload);t=copy.deepcopy(task);tasks=[t]
            if kind=='no_capability':p['options']['step_capabilities']=[]
            elif kind=='extra_report':t['outputs'].append(dict(path='facts.md',media_type='text/markdown'))
            else:tasks.append(dict(id='sources',execution=dict(capability='web.sources')))
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'excludes new web research'):
                text_evidence_planning.bind(dict(tasks=tasks),p)


if __name__=='__main__':unittest.main()
