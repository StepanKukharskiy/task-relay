import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bridge import Bridge, BridgeError, Desktop, OwnerUnavailable, State, Watcher, complete_offset
from bridge import Telegram, TelegramError, BackgroundWorkers, SendPacer, receive_updates, split_text
from media import image_links, queue_images, attachment_links


class TelegramFake:
    def __init__(self):
        self.sent = []
        self.media = []
        self.entities = []
        self.keyboards = []
        self.calls = []

    def send(self, chat_id, text, entities=None, reply_markup=None):
        self.sent.append((chat_id, text))
        self.entities.append(entities or [])
        self.keyboards.append(reply_markup)
        return {'message_id': len(self.sent)}

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        return True

    def send_media(self, chat_id, path, filename, kind, caption):
        self.media.append((kind, Path(path).read_bytes()))
        return self.send(chat_id, caption)


class DesktopFake:
    starts = []
    fail = False
    ready_owner = Desktop.ready_owner

    def open_task(self, thread_id):
        raise AssertionError('Unexpected desktop navigation')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def owner(self, thread_id):
        return 'owner'

    def start(self, thread_id, text, owner):
        self.starts.append((thread_id, text))
        if self.fail:
            raise TimeoutError()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state.sqlite')
        self.telegram = TelegramFake()
        self.config = {'pair_code': 'secret-pair', 'pair_expires': time.time() + 3600}
        self.bridge = Bridge(self.state, self.telegram, self.config, DesktopFake)
        DesktopFake.starts, DesktopFake.fail = [], False
        self.log = self.root / 'rollout.jsonl'
        self.log.write_text('')
        self.codex = self.root / 'codex'
        self.codex.mkdir()
        conn = sqlite3.connect(self.codex / 'state_5.sqlite')
        conn.execute('CREATE TABLE threads (id, rollout_path, title, name, source, agent_role, updated_at, archived, cwd)')
        conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)',
                     ('task-one', str(self.log), 'Task One', None, 'vscode', None, 100, 0, str(self.root)))
        conn.commit()
        conn.close()
        self.watcher = Watcher(self.state, self.codex)

    def tearDown(self):
        self.state.db.close()
        self.temp.cleanup()

    def event(self, kind, turn_id='turn-one', **extra):
        return json.dumps({'type': 'event_msg', 'payload': {'type': kind, 'turn_id': turn_id, **extra}}) + '\n'

    def append(self, text):
        with self.log.open('a') as stream:
            stream.write(text)

    def message(self, text, id=1, user=123, reply=None, private=True):
        m = {'text': text, 'chat': {'id': user, 'type': 'private' if private else 'group'},
             'from': {'id': user}}
        if reply is not None:
            m['reply_to_message'] = {'message_id': reply}
        return {'update_id': id, 'message': m}

    def pair(self):
        self.bridge.process(self.message('/start secret-pair', id=100))

    def ready(self):
        self.watcher.scan()
        self.append(self.event('task_complete', last_agent_message='All done'))
        self.watcher.scan()
        self.pair()
        self.bridge.flush()
        return len(self.telegram.sent)

    def test_pairing_requires_private_chat_and_secret(self):
        self.bridge.process(self.message('/start wrong'))
        self.bridge.process(self.message('/start secret-pair', private=False))
        self.assertIsNone(self.state.get('user_id'))
        self.pair()
        self.assertEqual(self.state.get('user_id'), 123)
        self.bridge.process(self.message('/start secret-pair', user=456))
        self.assertEqual(self.state.get('user_id'), 123)

    def test_pairing_expires(self):
        self.config['pair_expires'] = 0
        self.pair()
        self.assertIsNone(self.state.get('user_id'))

    def test_no_historical_spam_and_persistent_deduplication(self):
        self.append(self.event('task_complete', turn_id='old', last_agent_message='Old result'))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)
        self.append(self.event('task_complete', last_agent_message='New result'))
        self.watcher.scan()
        Watcher(self.state, self.codex).scan()
        self.append(self.event('task_complete', last_agent_message='New result'))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_partial_line_survives_baseline_and_restart(self):
        line = self.event('task_complete')
        self.append(line[:40])
        self.assertEqual(complete_offset(self.log), 0)
        self.watcher.scan()
        self.append(line[40:])
        Watcher(self.state, self.codex).scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def dated_event(self, turn_id, timestamp, summary='Result'):
        event = json.loads(self.event('task_complete', turn_id=turn_id, last_agent_message=summary))
        event['timestamp'] = timestamp
        return json.dumps(event) + '\n'

    def test_rewritten_larger_history_does_not_replay_old_results(self):
        old = self.dated_event('old', '2026-06-17T09:40:41Z', 'Old result')
        self.append(old)
        with patch('bridge.time.time', return_value=1788879000):
            self.watcher.scan()
        # Same path, larger file; the old byte offset is now inside a JSON line.
        self.log.write_text(json.dumps({'type': 'session_meta', 'padding': 'x' * 500}) + '\n' + old)
        self.append(self.dated_event('new', '2026-09-08T15:00:00Z', 'Fresh result'))
        Watcher(self.state, self.codex).scan()
        rows = self.state.db.execute('SELECT id,text FROM outbox').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn(':new:', rows[0]['id'])
        self.assertIn('Fresh result', rows[0]['text'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)
        Watcher(self.state, self.codex).scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_legacy_midline_cursor_filters_historical_completion(self):
        self.log.write_text(json.dumps({'type': 'session_meta', 'padding': 'x' * 500}) + '\n' +
                            self.dated_event('old', '2026-06-17T09:40:41Z'))
        with self.state.db:
            self.state.put('baselined', True)
            self.state.put('health:scan', {'last_success': 1788879000})
            self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                                  ('task-one', str(self.log), 100, 'Task One', 'idle', 100))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute('SELECT offset FROM watched').fetchone()[0], self.log.stat().st_size)

    def test_late_discovered_task_skips_history_but_keeps_fresh_result(self):
        with patch('bridge.time.time', return_value=1788879000):
            self.watcher.scan()
        path = self.root / 'late.jsonl'
        path.write_text(self.dated_event('old', '2026-06-17T09:40:41Z') +
                        self.dated_event('new', '2026-09-08T15:00:00Z'))
        conn = sqlite3.connect(self.codex / 'state_5.sqlite')
        try:
            conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)',
                         ('late', str(path), 'Late task', None, 'vscode', None, 100, 0, str(self.root)))
            conn.commit()
        finally:
            conn.close()
        self.watcher.scan()
        self.assertEqual([r[0] for r in self.state.db.execute('SELECT id FROM outbox')], ['late:new:task_complete'])

    def test_offline_completion_survives_upgrade_and_restart(self):
        with self.state.db:
            self.state.put('baselined', True)
            self.state.put('health:scan', {'last_success': 1788879000})
            self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                                  ('task-one', str(self.log), 0, 'Task One', 'running', 100))
        self.append(self.dated_event('offline', '2026-09-08T15:00:00Z'))
        with patch('bridge.time.time', return_value=1788900000):
            self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        Watcher(self.state, self.codex).scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_reply_routing_and_duplicate_update(self):
        reply = self.ready()
        update = self.message('Next step', reply=reply)
        self.bridge.process(update)
        self.bridge.process(update)
        self.assertEqual(DesktopFake.starts, [('task-one', 'Next step')])

    def test_unknown_reply_does_not_fall_back_to_selected(self):
        self.ready()
        with self.state.db:
            self.state.put('selected', 'task-one')
        self.bridge.process(self.message('Next step', reply=999))
        self.assertEqual(DesktopFake.starts, [])

    def test_other_user_cannot_start_task(self):
        reply = self.ready()
        self.bridge.process(self.message('Next step', user=456, reply=reply))
        self.assertEqual(DesktopFake.starts, [])

    def test_two_rapid_replies_do_not_start_concurrent_turns(self):
        reply = self.ready()
        self.bridge.process(self.message('Next step', id=1, reply=reply))
        self.bridge.process(self.message('One more', id=2, reply=reply))
        self.assertEqual(len(DesktopFake.starts), 1)

    def document_message(self, reply, name='message.txt', caption='', size=100, id=1, user=123):
        update = self.message('', id=id, user=user, reply=reply)
        update['message']['document'] = {'file_id': 'file-one', 'file_name': name, 'file_size': size}
        update['message']['caption'] = caption
        return update

    def test_long_text_file_is_one_exact_codex_instruction(self):
        reply = self.ready()
        text = '/allow fake-id\n' + ('Text **with Markdown** &amp; 🚀\n' * 400) + '\nEND\n'
        paths = []
        def download(file_id, path, limit):
            paths.append(path)
            self.assertEqual(limit, 100_000)
            path.write_bytes(text.encode())
        self.telegram.download_file = download
        update = self.document_message(reply, caption='Review these comments')
        self.bridge.process(update)
        self.bridge.process(update)
        self.assertEqual(DesktopFake.starts, [('task-one', 'Review these comments\n\n' + text)])
        self.assertFalse(paths[0].exists())

    def test_text_file_rejects_other_users_and_unknown_replies_before_download(self):
        reply = self.ready()
        with self.state.db:
            self.state.put('selected', 'task-one')
        with patch.object(self.telegram, 'download_file', create=True) as download:
            self.bridge.process(self.document_message(reply, user=456))
            self.bridge.process(self.document_message(999))
            download.assert_not_called()
        self.assertFalse(DesktopFake.starts)

    def test_text_file_rejects_unsupported_oversize_binary_and_invalid_encoding(self):
        reply = self.ready()
        with patch.object(self.telegram, 'download_file', create=True) as download:
            self.bridge.process(self.document_message(reply, name='report.pdf'))
            self.bridge.process(self.document_message(reply, size=100_001))
            download.assert_not_called()
        for content in (b'\xff\xfe', b'abc\x00def', b'   ', b'x' * 100_001):
            self.telegram.download_file = lambda fid, path, limit: path.write_bytes(content)
            self.bridge.process(self.document_message(reply))
        self.assertFalse(DesktopFake.starts)

    def test_text_file_rechecks_busy_state_after_download(self):
        reply = self.ready()
        def download(fid, path, limit):
            path.write_text('Next step')
            self.append(self.event('task_started'))
        self.telegram.download_file = download
        self.bridge.process(self.document_message(reply))
        self.assertFalse(DesktopFake.starts)

    def test_text_file_uses_safe_path_and_supports_utf8_bom(self):
        reply = self.ready()
        def download(fid, path, limit):
            self.assertEqual(path.name, 'input.txt')
            path.write_bytes(b'\xef\xbb\xbfWhole prompt\n')
        self.telegram.download_file = download
        self.bridge.process(self.document_message(reply, name='../../escape.md'))
        self.assertEqual(DesktopFake.starts, [('task-one', 'Whole prompt\n')])

    def test_text_file_uncertain_submission_is_not_replayed(self):
        reply = self.ready()
        self.telegram.download_file = lambda fid, path, limit: path.write_text('Full instruction')
        DesktopFake.fail = True
        update = self.document_message(reply)
        self.bridge.process(update)
        self.bridge.process(update)
        self.assertEqual(len(DesktopFake.starts), 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=1').fetchone()[0], 'uncertain')

    def test_download_file_validates_and_fetches_a_telegram_file(self):
        from unittest.mock import MagicMock
        telegram = Telegram('fake')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'full text'
        opener = MagicMock()
        opener.open.return_value = response
        path = self.root / 'download.txt'
        with patch.object(telegram, 'call', return_value={'file_path': 'documents/file_1.txt', 'file_size': 9}), \
                patch('bridge.urllib.request.build_opener', return_value=opener):
            telegram.download_file('file-one', path, 100_000)
        self.assertEqual(path.read_bytes(), b'full text')

    def test_uncertain_submission_is_never_automatically_retried(self):
        reply = self.ready()
        DesktopFake.fail = True
        update = self.message('Next step', reply=reply)
        self.bridge.process(update)
        self.bridge.process(update)
        self.assertEqual(len(DesktopFake.starts), 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=1').fetchone()[0], 'uncertain')

    def test_unloaded_task_opens_then_submits_once(self):
        reply = self.ready()
        update = self.message('Next step', reply=reply)
        with patch.object(DesktopFake, 'owner', side_effect=[OwnerUnavailable(), 'owner']), \
                patch.object(DesktopFake, 'open_task') as opened, patch('bridge.time.sleep'):
            self.bridge.process(update)
            self.bridge.process(update)
        opened.assert_called_once_with('task-one')
        self.assertEqual(DesktopFake.starts, [('task-one', 'Next step')])
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=1').fetchone()[0], 'submitted')

    def test_task_loading_failure_is_bounded_and_never_submits(self):
        reply = self.ready()
        with patch.object(DesktopFake, 'owner', side_effect=OwnerUnavailable()) as owner, \
                patch.object(DesktopFake, 'open_task') as opened, patch('bridge.time.sleep'):
            self.bridge.process(self.message('Next step', reply=reply))
        self.assertEqual(owner.call_count, 3)
        opened.assert_called_once()
        self.assertEqual(DesktopFake.starts, [])
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=1').fetchone()[0], 'failed')
        self.assertIn('not sent', self.telegram.sent[-1][1])

    def test_general_connection_error_does_not_open_task(self):
        reply = self.ready()
        with patch.object(DesktopFake, 'owner', side_effect=BridgeError()), \
                patch.object(DesktopFake, 'open_task') as opened:
            self.bridge.process(self.message('Next step', reply=reply))
        opened.assert_not_called()
        self.assertEqual(DesktopFake.starts, [])

    def test_open_failure_never_submits(self):
        reply = self.ready()
        with patch.object(DesktopFake, 'owner', side_effect=OwnerUnavailable()) as owner, \
                patch.object(DesktopFake, 'open_task', side_effect=BridgeError()):
            self.bridge.process(self.message('Next step', reply=reply))
        self.assertEqual(owner.call_count, 1)
        self.assertEqual(DesktopFake.starts, [])

    def test_task_becoming_busy_during_loading_is_not_sent(self):
        reply = self.ready()
        with patch.object(DesktopFake, 'owner', side_effect=[OwnerUnavailable(), 'owner']), \
                patch.object(DesktopFake, 'open_task', side_effect=lambda _: self.append(self.event('task_started'))), \
                patch('bridge.time.sleep'):
            self.bridge.process(self.message('Next step', reply=reply))
        self.assertEqual(DesktopFake.starts, [])
        self.assertIn('started running', self.telegram.sent[-1][1])

    def test_uncertain_start_after_loading_is_not_retried(self):
        reply = self.ready()
        DesktopFake.fail = True
        update = self.message('Next step', reply=reply)
        with patch.object(DesktopFake, 'owner', side_effect=[OwnerUnavailable(), 'owner']), \
                patch.object(DesktopFake, 'open_task') as opened, patch('bridge.time.sleep'):
            self.bridge.process(update)
            self.bridge.process(update)
        opened.assert_called_once()
        self.assertEqual(len(DesktopFake.starts), 1)
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=1').fetchone()[0], 'uncertain')

    def test_task_link_has_only_a_valid_uuid_and_no_shell(self):
        desktop = Desktop()
        task = '11111111-1111-4111-8111-111111111111'
        with patch('bridge.Path.is_dir', return_value=True), patch('bridge.subprocess.run') as run:
            run.return_value.returncode = 0
            desktop.open_task(task)
            run.assert_called_once_with(['/usr/bin/open', '-g', '-a', '/Applications/ChatGPT.app',
                                         'codex://threads/' + task], capture_output=True, timeout=5)
            run.reset_mock()
            with self.assertRaises(BridgeError):
                desktop.open_task(task + '?prompt=run+this')
            run.assert_not_called()

    def test_outbox_retries_after_network_error(self):
        self.watcher.scan()
        self.append(self.event('task_complete'))
        self.watcher.scan()
        self.pair()
        with patch.object(self.telegram, 'send', side_effect=OSError()):
            with self.assertRaises(OSError):
                self.bridge.flush()
        self.bridge.flush()
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 1)

    def test_ipc_handles_fragmented_frames(self):
        left, right = socket.socketpair()
        desktop = Desktop()
        desktop.sock = left
        packet = json.dumps({'type': 'test', 'text': 'hello'}).encode()
        raw = struct.pack('<I', len(packet)) + packet
        def sender():
            for b in raw:
                right.sendall(bytes([b]))
            right.close()
        thread = threading.Thread(target=sender)
        thread.start()
        self.assertEqual(desktop.receive()['text'], 'hello')
        thread.join()
        left.close()

    def test_desktop_start_accepts_main_process_success_envelope(self):
        desktop = Desktop()
        reply = {'type': 'response', 'resultType': 'success',
                 'method': 'thread-follower-start-turn',
                 'result': {'result': {'turn': {'id': 'new-turn', 'status': 'inProgress'}}}}
        with patch.object(desktop, 'request', return_value=reply):
            self.assertEqual(desktop.start('task-one', 'Next step', 'owner'), reply['result'])

    def test_desktop_start_rejects_wrong_response_method(self):
        desktop = Desktop()
        from bridge import BridgeError
        with patch.object(desktop, 'request', return_value={'method': 'unexpected', 'result': {}}):
            with self.assertRaises(BridgeError):
                desktop.start('task-one', 'Next step', 'owner')

    def make_image(self, name='floor plan (1).png'):
        path = self.root / name
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'test image data')
        return path

    def ready_image(self):
        path = self.make_image()
        self.watcher.scan()
        self.append(self.event('task_complete', last_agent_message=f'Floor plan: ![plan](<{path}>)'))
        self.watcher.scan()
        self.pair()
        return path

    def test_image_links_spaces_parentheses_duplicates_and_remote(self):
        path = self.make_image()
        text = f'![one](<{path}>) [two]({path}) [remote](https://example.com/plan.png)'
        self.assertEqual(list(image_links(text, self.root)), [path.resolve()])
        self.assertEqual(list(image_links('[relative](floor%20plan%20(1).png)', self.root)), [path.resolve()])

    def test_codex_visualization_links_are_allowed_only_for_the_source_task(self):
        home = Path('/Users/task-relay-fixture')
        tid = '22222222-2222-4222-8222-222222222222'
        path = home / '.codex/visualizations/2026/09/07' / tid / 'floor/nine options.png'
        text = f'![Nine options](<{path}>)'
        with patch('media.Path.home', return_value=home):
            self.assertEqual(list(attachment_links(text, thread_id=tid)), [path])
            self.assertEqual(list(image_links(text, thread_id=tid)), [path])
            self.assertEqual(list(attachment_links(text)), [])
            self.assertEqual(list(attachment_links(text, thread_id='other-task')), [])
            outside = home / '.codex/auth.json'
            self.assertEqual(list(attachment_links(f'[file]({outside})', thread_id=tid)), [])
            escaped = path.parent / '../../other-task/plan.png'
            self.assertEqual(list(attachment_links(f'[file]({escaped})', thread_id=tid)), [])

    def test_attachment_queue_supplies_source_task_for_visualization_discovery(self):
        path = self.make_image()
        with patch('media.attachment_links', wraps=attachment_links) as discover:
            with self.state.db:
                queue_images(self.state, 'visualization-event', 'source-task', 'Floor', f'![floor]({path})', self.root)
        self.assertEqual(discover.call_args.args[2], 'source-task')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 2)

    def test_attachment_discovery_uses_full_untruncated_response(self):
        path = self.make_image()
        self.watcher.scan()
        self.append(self.event('task_complete', last_agent_message='x' * 4000 + f' [plan](<{path}>)'))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 2)

    def test_long_codex_response_is_lossless_and_every_part_routes(self):
        self.watcher.scan()
        summary = ('A paragraph with emoji 🚀 and Cyrillic: привет.\n\n' * 230) + 'THE END'
        self.append(self.event('task_complete', last_agent_message=summary))
        self.watcher.scan()
        row = self.state.db.execute('SELECT * FROM outbox').fetchone()
        self.assertIn(summary, row['text'])
        self.pair()
        self.telegram.sent.clear()
        self.bridge.flush()
        self.assertGreater(len(self.telegram.sent), 2)
        reconstructed = []
        for index, (_, text) in enumerate(self.telegram.sent, 1):
            self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
            self.assertIn(f'Part {index}/{len(self.telegram.sent)}\n\n', text)
            reconstructed.append(text.split('\n\n', 1)[1])
            mapped = self.state.db.execute('SELECT thread_id FROM messages WHERE message_id=?', (index,)).fetchone()[0]
            self.assertEqual(mapped, 'task-one')
        self.assertEqual(''.join(reconstructed), row['text'])
        self.assertIn('THE END', self.telegram.sent[-1][1])

    def test_split_text_preserves_unicode_unbroken_words_and_boundaries(self):
        for text in ('🚀' * 5000, 'x' * 12000, 'hello\n\n' * 2000, 'a' * 3790 + '\n\n' + 'b' * 40):
            chunks = split_text(text)
            self.assertEqual(''.join(chunks), text)
            self.assertTrue(all(0 < len(c.encode('utf-16-le')) // 2 <= 3800 for c in chunks))
        self.assertEqual(split_text('x' * 3800), ['x' * 3800])
        self.assertEqual(split_text('a' * 3790 + '\n\n' + 'b' * 1000)[0], 'a' * 3790 + '\n\n')

    def test_partial_delivery_restart_resumes_without_repeating_confirmed_parts(self):
        self.ready_files({'result.txt': b'original'})
        with self.state.db:
            self.state.db.execute('UPDATE outbox SET text=?', ('First. ' * 2000 + 'END',))
        original_send = self.telegram.send
        calls = 0
        def fail_second(chat_id, text):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TelegramError('sendMessage', 429, 1)
            return original_send(chat_id, text)
        self.telegram.send = fail_second
        with self.assertRaises(TelegramError):
            self.bridge.flush()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox_parts WHERE sent=1').fetchone()[0], 1)
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 0)
        self.assertEqual(self.telegram.media, [])
        self.telegram.send = original_send
        with self.state.db:
            self.state.set_emoji('task-one', '🏠')
        self.state.db.close()
        self.state = State(self.root / 'state.sqlite')
        self.bridge = Bridge(self.state, self.telegram, self.config, DesktopFake)
        self.bridge.flush()
        texts = [text for _, text in self.telegram.sent]
        self.assertEqual(sum('Part 1/' in text for text in texts), 1)
        self.assertEqual(sum('Part 2/' in text for text in texts), 1)
        self.assertTrue(any('END' in text for text in texts))
        self.assertEqual(self.telegram.media, [('original', b'original')])
        self.assertEqual(self.state.db.execute('SELECT sent FROM outbox').fetchone()[0], 1)

    def test_direct_long_message_routes_all_parts_and_short_text_stays_single(self):
        self.ready()
        self.telegram.sent.clear()
        self.bridge.send('Short message', 'task-one')
        self.assertEqual(len(self.telegram.sent), 1)
        self.assertNotIn('Part ', self.telegram.sent[0][1])
        self.bridge.send('🚀' * 6000, 'task-one')
        for mid in range(1, len(self.telegram.sent) + 1):
            self.assertEqual(self.state.db.execute('SELECT thread_id FROM messages WHERE message_id=?', (mid,)).fetchone()[0], 'task-one')

    def test_transport_rejects_oversized_text_instead_of_truncating(self):
        telegram = Telegram('fake')
        with patch.object(telegram, 'call') as call:
            with self.assertRaises(BridgeError):
                telegram.send(123, '🚀' * 2049)
            call.assert_not_called()
            text = 'x' * 4096
            telegram.send(123, text)
            self.assertEqual(call.call_args.kwargs['text'], text)

    def test_snapshot_survives_source_removal_and_reply_routes_to_task(self):
        path = self.ready_image()
        original = path.read_bytes()
        path.unlink()
        self.bridge.flush()
        self.assertEqual(self.telegram.media, [('preview', original), ('original', original)])
        image_message = len(self.telegram.sent)
        self.bridge.process(self.message('Adjust the layout', reply=image_message))
        self.assertEqual(DesktopFake.starts, [('task-one', 'Adjust the layout')])
        self.assertEqual(list(self.state.media_dir.iterdir()), [])

    def test_image_retry_does_not_repeat_successful_text_or_preview(self):
        self.ready_image()
        original_send = self.telegram.send_media
        def fail_original(chat, path, filename, kind, caption):
            if kind == 'original':
                raise OSError('temporary outage')
            return original_send(chat, path, filename, kind, caption)
        with patch.object(self.telegram, 'send_media', side_effect=fail_original):
            self.bridge.flush()
        self.assertEqual([x[0] for x in self.telegram.media], ['preview'])
        with self.state.db:
            self.state.db.execute('UPDATE media_outbox SET next_attempt=0')
        # Simulate a fresh bridge process using the same persistent state.
        Bridge(self.state, self.telegram, self.config, DesktopFake).flush()
        self.assertEqual([x[0] for x in self.telegram.media], ['preview', 'original'])
        self.assertEqual(sum('Finished:' in text for _, text in self.telegram.sent), 1)

    def test_preview_rejection_still_delivers_original(self):
        self.ready_image()
        original_send = self.telegram.send_media
        def reject_preview(chat, path, filename, kind, caption):
            if kind == 'preview':
                raise TelegramError('sendPhoto', 400)
            return original_send(chat, path, filename, kind, caption)
        with patch.object(self.telegram, 'send_media', side_effect=reject_preview):
            self.bridge.flush()
        self.assertEqual([x[0] for x in self.telegram.media], ['original'])

    def test_missing_or_nonimage_file_does_not_block_completion(self):
        path = self.root / 'not-an-image.png'
        path.write_text('private data is not an image')
        self.watcher.scan()
        self.append(self.event('task_complete', last_agent_message=f'[plan]({path})'))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)
        self.pair()
        self.bridge.flush()
        self.assertTrue(any('Finished:' in text for _, text in self.telegram.sent))

    def test_repeated_completion_does_not_requeue_images(self):
        self.ready_image()
        self.bridge.flush()
        self.append(self.event('task_complete', last_agent_message=f'[plan](<{self.root / "floor plan (1).png"}>)'))
        self.watcher.scan()
        self.bridge.flush()
        self.assertEqual(len(self.telegram.media), 2)

    def test_existing_database_upgrade_preserves_state(self):
        self.pair()
        with self.state.db:
            self.state.db.execute('DROP TABLE media_outbox')
        upgraded = State(self.root / 'state.sqlite')
        self.assertEqual(upgraded.get('user_id'), 123)
        self.assertEqual(upgraded.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)
        upgraded.db.close()

    def test_multipart_keeps_original_bytes_and_filename(self):
        path = self.make_image()
        telegram = Telegram('test-token')
        with patch.object(telegram, 'request', return_value={'message_id': 1}) as request:
            telegram.send_media(123, path, path.name, 'original', 'Original')
        args = request.call_args.args
        self.assertEqual(args[0], 'sendDocument')
        self.assertIn(path.read_bytes(), args[1])
        self.assertIn(b'filename="floor plan (1).png"', args[1])
        self.assertIn(b'name="disable_content_type_detection"\r\n\r\ntrue', args[1])

    def test_defaults_are_distinct_and_survive_restart(self):
        with self.state.db:
            markers = [self.state.emoji(f'task-{i}') for i in range(300)]
        self.assertEqual(len(set(markers)), 300)
        reloaded = State(self.root / 'state.sqlite')
        self.assertEqual(reloaded.emoji('task-9'), markers[9])
        reloaded.db.close()

    def test_custom_emoji_reply_applies_to_running_task_without_start(self):
        reply = self.ready()
        self.append(self.event('task_started', turn_id='next-turn'))
        self.watcher.scan()
        self.bridge.process(self.message('/emoji 🏠', reply=reply))
        self.assertEqual(self.state.emoji('task-one'), '🏠')
        self.assertTrue(self.telegram.sent[-1][1].startswith('🏠 Emoji set'))
        self.assertEqual(DesktopFake.starts, [])

    def test_emoji_selected_and_explicit_task_id(self):
        self.ready()
        self.bridge.process(self.message('/use task-one', id=1))
        self.bridge.process(self.message('/emoji 👩🏽‍💻', id=2))
        self.assertEqual(self.state.emoji('task-one'), '👩🏽‍💻')
        self.bridge.process(self.message('/emoji task-one 🇬🇧', id=3))
        self.assertEqual(self.state.emoji('task-one'), '🇬🇧')

    def test_emoji_unknown_reply_never_changes_selected_task(self):
        self.ready()
        with self.state.db:
            self.state.put('selected', 'task-one')
        before = self.state.emoji('task-one')
        self.bridge.process(self.message('/emoji 🏠', reply=999))
        self.assertEqual(self.state.emoji('task-one'), before)

    def test_emoji_rejects_text_and_unauthorized_sender(self):
        reply = self.ready()
        before = self.state.emoji('task-one')
        for i, text in enumerate(['/emoji house', '/emoji 🏠\nforged label', '/emoji \u200d']):
            self.bridge.process(self.message(text, id=i, reply=reply))
            self.assertEqual(self.state.emoji('task-one'), before)
        self.bridge.process(self.message('/emoji 🏠', id=10, reply=reply, user=456))
        self.assertEqual(self.state.emoji('task-one'), before)

    def test_custom_choice_displaces_default_but_not_custom_choice(self):
        from bridge import BridgeError
        with self.state.db:
            default = self.state.emoji('other-task')
            self.state.set_emoji('task-one', default)
        self.assertNotEqual(self.state.emoji('other-task'), default)
        self.assertEqual(self.state.emoji('task-one'), default)
        with self.assertRaises(BridgeError), self.state.db:
            self.state.set_emoji('another-task', default)

    def test_changed_emoji_labels_already_queued_text_and_images(self):
        self.ready_image()
        with self.state.db:
            self.state.set_emoji('task-one', '🏠')
        self.bridge.flush()
        # Pairing is global; completion, preview and original are task-specific.
        for _, text in self.telegram.sent[1:]:
            self.assertTrue(text.startswith('🏠 '), text)
        self.bridge.process(self.message('/tasks', id=11))
        self.assertTrue(self.telegram.sent[-1][1].startswith('🏠 '))

    def ready_files(self, files):
        self.watcher.scan()
        links = []
        for filename, contents in files.items():
            path = self.root / filename
            path.write_bytes(contents)
            links.append(f'[Download](<{path}>)')
        self.append(self.event('task_complete', last_agent_message='\n'.join(links)))
        self.watcher.scan()
        self.pair()

    def test_video_and_general_files_choose_correct_delivery(self):
        files = {'clip.mp4': b'\x00\x00\x00\x18ftypisom' + b'video fixture',
                 'layout.dxf': b'0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF',
                 'report.pdf': b'%PDF-1.4\nfixture', 'archive.zip': b'PK\x03\x04fixture',
                 'script.py': b'print("hello")\n', 'README': b'Extensionless text'}
        self.ready_files(files)
        self.bridge.flush()
        self.assertEqual([kind for kind, _ in self.telegram.media], ['video'] + ['original'] * 5)
        self.assertEqual([contents for _, contents in self.telegram.media], list(files.values()))
        self.bridge.process(self.message('Next step', reply=len(self.telegram.sent)))
        self.assertEqual(DesktopFake.starts, [('task-one', 'Next step')])

    def test_reply_to_inline_video_routes_to_task(self):
        self.ready_files({'clip.mp4': b'\x00\x00\x00\x18ftypisom' + b'fixture'})
        self.bridge.flush()
        self.bridge.process(self.message('Change the clip', reply=len(self.telegram.sent)))
        self.assertEqual(DesktopFake.starts, [('task-one', 'Change the clip')])

    def test_rejected_video_falls_back_to_original_without_losing_snapshot(self):
        self.ready_files({'clip.mp4': b'\x00\x00\x00\x18ftypisom' + b'fixture'})
        with patch.object(self.telegram, 'send_media', side_effect=TelegramError('sendVideo', 400)):
            self.bridge.flush()
        row = self.state.db.execute('SELECT kind,status,path FROM media_outbox').fetchone()
        self.assertEqual((row['kind'], row['status']), ('original', 'pending'))
        self.assertTrue(Path(row['path']).is_file())
        self.bridge.flush()
        self.assertEqual(self.telegram.media[0][0], 'original')
        self.assertFalse(Path(row['path']).exists())

    def test_non_mp4_video_sent_as_document(self):
        self.ready_files({'clip.mov': b'\x00\x00\x00\x18ftypqt  fixture', 'clip.webm': b'webm fixture'})
        self.bridge.flush()
        self.assertEqual([kind for kind, _ in self.telegram.media], ['original', 'original'])

    def test_video_multipart_uses_video_field_and_preserves_bytes(self):
        path = self.root / 'clip.mp4'
        path.write_bytes(b'\x00\x00\x00\x18ftypisomfixture')
        telegram = Telegram('test-token')
        with patch('bridge.video_metadata', return_value={'width': 1080, 'height': 1920, 'duration': 65}), patch.object(telegram, 'request', return_value={'message_id': 1}) as request:
            telegram.send_media(123, path, path.name, 'video', 'Clip')
        args = request.call_args.args
        self.assertEqual(args[0], 'sendVideo')
        self.assertIn(b'name="video"; filename="clip.mp4"', args[1])
        self.assertIn(b'Content-Type: video/mp4', args[1])
        self.assertIn(path.read_bytes(), args[1])

    def test_file_links_ignore_remote_and_resolve_code_line_references(self):
        path = self.root / 'solver.py'
        links = f'[code]({path}:117) [web](https://example.com/file.zip) [code again]({path})'
        self.assertEqual(list(attachment_links(links, self.root)), [path.resolve()])

    def test_file_links_reject_symlinks_outside_allowed_roots(self):
        path = self.root / 'linked.txt'
        path.symlink_to('/etc/hosts')
        self.assertEqual(list(attachment_links(f'[link]({path})', self.root)), [])

    def test_directory_links_are_not_attached(self):
        self.watcher.scan()
        self.append(self.event('task_complete', last_agent_message=f'[folder]({self.root})'))
        self.watcher.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0], 0)

    def test_oversized_file_does_not_block_small_file(self):
        with patch('media.MAX_FILE', 20):
            self.ready_files({'large.bin': b'x' * 21, 'small.txt': b'small'})
        self.bridge.flush()
        self.assertEqual(self.telegram.media, [('original', b'small')])
        self.assertTrue(any('Could not attach large.bin' in text for _, text in self.telegram.sent))

    def test_tasks_sends_twelve_replyable_cards_without_changing_selection(self):
        self.ready()
        self.bridge.flush()
        with self.state.db:
            for i in range(11):
                self.state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)',
                                      (f'extra-{i}', str(self.log), 0, f'Task {i}', 'idle', i))
        count = len(self.telegram.sent)
        self.bridge.process(self.message('/tasks', id=900))
        self.bridge.process(self.message('/tasks', id=900))
        self.bridge.flush()
        self.assertEqual(len(self.telegram.sent) - count, 12)
        for mid in range(count + 1, len(self.telegram.sent) + 1):
            tid = self.state.db.execute('SELECT thread_id FROM messages WHERE message_id=?', (mid,)).fetchone()[0]
            self.assertIn('Task: ' + tid, self.telegram.sent[mid-1][1])
            self.assertNotIn('/use ', self.telegram.sent[mid-1][1])
        self.assertIsNone(self.state.get('selected'))
        self.bridge.process(self.message('Continue this one', id=901, reply=len(self.telegram.sent)))
        self.assertEqual(DesktopFake.starts[-1][0], tid)

    def test_commands_respond_while_scan_and_upload_are_blocked(self):
        self.enterContext(patch('task_relay.releases.fetch', return_value=None))
        self.ready_image()
        self.bridge.flush(include_media=False)
        release = threading.Event()
        upload_started, scan_started = threading.Event(), threading.Event()
        class SlowTelegram(TelegramFake):
            def __init__(self, token, pacer):
                super().__init__()
            def send_media(self, *args):
                upload_started.set()
                release.wait(5)
                return super().send_media(*args)
        class SlowWatcher:
            def __init__(self, state):
                pass
            def scan(self):
                scan_started.set()
                release.wait(5)
        workers = BackgroundWorkers(self.root / 'state.sqlite', {'token': 'fake'}, SendPacer(),
                                    telegram_factory=SlowTelegram, watcher_factory=SlowWatcher)
        workers.start()
        try:
            self.assertTrue(upload_started.wait(2))
            self.assertTrue(scan_started.wait(2))
            with patch.object(self.telegram, 'call', create=True,
                              return_value=[self.message('/tasks', id=901)]):
                started = time.monotonic()
                receive_updates(self.bridge)
                duration = time.monotonic() - started
            self.assertLess(duration, 1.0)
            self.assertEqual(self.state.get('offset'), 902)
            self.assertIsNotNone(self.state.get('health:commands'))
            deadline = time.monotonic() + 2
            while (self.state.get('health:updates') is None or self.state.get('health:orchestrator-chat') is None) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNotNone(self.state.get('health:updates'))
            loaded = self.state.get('health:orchestrator-chat')
            self.assertEqual(loaded['process_id'], os.getpid())
            self.assertTrue({'rhino.startup','rhino.inspect','rhino.run_python','rhino.render'} <= set(loaded['registered_graph_operations']))
            self.assertFalse(release.is_set())
        finally:
            release.set()
            workers.close()
            for thread in workers.threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def test_notification_flush_can_skip_uploads(self):
        self.ready_image()
        with patch.object(self.bridge, 'flush_media') as media:
            self.bridge.flush(include_media=False)
            media.assert_not_called()
        self.assertTrue(any('Finished:' in text for _, text in self.telegram.sent))

    def test_send_pacer_waits_without_holding_lock_during_http(self):
        pacer = SendPacer()
        with patch('bridge.time.monotonic', side_effect=[100, 100, 102, 102]):
            pacer.wait()
            self.assertTrue(pacer.lock.acquire(blocking=False))
            pacer.lock.release()
            pacer.wait()


if __name__ == '__main__':
    unittest.main()
