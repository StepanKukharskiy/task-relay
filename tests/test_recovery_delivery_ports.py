"""Exact port compilation and reviewed-version carry-forward through delivery."""
import copy,json,unittest
from pathlib import Path
from task_relay import completion_recovery as recovery,pipelines
from orchestrator import contracts
from orchestrator.handoff_contracts import bind_stage,ContractError
from orchestrator.storage import transaction
from tests import test_completion_recovery as fixture
from tests.test_orchestrator import pair

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    stage=fixture.Tests.stage
    create=fixture.Tests.create
    step=fixture.Tests.step

    def parent(self):
        plan=pair(max_attempts=1);plan['id']='parent';plan['deliverables']={'carried':{'description':'Saved evidence','task':'produce','output':'output.txt'}}
        self.rt.create(plan);self.rt.tick('parent');self.factory.finish(self.rt.task('parent','produce')['latest']);self.rt.tick('parent');self.factory.finish(self.rt.task('parent','review')['latest'],'accept');self.rt.tick('parent')
        self.assertEqual(self.rt.status('parent')['status'],'completed');origin=self.rt.output('parent','produce','output.txt');aid=self.rt.register(Path(origin['blob']),'Frozen alias')
        payload=dict(planner_budget_binding_version=2,sources=[dict(artifact=aid,path='evidence.txt',sha256=origin['sha256'],bytes=origin['bytes'])],recorded_external_sources=[dict(artifact=aid,origin_artifact=origin['id'],attempt=origin['attempt'])],completion_recovery=dict(parent='parent',original_plan=plan,completed_read_operations=[dict(task='produce',attempt=origin['attempt'])]))
        return plan,origin,aid,payload

    def test_native_completion_carries_exact_reviewed_input_to_next_stage(self):
        old,origin,aid,payload=self.parent()
        stage=self.stage(route='production');stage['deliverables']={'outline':'New result','carried':'Saved evidence'};stage['handoff']={'inputs':[],'outputs':{'outline':{'media_type':'text/plain'},'carried':{'media_type':'text/plain'}}}
        p=self.create([stage,self.stage('finish')]);s=self.step(p,'outline')
        child=pair(max_attempts=1);child['id']='child';child['tasks'][0]['outputs'][0]['purpose']='New result';child['reused_operations']={'web.sources':[aid]}
        coverage=recovery.bind_deliveries(child,payload,{'deliverables':stage['deliverables']},{})
        self.assertEqual(coverage['carried'],{'artifact':aid});child['deliverables']={ident:{'description':stage['deliverables'][ident],**value} for ident,value in coverage.items()}
        bind_stage(stage,child,sources=payload['sources']);recovery.validate_carried_deliveries(self.state,child,{'run':'parent','plan':old})
        self.rt.create(child);self.rt.tick('child');self.factory.finish(self.rt.task('child','produce')['latest']);self.rt.tick('child');self.factory.finish(self.rt.task('child','review')['latest'],'accept');self.rt.tick('child')
        with transaction(self.state.db):
            self.state.db.execute('insert into completion_recoveries values(?,?,?,?,?,?)',(p['id'],'outline','parent',1,998,json.dumps({'run':'parent','plan':old})))
            self.state.db.execute("update relay_pipeline_steps set status='running',target_kind='production_run',target='child' where pipeline=? and id='outline'",(p['id'],))
            pipelines.advance_production(self.state,p,self.step(p,'outline'),'child')
        delivered=self.step(p,'outline');self.assertEqual(delivered['status'],'completed')
        binding=json.loads(delivered['result'])['deliverables']['carried'];self.assertEqual(binding['artifact'],aid)
        self.assertEqual(Path(binding['path']).read_bytes(),Path(origin['blob']).read_bytes())
        self.assertEqual(self.rt.task('parent','produce')['attempts'],1)

    def test_ambiguous_ports_unreviewed_or_changed_versions_cannot_carry(self):
        old,origin,aid,payload=self.parent();new=pair();new['reused_operations']={'web.sources':[aid]};opts={'deliverables':{'carried':'Saved evidence'}}
        coverage=recovery.bind_deliveries(new,payload,opts,{});self.assertEqual(coverage,{'carried':{'artifact':aid}})
        with transaction(self.state.db):self.state.db.execute("update production_tasks set status='blocked' where run='parent' and id='review'")
        with self.assertRaisesRegex(ValueError,'independently reviewed'):recovery.validate_carried_deliveries(self.state,new,{'run':'parent','plan':old})
        with transaction(self.state.db):self.state.db.execute("update production_tasks set status='completed' where run='parent' and id='review'")
        new['carried_deliverables']['carried']['sha256']='bad'
        with self.assertRaisesRegex(ValueError,'version changed'):recovery.validate_carried_deliveries(self.state,new,{'run':'parent','plan':old})
        new['carried_deliverables']['carried']['sha256']=origin['sha256']
        blob=Path(self.rt.artifact(aid)['blob']);original_bytes=blob.read_bytes();blob.chmod(0o600);blob.write_bytes(b'x'*len(original_bytes))
        with self.assertRaisesRegex(ValueError,'stored bytes changed'):recovery.validate_carried_deliveries(self.state,new,{'run':'parent','plan':old})
        ambiguous=pair();ambiguous['tasks'][0]['outputs']=[dict(path='a.txt',purpose='Saved evidence'),dict(path='b.txt',purpose='Saved evidence')]
        self.assertEqual(recovery.bind_deliveries(ambiguous,payload,opts,{}),{})
        original={'carried':{'task':'unknown','output':'unknown'}};self.assertEqual(recovery.bind_deliveries(new,payload,opts,original),original)
