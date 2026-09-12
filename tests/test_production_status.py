import unittest
import json
from pathlib import Path
from unittest.mock import patch
from tests import test_production_control as fixtures
import production_status as status
import production_control as pc
import orchestrator_chat as chat
import production_continuations as cont


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    message=fixtures.Tests.message
    click=fixtures.Tests.click
    worker=fixtures.Tests.worker
    stage_card=fixtures.Tests.stage_card
    finish_stage=fixtures.Tests.finish_stage
    blocked_revision=fixtures.Tests.blocked_revision

    def delivered(self,run='demo'):
        event='production:'+run+':status-test'
        with self.state.db:pc.notice(self.state,run,'status-test','Production progress')
        self.bridge.flush(False)
        return self.state.db.execute('SELECT message_id FROM orchestrator_messages WHERE focus=? ORDER BY message_id DESC LIMIT 1',(run,)).fetchone()[0],event

    def press(self,mid,ident='status-click',user=7,data=None):
        self.bridge.process({'update_id':800,'callback_query':{'id':ident,'data':data or status.token('demo'),
            'from':{'id':user},'message':{'chat':{'id':7,'type':'private'},'message_id':mid}}})

    def test_card_button_reads_fresh_state_and_repeated_callback_is_deduplicated(self):
        mid,event=self.delivered()
        markup=chat.controls(self.state,event)
        self.assertEqual(markup['inline_keyboard'][0][0]['text'],'Check status')
        self.assertLessEqual(len(status.token('x'*80).encode()),64)
        with patch.object(chat,'generate',side_effect=AssertionError('No model allowed')):
            self.press(mid);self.press(mid)
        notices=list(self.state.db.execute("SELECT text FROM outbox WHERE id LIKE 'production:demo:status:%'"))
        self.assertEqual(len(notices),1)
        self.assertIn('Queued; scheduling is off',notices[0][0])
        self.click(self.stage_card()['token']);worker=self.worker();worker.tick();worker.tick()
        self.press(mid,'fresh-click')
        text=self.state.db.execute("SELECT text FROM outbox WHERE id LIKE 'production:demo:status:%' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIn('produce: Running',text)
        self.assertIn('Waiting for produce (running)',text)
        self.assertEqual(self.factory.calls.__len__(),1)
        self.bridge.flush(False)
        reply=self.state.db.execute("SELECT message_id FROM orchestrator_messages WHERE focus='demo' ORDER BY message_id DESC LIMIT 1").fetchone()[0]
        self.message('Explain this stage',900,reply=reply)
        self.assertEqual(self.state.db.execute('SELECT focus FROM orchestrator_chats WHERE id=900').fetchone()[0],'demo')

    def test_unpaired_user_or_wrong_message_cannot_use_button(self):
        mid,_=self.delivered()
        self.press(mid,user=8)
        self.press(mid+100)
        self.press(mid,data=status.token('another-run'))
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'production:demo:status:%'").fetchone()[0],0)

    def test_inspection_delivers_recorded_details_once_without_dispatch(self):
        self.click(self.stage_card()['token']);worker=self.worker();worker.tick()
        self.factory.finish(self.rt.task('demo','produce')['latest']);worker.tick()
        mid,_=self.delivered()
        count=len(self.factory.calls)
        self.press(mid,'inspect',user=8,data=status.token('demo','prodinspect'))
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM media_outbox WHERE id LIKE 'production-inspection:%'").fetchone()[0],0)
        with patch.object(chat,'generate',side_effect=AssertionError('No model allowed')):
            self.press(mid,'inspect',data=status.token('demo','prodinspect'))
            self.press(mid,'inspect',data=status.token('demo','prodinspect'))
        rows=self.state.db.execute("SELECT * FROM media_outbox WHERE id LIKE 'production-inspection:%'").fetchall()
        self.assertEqual(len(rows),1);report=json.loads(Path(rows[0]['path']).read_text())
        self.assertEqual(report['backend']['model'],'fixed-model')
        self.assertTrue(report['artifact_lineage']['dependencies'])
        context = pc.inspect(self.state,'demo')[0]
        self.assertEqual(context['artifact_lineage']['dependencies'],report['artifact_lineage']['dependencies'])
        self.assertEqual(report['attempts'][0]['receipt']['usage'],[{'input_tokens':100}])
        self.assertIn('unknown',report['usage_note'])
        self.assertTrue(any(e['kind']=='checks_recorded' for e in report['events']))
        self.assertEqual(len(self.factory.calls),count)
        self.bridge.flush(False);self.bridge.flush_media()
        self.assertEqual(self.state.db.execute('SELECT status FROM media_outbox WHERE id=?',(rows[0]['id'],)).fetchone()[0],'sent')

    def test_blocked_dependency_old_review_and_successor_are_distinguished(self):
        self.blocked_revision()
        run,text=status.current(self.state,'demo')
        self.assertIn('Missing dated market sources',text)
        self.assertIn('Waiting for produce (blocked)',text)
        self.assertIn('earlier review does not approve',text)
        self.assertIn('Attempt budget exhausted',text)
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            cont.enqueue(self.state,{'id':77,'prompt':'Continue with sources'},'demo')
        cont.apply(self.worker())
        run,text=status.current(self.state,'demo')
        self.assertNotEqual(run,'demo')
        self.assertIn('Current continuation of demo',text)
        self.assertIn('attempt 0/1',text)

    def test_status_button_preserves_action_buttons_and_review_gate(self):
        row=self.stage_card()
        markup=chat.controls(self.state,'orchestrator:'+str(row['job_id']))
        self.assertEqual(len(markup['inline_keyboard']),2)
        self.assertEqual(markup['inline_keyboard'][-1][0]['text'],'Check status')
        self.click(row['token']);worker=self.worker();worker.tick()
        self.factory.finish(self.rt.task('demo','produce')['latest']);worker.tick()
        run,text=status.current(self.state,'demo')
        self.assertNotIn('earlier review',text)
        self.factory.finish(self.rt.task('demo','review')['latest'],decision='accept');worker.tick()
        run,text=status.current(self.state,'demo')
        self.assertIn('Ready for your review',text)
        self.assertIn('No later stage starts automatically',text)
        self.assertFalse(self.state.get('production-enabled:demo'))


if __name__=='__main__':unittest.main()
