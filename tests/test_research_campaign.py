"""Controller integration with tiny saved captures; no provider or Safari actions."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from orchestrator import operation_contracts as c, operation_records as records, research_quality as q
from orchestrator.gemini_worker import Files
from orchestrator.storage import transaction
from task_relay import research_campaign as campaign, pipelines as pipe, workflow_builder
from tests import test_production_planning as fixtures
from tests.test_research_quality import plan


def policy(**kw):
    return dict(version=1,entity_type='person',target_count=2,batch_size=2,max_batches=3,
        required_fields=['manual_work'],criteria=[dict(id='fit',question='Does the evidence establish manual catalog work?')],
        discovery_instruction='Discover new operator identities from relevant query pages.',
        assessment_instruction='Inspect discovered profiles and record evidence and unknowns.',**kw)


class Tests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self)
        del self.fail
    tearDown=fixtures.Tests.tearDown

    def create(self,p=None):
        action=dict(kind='plan_pipeline',title='Research fixture',planning_only=False,research_campaign=p or policy(),
            stage_details=[dict(id='deliver',instruction='Deliver all requested results and honest shortfalls.',
                route='production',gate='selection',capabilities=[],outputs={'report':{'format':'markdown','description':'Report'}},uses=[])])
        self.request(action,'Find two operators. Retain holds and rejection reasons.',1)
        row=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(row,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=1').fetchone()[0])
        self.p=row;return row

    request=fixtures.Tests.request

    def step(self,number,phase):
        return self.state.db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id=?',
            (self.p['id'],f'campaign_{number:02d}_{phase}')).fetchone()

    def record(self,name='alpha',verdict='met',phase='discover',domain='x.com'):
        return dict(url=f'https://{domain}/{name}',name=name,identity_support=[dict(observation='o1',quote=name)],
            facts=[dict(field='discovery_reason' if phase=='discover' else 'manual_work',status='observation',
                text='Manual catalog work',supports=[dict(observation='o1',quote='catalog work')])],
            assessment=[] if phase=='discover' else [dict(criterion='fit',verdict=verdict,reason='Manual catalog work is observed.' if verdict!='unknown' else 'Not established.',
                supports=[] if verdict=='unknown' else [dict(observation='o1',quote='catalog work')])])

    def finished(self,number,phase,values,*,accept=True,visited=True):
        """Install exact operation checkpoints/artifacts and a saved audit receipt."""
        s=self.step(number,phase);run='run-'+s['id'];producer_id=run+'-producer';review_id=run+'-review'
        progress=campaign.context(self.state,self.p,s)
        p=plan();producer,review=p['tasks']
        producer.update(objective='Bounded research',instruction='Read relevant pages.',research={'mode':'campaign','parameters':progress['batch_parameters']},max_attempts=1)
        for t in (producer,review):t['limits'].update(seconds=300,tool_calls=24 if t is producer else 16,provider_requests=24 if t is producer else 16,response_tokens=4096)
        q.bind(p,'Research entities.',structured=True)
        p['deliverables']={'candidates':{'task':producer['id'],'output':'evidence.json'},'summary':{'task':producer['id'],'output':'summary.md'}}
        self.state.db.execute('INSERT INTO production_runs VALUES (?,?,?)',(run,c.encoded(p),'active'))
        root=self.state.media_dir.parent/'campaign-fixture'/run;root.mkdir(parents=True)
        producer.update(workspace=str(root/'producer'),assignment_id=producer_id,inputs=[])
        Path(producer['workspace']).mkdir()
        def save(task,ident,tid):
            self.state.db.execute('INSERT INTO production_assignments VALUES (?,?,?,?,?)',('assignment-'+ident,run,tid,1,c.encoded(task)))
            self.state.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',
                (ident,run,tid,'assignment-'+ident,'completed',None,c.encoded(task),'{}',None,None))
            self.state.db.execute('INSERT INTO production_tasks VALUES (?,?,?,?,?,?)',(run,tid,'assignment-'+ident,'completed',1,ident))
        save(producer,producer_id,producer['id'])
        source='catalog work '+ ' '.join(v['name']+' '+v['url'] for v in values)
        producer_files=Files(producer);store=records.Store(producer,self.state.db)
        for i,value in enumerate(values):store.submit(dict(request_key=str(i),revision=i,records=[value]),{'sources':{'o1':source}})
        store.export(producer_files,complete=True)
        summary=b'[Limitation] Only saved captures were inspected.\n'
        producer_files.call('file_write',dict(path='summary.md',text=summary.decode()))
        captures=[dict(observation='o1',text=source,url=values[0]['url'] if values and visited else 'https://x.com/search?q=fixture')]
        if visited:captures.extend(dict(observation='visit'+str(i),text=source,url=v['url']) for i,v in enumerate(values[1:]))
        pack=dict(observations=captures,coverage_note='Only saved captures were inspected.')
        research=q.candidate(producer['research_delivery'],producer_files.read_bytes,pack);research['audit_path']='delivery/research_audit.json'
        pack['research']=research
        workspace=root/'review';workspace.mkdir()
        raw=c.encoded(pack).encode();(workspace/'raw.json').write_bytes(raw)
        raw_id=self.rt.register(workspace/'raw.json','Raw synthetic research evidence',run=run,path='raw.json')
        review.update(workspace=str(workspace),assignment_id=review_id,review_target=producer_id,
            inputs=[dict(path='raw.json',artifact=raw_id,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))],
            computer_review=dict(path='raw.json',sha256=hashlib.sha256(raw).hexdigest(),research=research))
        save(review,review_id,review['id'])
        audit_store=records.Store(review,self.state.db);audit_files=Files(review)
        ctx=records.audit_context(review,audit_files.read_bytes)
        claims=[dict(claim=u['claim'],verdict='supported',reason='Entire synthetic claim is supported.',
            supports=[dict(observation='coverage' if u['kind']=='limitation' else 'o1',quote=pack['coverage_note'] if u['kind']=='limitation' else 'catalog work')]) for u in research['units']]
        for i in range(0,len(claims),3):audit_store.submit(dict(request_key=str(i),revision=i//3,records=claims[i:i+3]),ctx)
        audit_store.export(audit_files,complete=True)
        bindings={}
        for t,ident,paths in ((producer,producer_id,['evidence.json','summary.md']),(review,review_id,['delivery/research_audit.json'])):
            for path in paths:
                aid=self.rt.register(Path(t['workspace'])/path,path,run=run,task=t['id'],attempt=ident,path=path)
                if t is producer:bindings['candidates' if path.endswith('.json') else 'summary']=pipe.artifact_source(self.state,aid)
        if accept:self.rt.event(run,producer['id'],producer_id,'model_review_accepted',{'review_attempt':review_id,'user_approval':False})
        self.state.db.commit()
        return s,run,bindings

    def ingest(self,number,phase,values):
        s,run,bindings=self.finished(number,phase,values)
        with transaction(self.state.db):
            campaign.consume(self.state,self.p,s,run,self.rt,bindings)
            pipe.complete(self.state,self.p,s,list(bindings.values()),c.encoded({'run':run,'deliverables':bindings}))
        return s,run,bindings

    def test_controller_replenishes_then_stops_and_freezes_next_queue(self):
        self.create()
        self.ingest(1,'discover',[self.record('alpha'),self.record('beta')])
        self.ingest(1,'assess',[self.record('alpha','met','assess'),self.record('beta','unmet','assess')])
        first=campaign.ledger(self.state,self.p['id']);self.assertEqual(first['counts']['qualified'],1)
        pipe.tick(self.state);s=self.step(2,'discover')
        self.assertEqual(s['status'],'queued')
        frozen=pipe.request_context(self.state,s['request_id'])['inputs']['research_campaign']
        self.assertEqual(frozen['batch_parameters']['max_records'],1)
        self.assertEqual(frozen['counts']['rejected'],1)
        queued=self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        pipe.tick(self.state);self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],queued)
        self.state.db.execute("UPDATE orchestrator_chats SET status='sent' WHERE id=?",(s['request_id'],))
        self.ingest(2,'discover',[self.record('gamma')]);self.ingest(2,'assess',[self.record('gamma','met','assess')])
        for _ in range(2):pipe.tick(self.state)
        self.assertEqual(self.step(3,'discover')['status'],'skipped');self.assertEqual(self.step(3,'assess')['status'],'skipped')
        self.assertEqual(campaign.ledger(self.state,self.p['id'])['outcome'],'target_reached')

    def test_empty_and_duplicate_discovery_exhaust_honestly(self):
        self.create();self.ingest(1,'discover',[self.record('Alpha')])
        self.ingest(1,'assess',[self.record('Alpha','unknown','assess')])
        self.ingest(2,'discover',[self.record('alpha',domain='twitter.com')])
        with transaction(self.state.db):self.assertTrue(campaign.skip_unused(self.state,self.p,self.step(2,'assess')))
        self.ingest(3,'discover',[])
        with transaction(self.state.db):self.assertTrue(campaign.skip_unused(self.state,self.p,self.step(3,'assess')))
        value=campaign.ledger(self.state,self.p['id'])
        self.assertEqual(value['counts'],dict(discovered=0,qualified=0,held=1,rejected=0))
        self.assertEqual(value['outcome'],'shortfall');self.assertEqual(value['remaining'],2)
        self.assertEqual(len(value['entities'][0]['versions']),3)

    def test_receipt_ingest_is_atomic_idempotent_and_requires_accepted_review(self):
        self.create();s,run,bindings=self.finished(1,'discover',[self.record()],accept=False)
        with self.assertRaisesRegex(ValueError,'accepted'):
            with transaction(self.state.db):campaign.consume(self.state,self.p,s,run,self.rt,bindings)
        self.assertEqual(campaign.ledger(self.state,self.p['id'])['entities'],[])
        self.rt.event(run,'produce',run+'-producer','model_review_accepted',{'review_attempt':run+'-review'})
        with self.assertRaisesRegex(RuntimeError,'crash'):
            with transaction(self.state.db):
                campaign.consume(self.state,self.p,s,run,self.rt,bindings);raise RuntimeError('crash before commit')
        self.assertEqual(campaign.ledger(self.state,self.p['id'])['entities'],[])
        with transaction(self.state.db):campaign.consume(self.state,self.p,s,run,self.rt,bindings)
        with transaction(self.state.db):campaign.consume(self.state,self.p,s,run,self.rt,bindings)
        self.assertEqual(len(campaign.ledger(self.state,self.p['id'])['entities']),1)
        with self.assertRaisesRegex(ValueError,'Conflicting'):campaign.consume(self.state,self.p,s,'foreign',self.rt,bindings)

    def test_changed_capture_and_search_only_qualification_cannot_count(self):
        self.create();self.ingest(1,'discover',[self.record()])
        s,run,bindings=self.finished(1,'assess',[self.record(phase='assess')],visited=False)
        with self.assertRaisesRegex(ValueError,'captured profile'):campaign.consume(self.state,self.p,s,run,self.rt,bindings)
        review=self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(run+'-review',)).fetchone()
        Path(json.loads(review[0])['workspace'],'raw.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):campaign.consume(self.state,self.p,s,run,self.rt,bindings)
        self.assertEqual(campaign.ledger(self.state,self.p['id'])['counts']['qualified'],0)

    def test_pause_cancel_and_uncertain_never_replay_a_slot(self):
        self.create();self.state.db.execute("UPDATE relay_pipelines SET status='paused'")
        pipe.tick(self.state);self.assertEqual(self.step(1,'discover')['status'],'pending')
        self.state.db.execute("UPDATE relay_pipelines SET status='active'");pipe.tick(self.state)
        s=self.step(1,'discover');self.state.db.execute("UPDATE orchestrator_chats SET status='uncertain' WHERE id=?",(s['request_id'],))
        pipe.tick(self.state);self.assertEqual(self.step(1,'discover')['status'],'blocked')
        count=self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0]
        pipe.tick(self.state);self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],count)
        self.state.db.execute("UPDATE relay_pipelines SET status='cancelled'")
        pipe.tick(self.state);self.assertEqual(self.step(2,'discover')['status'],'pending')

    def test_budget_and_contract_cannot_be_invented_by_planner(self):
        self.create();action=json.loads(self.p['spec']);snap={'capabilities':{'graph_operations':[]}}
        bad=copy.deepcopy(action);bad['research_campaign']['target_count']=100
        with self.assertRaisesRegex(ValueError,'capacity'):pipe.validate(bad,snap)
        bad=copy.deepcopy(action);bad['stages'][0]['instruction']='Different scope'
        with self.assertRaisesRegex(ValueError,'compiled'):pipe.validate(bad,snap)
        producer_plan=plan();producer,review=producer_plan['tasks']
        producer['limits'].update(seconds=300,provider_requests=24,tool_calls=24,response_tokens=4096)
        review['limits'].update(seconds=600,provider_requests=16,tool_calls=16,response_tokens=4096)
        producer['max_attempts']=review['max_attempts']=1
        campaign.bind_plan(producer_plan,action['stages'][0],campaign.context(self.state,self.p,self.step(1,'discover')))
        review['max_attempts']=2
        with self.assertRaisesRegex(ValueError,'budget'):campaign.bind_plan(producer_plan,action['stages'][0],campaign.context(self.state,self.p,self.step(1,'discover')))

    def test_entity_policy_reuse_and_claim_coverage(self):
        for entity in ('person','supplier'):
            p=policy();p['entity_type']=entity;campaign.validate_policy(p)
            params=campaign.parameters(p,'assess');record=self.record(phase='assess')
            c.batch_record(record,params,{'sources':{'o1':'alpha https://x.com/alpha catalog work'}})
            record['assessment'][0]['criterion']='invented'
            with self.assertRaisesRegex(ValueError,'criterion'):c.batch_record(record,params)
        self.create();s,run,b=self.finished(1,'discover',[])
        campaign.consume(self.state,self.p,s,run,self.rt,b)
        self.assertEqual(json.loads(Path(b['candidates']['path']).read_bytes())['records'],[])

    def test_twenty_entities_through_production_completion_and_final_context(self):
        p=policy();p.update(target_count=20,max_batches=12)
        self.create(p)
        for number in range(1,11):
            for phase in ('discover','assess'):
                values=[self.record('person'+str(number*2+i),phase=phase) for i in range(2)]
                s,run,bindings=self.finished(number,phase,values)
                with transaction(self.state.db):pipe.advance_production(self.state,self.p,s,run)
                self.assertEqual(self.step(number,phase)['status'],'completed')
        for _ in range(5):pipe.tick(self.state)
        final=self.state.db.execute("SELECT * FROM relay_pipeline_steps WHERE pipeline=? AND id='deliver'",(self.p['id'],)).fetchone()
        self.assertEqual(final['status'],'queued')
        value=pipe.request_context(self.state,final['request_id'])['inputs']['research_campaign']
        self.assertEqual(value['counts']['qualified'],20);self.assertEqual(len(value['entities']),20)
        self.assertEqual(value['outcome'],'target_reached');self.assertFalse(value['user_accepted'])
        self.assertEqual(len(value['receipts']),20)
        self.assertEqual(self.step(12,'assess')['status'],'skipped')
        from task_relay import workflow_files
        exported=workflow_files.job_state_for_pipeline(self.state,self.p['id'])
        self.assertEqual(exported['research_campaign']['counts']['qualified'],20)
        self.assertEqual(len([s for s in pipe.request_context(self.state,final['request_id'])['inputs']['sources'] if s['name']=='raw.json']),20)

    def test_real_stage_planner_freezes_provider_neutral_contract_and_budget(self):
        from tests import test_safari_planning_routing as safari
        from task_relay import orchestrator_chat as chat, production_planning as planning,computer_target
        from orchestrator import executors,worker_capabilities as workers
        self.create();pipe.tick(self.state);s=self.step(1,'discover')
        action=fixtures.Tests.action(self,executor='gemini-computer',step_capabilities=[],
            deliverables=json.loads(self.p['spec'])['stages'][0]['deliverables'])
        with patch.object(executors,'catalog',return_value=copy.deepcopy(safari.CATALOG)),patch.object(executors,'available'),patch.object(workers,'capture',side_effect=lambda state,backend,locked=False:[workers.entry(backend)] if locked else copy.deepcopy(safari.CATALOG)),patch.object(computer_target,'runtime',return_value=safari.runtime()):
            chat.Worker(self.state,lambda *_:json.dumps({'answer':'Plan the saved campaign slot.','action':action})).tick()
        row=self.state.db.execute('SELECT * FROM production_plans WHERE request_id=?',(s['request_id'],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row['options'])['max_attempts'],1)
        proposal=fixtures.Tests.response(self);producer,review=proposal['plan']['tasks']
        for t in (producer,review):
            t.pop('tools');t.pop('user_gate',None);t['worker']={'requires':['files.text']}
            t['max_attempts']=1;t['limits']=dict(seconds=300,tool_calls=24 if t is producer else 16,provider_requests=24 if t is producer else 16,response_tokens=8192,output_bytes=200000)
        producer['worker']['requires'].append('computer.use')
        producer['computer']=dict(selection=safari.runtime()['selection'],url='https://example.com/profile',allowed_urls=['https://example.com/profile'],max_seconds=300)
        producer['outputs']=[dict(path='delivery/candidates.json',purpose='Candidates'),dict(path='delivery/summary.md',purpose='Summary')]
        review['inputs']=[dict(from_task=producer['id'],output=o['path'],path='candidate/'+o['path'],purpose=o['purpose'],authority='Unaccepted evidence') for o in producer['outputs']]
        proposal['deliverable_map']={k:dict(task=producer['id'],output=o['path']) for k,o in zip(('candidates','summary'),producer['outputs'])}
        _,result=planning.validate_result(json.dumps(proposal),row)
        self.assertEqual(result['tasks'][0]['operation_contract']['id'],'research.batch')
        self.assertEqual(result['tasks'][0]['operation_contract']['parameters']['criteria'],[])
        self.assertEqual(result['tasks'][1]['operation_contract']['id'],'research.audit')
        self.assertTrue(all(t['max_attempts']==1 for t in result['tasks']))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        for url in ('https://x.com','https://x.com/home','https://x.com/explore','https://x.com/search',
                    'https://twitter.com/search?q=%20','https://x.com/search?q='):
            producer['computer'].update(url=url,allowed_urls=[url])
            with self.assertRaisesRegex(ValueError,'landing page or empty search'):
                planning.validate_result(json.dumps(proposal),row)
        for url in ('https://x.com/search?q=Amazon%20catalog&f=live','https://x.com/fixture'):
            producer['computer'].update(url=url,allowed_urls=[url])
            _,valid=planning.validate_result(json.dumps(proposal),row)
            self.assertEqual(valid['tasks'][0]['computer']['spec']['url'],url)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_attempts').fetchone()[0],0)


if __name__=='__main__':unittest.main()
