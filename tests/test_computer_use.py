"""Controlled O15.1 identity/publication failures; no desktop or model calls."""
import base64
import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from task_relay import computer_contract as contract
from task_relay import computer_use
from task_relay.host import UnsupportedHost
from task_relay.host_computer import Observer, require_host


TARGET = {'pid': 100, 'window_id': 42, 'launch_id': '1234.000001'}


def png():
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0\xff\xff\xff')) + chunk(b'IEND', b''))


class Helper:
    identity = {'protocol': contract.PROTOCOL, 'binary_sha256': 'fixture-helper'}

    def __init__(self, mutate=None, fail=False):
        self.calls = 0
        self.mutate = mutate
        self.fail = fail

    def call(self, request):
        self.calls += 1
        if self.fail:
            raise TimeoutError('fixture transport interruption')
        result = {'protocol': contract.PROTOCOL, 'ok': True, 'target': copy.deepcopy(TARGET),
                  'url': request['expected_url'], 'captured_at': '2026-09-28T12:00:00Z',
                  'text': 'Synthetic supplier catalog issue.', 'truncated': False,
                  'coverage': ['visible_accessibility_static_text_only'], 'document_stable': True}
        if request['capture']:
            result['png_base64'] = base64.b64encode(png()).decode()
        if self.mutate:
            self.mutate(result)
        return result


class ComputerObservationTests(unittest.TestCase):
    def frozen(self, capture=False):
        return contract.request(TARGET, 'https://example.com/profile', 'Inspect this selected fixture.', capture)

    def test_exact_request_and_evidence_are_preserved_and_no_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder).resolve() / 'observation'
            helper = Helper()
            frozen = self.frozen(True)
            result = computer_use.observe(helper, frozen, out)
            self.assertEqual((out / 'viewport.png').read_bytes(), png())
            self.assertEqual(json.loads((out / 'intent.json').read_text())['request'], frozen)
            self.assertEqual(result['review_status'], 'unreviewed')
            self.assertFalse(result['job_registered'])
            self.assertTrue((out / 'completed.json').is_file())
            with self.assertRaises(ValueError):
                computer_use.observe(helper, frozen, out)
            self.assertEqual(helper.calls, 1)

    def test_changed_window_process_or_url_cannot_publish(self):
        for mutate in (lambda r: r['target'].update(window_id=43),
                       lambda r: r['target'].update(launch_id='reused-pid'),
                       lambda r: r.update(url='https://other.example/private'),
                       lambda r: r.update(document_stable=False)):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as folder:
                out = Path(folder).resolve() / 'observation'
                with self.assertRaises(ValueError):
                    computer_use.observe(Helper(mutate), self.frozen(True), out)
                self.assertTrue((out / 'uncertain.json').exists())
                self.assertFalse((out / 'page.txt').exists())
                self.assertFalse((out / 'viewport.png').exists())
                self.assertFalse((out / 'completed.json').exists())

    def test_timeout_retains_intent_and_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder).resolve() / 'observation'
            helper = Helper(fail=True)
            with self.assertRaises(TimeoutError):
                computer_use.observe(helper, self.frozen(), out)
            with self.assertRaises(ValueError):
                computer_use.observe(helper, self.frozen(), out)
            self.assertEqual(helper.calls, 1)
            self.assertEqual(json.loads((out / 'uncertain.json').read_text())['replay'], 'prohibited')

    def test_failed_publication_never_recaptures(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder).resolve() / 'observation'
            helper = Helper()
            real_write = computer_use.write_new
            def write(path, value):
                if path.name == 'evidence.json':
                    raise OSError('fixture full disk')
                return real_write(path, value)
            with patch.object(computer_use, 'write_new', write), self.assertRaises(OSError):
                computer_use.observe(helper, self.frozen(), out)
            self.assertTrue((out / 'page.txt').exists())
            self.assertFalse((out / 'completed.json').exists())
            with self.assertRaises(ValueError):
                computer_use.observe(helper, self.frozen(), out)
            self.assertEqual(helper.calls, 1)

    def test_native_abort_discards_output_and_preserves_no_replay_receipt(self):
        # A native framework can abort after reading/capturing. Even plausible
        # stdout must not become evidence, and stderr may contain private data.
        helper = Observer.__new__(Observer)
        helper.binary = Path('/fixture/ComputerObserver')
        helper.identity = Helper.identity
        frozen = self.frozen(True)
        result = subprocess.CompletedProcess([], -6,
            stdout=json.dumps(Helper().call(frozen)).encode(), stderr=b'private-native-diagnostic')
        with tempfile.TemporaryDirectory() as folder, patch(
                'task_relay.host_computer.subprocess.run', return_value=result) as native:
            out = Path(folder).resolve() / 'observation'
            with self.assertRaises(ValueError) as raised:
                computer_use.observe(helper, frozen, out)
            self.assertNotIn('private-native-diagnostic', str(raised.exception))
            self.assertEqual({p.name for p in out.iterdir()}, {'intent.json', 'uncertain.json'})
            with self.assertRaises(ValueError):
                computer_use.observe(helper, frozen, out)
            self.assertEqual(native.call_count, 1)

    def test_empty_oversized_or_ungranted_evidence_is_rejected(self):
        for mutate in (lambda r: r.update(text=''), lambda r: r.update(text='\u00e9' * 12001),
                       lambda r: r.update(png_base64=base64.b64encode(png()).decode()),
                       lambda r: r.update(captured_at='yesterday'),
                       lambda r: r.update(protocol='other')):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                contract.validate_response(Helper(mutate).call(self.frozen()), self.frozen())

    def test_capture_bytes_are_checked(self):
        with self.assertRaises(ValueError):
            contract.validate_response(Helper(lambda r: r.update(png_base64=base64.b64encode(b'not an image').decode())).call(self.frozen(True)), self.frozen(True))

    def test_only_explicit_loopback_fixture_can_use_http(self):
        for value in ('http://example.com/', 'https://user:secret@example.com/', 'file:///tmp/test',
                      'https://example.com/#unknown', 'https://example.com/\n'):
            with self.subTest(url=value), self.assertRaises(ValueError):
                contract.url(value, fixture=True)
        with self.assertRaises(ValueError):
            contract.url('http://127.0.0.1:9999/')
        self.assertEqual(contract.url('http://127.0.0.1:9999/', fixture=True), 'http://127.0.0.1:9999/')

    def test_output_link_cannot_redirect_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'real').mkdir(); (root / 'alias').symlink_to(root / 'real')
            helper = Helper()
            with self.assertRaises(ValueError):
                computer_use.observe(helper, self.frozen(), root / 'alias' / 'observation')
            self.assertEqual(helper.calls, 0)
            self.assertEqual(list((root / 'real').iterdir()), [])

    def test_unsupported_host_fails_before_native_calls(self):
        with patch('task_relay.host_computer.sys.platform', 'linux'), self.assertRaises(UnsupportedHost):
            require_host()

    def test_permission_blocker_is_not_an_observation(self):
        result = {'protocol': contract.PROTOCOL, 'ok': False, 'error': 'accessibility_permission_required'}
        with self.assertRaisesRegex(ValueError, 'accessibility_permission_required'):
            contract.validate_response(result, self.frozen())


if __name__ == '__main__':
    unittest.main()
