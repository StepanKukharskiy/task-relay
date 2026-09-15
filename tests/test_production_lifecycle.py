import unittest
from unittest.mock import patch

from task_relay.bridge import State,Bridge
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
from task_relay import production_control as pc
from task_relay import production_lifecycle as lifecycle
from task_relay import production_status as status
from tests import test_production_status as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    message=fixtures.Tests.message
    click=fixtures.Tests.click
    worker=fixtures.Tests.worker
    stage_card=fixtures.Tests.stage_card

    def control(self,verb,key):
        with self.state.db:pc.notice(self.state,'demo',key,'Current stage controls')
        self.bridge.flush(False)
        card=self.state.db.execute('SELECT * FROM production_control_cards WHERE event_id=? AND verb=?',('production:demo:'+key,verb)).fetchone()
        self.assertIsNotNone(card)
        mid=self.state.db.execute('SELECT message_id FROM production_control_messages WHERE token=?',(card['token'],)).fetchone()[0]
        return card,mid

    def press(self,card,mid,user=7):
        self.bridge.process({'update_id':990,'callback_query':{'id':card['token'],'data':'prodcontrol:'+card['token'],
            'from':{'id':user},'message':{'chat':{'id':7,'type':'private'},'message_id':mid}}})

    def reopen(self):
        path=self.state.media_dir.parent/'state.sqlite';self.rt.close();self.state.db.close()
        self.state=State(path);self.bridge=Bridge(self.state,self.telegram,{})
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)

    def test_pause_collects_running_work_after_restart_and_resume_dispatches_once(self):
        self.click(self.stage_card()['token']);self.worker().tick()
        producer=self.rt.task('demo','produce')['latest']
        card,mid=self.control('pause','pause');self.press(card,mid);self.press(card,mid)
        self.assertEqual(self.rt.status('demo')['status'],'paused')
        self.reopen();self.factory.finish(producer);self.worker().tick()
        self.assertEqual(self.factory.calls,[producer])
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_review')
        resume,rid=self.control('resume','resume');self.press(resume,rid);self.worker().tick()
        self.press(resume,rid);self.press(card,mid);self.worker().tick()
        self.assertEqual(len(self.factory.calls),2)
        self.assertEqual(self.rt.status('demo')['status'],'active')
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_events WHERE kind='production_paused'").fetchone()[0],1)

    def test_cancel_intent_recovers_before_adapter_call_and_uncertainty_does_not_erase_it(self):
        self.click(self.stage_card()['token']);self.worker().tick()
        producer=self.rt.task('demo','produce')['latest']
        card,mid=self.control('cancel','cancel')
        with patch.object(self.factory,'cancel',side_effect=AssertionError('No I/O in callback')):self.press(card,mid)
        self.assertEqual(self.rt.task('demo','produce')['status'],'cancelling')
        self.assertIn('not yet confirmed',status.current(self.state,'demo')[1])
        self.reopen()
        self.factory.sessions[producer]['status']={'status':'uncertain','reason':'Supervisor receipt unavailable'}
        with patch.object(self.factory,'cancel') as cancel:
            self.worker().tick();self.worker().tick()
            self.assertEqual(cancel.call_count,2)
        self.assertEqual(self.rt.task('demo','produce')['status'],'cancelling')
        self.assertIn('Supervisor receipt unavailable',self.rt.status('demo')['attempts'][0]['error'])
        self.worker().tick();self.press(card,mid);self.worker().tick()
        self.assertEqual(self.rt.task('demo','produce')['status'],'cancelled')
        self.assertEqual(self.factory.calls,[producer])
        self.assertNotIn('not yet confirmed',status.current(self.state,'demo')[1])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_events WHERE kind='cancellation_requested'").fetchone()[0],1)

    def test_delivery_owner_channel_stale_controls_and_rollback(self):
        self.click(self.stage_card()['token'])
        card,mid=self.control('pause','pause')
        self.press(card,mid,user=8);self.press(card,mid+10000)
        with self.state.db:self.state.db.execute('UPDATE outbox SET sent=0 WHERE id=?',(card['event_id'],))
        self.press(card,mid)
        with self.state.db:self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(card['event_id'],))
        self.state.channel='messages';self.press(card,mid);del self.state.channel
        self.assertEqual(self.rt.status('demo')['status'],'active')
        with patch.object(pc,'notice',side_effect=ValueError('Injected notice failure')):self.press(card,mid)
        self.assertEqual(self.rt.status('demo')['status'],'active')
        self.assertEqual(self.state.get('production-control-epoch:demo',0),0)
        self.press(card,mid)
        resume,rid=self.control('resume','resume')
        spec=self.rt.spec(self.rt.task('demo','produce'));spec['instruction']='Changed scope'
        self.rt.replace_future('demo',spec)
        self.press(resume,rid);self.worker().tick()
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.rt.status('demo')['status'],'paused')

    def test_disabled_dispatch_still_collects_already_running_attempt(self):
        self.click(self.stage_card()['token']);self.worker().tick()
        producer=self.rt.task('demo','produce')['latest']
        with self.state.db:self.state.put('production-enabled:demo',False)
        self.factory.finish(producer);self.worker().tick()
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_review')
        self.assertEqual(self.factory.calls,[producer])

    def test_cancel_before_dispatch_and_nested_runtime_cancel_have_no_side_effect(self):
        self.click(self.stage_card()['token']);card,mid=self.control('cancel','cancel')
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'Commit pending'):
            self.rt.cancel('demo')
        self.press(card,mid);self.worker().tick()
        self.assertEqual(self.factory.calls,[])
        self.assertTrue(all(t['status']=='cancelled' for t in self.rt.status('demo')['tasks']))


if __name__=='__main__':unittest.main()
