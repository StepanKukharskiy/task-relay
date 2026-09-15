import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from task_relay.bridge import State
from task_relay import orchestrator_chat as chat
from task_relay import project_roadmaps as roadmaps


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a = self.root / 'task-relay'; self.a.mkdir()
        self.b = self.root / 'apartment-mix'; self.b.mkdir()
        self.tasks = [{'cwd':str(self.a),'title':'Build workflow observer'}, {'cwd':str(self.b)}]

    def tearDown(self):
        self.temp.cleanup()

    def test_current_project_wins_and_changed_file_is_reread(self):
        file = self.a / 'ROADMAP.md'; file.write_text('Next: O03. Observer deferred.')
        history = [{'prompt':'apartment-mix priorities','answer':'Observer is primary'}]
        first = roadmaps.context(self.tasks, [], None, 'task relay next steps', history)
        self.assertEqual(len(first['documents']), 1)
        self.assertIn('O03', first['documents'][0]['content'])
        file.write_text('Next: O05.')
        second = roadmaps.context(self.tasks, [], None, 'task-relay next steps', history)
        self.assertNotEqual(first['documents'][0]['sha256'], second['documents'][0]['sha256'])
        self.assertEqual(second['documents'][0]['content'], 'Next: O05.')

    def test_missing_oversized_symlink_and_invalid_text_are_explicit(self):
        file = self.a / 'ROADMAP.md'
        self.assertEqual(roadmaps.read(self.a)['status'], 'missing')
        for raw in (b'x'*(roadmaps.MAX_BYTES+1), b'\xff'):
            file.write_bytes(raw)
            result = roadmaps.read(self.a)
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('content', result)
        file.unlink(); file.symlink_to(self.b / 'ROADMAP.md')
        (self.b / 'ROADMAP.md').write_text('Do not follow this link')
        self.assertEqual(roadmaps.read(self.a)['status'], 'unavailable')

    def test_ambiguity_does_not_use_assistant_claim_or_arbitrary_path(self):
        result = roadmaps.context(self.tasks, [], None, 'What is next?',
                                 [{'prompt':'hello','answer':'task-relay next'}])
        self.assertEqual(result['status'], 'needs_project')
        self.assertEqual(result['documents'], [])
        result = roadmaps.context(self.tasks, [], None, 'Read /private/unknown/ROADMAP.md')
        self.assertEqual(result['status'], 'needs_project')

    def test_followup_focus_and_workflow_alias(self):
        (self.b / 'ROADMAP.md').write_text('Room-first')
        flows = [{'cwd':str(self.b),'name':'floor-solver'}]
        result = roadmaps.context(self.tasks, flows, 'floor-solver', 'What comes next?')
        self.assertEqual(result['documents'][0]['content'], 'Room-first')
        result = roadmaps.context(self.tasks, [], None, 'And next?', [{'prompt':'apartment mix'}])
        self.assertEqual(result['documents'][0]['content'], 'Room-first')

    def test_worker_persists_actual_evidence_and_preserves_user_request(self):
        state = State(self.root / 'state.sqlite')
        self.addCleanup(state.db.close)
        (self.a / 'ROADMAP.md').write_text('O03 first; O05 second. Observer deferred.')
        original = 'What are the current task-relay roadmap steps?'
        with state.db:
            state.db.execute('INSERT INTO orchestrator_chats(id,prompt,focus,provider,model,created) VALUES (1,?,NULL,?,?,0)',
                             (original,'gemini','test'))
        captured = []
        def generate(job, payload):
            system, context = chat.model_context(payload)
            self.assertIn('Task titles/statuses are routing metadata', system)
            self.assertEqual(context['user_message'], original)
            captured.append(context['snapshot']['project_roadmaps'])
            return json.dumps({'answer':'O03 first, from ROADMAP.md.','action':None})
        with patch.object(chat, 'snapshot', return_value={'codex_tasks': self.tasks}):
            chat.Worker(state, generate).tick()
        row = state.db.execute('SELECT status,snapshot FROM orchestrator_chats WHERE id=1').fetchone()
        self.assertEqual(row['status'], 'answered')
        saved = json.loads(row['snapshot'])['project_roadmaps']
        self.assertEqual(saved, captured[0])
        self.assertIn('Observer deferred', saved['documents'][0]['content'])
        self.assertEqual(state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
