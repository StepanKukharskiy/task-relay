import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge import Bridge, State, Telegram, TelegramError, split_text
from tests.test_bridge import TelegramFake, DesktopFake
import telegram_text as fmt


class Tests(unittest.TestCase):
    def test_bold_headings_links_entities_and_literal_html(self):
        text, entities = fmt.render('# Heading\n**Bold** and *italic* &amp; <tag>\n[Docs](https://example.com)')
        self.assertEqual(text, 'Heading\nBold and italic & <tag>\nDocs')
        self.assertEqual({e['type'] for e in entities}, {'bold', 'italic', 'text_link'})
        self.assertEqual([e['url'] for e in entities if e['type'] == 'text_link'], ['https://example.com'])

    def test_code_fences_keep_literal_markdown_and_language(self):
        text, entities = fmt.render('Before\n```python\nprint("**literal**")\n```\nAfter `hello_world`')
        self.assertEqual(text, 'Before\nprint("**literal**")\nAfter hello_world')
        self.assertEqual({e['type'] for e in entities}, {'pre', 'code'})
        self.assertEqual(next(e for e in entities if e['type'] == 'pre')['language'], 'python')

    def test_local_links_are_readable_without_broken_click_targets(self):
        text, entities = fmt.render(r'**&#x54;he file:** [claude\_runner.py]\(/absolute/project/claude_runner.py:130\)')
        self.assertEqual(text, 'The file: claude_runner.py')
        self.assertEqual([e['type'] for e in entities], ['bold'])

    def test_bold_and_code_styles_survive_multipart_and_unicode_offsets(self):
        for raw, kind, expected in [('**' + '🚀' * 6000 + '**', 'bold', '🚀' * 6000),
                                    ('```\n' + 'line\n' * 2500 + '```', 'pre', 'line\n' * 2500)]:
            parts = fmt.parts(raw, split_text)
            restored = []
            for i, (text, entities) in enumerate(parts, 1):
                header = f'Part {i}/{len(parts)}\n\n'
                self.assertTrue(text.startswith(header))
                body = text[len(header):]
                restored.append(body)
                self.assertLessEqual(fmt.units(text), 4096)
                self.assertEqual(entities, [{'type': kind, 'offset': fmt.units(header), 'length': fmt.units(body)}])
            self.assertEqual(''.join(restored), expected)

    def test_formatted_outbox_persists_entities_and_task_emoji_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite'
            state = State(path)
            with state.db:
                state.put('chat_id', 123)
                state.db.execute('INSERT INTO watched VALUES (?,?,?,?,?,?)', ('task', '', 0, 'Title', 'idle', 1))
                state.set_emoji('task', '🚀')
                state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)', ('event', 'task', '**Bold**'))
            bot = TelegramFake()
            bridge = Bridge(state, bot, {}, DesktopFake)
            bridge.flush()
            self.assertEqual(bot.sent[0][1], '🚀 Bold')
            self.assertEqual(bot.entities[0], [{'type': 'bold', 'offset': 3, 'length': 4}])
            saved = json.loads(state.db.execute('SELECT entities FROM outbox_parts').fetchone()[0])
            self.assertEqual(saved[0]['offset'], 0)
            self.assertEqual(state.db.execute('SELECT thread_id FROM messages').fetchone()[0], 'task')
            state.db.close()

    def test_transport_uses_entities_not_markdown_parse_mode(self):
        telegram = Telegram('fake')
        entities = [{'type': 'bold', 'offset': 0, 'length': 4}]
        with patch.object(telegram, 'call') as call:
            telegram.send(123, 'Bold', entities=entities)
        self.assertEqual(call.call_args.kwargs['entities'], entities)
        self.assertNotIn('parse_mode', call.call_args.kwargs)

    def test_format_rejection_falls_back_to_text_but_rate_limit_does_not_resend(self):
        telegram = Telegram('fake')
        entities = [{'type': 'bold', 'offset': 0, 'length': 4}]
        with patch.object(telegram, 'call', side_effect=[TelegramError('sendMessage', 400), {'message_id': 1}]) as call:
            self.assertEqual(telegram.send(123, 'Bold', entities), {'message_id': 1})
            self.assertNotIn('entities', call.call_args.kwargs)
        with patch.object(telegram, 'call', side_effect=TelegramError('sendMessage', 429)) as call:
            with self.assertRaises(TelegramError):
                telegram.send(123, 'Bold', entities)
            self.assertEqual(call.call_count, 1)
