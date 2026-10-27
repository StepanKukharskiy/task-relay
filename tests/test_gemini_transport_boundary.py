"""Real Gemini transport validation through the registered image lifecycle.

Only the HTTP opener is replaced; no network or paid calls.
"""
import base64
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from task_relay import gemini
from orchestrator import operation_lifecycle
from orchestrator.runtime import Runtime
from orchestrator.runtime_outcomes import UncertainOperation
from orchestrator.step_runner import execute
from tests import test_mixed_execution as mixed
from tests import test_media_pipeline as media
from tests.test_gemini import PNG, result
from tests.test_orchestrator import plan


class TransportTests(unittest.TestCase):
    def test_invalid_preparation_never_enters_transport(self):
        cases = [
            ('models/test:generateContent', {}, {'timeout': 600}),
            ('models/test:generateContent', {}, {'timeout': True}),
            ('models/test:generateContent', {}, {'max_response_bytes': 0}),
            ('../secret', {}, {}),
            (None, {}, {}),
            ('models/test:generateContent', {'secret': object()}, {}),
        ]
        for path, payload, bounds in cases:
            with self.subTest(path=path, bounds=bounds):
                client = gemini.Client('private-key')
                client.opener = MagicMock()
                with self.assertRaises(gemini.LocalRequestError) as caught:
                    client.request(path, payload, **bounds)
                self.assertFalse(caught.exception.uncertain)
                self.assertNotIn('private-key', str(caught.exception))
                self.assertNotIn('secret', str(caught.exception))
                client.opener.open.assert_not_called()


class ImageLifecycleTests(unittest.TestCase):
    setUp = mixed.Tests.setUp
    tearDown = mixed.Tests.tearDown
    input = mixed.Tests.input
    image_step = media.GraphTests.image_step

    def real_client(self, *, response=None, error=None):
        client = gemini.Client('fixture')
        client.opener = MagicMock()
        if error:
            client.opener.open.side_effect = error
        else:
            response = response or result([{'inlineData': {
                'mimeType': 'image/png', 'data': base64.b64encode(PNG).decode()}}])
            client.opener.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        self.ops.client = client
        return client

    def run_image(self, seconds=600):
        item = self.image_step()
        item['limits'] = {'seconds': seconds}
        self.rt.create(plan([item]))
        self.rt.tick('demo')
        aid = self.rt.task('demo', 'photo')['latest']
        session = json.loads(self.rt.db.execute(
            'SELECT session FROM production_attempts WHERE id=?', (aid,)).fetchone()[0])
        control = Path(session['control'])
        launch = json.loads((control/'launch.json').read_text())
        frozen = json.loads((Path(launch['workspace'])/'.relay/ASSIGNMENT.json').read_text())
        self.rt.tick('demo')
        return control, frozen

    def restart(self):
        self.rt.close()
        self.rt = Runtime(self.root/'runtime', self.factory)
        for _ in range(3):
            self.rt.tick('demo')

    def test_real_image_transport_and_collection_respect_both_time_limits(self):
        client = self.real_client()
        control, frozen = self.run_image()
        self.assertEqual(frozen['limits']['seconds'], 600)
        self.assertEqual(client.opener.open.call_args.kwargs['timeout'], 120)
        self.assertEqual(self.rt.status('demo')['status'], 'awaiting_user')
        output = self.rt.output('demo', 'photo', 'tower-photo.png')
        self.assertTrue(Path(output['blob']).read_bytes().startswith(b'\x89PNG'))
        self.restart()
        client.opener.open.assert_called_once()
        self.assertEqual(self.rt.output('demo', 'photo', 'tower-photo.png')['sha256'], output['sha256'])
        with self.assertRaisesRegex(ValueError, 'Cannot replay'):
            execute(frozen, control, lambda _: client, lambda: {'api_key': 'fixture'})
        client.opener.open.assert_called_once()

    def test_smaller_task_deadline_is_not_expanded(self):
        client = self.real_client()
        self.run_image(60)
        self.assertEqual(client.opener.open.call_args.kwargs['timeout'], 60)
        self.assertEqual(self.rt.status('demo')['status'], 'awaiting_user')

    def test_real_local_validation_receipt_is_no_effect_and_survives_restart(self):
        client = self.real_client()
        request = client.request
        # Reproduce the old adapter/client disagreement at the real validator.
        client.request = lambda path, payload, **bounds: request(path, payload, **dict(bounds, timeout=600))
        control, frozen = self.run_image()
        receipt = json.loads((control/'operation.json').read_text())
        self.assertEqual((receipt['outcome'], receipt['effect'], receipt['submission']),
                         ('rejected', 'none', 'not_started'))
        self.assertTrue((control/'request.json').exists())
        self.assertFalse((control/'response.json').exists())
        self.assertEqual(operation_lifecycle.terminal(frozen, control)['effect'], 'none')
        self.assertEqual(self.rt.status('demo')['status'], 'blocked')
        attempt = self.rt.status('demo')['attempts'][-1]
        self.assertEqual(json.loads(attempt['receipt'])['external_outcome'], 'not_submitted')
        before = (control/'operation.json').read_bytes()
        self.restart()
        client.opener.open.assert_not_called()
        self.assertEqual((control/'operation.json').read_bytes(), before)
        self.assertEqual(self.rt.status('demo')['status'], 'blocked')

    def test_post_submission_errors_stay_uncertain_without_retry(self):
        client = self.real_client(error=TimeoutError('secret transport detail'))
        control, frozen = self.run_image()
        self.assertEqual(self.rt.status('demo')['status'], 'uncertain')
        with self.assertRaises(UncertainOperation):
            operation_lifecycle.terminal(frozen, control)
        self.restart()
        client.opener.open.assert_called_once()
        self.assertEqual(self.rt.status('demo')['status'], 'uncertain')
        self.assertNotIn('secret', (control/'operation.json').read_text())
        receipt=json.loads((control/'operation.json').read_text())
        self.assertEqual(receipt['failure_kind'],'timeout')
        self.assertEqual(receipt['exception_type'],'TimeoutError')
        from orchestrator.runtime import failure_detail
        attempt=self.rt.db.execute('SELECT * FROM production_attempts WHERE id=?',
            (self.rt.task('demo','photo')['latest'],)).fetchone()
        detail=failure_detail(self.rt.db,attempt)
        self.assertIn('Request timed out',detail)
        self.assertIn('No automatic retry',detail)

    def test_connection_diagnostic_retains_category_not_secret_exception(self):
        import urllib.error
        client=self.real_client(error=urllib.error.URLError('https://secret.invalid/?key=fixture'))
        control,_=self.run_image()
        receipt=json.loads((control/'operation.json').read_text())
        self.assertEqual(receipt['failure_kind'],'connection')
        self.assertEqual(receipt['exception_type'],'URLError')
        self.assertNotIn('secret',json.dumps(receipt))
        self.assertNotIn('fixture',json.dumps(receipt))
        self.restart()
        client.opener.open.assert_called_once()

    def test_invalid_response_retains_category_without_body(self):
        client=self.real_client()
        client.opener.open.return_value.__enter__.return_value=io.BytesIO(b'not-json-secret')
        control,_=self.run_image()
        receipt=json.loads((control/'operation.json').read_text())
        self.assertEqual(receipt['failure_kind'],'invalid-response')
        self.assertEqual(receipt['exception_type'],'JSONDecodeError')
        self.assertNotIn('secret',json.dumps(receipt))
        self.restart()
        client.opener.open.assert_called_once()

    def test_old_uncertain_receipt_is_not_reclassified(self):
        client = self.real_client(error=TimeoutError())
        control, frozen = self.run_image()
        # Historical intent + generic local error is not the new typed proof.
        original = json.dumps({'outcome': 'uncertain', 'effect': 'uncertain',
                               'reason': 'Invalid bounded Gemini transport limits', 'usage': None})
        (control/'operation.json').write_text(original)
        with self.assertRaises(UncertainOperation):
            operation_lifecycle.terminal(frozen, control)
        self.restart()
        self.assertEqual((control/'operation.json').read_text(), original)
        self.assertEqual(self.rt.status('demo')['status'], 'uncertain')
        client.opener.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
