"""Desktop discovery preserves old histories and exposes only saved state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay.desktop_library import workflows, automation_tools
from task_relay.desktop_conversation import bounded_messages, codex_messages, messages
from task_relay.desktop_tasks import DesktopTaskError
from task_relay.desktop_approvals import inbox
from task_relay.relay_paths import Paths


class DesktopLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = Paths(root/'app', root/'data', root/'workspaces', root/'generated')

    def state(self):
        state = State(self.paths.state)
        self.addCleanup(state.db.close)
        return state

    def test_empty_library_does_not_create_database(self):
        self.assertEqual(workflows(paths=self.paths)['items'], [])
        self.assertEqual(inbox(self.paths)['items'], [])
        self.assertFalse(self.paths.data.exists())

    def test_linked_history_paginates_and_keeps_corrupt_record_visible(self):
        state = self.state()
        with state.db:
            for i in range(42):
                state.db.execute('INSERT INTO workflows VALUES (?,?,?)', (str(i), 3, json.dumps({'status':'paused', 'direction':'Exact input'})))
            state.db.execute("UPDATE workflows SET data='invalid' WHERE name='41'")
        before = state.db.total_changes
        first = workflows(paths=self.paths)
        self.assertEqual(first['total'], 42)
        self.assertEqual(first['items'][0]['status'], 'Unknown')
        second = workflows(offset=first['next_offset'], paths=self.paths)
        self.assertEqual(len(second['items']), 2)
        self.assertEqual(len({i['id'] for i in first['items'] + second['items']}), 42)
        self.assertIsNone(second['next_offset'])
        self.assertEqual(state.db.total_changes, before)
        with self.assertRaises(DesktopTaskError): workflows(offset=-1, paths=self.paths)

    def test_runs_exist_without_desktop_drafts(self):
        state = self.state()
        with state.db:
            state.db.execute("INSERT INTO production_runs VALUES ('run',?, 'waiting')", (json.dumps({'title':'Existing workflow'}),))
        self.assertEqual(workflows('runs', paths=self.paths)['items'][0]['title'], 'Existing workflow')
        self.assertEqual(workflows('plans', paths=self.paths)['items'], [])

    def test_codex_history_uses_message_records_once_and_skips_partial_tail(self):
        path = self.paths.data.parent/'rollout.jsonl'
        records = [dict(type='response_item',payload=dict(type='message',role=role,content=[dict(type=kind,text=text)]))
                   for role,kind,text in [('user','input_text','**Exact request**'),('assistant','output_text','```python\nprint(1)\n```')]]
        records.append(dict(type='event_msg',payload=dict(type='agent_message',message='duplicate')))
        path.write_text('\n'.join(json.dumps(r) for r in records)+'\n{"type":')
        actual = codex_messages(path)
        self.assertEqual([r['role'] for r in actual], ['user','assistant'])
        self.assertEqual(actual[0]['text'], '**Exact request**')

    def test_saved_input_is_not_duplicated_by_its_backend_job_or_replayed(self):
        state = self.state()
        with state.db:
            state.db.execute("INSERT INTO desktop_commands VALUES ('req','task','Exact request',-1,'uncertain',1,NULL)")
            state.db.execute("INSERT INTO backend_jobs(id,thread_id,update_id,prompt,status,created_at) VALUES ('job','task',-1,'Exact request','waiting',1)")
        before = state.db.total_changes
        actual = messages(state.db, {'id':'task','backend':'openai'}, [{'id':'desktop:req:1','text':'Uncertain','channel':'desktop'}])
        self.assertEqual([r['text'] for r in actual], ['Exact request','Uncertain'])
        self.assertEqual(actual[0]['status'], 'uncertain')
        self.assertEqual(state.db.total_changes, before)

    def test_large_history_fits_bridge_without_changing_saved_input(self):
        original = 'x' * 300000
        result = bounded_messages([{'id':'large','text':original,'role':'user'}])
        self.assertLess(len(json.dumps(result)), 100000)
        self.assertIn('Display excerpt', result[0]['text'])
        self.assertEqual(len(original), 300000)

    def test_approval_inbox_finds_an_unselected_job_without_dispatch(self):
        from task_relay import codex_approvals
        state = self.state()
        with state.db:
            state.db.execute("INSERT INTO watched(id,title,status) VALUES ('other','Other job','running')")
        request = {'id':11, 'method':codex_approvals.COMMAND,
                   'params':{'threadId':'other','turnId':'turn','itemId':'item','command':'echo fixture'}}
        codex_approvals.sync(state, 'other', 'owner', {'requests':[request], 'turns':[]}, 'Other job')
        before = state.db.total_changes
        self.assertEqual(inbox(self.paths)['items'], [{'task_id':'other','title':'Other job','count':1}])
        self.assertEqual(state.db.total_changes, before)

    def test_catalog_uses_registry_availability_without_running_tools(self):
        with patch('orchestrator.execution.catalog', return_value=[{'id':'fixture','version':1,'available':False}]), patch('orchestrator.executors.catalog', return_value=[]):
            result = automation_tools()
        self.assertFalse(result['tools'][0]['available'])
        self.assertFalse(result['automatic_extraction'])
        self.assertIn('generate_image', [a['id'] for a in result['actions']])


if __name__ == '__main__': unittest.main()
