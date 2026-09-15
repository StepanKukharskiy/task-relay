import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_production_control as fixture
from task_relay import production_control as pc
from task_relay import production_continuations as cont
from task_relay import production_feedback as feedback
from task_relay import orchestrator_chat as chat


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    message=fixture.Tests.message
    click=fixture.Tests.click
    worker=fixture.Tests.worker
    stage_card=fixture.Tests.stage_card
    finish_stage=fixture.Tests.finish_stage
    blocked_revision=fixture.Tests.blocked_revision

    def test_unapplied_user_corrections_and_desktop_clarification_reach_both_workers(self):
        self.blocked_revision()
        earlier='The text is still about what I wanted to build. Use history of agents, market, future.'
        self.message('/orchestrator '+earlier,600)
        with self.state.db:
            self.state.db.execute("UPDATE orchestrator_chats SET focus='demo',status='answered',answer='Invented assistant direction' WHERE id=600")
            self.state.db.execute("INSERT INTO production_user_notes VALUES ('clarification','demo','Yes—history of AI agents, then market, then future','Desktop user clarification',1)")
        self.message('/orchestrator Unrelated project instructions',601)
        with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET focus='unrelated',status='answered' WHERE id=601")
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            cont.enqueue(self.state,{'id':700,'prompt':'Continue with this direction'},'demo')
        # Later user history must not silently alter an already queued contract.
        with self.state.db:self.state.db.execute("INSERT INTO production_user_notes VALUES ('later','demo','Later change','Desktop user',2)")
        worker=self.worker();worker.tick()
        row=self.state.db.execute('SELECT child FROM production_continuations').fetchone()
        for tid in ('produce','review'):
            spec=self.rt.spec(self.rt.task(row['child'],tid))
            item=next(i for i in spec['inputs'] if i['path']=='continuation/USER_FEEDBACK.json')
            text=Path(self.rt.artifact(item['artifact'])['blob']).read_text()
            self.assertIn(earlier,text)
            self.assertIn('history of AI agents',text)
            self.assertNotIn('Invented assistant direction',text)
            self.assertNotIn('Unrelated project',text)
            self.assertNotIn('Later change',text)
            self.assertIn('changed passages',spec['criteria'][-1])
            self.assertIn('replaces the framing',spec['instruction'])

    def test_large_source_pack_is_not_inlined_and_current_feedback_stays_available(self):
        for number in range(4):
            file=Path(self.temp.name).resolve()/('guide'+str(number)+'.md');file.write_text('Guide text\n'*5000)
            self.rt.register(file,'Guide',run='demo',path=file.name)
        catalog=[{'cwd':self.temp.name,'title':'Task '+str(i),'description_excerpt':'x'*1600} for i in range(200)]
        with self.state.db:self.state.put('orchestrator_routing_enabled',True)
        with patch.object(chat.task_routing,'catalog',return_value=catalog):
            snap=chat.snapshot(self.state,'demo')
        view=next(v for v in snap['production_runs'] if v['name']=='demo')
        self.assertTrue(view['omitted_reference_texts'])
        self.assertLessEqual(sum(len(x['text'].encode()) for x in view['reference_texts']),48000)
        self.assertEqual(len(view['registered_files']),5)
        self.assertLess(len(json.dumps(snap)),500000)

    def test_context_failure_is_identified_and_original_message_preserved(self):
        original='Continue the video; where is the history?'
        self.message('/orchestrator '+original,777)
        with patch.object(chat,'snapshot',side_effect=ValueError('Workflow evidence exceeds the conversation limit.')), patch.object(chat,'generate') as model:
            chat.Worker(self.state,model).tick()
        model.assert_not_called()
        row=self.state.db.execute('SELECT prompt,answer FROM orchestrator_chats WHERE id=777').fetchone()
        self.assertEqual(row['prompt'],original)
        self.assertIn('did not reach the model',row['answer'])
        self.assertIn('rephrasing is not required',row['answer'])
        self.assertEqual(self.state.db.execute('SELECT phase FROM orchestrator_chat_errors WHERE job_id=777').fetchone()[0],'context')

    def test_history_overflow_is_explicit_and_chat_excerpts_mark_omissions(self):
        for i in range(3):
            self.message('/orchestrator '+('User direction '+str(i)+' ')*300,600+i)
            with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET focus='demo' WHERE id=?",(600+i,))
        context=feedback.context(self.state,'demo',limit=6000)
        self.assertFalse(context['complete'])
        self.assertTrue(context['omitted_turn_ids'])
        with patch.object(feedback,'MAX_HISTORY_BYTES',100):
            with self.assertRaisesRegex(ValueError,'No feedback was silently dropped'):
                feedback.collect(self.state,'demo')


if __name__=='__main__':unittest.main()
