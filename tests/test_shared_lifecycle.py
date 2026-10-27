"""Composed correction-to-delivery qualification with unchanged live ceilings."""
import json
import unittest
from pathlib import Path
from orchestrator import contracts as c, step_runner
from tests.lifecycle_fixture import Lifecycle
from tests.test_owner_intents import worker


class CorrectionDelivery(Lifecycle,unittest.TestCase):
    def test_repeated_correction_composition_final_review_and_completion(self):
        final=self.corrected()
        self.delegate('compose',[dict(id='compose',objective='Compose exact corrected text',operation='text.bundle',inputs=[{'artifact':final['id']}]),
            dict(id='final_review',objective='Review the complete exact composed delivery',review_of='compose')])
        aid=self.rt.task('job','compose')['latest'];s=self.factory.sessions[aid]
        Path(s['session']['control']).mkdir(parents=True,exist_ok=True)
        result=step_runner.execute(s['frozen'],Path(s['session']['control']))
        self.assertEqual(result['outcome'],'completed')
        s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        self.restart();self.rt.tick('job')
        output=self.rt.output('job','compose',s['frozen']['outputs'][0]['path'])
        self.assertIn('gap: 2',Path(output['blob']).read_text())
        self.work('final_review','Exact composed price, source and two-option shortfall checked.',decision='accept')
        self.invoke([('job_complete',dict(deliverables_json=c.encoded({'report':output['id']}),summary='Reviewed exact composed delivery with explicit target gap'))])
        self.rt.tick('job');self.assertEqual(self.rt.status('job')['status'],'completed')
        self.invariants()

    def test_repeated_correction_uncertain_peer_and_drain_export_exact_partial(self):
        final=self.corrected()
        self.delegate('peers',[worker('unknown'),worker('slow')])
        aid=self.rt.task('job','unknown')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='Dispatched effect has no correlated receipt')
        self.rt.tick('job');status=self.rt.status('job');calls=list(self.factory.calls)
        self.assertIn('settlement',status);self.assertNotIn('delivery',status)
        self.restart();self.work('slow','Available unreviewed peer text.')
        delivery=self.export_partial(final)
        self.assertEqual(calls,self.factory.calls)
        labels={a['task']:a['review_status'] for a in delivery['candidates']}
        self.assertEqual(labels['v1'],'requires_attention');self.assertEqual(labels['v2'],'requires_attention')
        self.assertEqual(labels['slow'],'unreviewed');self.assertNotIn('unknown',labels)
        self.assertTrue(any(a['attempt']==aid and a['state']=='uncertain' for a in delivery['attention']))

    def test_repeated_correction_rejected_proposals_export_without_acceptance(self):
        final=self.corrected()
        bad=[('job_delegate',dict(request_id='bad-'+str(n),tasks=[dict(id='invalid',objective='Bad schema',content={'unsupported':True})])) for n in range(3)]
        # Real tool-loop proposal recovery exhausts its original allowance.
        with self.assertRaisesRegex(ValueError,'proposal correction|no automatic wake') as failure:
            self.invoke(bad)
        aid=self.rt.task('job','owner')['latest'];control=Path(self.factory.sessions[aid]['session']['control'])
        # The controlled process observer reports the actual raised loop error.
        (control/'fixture-process-error.json').write_text(json.dumps(dict(error=str(failure.exception))))
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason=str(failure.exception),external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');self.export_partial(final,'blocked')

    def test_uncertain_exact_review_keeps_completed_file_with_attention(self):
        final=self.corrected()
        self.delegate('snapshot',[dict(id='snapshot',objective='Reassess the exact final candidate',review_of='v3')])
        self.work('snapshot','Source observation remains unresolved.',decision='accept',uncertain=True)
        status=self.rt.status('job');self.assertEqual(status['status'],'uncertain')
        candidate=next(a for a in status['delivery']['candidates'] if a['artifact']==final['id'])
        self.assertEqual(candidate['review_status'],'requires_attention')
        self.assertTrue(any(j['state']=='uncertain' for j in candidate['reviews']))
        self.invariants()


class RegisteredCorrections(unittest.TestCase):
    """Two actual registered baseline amendments, re-review and terminal gaps."""
    from tests.test_content_baseline_construction import Baselines as fixture
    from tests.lifecycle_fixture import LIMITS
    source=fixture.source;session=fixture.session;invoke=fixture.invoke
    run_worker=fixture.run_worker;args=fixture.args;tearDown=fixture.tearDown

    def create(self,inputs):
        from tests.lifecycle_fixture import grant
        limits=grant()
        # Preserve the registered fixture's content authority, replacing only its
        # smaller test ceilings with the unchanged qualification ceilings.
        for key,value in limits.items():
            if key not in ('workers','operations','deliverables'):self.grant[key]=value
        self.grant['deliverables']={'catalog':'application/json','missing':'application/pdf'}
        self.grant['review_snapshot_version']=1
        return self.fixture.create(self,inputs=inputs)

    def setUp(self):self.fixture.setUp(self)

    def test_registered_repeated_amendment_review_restart_and_partial_gaps(self):
        import copy
        from orchestrator import operation_contracts as oc,sourcing_contract,job_owner
        from orchestrator.runtime import Runtime
        selected=self.new['artifact'];source=self.pack['artifact'];previous=copy.deepcopy(self.base)
        for n in (1,2):
            ident='repair'+str(n);args=self.args();args['request_id']=ident
            task=args['tasks'][0];task['id']=ident
            task['content']['baseline']={'artifact':selected}
            task['content']['sources']['source_pack_path']={'artifact':source}
            task['inputs'].extend([{'artifact':selected},{'artifact':source}])
            # Duplicate reference identities are normalized by the compiler.
            task['inputs']=list({v['artifact']:v for v in task['inputs']}.values())
            self.invoke([('job_catalog',dict(operations=[],records=True)),('job_delegate',args)])
            self.rt.tick('job');spec=self.rt.spec(self.rt.task('job',ident));params=spec['operation_contract']['parameters']
            self.assertNotIn('repair1',spec['dependencies'])
            self.assertEqual(next(i['artifact'] for i in spec['inputs'] if i['path']==params['base_catalog_path']),selected)
            self.rt.close();self.rt=Runtime(self.root,self.factory)
            record=dict(item='item-a',options=[],gap='Correction '+str(n)+': no supported option; target 3 unmet.')
            self.run_worker(ident,lambda f:[('operation_amend',dict(request_key='fix',revision=0,expected_record_sha256=oc.digest(previous['records'][0]),record=record))])
            artifact=self.rt.output('job',ident,'outputs/result.json')
            data=json.loads(Path(artifact['blob']).read_text());self.assertEqual(data['items'][0]['options'],[])
            self.assertEqual(data['parameters']['options_per_item'],3);self.assertEqual(data['parameters']['count_policy'],'target')
            reviewer=next(t['id'] for t in self.rt.status('job')['tasks'] if t['id'].startswith(ident+'_review'))
            f=self.factory.sessions[self.rt.task('job',reviewer)['latest']]['frozen']
            ctx=sourcing_contract.context(f,lambda p:(Path(f['workspace'])/p).read_bytes())
            self.assertEqual(ctx['catalog_sha256'],artifact['sha256'])
            rows=[dict(item=k,item_sha256=oc.digest(v),verdict='supported',reason='Explicit shortfall and retained evidence checked') for k,v in ctx['items'].items()]
            self.run_worker(reviewer,lambda f:[('file_read',dict(path=f['operation_contract']['parameters']['catalog_path'],offset=0,limit=24000))]+
                [('operation_submit',dict(request_key='r'+str(i),revision=i,records=[r])) for i,r in enumerate(rows)],decision='accept')
            self.assertEqual(self.rt.task('job',ident)['status'],'completed')
            previous=data;selected=artifact['id'];source=self.rt.output('job',ident,params['source_pack_output'])['id']
        from orchestrator.runtime_outcomes import Hold
        with self.assertRaisesRegex(Hold,'PDF is unavailable') as stop:
            self.invoke([('job_stop',dict(reason='PDF is unavailable in this fixture; preserve corrected catalog and explicit target gaps.'))])
        aid=self.rt.task('job','owner')['latest']
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason=str(stop.exception),external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');d=self.rt.status('job')['delivery']
        self.assertEqual(d['missing_formats'],{'missing':'application/pdf'})
        self.assertEqual(next(a['review_status'] for a in d['candidates'] if a['artifact']==selected),'reviewed')
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['task_limits'],self.LIMITS)
        self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))
        self.assertFalse(d['complete']);self.assertFalse(d['user_acceptance'])


if __name__=='__main__':unittest.main()
