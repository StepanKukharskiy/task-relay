import base64
from pathlib import Path
import unittest
from unittest.mock import patch

import codex_inputs as inputs
import gemini
from tests import test_bridge as fixture
from bridge import BridgeError, Desktop, State

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


class InputTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.Tests()
        self.f.setUp()
        self.state, self.bridge, self.telegram = self.f.state, self.f.bridge, self.f.telegram
        self.reply = self.f.ready()
        self.telegram.download_file = lambda fid, path, limit: gemini.atomic_bytes(path, PNG)
        self.worker = inputs.Worker(self.state, self.telegram)
        self.starts = []
        test = self
        class DesktopFake(fixture.DesktopFake):
            def start(self, tid, text, owner, images=None):
                test.starts.append((tid, text, images or []))
        self.bridge.desktop_factory = DesktopFake

    def tearDown(self):
        self.f.tearDown()

    def upload(self, kind='document', name='diagram.png', id=10, reply=True, **fields):
        update = self.f.message('', id=id, reply=self.reply if reply else None)
        update['message'].update({'message_id': 1000 + id, kind: {
            'file_id': 'file-' + str(id), 'file_name': name, 'file_size': len(PNG)}, **fields})
        if kind == 'photo':
            update['message']['photo'] = [{'file_id': 'small', 'width': 1, 'height': 1},
                                        {'file_id': 'large', 'width': 10, 'height': 10}]
        self.bridge.process(update)
        return update

    def rows(self):
        return self.state.db.execute('SELECT * FROM codex_inputs ORDER BY update_id').fetchall()

    def instruct(self, text='Describe the attachments', id=50):
        self.bridge.process(self.f.message(text, id=id, reply=self.reply))

    def test_image_is_staged_then_sent_as_native_visual_input(self):
        update = self.upload(caption='Compare this /allow fake-id')
        self.bridge.process(update)
        self.assertEqual(len(self.rows()), 1)
        self.assertFalse(self.starts)
        self.worker.tick()
        row = self.rows()[0]
        self.assertEqual(Path(row['path']).read_bytes(), PNG)
        self.assertEqual(Path(row['path']).stat().st_mode & 0o777, 0o600)
        self.instruct()
        self.assertEqual(self.starts[0][0], 'task-one')
        self.assertEqual(self.starts[0][2], [row['path']])
        self.assertIn('Compare this /allow fake-id', self.starts[0][1])
        self.assertEqual(self.rows()[0]['status'], 'used')
        self.assertTrue(Path(row['path']).exists())
        self.assertEqual(inputs.prepare(self.state, 'task-one', 'next'), ('next', [], []))

    def test_photos_use_largest_size_and_own_upload_is_replyable(self):
        self.upload(kind='photo')
        self.assertEqual(self.rows()[0]['file_id'], 'large')
        self.assertEqual(self.bridge.target_task({'reply_to_message': {'message_id': 1010}}, 123), 'task-one')

    def test_album_continuations_ignore_unrelated_selected_task(self):
        self.upload(media_group_id='album')
        with self.state.db:
            self.state.put('selected', 'unrelated')
        self.upload(id=11, reply=False, media_group_id='album')
        self.assertEqual([r['thread_id'] for r in self.rows()], ['task-one', 'task-one'])
        self.worker.tick()
        self.worker.tick()
        self.instruct()
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(len(self.starts[0][2]), 2)

    def test_album_rejects_conflicting_or_unknown_explicit_reply(self):
        self.upload(media_group_id='album')
        message = self.f.message('', id=11, reply=999)
        message['message'].update({'media_group_id': 'album', 'document': {'file_id': 'other', 'file_name': 'a.pdf'}})
        self.bridge.process(message)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn('conflicting', self.telegram.sent[-1][1])

    def test_documents_audio_video_voice_and_animations_are_saved_as_files(self):
        for i, (kind, name) in enumerate([('document', 'review.pdf'), ('document', 'work.docx'),
                ('document', 'data.xlsx'), ('video', 'clip.mp4'), ('audio', 'sound.mp3'),
                ('voice', 'voice.ogg'), ('animation', 'moving.gif'), ('video_note', 'note.mp4'),
                ('document', 'model.3dm'), ('sticker', 'sticker.tgs')], 10):
            self.upload(kind=kind, name=name, id=i)
            self.worker.tick()
        self.instruct()
        self.assertEqual(len(self.starts), 1)
        self.assertFalse(self.starts[0][2])
        for row in self.rows():
            self.assertIn(row['path'], self.starts[0][1])
            self.assertTrue(Path(row['path']).is_file())
        self.assertIn('not been transcribed', self.starts[0][1])

    def test_pending_download_blocks_instruction(self):
        self.upload()
        self.instruct()
        self.assertFalse(self.starts)
        self.assertIn('still downloading', self.telegram.sent[-1][1])
        self.worker.tick()
        self.instruct(id=51)
        self.assertEqual(len(self.starts), 1)

    def test_bad_image_fails_and_blocks_omission_until_forgotten(self):
        self.telegram.download_file = lambda fid, path, limit: gemini.atomic_bytes(path, b'not an image')
        self.upload()
        self.worker.tick()
        row = self.rows()[0]
        self.assertEqual(row['status'], 'failed')
        self.instruct()
        self.assertFalse(self.starts)
        self.bridge.process(self.f.message('/forget ' + row['id'], id=51, reply=self.reply))
        self.instruct(id=52)
        self.assertEqual(len(self.starts), 1)

    def test_download_failure_retries_then_reports_once(self):
        def fail(*args): raise BridgeError('Connection failed')
        self.telegram.download_file = fail
        self.upload()
        for _ in range(3):
            with self.state.db:
                self.state.db.execute('UPDATE codex_inputs SET next_attempt=0')
            self.worker.tick()
        self.worker.tick()
        self.assertEqual(self.rows()[0]['attempts'], 3)
        self.assertEqual(self.rows()[0]['status'], 'failed')
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE id LIKE 'codex-input:%'").fetchone()[0], 1)

    def test_unknown_reply_and_unauthorized_users_do_not_stage_files(self):
        with self.state.db:
            self.state.put('selected', 'task-one')
        for user, reply in ((456, self.reply), (123, 999)):
            update = self.f.message('', id=10, user=user, reply=reply)
            update['message']['photo'] = [{'file_id': 'image', 'width': 10, 'height': 10}]
            self.bridge.process(update)
        self.assertFalse(self.rows())

    def test_filename_cannot_escape_storage_and_bytes_are_checked(self):
        self.upload(name='../../outside.png')
        self.worker.tick()
        path = Path(self.rows()[0]['path'])
        self.assertEqual(path.name, 'outside.png')
        self.assertTrue(path.is_relative_to((self.state.media_dir.parent / 'codex-inputs').resolve()))
        path.write_bytes(PNG + b'changed')
        self.instruct()
        self.assertFalse(self.starts)
        self.assertIn('changed', self.telegram.sent[-1][1])

    def test_symlink_or_missing_file_is_not_sent(self):
        self.upload()
        self.worker.tick()
        path = Path(self.rows()[0]['path'])
        path.unlink()
        outside = self.f.root / 'outside.png'
        outside.write_bytes(PNG)
        path.symlink_to(outside)
        self.instruct()
        self.assertFalse(self.starts)

    def test_maximum_count_and_declared_size_rejections_roll_back(self):
        with patch.object(inputs, 'MAX_COUNT', 1):
            self.upload()
            self.upload(id=11)
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNone(self.state.db.execute('SELECT * FROM incoming WHERE id=11').fetchone())
        with patch.object(inputs, 'MAX_FILE', 1):
            self.upload(id=12)
        self.assertEqual(len(self.rows()), 1)

    def test_actual_total_size_is_bounded_when_declared_size_is_missing(self):
        for n in (10, 11):
            update = self.f.message('', id=n, reply=self.reply)
            update['message']['document'] = {'file_id': str(n), 'file_name': 'input.png'}
            self.bridge.process(update)
        with patch.object(inputs, 'MAX_TOTAL', len(PNG) + 1):
            self.worker.tick()
            self.worker.tick()
        self.assertEqual([r['status'] for r in self.rows()], ['ready', 'failed'])

    def test_forgetting_pending_file_during_download_prevents_ready_notification(self):
        self.upload()
        token = self.rows()[0]['id']
        def download(fid, path, limit):
            gemini.atomic_bytes(path, PNG)
            inputs.forget(self.state, 'task-one', token)
        self.telegram.download_file = download
        self.worker.tick()
        self.assertEqual(self.rows()[0]['status'], 'forgotten')
        self.assertFalse(self.state.db.execute("SELECT 1 FROM outbox WHERE id LIKE 'codex-input:%'").fetchone())

    def test_restart_preserves_pending_download_and_prevents_replaying_used_files(self):
        self.upload()
        restored = State(self.f.root / 'state.sqlite')
        try:
            db = restored.db
            self.assertEqual(db.execute('SELECT status FROM codex_inputs').fetchone()[0], 'pending')
        finally:
            restored.db.close()
        inputs.Worker(self.state, self.telegram).tick()
        self.instruct()
        inputs.initialize(self.state.db)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM codex_input_uses').fetchone()[0], 1)
        self.assertFalse(inputs.prepare(self.state, 'task-one', 'next')[2])

    def test_uncertain_submission_does_not_replay_images(self):
        self.upload()
        self.worker.tick()
        parent = self.bridge.desktop_factory
        class Lost(parent):
            def start(self, *args, **kwargs):
                super().start(*args, **kwargs)
                raise TimeoutError()
        self.bridge.desktop_factory = Lost
        self.instruct()
        self.instruct()
        self.assertEqual(len(self.starts), 1)
        self.assertEqual(self.rows()[0]['status'], 'used')
        self.assertEqual(self.state.db.execute('SELECT status FROM incoming WHERE id=50').fetchone()[0], 'uncertain')

    def test_connection_failure_keeps_attachments_ready(self):
        self.upload()
        self.worker.tick()
        with patch.object(self.bridge.desktop_factory, 'ready_owner', side_effect=BridgeError('offline')):
            self.instruct()
        self.assertEqual(self.rows()[0]['status'], 'ready')
        self.assertFalse(self.starts)

    def test_forget_is_scoped_to_exact_task(self):
        self.upload()
        token = self.rows()[0]['id']
        self.assertIn('not found', inputs.forget(self.state, 'different-task', token))
        self.assertEqual(self.rows()[0]['status'], 'pending')

    def test_desktop_payload_contains_text_and_local_images_with_inherited_settings(self):
        desktop = Desktop()
        with patch.object(desktop, 'request', return_value={
                'method': 'thread-follower-start-turn', 'result': {'result': {}}}) as request:
            desktop.start('task', 'Inspect these', 'owner', ['/absolute/photo.png', '/absolute/other.jpg'])
        call = request.call_args
        payload = call.args[1]['turnStart']
        self.assertEqual(payload['request']['input'], [
            {'type': 'text', 'text': 'Inspect these', 'text_elements': []},
            {'type': 'localImage', 'path': '/absolute/photo.png'},
            {'type': 'localImage', 'path': '/absolute/other.jpg'}])
        self.assertEqual(payload['context'], {'inheritThreadSettings': True})
        self.assertEqual(call.kwargs, {'target': 'owner'})


if __name__ == '__main__':
    unittest.main()
