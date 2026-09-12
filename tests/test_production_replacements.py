import json
import sqlite3
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_orchestrator_chat as fixtures
from tests import test_artifact_replacements as core
from tests.test_orchestrator import FakeFactory
from orchestrator.runtime import Runtime
from orchestrator import artifact_replacements as ar
import orchestrator_chat as chat
import production_control as pc
import production_replacements as replacements

class Tests(unittest.TestCase):
    message=fixtures.Tests.message
    make=core.Tests.make
    def setUp(self):
        fixtures.Tests.setUp(self);self.state.media_dir=self.state.media_dir.resolve()
        self.factory=FakeFactory();self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)
        self.old,self.a=self.make('old');self.new,self.b=self.make('new',[self.old]);self.derived,_=self.make('derived',[self.old])
    def tearDown(self):self.rt.close();fixtures.Tests.tearDown(self)
    def prepare(self,ident=50):
        self.message('/orchestrator Replace the old selected model with the new selected model. Do not rebuild.',ident)
        action={'kind':'replace_selection','old_decision':self.a,'new_decision':self.b}
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Prepared a replacement decision.','action':action})).tick()
        row=self.state.db.execute('SELECT * FROM production_replacement_cards WHERE request_id=?',(ident,)).fetchone()
        self.assertIsNotNone(row,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()[0])
        return row
    def delivered(self,row):
        self.bridge.flush(False)
        return self.state.db.execute('SELECT message_id FROM production_replacement_messages WHERE token=?',(row['token'],)).fetchone()[0]
    def press(self,row,mid,user=7,verb='apply'):
        self.bridge.process({'update_id':999,'callback_query':{'id':'replacement-'+verb,'data':'prodreplace:'+verb+':'+row['token'],
          'from':{'id':user},'message':{'chat':{'id':7,'type':'private'},'message_id':mid}}})
    def test_conversation_card_delivered_identity_duplicate_and_no_workers(self):
        calls=list(self.factory.calls);row=self.prepare()
        self.assertIn('Replace selected version',chat.controls(self.state,row['event_id'])['inline_keyboard'][0][0]['text'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
        with self.rt.transaction():
            with self.assertRaisesRegex(ValueError,'delivered card'):replacements.apply(self.state,row['token'],7,1)
        mid=self.delivered(row);self.press(row,mid,user=8);self.press(row,mid+100)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
        self.press(row,mid);self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],1)
        self.assertEqual({r['artifact'] for r in ar.view(self.state.db,'old')['outdated_outputs']},{self.old,self.derived})
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(pc.inspect(self.state,'new')[0]['artifact_replacements']['heads'][0]['current_decision'],self.b)
    def test_stale_card_and_changed_file_leave_replacement_unapplied(self):
        row=self.prepare();mid=self.delivered(row)
        p=Path(self.rt.artifact(self.new)['blob']);p.chmod(0o600);p.write_text('tampered')
        self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_replacement_cards').fetchone()[0],'pending')
    def test_reverse_decision_invalidates_an_older_card_even_when_current_returns(self):
        row=self.prepare();mid=self.delivered(row)
        self.rt.replace_selection(self.a,self.b,0,'outside','Use new')
        self.rt.replace_selection(self.b,self.a,1,'reverse','Use old again')
        self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_replacement_cards').fetchone()[0],'pending')
    def test_dismissal_retains_decisions_and_does_not_replace(self):
        row=self.prepare();mid=self.delivered(row);self.press(row,mid,verb='dismiss');self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_replacement_cards').fetchone()[0],'dismissed')
    def test_pending_feedback_blocks_card(self):
        row=self.prepare();mid=self.delivered(row)
        self.message('Wait, check the other model first.',51,reply=mid)
        self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)
    def test_next_stage_gets_current_replacement_and_binds_revision(self):
        import production_stages as stages
        before=stages.snapshot(self.state,self.rt,'old','telegram')
        self.rt.replace_selection(self.a,self.b,0,'choice','Use new')
        after=stages.snapshot(self.state,self.rt,'old','telegram')
        self.assertNotEqual(before['replacement_revisions'],after['replacement_revisions'])
        prior,sources,job=stages.sources(self.state,self.rt,'old','telegram',123)
        current=next(s for s in sources if s['artifact']==self.new)
        self.assertTrue(current['path'].startswith('current-selection/'))
        self.assertEqual(current['sha256'],self.rt.artifact(self.new)['sha256'])
        self.assertEqual(prior['decisions'][0]['artifact'],self.old)

    def test_feedback_on_an_earlier_stage_blocks_replacement(self):
        row=self.prepare();mid=self.delivered(row)
        self.message('Wait, keep the earlier model.',51)
        with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET focus='old' WHERE id=51")
        self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],0)

    def test_notice_failure_rolls_back_card_and_validity_then_retry_succeeds(self):
        row=self.prepare();mid=self.delivered(row)
        with patch.object(pc,'notice',side_effect=sqlite3.OperationalError('disk full')):self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacement_heads').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_artifact_validity').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_replacement_cards').fetchone()[0],'pending')
        self.press(row,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_replacements').fetchone()[0],1)

if __name__=='__main__':unittest.main()
