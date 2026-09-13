import json
from pathlib import Path
import unittest
from unittest.mock import patch

from bridge import State,Bridge
from orchestrator.runtime import Runtime
from orchestrator.storage import transaction
import production_control as pc
import production_planning as planning
import production_status as status
import production_selections as selections
from tests import test_production_planning as fixtures


class Tests(unittest.TestCase):
    def test_pending_execution_button_preserves_selection_and_queues_only_one_plan(self):
        card,mid=self.selected()
        with self.state.db:
            p=json.loads(self.state.db.execute("SELECT plan FROM production_runs WHERE id='production-1'").fetchone()[0])
            p['deferred_operations']={'rhino.run_python':'Prepare exact script before execution'}
            p['deliverables']={'drawing':{'description':'Facade drawing','deferred_operation':'rhino.run_python'}}
            self.state.db.execute("UPDATE production_runs SET plan=? WHERE id='production-1'",(json.dumps(p),))
        _,text=status.current(self.state,'production-1')
        self.assertIn('Preparation ready; execution pending',text)
        self.assertIn('Not generated yet: Facade drawing',text)
        before=len(self.factory.calls)
        with patch('task_relay.capabilities.catalog',return_value={'graph_operations':[{'id':'rhino.run_python','available':True}]}):
            with transaction(self.state.db):first=status.plan_execution(self.state,'production-1')
            with transaction(self.state.db):second=status.plan_execution(self.state,'production-1')
        plans=self.state.db.execute("SELECT * FROM production_plans WHERE id!='plan-1'").fetchall()
        self.assertEqual(len(plans),1);self.assertEqual(plans[0]['status'],'queued')
        self.assertEqual(len(self.factory.calls),before)
        payload=json.loads(plans[0]['context'])
        self.assertIn(card['artifact'],payload['required_artifacts'])
        self.assertEqual(payload['options']['deliverables'],{'drawing':'Facade drawing'})

    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    ready=fixtures.Tests.ready
    click=fixtures.Tests.click
    start=fixtures.Tests.start

    def finish(self,run):
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.factory.finish(self.rt.task(run,'produce')['latest']);worker.tick()
        self.factory.finish(self.rt.task(run,'review')['latest'],decision='accept');worker.tick()
        self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=? ORDER BY rowid DESC LIMIT 1',(run,)).fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        return card,mid

    def selected(self):
        self.start(self.ready());return self.finish('production-1')

    def next_plan(self,ident=2):
        self.queue(ident,self.action(previous_run='production-1'),'Use the selected brief to write a plain text checklist. Keep the original restrictions.')
        planning.Worker(self.state,lambda *_:(json.dumps(self.response()),{})).tick()
        self.assertEqual(self.row(ident)['status'],'ready',self.row(ident)['error'])
        return self.row(ident)

    def test_two_stages_keep_selected_bytes_instructions_identity_and_recover_once(self):
        card,mid=self.selected();selected=self.rt.artifact(card['artifact'])
        row=self.next_plan();payload=json.loads(row['context'])
        self.assertEqual(payload['options']['job_request_id'],1)
        self.assertEqual(payload['previous_stage']['decisions'][0]['artifact'],card['artifact'])
        self.assertIn(card['artifact'],payload['required_artifacts'])
        self.assertEqual(len(self.factory.calls),2)
        self.start(row);worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        producer=self.rt.task('production-2','produce')['latest']
        worker.close();self.state.db.close()
        self.state=State(self.root/'state.sqlite');self.bridge=Bridge(self.state,self.telegram,{})
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
        self.click(row['token']);worker.tick()
        self.assertEqual(len(self.factory.calls),3)
        source=next(i for i in self.factory.sessions[producer]['frozen']['inputs'] if i['artifact']==card['artifact'])
        self.assertEqual((self.factory.sessions[producer]['workspace']/source['path']).read_bytes(),Path(selected['blob']).read_bytes())
        context=json.loads((self.factory.sessions[producer]['workspace']/'previous-stage/CONTEXT.json').read_text())
        self.assertIn('Do not render',context['original_request'])
        self.assertEqual(context['previous_stage']['decisions'][0]['purpose'],card['purpose'])
        self.factory.finish(producer);worker.tick()
        reviewer=self.rt.task('production-2','review')['latest']
        self.assertEqual((self.factory.sessions[reviewer]['workspace']/source['path']).read_bytes(),Path(selected['blob']).read_bytes())
        self.factory.finish(reviewer,decision='accept');worker.tick()
        self.bridge.flush(False);self.bridge.flush_media()
        next_card=self.state.db.execute("SELECT * FROM production_selection_cards WHERE run='production-2'").fetchone()
        next_mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(next_card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,next_card['token'],7,next_mid)
        before=self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,next_card['token'],7,next_mid)
        worker.tick();self.bridge.flush(False);self.bridge.flush_media()
        self.assertEqual(len(self.factory.calls),4)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],2)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0],before)
        current,text=status.current(self.state,'production-1')
        self.assertEqual(current,'production-2');self.assertIn('Earlier stages: production-1',text)

    def test_unselected_or_changed_decisions_cannot_start_next_stage(self):
        self.start(self.ready())
        self.request(self.action(previous_run='production-1'),'Next stage',2)
        self.assertIsNone(self.row(2))
        card,mid=self.finish('production-1');row=self.next_plan(3)
        self.bridge.flush(False)
        with self.state.db:self.state.db.execute("UPDATE production_decisions SET note='Changed decision' WHERE artifact=?",(card['artifact'],))
        self.click(row['token']);self.assertEqual(self.row(3)['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)

    def test_pending_parent_feedback_blocks_approval_without_losing_the_plan(self):
        card,mid=self.selected();row=self.next_plan();self.bridge.flush(False)
        self.bridge.process({'update_id':4,'message':{'text':'Before continuing, explain the decision.',
            'reply_to_message':{'message_id':mid},'chat':{'id':7,'type':'private'},'from':{'id':7}}})
        self.click(row['token']);self.assertEqual(self.row(2)['status'],'ready')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)

    def test_duplicate_proposals_and_clarification_preserve_one_successor(self):
        self.selected();row=self.next_plan()
        self.request(self.action(previous_run='production-1'),'Next stage again',3)
        self.assertIsNone(self.row(3))
        follow=self.queue(4,self.action(parent_id=row['id']),'Use a shorter checklist.')
        self.assertEqual(self.row(2)['status'],'superseded')
        planning.Worker(self.state,lambda *_:(json.dumps(self.response()),{})).tick()
        self.start(self.row(4));self.click(row['token'])
        self.assertEqual(self.state.db.execute('SELECT child FROM production_stage_links').fetchone()[0],'production-4')
        self.assertEqual(json.loads(follow['options'])['job_request_id'],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)

    def test_registration_rollback_and_cross_channel_preserve_parent(self):
        self.selected();row=self.next_plan();self.bridge.flush(False)
        with patch('production_stages.register',side_effect=ValueError('Interrupted lineage registration')):self.click(row['token'])
        self.assertEqual(self.row(2)['status'],'ready')
        self.assertIsNone(self.state.db.execute('SELECT child FROM production_stage_links').fetchone()[0])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.state.channel='messages'
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'original channel'):planning.apply(self.state,row['token'],'start')
        del self.state.channel
        self.click(row['token']);self.assertEqual(self.row(2)['status'],'started')


if __name__=='__main__':unittest.main()
