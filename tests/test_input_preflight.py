"""Late-bound input failures stay local and visible; no providers or apps run."""
import unittest
from unittest.mock import patch

from orchestrator import executors, execution
from tests import test_production_planning as fixtures
from tests.test_gemini_executor import graph
from tests.test_orchestrator import plan, task
from tests.test_browser_screenshots import png
from task_relay import production_control as pc


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown

    def source(self,raw,path='source.txt'):
        file=self.rt.root/path;file.write_bytes(raw)
        return dict(artifact=self.rt.register(file,'Fixture'),path=path,purpose='Exact source',authority='Evidence')

    def error(self,tid):
        view=pc.inspect(self.state,'demo')[0]
        return next(t['error'] for t in view['tasks'] if t['id']==tid)

    def test_new_upstream_text_is_checked_before_reviewer_attempt(self):
        self.rt.create(graph());self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        (self.factory.sessions[aid]['workspace']/'output.txt').write_text('x'*65)
        with patch.object(executors,'MAX_INPUT_BYTES',64):self.rt.tick('demo')
        review=self.rt.task('demo','review')
        self.assertEqual((review['status'],review['attempts']),('blocked',0))
        self.assertEqual(len(self.factory.calls),1)
        self.assertIn('Input check failed before dispatch: API text input pack',self.error('review'))
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_review')
        self.assertIsNotNone(self.rt.output('demo','produce','output.txt'))

    def test_invalid_utf8_upstream_does_not_launch_reviewer(self):
        self.rt.create(graph());self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid)
        (self.factory.sessions[aid]['workspace']/'output.txt').write_bytes(b'\xff')
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['attempts'],0)
        self.assertIn('UTF-8 text inputs: candidate.txt',self.error('review'))
        view=pc.inspect(self.state,'demo')[0]
        self.assertEqual(view['output_texts'],[])
        self.assertIn('Text preview unavailable',view['omitted_output_texts'][0]['reason'])
        self.assertIsNotNone(self.rt.output('demo','produce','output.txt'))

    def test_changed_source_blocks_its_task_but_not_independent_work(self):
        source=self.source(b'original')
        self.rt.create(plan([task(inputs=[source]),task('independent')]))
        from pathlib import Path
        blob=Path(self.rt.artifact(source['artifact'])['blob']);blob.chmod(0o600);blob.write_bytes(b'modified')
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],0)
        self.assertEqual(self.rt.task('demo','independent')['attempts'],1)
        self.assertIn('Registered artifact content changed: source.txt',self.error('produce'))
        self.rt.tick('demo')
        self.assertEqual(len(self.factory.calls),1)

    def test_revision_preflight_reason_replaces_old_attempt_error(self):
        value=graph()
        for t in value['tasks']:t['max_attempts']=2
        self.rt.create(value);self.rt.tick('demo')
        aid=self.rt.task('demo','produce')['latest'];self.factory.finish(aid,decision='blocked')
        self.rt.tick('demo');self.rt.revise('demo','produce','Correct the draft')
        with patch.object(executors,'MAX_INPUT_BYTES',1):self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['attempts'],1)
        self.assertIn('Input check failed before dispatch',self.error('produce'))
        self.assertEqual(len(self.factory.calls),1)

    def test_browser_png_has_separate_allowance_and_code_accepts_binary(self):
        image={**self.source(png(),'map.png'),'media_type':'image/png'}
        with patch.object(executors,'MAX_INPUT_BYTES',1):
            resolved=self.rt.checked_inputs('unused',{'inputs':[image]}, {'type':'gemini-browser'})
            self.assertEqual(resolved[0]['artifact'],image['artifact'])
            self.rt.checked_inputs('unused',{'inputs':[image]}, {'type':'gemini-code'})

    def test_registered_operation_checks_exact_bound_total(self):
        source=self.source(b'12345')
        spec={'inputs':[source],'execution':{'capability':'images.collect'}}
        with patch.dict(execution.REGISTRY['images.collect'],input_bytes=4):
            with self.assertRaisesRegex(ValueError,'input byte limit exceeded'):
                self.rt.checked_inputs('unused',spec,{'type':'codex-cli'})
