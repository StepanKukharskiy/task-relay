"""Outcome routing and source handoff with controlled model responses; no media."""
import copy
import json
import unittest
from unittest.mock import patch
from task_relay import capabilities,orchestrator_context,orchestrator_chat as chat,production_planning as planning
from orchestrator import contracts,hyperframes_project
from tests import test_production_planning as pf,test_production_stages as sf
from tests.test_hyperframes import graph


class DiscoveryTests(unittest.TestCase):
    def test_local_video_requires_both_operations_and_retains_actual_blocker(self):
        ops=[dict(id=cap,available=True) for cap in ('hyperframes.preview','hyperframes.render')]
        self.assertTrue(capabilities.local_video(ops)['available'])
        ops[1].update(available=False,blocker='Runtime identity changed')
        result=capabilities.local_video(ops)
        self.assertFalse(result['available']);self.assertIn('Runtime identity changed',result['blocker'])
        self.assertNotIn('media.compose',result['step_capabilities'])
        self.assertFalse(capabilities.local_video([])['available'])

    def test_compaction_keeps_reel_discovery_and_exact_user_request(self):
        ops=[dict(id=cap,available=True) for cap in ('hyperframes.preview','hyperframes.render')]
        info=capabilities.local_video(ops)
        payload=dict(user_message='make me a reel',snapshot=dict(capabilities=dict(graph_operations=ops,local_video=info),
            production_runs=[{'name':'completed-content','status':'completed','details':'x'*200000}]))
        overview=orchestrator_context.overview(payload)
        self.assertEqual(overview['user_message'],'make me a reel')
        self.assertEqual(overview['current_execution_availability']['local_video'],info)
        self.assertEqual(payload['snapshot']['capabilities']['local_video'],info)


class RequestTests(unittest.TestCase):
    tearDown=pf.Tests.tearDown;request=pf.Tests.request;action=pf.Tests.action;queue=pf.Tests.queue
    row=pf.Tests.row;response=pf.Tests.response;ready=pf.Tests.ready;click=pf.Tests.click;start=pf.Tests.start
    finish=sf.Tests.finish;selected=sf.Tests.selected

    def setUp(self):
        pf.Tests.setUp(self)
        del self.fail
        p=patch.object(hyperframes_project,'available',return_value={'adapter':'controlled'});p.start();self.addCleanup(p.stop)

    def test_short_followup_carries_selected_sources_and_keeps_mp4_pending(self):
        card,_=self.selected()
        prior=tuple(self.state.db.execute("SELECT * FROM production_runs WHERE id='production-1'").fetchone())
        old_attempts=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        calls=len(self.factory.calls);captured=[]
        # Controlled semantic action: the real chat boundary supplies current
        # discovery and selected stage identity. No paid model inference is claimed.
        def generate(job,payload):
            captured.append(payload)
            local=payload['snapshot']['capabilities']['local_video']
            self.assertTrue(local['available'])
            stage=next(r for r in payload['snapshot']['production_runs'] if r['name']=='production-1')
            self.assertEqual(stage['status'],'completed')
            action=self.action(previous_run=stage['name'],step_capabilities=local['step_capabilities'],deliverables={'reel':'Rendered MP4 reel'})
            return json.dumps(dict(answer='Preparing a reel plan from your selected content.',action=action))
        self.bridge.process({'update_id':2,'message':{'text':'make me a reel','chat':{'id':7,'type':'private'},'from':{'id':7}}})
        worker=chat.Worker(self.state,generate);worker.tick();worker.tick()
        self.assertEqual(len(captured),1)
        row=dict(self.row(2));self.assertEqual(row['request'],'make me a reel')
        payload=json.loads(row['context']);self.assertIn(card['artifact'],payload['required_artifacts'])
        selected=next(s for s in payload['sources'] if s['artifact']==card['artifact'])
        self.assertEqual(selected['sha256'],self.rt.artifact(card['artifact'])['sha256'])
        result=self.response();result['plan']['tasks']=[contracts.assignment(t) for t in graph()['tasks']]
        result['deferred_operations']={'hyperframes.render':'Encode the selected preview project after its review.'}
        result['deliverable_map']={'reel':{'deferred_operation':'hyperframes.render'}}
        planning.Worker(self.state,lambda *_:(json.dumps(result),{})).tick()
        row=self.row(2);self.assertEqual(row['status'],'ready',row['error'])
        planned=json.loads(row['plan']);self.assertEqual(planned['deliverables']['reel']['deferred_operation'],'hyperframes.render')
        self.assertTrue(any(i.get('artifact')==card['artifact'] for i in planned['tasks'][0]['inputs']))
        self.assertEqual(len(self.factory.calls),calls)
        self.assertEqual(tuple(self.state.db.execute("SELECT * FROM production_runs WHERE id='production-1'").fetchone()),prior)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')],old_attempts)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        # A planner cannot quietly stop at a storyboard or omit the requested MP4.
        bad=copy.deepcopy(result);bad.pop('deliverable_map')
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(bad),dict(row))

    def test_capability_question_with_no_action_starts_no_plan(self):
        self.bridge.process({'update_id':1,'message':{'text':'Can you make reels?','chat':{'id':7,'type':'private'},'from':{'id':7}}})
        chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Yes, from your content and assets.',action=None))).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])


if __name__=='__main__':unittest.main()
