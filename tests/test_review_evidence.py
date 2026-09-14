import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import contracts as c, execution
from orchestrator.runtime import Runtime, dependencies_ready
from orchestrator.storage import transaction
from tests.test_orchestrator import FakeFactory, pair, task
from tests.test_blender_operations import operation


def graph(cap='blender.inspect'):
    value = pair(gate='Choose model', max_attempts=1)
    producer, reviewer = value['tasks']
    media = 'application/x-blender' if cap == 'blender.inspect' else 'application/vnd.rhino'
    producer['outputs'][0]['media_type'] = media
    reviewer['inputs'][0]['media_type'] = media
    helper = operation(cap, [dict(from_task='produce', output='output.txt', path='source.model',
        purpose='Inspect draft', authority='Unaccepted candidate', media_type=media)])
    helper.update(id='inventory', dependencies=['produce'])
    reviewer['dependencies'].append('inventory')
    reviewer['inputs'].append(dict(from_task='inventory', output='delivery/inspection.json', path='inventory.json',
        purpose='Independent evidence', authority='Inspection report', media_type='application/json'))
    value['tasks'].insert(1, helper)
    value['tasks'].append(task('later', dependencies=['produce']))
    return value


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.factory = FakeFactory()
        self.rt = Runtime(Path(self.temp.name)/'runtime', self.factory)
        self.available = patch('orchestrator.execution.available'); self.available.start()

    def tearDown(self):
        self.available.stop(); self.rt.close(); self.temp.cleanup()

    def finish(self, tid, **kwargs):
        self.factory.finish(self.rt.task('demo', tid)['latest'], **kwargs)
        return self.rt.tick('demo')

    def test_inspection_then_review_preserves_candidate_and_downstream_gate(self):
        self.rt.create(graph()); self.rt.tick('demo')
        first = self.rt.task('demo', 'produce')['latest']
        self.finish('produce')
        self.assertEqual(self.rt.task('demo','produce')['status'], 'awaiting_review')
        self.assertEqual(self.rt.task('demo','inventory')['attempts'], 1)
        self.assertEqual(self.rt.task('demo','review')['attempts'], 0)
        self.assertEqual(self.rt.task('demo','later')['attempts'], 0)
        inspection = self.rt.task('demo','inventory')['latest']
        frozen = self.factory.sessions[inspection]['frozen']
        self.assertEqual(frozen['inputs'][0]['artifact'], self.rt.output('demo','produce','output.txt')['id'])
        # Restart drains the inspection; it does not repeat modeling or inspection.
        root=self.rt.root; self.rt.close(); self.rt=Runtime(root,self.factory)
        self.rt.tick('demo'); self.finish('inventory')
        self.assertEqual(self.rt.task('demo','review')['attempts'],1)
        self.finish('review',decision='accept')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.assertEqual(self.rt.task('demo','later')['attempts'],0)
        self.assertEqual(self.rt.task('demo','produce')['latest'],first)
        self.assertEqual(self.factory.calls.count(first),1)
        self.assertEqual(self.factory.calls.count(inspection),1)

    def test_failed_inspection_blocks_review_without_replay(self):
        self.rt.create(graph());self.rt.tick('demo');self.finish('produce')
        self.finish('inventory',decision='blocked');self.rt.tick('demo')
        self.assertEqual(self.rt.status('demo')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertEqual(len(self.factory.calls),2)

    def test_rejected_review_cannot_reuse_inspection_for_new_candidate(self):
        self.rt.create(graph());self.rt.tick('demo');self.finish('produce');self.finish('inventory')
        self.finish('review',decision='revise')
        self.assertEqual(self.rt.status('demo')['status'],'blocked')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1)
        self.assertEqual(self.rt.task('demo','later')['attempts'],0)

    def test_rhino_and_blender_inspection_readiness_and_nonready_states(self):
        for cap in ('rhino.inspect','blender.inspect'):
            specs=c.plan(graph(cap))['tasks'];helper=specs[1]
            for status in ('awaiting_review','blocked','uncertain','awaiting_user','running'):
                states=[{'id':a['id'],'status':status if a['id']=='produce' else 'queued'} for a in specs]
                self.assertEqual(dependencies_ready(helper,states,specs),status=='awaiting_review')
                self.assertFalse(dependencies_ready(specs[-1],states,specs))
            self.assertFalse(dependencies_ready(helper,states))

    def test_semantic_cycles_rejected_before_dispatch(self):
        for change in ('ordinary_worker','unused_inspection','gated_inspection','other_review'):
            value=graph();helper=value['tasks'][1];review=value['tasks'][2]
            if change=='ordinary_worker':
                helper.pop('execution');helper['tools']=['files','shell']
            elif change=='unused_inspection':
                review['inputs']=[i for i in review['inputs'] if i.get('from_task')!='inventory']
            elif change=='gated_inspection':helper['user_gate']='Choose inspection'
            else:helper['dependencies'].append('review')
            with self.assertRaisesRegex(ValueError,'cycle'):
                c.plan(value)
        self.assertEqual(self.factory.calls,[])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        from tests.test_production_control import Tests
        Tests.setUp(self)
        self.available=patch('orchestrator.execution.available');self.available.start()

    def tearDown(self):
        from tests.test_production_control import Tests
        self.available.stop();Tests.tearDown(self)

    def stalled(self):
        import production_control as pc
        value=graph();value['id']='stalled';self.rt.create(value)
        self.rt.tick('stalled')
        self.factory.finish(self.rt.task('stalled','produce')['latest'])
        self.rt.tick('stalled',dispatch=False)
        original=self.state.db.execute('SELECT plan FROM production_runs WHERE id=?',('stalled',)).fetchone()[0]
        with transaction(self.state.db):
            self.state.db.execute('''INSERT INTO production_plans(id,request_id,channel,request,options,context,
                context_hash,provider,model,status,plan,token,expires,run,created)
                VALUES ('evidence-plan',987,'telegram','Approved work','{}','{}','fixture','gemini','fixture',
                'started',?,'fixture-token',9999999999,'stalled',1)''',(original,))
            tasks=self.rt.status('stalled')['tasks']
            self.state.put('production-status:stalled',{'status':'blocked','tasks':sorted([[t['id'],t['status'],t['attempts']] for t in tasks])})
        return pc

    def test_explicit_recovery_keeps_assignments_attempts_and_dispatches_after_commit(self):
        pc=self.stalled()
        before=[dict(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='stalled'")]
        with transaction(self.state.db):
            pc.resume_review_evidence(self.state,'stalled','The inspection is stuck; continue.')
            self.assertEqual(len(self.factory.calls),1)
        self.assertEqual(before,[dict(r) for r in self.state.db.execute("SELECT * FROM production_attempts WHERE run='stalled'")])
        pc.Worker(self.state,lambda _:self.rt).tick()
        self.assertEqual(self.rt.task('stalled','inventory')['attempts'],1)
        self.assertEqual(self.rt.task('stalled','produce')['attempts'],1)
        with transaction(self.state.db),self.assertRaises(ValueError):pc.resume_review_evidence(self.state,'stalled','Again')

    def test_pause_or_epoch_change_prevents_recovery(self):
        pc=self.stalled()
        with transaction(self.state.db):
            self.state.put('production-control-epoch:stalled',1)
            with self.assertRaises(ValueError):pc.resume_review_evidence(self.state,'stalled','Continue')
        self.assertEqual(len(self.factory.calls),1)

    def test_changed_candidate_prevents_recovery(self):
        pc=self.stalled()
        artifact=self.rt.output('stalled','produce','output.txt');p=Path(artifact['blob']);p.chmod(0o600);p.write_text('Changed')
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'artifact changed'):
            pc.resume_review_evidence(self.state,'stalled','Continue')
        self.assertEqual(len(self.factory.calls),1)

    def test_changed_assignment_prevents_recovery(self):
        pc=self.stalled()
        with transaction(self.state.db):
            helper=self.rt.task('stalled','inventory');spec=self.rt.spec(helper)
            spec['instruction']='Changed inspection request'
            self.state.db.execute('UPDATE production_assignments SET spec=? WHERE id=?',(json.dumps(spec),helper['assignment']))
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'assignments changed'):
            pc.resume_review_evidence(self.state,'stalled','Continue')
        self.assertEqual(len(self.factory.calls),1)
