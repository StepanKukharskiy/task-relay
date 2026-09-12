import json
from pathlib import Path
import unittest

import conversation_inputs as ci
import orchestrator_chat as chat
from tests import test_task_routing as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request

    def saved(self, ident, created, text, focus=None, channel='telegram'):
        with self.state.db:
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,status,created,answer) VALUES (?,?,?,?,?,?,?,?)',
                (ident,'Update the script',focus,'gemini','fixture','answered',created,text))
            self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))

    def test_handoff_carries_exact_newer_chat_draft(self):
        draft='S01: Ancient helpers.\nS02: Current market.\nS03: Future.'
        self.saved(900,1,draft)
        self.request({'kind':'route_task','task_id':'t0'},'Share the updated script with Codex.')
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        manifest=json.loads(row['input_manifest']);self.assertEqual(len(manifest),1)
        data=json.loads(Path(manifest[0]['path']).read_text())
        self.assertEqual(data['entries'][0]['answer'],draft)
        self.assertEqual(data['entries'][0]['id'],900)
        self.worker.tick()
        self.assertIn(manifest[0]['path'],self.calls[0][1])
        self.assertIn('not independently reviewed',self.calls[0][1])

    def test_history_orders_by_time_and_isolates_channel_focus_future(self):
        self.saved(999999,1,'old',focus='video')
        self.saved(2,2,'new',focus='video')
        self.saved(3,3,'other production',focus='other')
        self.saved(4,4,'other channel',focus='video',channel='messages')
        self.saved(5,10,'future',focus='video')
        self.saved(6,5,'current',focus='video')
        rows=ci.recent(self.state,{'id':6})
        self.assertEqual([r['answer'] for r in rows],['old','new'])

    def test_choice_delay_preserves_snapshot_and_tampering_blocks_send(self):
        self.saved(90,1,'original draft')
        self.request({'kind':'route_task','task_id':'t0'},'Share this with Codex.')
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        path=Path(json.loads(row['input_manifest'])[0]['path'])
        with self.state.db:self.state.db.execute("UPDATE orchestrator_chats SET answer='later text' WHERE id=90")
        self.assertIn('original draft',path.read_text())
        path.chmod(0o600);path.write_text('tampered')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'failed')

    def test_oversized_context_does_not_silently_drop_script(self):
        self.saved(90,1,'x'*(ci.MAX_BYTES+1))
        self.request({'kind':'route_task','task_id':'t0'},'Share this with Codex.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)
        self.assertEqual(self.calls,[])

    def test_explicit_handoff_keeps_task_catalog_on_production_reply(self):
        payload={'snapshot':{'focus':'video','production_runs':[{'name':'video','status':'blocked'}],
                             'codex_tasks':[{'id':'t0'}]},
                 'user_message':'Use this Codex task; share the video script there.'}
        system,result=chat.model_context(payload)
        self.assertEqual(result['snapshot']['codex_tasks'],[{'id':'t0'}])
        self.assertIn('independent handoff',system)
        payload['snapshot']['codex_tasks'][0]['title']='Turn vision into LinkedIn post'
        payload['user_message']='Share it with Turn vision into LinkedIn post.'
        _,result=chat.model_context(payload)
        self.assertIn('codex_tasks',result['snapshot'])
        payload['user_message']='We need more history in the opening.'
        _,result=chat.model_context(payload)
        self.assertEqual(result['interaction'],'production_review_reply')
        self.assertIn('codex_tasks',result['snapshot'])


if __name__=='__main__':unittest.main()
