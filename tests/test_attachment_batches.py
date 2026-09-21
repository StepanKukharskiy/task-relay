"""Telegram albums, caption binding and durable local delivery. No live sends."""
import io
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from task_relay import attachment_batches as batches, production_control as pc
from task_relay import orchestrator_chat as chat, routing_inputs
from tests import test_orchestrator_images as fixtures
from PIL import Image

_buffer = io.BytesIO()
Image.new("RGB", (2, 2)).save(_buffer, format="JPEG")
PHOTO = _buffer.getvalue()


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown

    def upload(self, ident, caption='', album='four-photos'):
        msg = {'message_id': ident, 'chat': {'id': 7, 'type': 'private'}, 'from': {'id': 7},
               'photo': [{'file_id': str(ident), 'width': 10, 'height': 10, 'file_size': len(PHOTO)}],
               'caption': caption}
        if album:msg['media_group_id'] = album
        self.bridge.process({'update_id': ident, 'message': msg})

    def download(self, count=4, failure=None):
        def fetch(ident, path, limit):
            if ident == failure:raise ValueError('fixture download failure')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(PHOTO)
        self.telegram.download_file = fetch
        worker = pc.Worker(self.state, telegram=self.telegram)
        for _ in range(count):worker.download()

    def finish(self):
        batches.finish(self.state, time.time() + batches.QUIET_SECONDS + 1)

    def test_four_images_one_notice_exact_caption_and_one_local_folder(self):
        caption = 'Can you save this to my computer?  '
        for ident in range(100, 104):self.upload(ident, caption if ident == 102 else '')
        self.upload(100)  # Duplicate Telegram update cannot create another file.
        self.download()
        batches.finish(self.state)  # Wait for the album's quiet window.
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 0)
        self.finish(); self.finish()
        row = self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        self.assertEqual(row['prompt'], caption)
        self.assertEqual(batches.selected(self.state, row['id']), [100, 101, 102, 103])
        uploads = self.state.db.execute('SELECT * FROM production_uploads').fetchall()
        self.assertEqual(len({Path(r['path']).parent for r in uploads}), 1)
        self.assertEqual(len({r['path'] for r in uploads}), 4)
        self.assertTrue(all(pc.upload_path(self.state, r).read_bytes() == PHOTO for r in uploads))
        notices = self.state.db.execute("SELECT text FROM outbox WHERE text LIKE '%attachment(s)%'").fetchall()
        self.assertEqual(len(notices), 1)
        self.assertIn(str(Path(uploads[0]['path']).parent), notices[0][0])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_partial_failure_preserves_files_and_does_not_dispatch_caption(self):
        for ident in range(100, 104):self.upload(ident, 'Use these four images' if ident == 100 else '')
        self.download(failure='102');self.finish()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 0)
        text = self.state.db.execute("SELECT text FROM outbox WHERE text LIKE '%Not saved:%'").fetchone()[0]
        self.assertIn('Saved 3 attachment(s)', text)
        self.assertIn('has not started work', text)

    def test_captionless_or_conflicting_captions_do_not_start_work(self):
        for ident, caption in [(100, ''), (101, ''), (102, 'Use this'), (103, 'Ignore that')]:
            self.upload(ident, caption, album='blank' if ident < 102 else 'conflicting')
        self.download();self.finish()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 0)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM outbox WHERE text LIKE '%attachment(s)%'").fetchone()[0], 2)

    def test_late_member_does_not_replay_or_change_dispatched_request(self):
        self.upload(100, 'Save this');self.download(1);self.finish()
        self.upload(101);self.download(1);self.finish()
        self.assertEqual(batches.selected(self.state, 100), [100])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 1)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM outbox WHERE text LIKE '%Late album attachments%'").fetchone())

    def test_caption_binding_and_notice_roll_back_together(self):
        self.upload(100, 'Save this');self.download(1)
        with patch.object(self.state, 'put', side_effect=RuntimeError('interrupted commit')):
            with self.assertRaises(RuntimeError):self.finish()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0], 0)
        self.assertIsNone(self.state.db.execute('SELECT request_id FROM relay_attachment_batches').fetchone()[0])
        self.finish()
        self.assertEqual(batches.selected(self.state, 100), [100])

    def test_caption_context_excludes_older_uploads_and_freezes_album_paths(self):
        self.upload(90, album=None);self.download(1);self.finish()
        self.upload(100, 'Model these photos');self.upload(101);self.download(2);self.finish()
        job = self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()
        payload = chat.conversation_context(self.state, job, chat.snapshot(self.state, None))
        self.assertEqual([f['id'] for f in payload['snapshot']['uploaded_files']], [100, 101])
        records = routing_inputs.freeze_uploads(self.state, job, batches.selected(self.state, job['id']))
        self.assertEqual([r['upload_id'] for r in records], [100, 101])
        row = self.state.db.execute('SELECT * FROM production_uploads WHERE id=100').fetchone()
        path = Path(row['path']);path.chmod(0o600);path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            routing_inputs.freeze_uploads(self.state, job, [100])

    def test_saved_albums_do_not_exhaust_next_albums_upload_allowance(self):
        for group, start in [('first', 100), ('second', 200)]:
            for ident in range(start, start + 6):self.upload(ident, album=group)
            self.download(6);self.finish()
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_uploads WHERE status='ready'").fetchone()[0], 12)

    def test_oversized_group_rolls_back_member_and_incoming_receipt(self):
        for ident in range(100, 111):self.upload(ident)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_uploads').fetchone()[0], 10)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_attachment_members').fetchone()[0], 10)
        self.assertIsNone(self.state.db.execute('SELECT 1 FROM incoming WHERE id=110').fetchone())
