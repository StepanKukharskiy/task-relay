import json
import unittest
from pathlib import Path
from unittest.mock import patch

from task_relay import production_control as pc
from task_relay import orchestrator_chat as chat
from tests import test_production_status as status_fixtures


class Tests(unittest.TestCase):
    setUp=status_fixtures.Tests.setUp
    tearDown=status_fixtures.Tests.tearDown
    message=status_fixtures.Tests.message
    click=status_fixtures.Tests.click
    worker=status_fixtures.Tests.worker
    stage_card=status_fixtures.Tests.stage_card

    def ready(self,quality=False):
        self.click(self.stage_card()['token']);worker=self.worker();worker.tick()
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        if quality:
            from orchestrator.outcomes import quality as finding
            path=self.factory.sessions[aid]['workspace']/'.relay/result.json';value=json.loads(path.read_text())
            value['findings']=[finding('layout','Image crops the subject','output.txt: preview evidence')]
            path.write_text(json.dumps(value))
        worker.tick()
        self.factory.finish(self.rt.task('demo','review')['latest'],decision='accept');worker.tick()
        self.bridge.flush(False)
        card=self.state.db.execute('SELECT * FROM production_selection_cards').fetchone()
        self.assertIsNotNone(card)
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        return card,mid

    def test_quality_card_requires_explicit_delivered_output_acceptance_and_clears_waiting_text(self):
        from orchestrator.outcomes import GATE
        from task_relay.production_activity import lines
        card,mid=self.ready(quality=True)
        self.assertEqual(card['purpose'],GATE)
        self.choose(card,mid)
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.bridge.flush_media();self.choose(card,mid)
        self.assertEqual(self.rt.task('demo','produce')['status'],'completed')
        task=next(t for t in pc.inspect(self.state,'demo')[0]['tasks'] if t['id']=='produce')
        text='\n'.join(lines(task))
        self.assertIn('Accepted with quality concerns',text)
        self.assertNotIn('waits for your decision',text)

    def choose(self,card,mid,user=7):
        self.bridge.process({'update_id':999,'callback_query':{'id':'choice','data':'prodselect:'+card['token'],
            'from':{'id':user},'message':{'chat':{'id':7,'type':'private'},'message_id':mid}}})

    def test_selection_requires_delivered_file_and_records_exact_identity_once(self):
        card,mid=self.ready()
        self.choose(card,mid)
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.bridge.flush_media()
        with patch.object(chat,'generate',side_effect=AssertionError('Selection needs no model')):
            self.choose(card,mid);self.choose(card,mid)
        decisions=self.state.db.execute('SELECT * FROM production_decisions').fetchall()
        self.assertEqual(len(decisions),1)
        self.assertEqual(decisions[0]['artifact'],card['artifact'])
        self.assertEqual(decisions[0]['purpose'],'creative selection')
        self.assertEqual(self.rt.task('demo','produce')['status'],'completed')
        self.assertFalse(self.state.get('production-enabled:demo'))
        self.assertEqual(len(self.factory.calls),2)
        events=self.state.db.execute("SELECT data FROM production_events WHERE kind='user_selected'").fetchall()
        self.assertEqual(json.loads(events[0]['data'])['sha256'],card['sha256'])

    def test_foreign_message_user_and_pending_reply_cannot_select(self):
        from task_relay import production_selections as selections
        card,mid=self.ready();self.bridge.flush_media()
        other=self.state.db.execute('''SELECT message_id FROM orchestrator_messages WHERE focus='demo'
            AND message_id NOT IN (SELECT message_id FROM production_selection_messages WHERE token=?)''',(card['token'],)).fetchone()[0]
        self.choose(card,mid,user=8);self.choose(card,other)
        self.state.channel='messages'
        self.assertEqual(selections.controls(self.state,card['event_id']),[])
        self.choose(card,mid)
        del self.state.channel
        self.message('Revise the wording first',1000,reply=mid)
        self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_multiple_outputs_select_only_the_clicked_artifact(self):
        from tests.test_orchestrator import pair
        value=pair(gate='Choose one wording');value['id']='choices'
        value['tasks'][0]['outputs'].append(dict(path='alternative.txt',purpose='Alternate wording'))
        value['tasks'][1]['inputs'].append(dict(from_task='produce',output='alternative.txt',path='alternative.txt',
                                               purpose='Inspect alternative',authority='Unaccepted candidate'))
        self.rt.create(value)
        with self.state.db:pc.start(self.state,'choices',pc.inspect(self.state,'choices')[0]['revision'])
        worker=self.worker();worker.tick()
        self.factory.finish(self.rt.task('choices','produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task('choices','review')['latest'],decision='accept');worker.tick()
        self.bridge.flush()
        cards=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=?',('choices',)).fetchall()
        self.assertEqual(len(cards),2)
        card=next(c for c in cards if self.rt.artifact(c['artifact'])['path']=='alternative.txt')
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        self.choose(card,mid)
        sibling=next(c for c in cards if c['token']!=card['token'])
        self.choose(sibling,mid)
        selected=self.state.db.execute('SELECT artifact,purpose FROM production_decisions WHERE run=?',('choices',)).fetchall()
        self.assertEqual([(r['artifact'],r['purpose']) for r in selected],[(card['artifact'],'Choose one wording')])

    def test_changed_artifact_and_cancelled_run_reject_selection(self):
        card,mid=self.ready();self.bridge.flush_media()
        blob=Path(self.rt.artifact(card['artifact'])['blob']);original=blob.read_bytes()
        blob.chmod(0o600);blob.write_bytes(b'changed')
        self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        blob.write_bytes(original);self.rt.cancel('demo')
        self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_old_attempt_cannot_select_after_revision(self):
        card,mid=self.ready();self.bridge.flush_media()
        self.rt.revise('demo','produce','Revise the text')
        self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_restart_preserves_card_and_transaction_rolls_back_decision(self):
        from task_relay.bridge import State,Bridge
        from orchestrator.runtime import Runtime
        card,mid=self.ready();self.bridge.flush_media()
        dbpath=Path(self.state.db.execute('PRAGMA database_list').fetchone()[2])
        self.rt.close();self.state.db.close()
        self.state=State(dbpath);self.bridge=Bridge(self.state,self.telegram,{})
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)
        with patch.object(pc,'notice',side_effect=ValueError('Injected receipt failure')):
            self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.choose(card,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],1)


if __name__=='__main__':unittest.main()
