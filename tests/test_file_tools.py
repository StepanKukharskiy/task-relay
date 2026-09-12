import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import file_tools as files


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / 'project'
        self.root.mkdir()
        (self.root / 'README.md').write_text('Alpha\nneedle one\nNeedle two\n')
        (self.root / 'src').mkdir()
        (self.root / 'src/main.py').write_text('print("needle")\n')

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, **args):
        defaults = {'path': '.', 'offset': 0, 'limit': 20}
        if name == 'file_list':
            defaults['recursive'] = True
        if name == 'file_search':
            defaults.update(query='needle', case_sensitive=False)
        defaults.update(args)
        return files.execute(self.root, name, json.dumps(defaults))

    def test_list_pagination_and_nonrecursive(self):
        first = self.call('file_list', limit=1)
        second = self.call('file_list', offset=first['next_offset'])
        self.assertEqual([r['path'] for r in first['entries'] + second['entries']],
                         ['README.md', 'src', 'src/main.py'])
        self.assertEqual(len(self.call('file_list', recursive=False)['entries']), 2)

    def test_read_long_unicode_lines_without_losing_characters(self):
        text = '🚀' * 25000 + '\nlast line'
        (self.root / 'unicode.txt').write_text(text)
        first = self.call('file_read', path='unicode.txt', limit=24000)
        second = self.call('file_read', path='unicode.txt', offset=first['next_offset'], limit=24000)
        self.assertEqual(first['text'] + second['text'], text)
        self.assertIsNone(second['next_offset'])
        self.assertEqual(self.call('file_read', path='unicode.txt', offset=25001)['start_line'], 2)

    def test_search_literal_case_and_pagination(self):
        first = self.call('file_search', limit=1)
        second = self.call('file_search', offset=1)
        self.assertEqual(first['matches'][0]['line'], 2)
        self.assertEqual([m['path'] for m in second['matches']], ['README.md', 'src/main.py'])
        self.assertEqual(len(self.call('file_search', case_sensitive=True)['matches']), 2)
        self.assertEqual(self.call('file_search', query='.*')['matches'], [])
        self.assertEqual(len(self.call('file_search', path='README.md')['matches']), 2)

    def test_traversal_and_absolute_escape_are_rejected(self):
        outside = self.parent / 'outside.txt'
        outside.write_text('outside contents')
        for path in ('../outside.txt', str(outside), 'src/../../outside.txt', 'src/../README.md'):
            with self.subTest(path=path):
                self.assertFalse(self.call('file_read', path=path)['ok'])
        self.assertTrue(self.call('file_read', path=str(self.root / 'README.md'))['ok'])

    def test_symlinks_and_hardlinks_never_read_or_list(self):
        outside = self.parent / 'outside.txt'
        outside.write_text('outside contents')
        (self.root / 'link.txt').symlink_to(outside)
        (self.root / 'linked-dir').symlink_to(self.parent, target_is_directory=True)
        os.link(outside, self.root / 'hard.txt')
        for path in ('link.txt', 'hard.txt', 'linked-dir/outside.txt'):
            self.assertFalse(self.call('file_read', path=path)['ok'])
        listing = json.dumps(self.call('file_list'))
        self.assertNotIn('link.txt', listing)
        self.assertNotIn('hard.txt', listing)
        self.assertNotIn('linked-dir', listing)

    def test_directory_swap_before_open_does_not_escape(self):
        outside = self.parent / 'outside'
        outside.mkdir()
        (outside / 'main.py').write_text('outside contents')
        real_open = os.open
        def swapping_open(path, flags, **kwargs):
            if path == 'src':
                (self.root / 'src').rename(self.root / 'original')
                (self.root / 'src').symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, **kwargs)
        with patch('file_tools.os.open', side_effect=swapping_open):
            self.assertFalse(self.call('file_read', path='src/main.py')['ok'])

    def test_hidden_private_and_credentials_excluded_everywhere(self):
        for name in ('.env', 'private', 'node_modules', 'credentials', '.git'):
            folder = self.root / name
            folder.mkdir()
            (folder / 'data.txt').write_text('needle confidential')
            self.assertFalse(self.call('file_read', path=f'{name}/data.txt')['ok'])
        for name in ('server.key', 'credentials.json', 'state.sqlite-wal'):
            (self.root / name).write_text('needle confidential')
            self.assertFalse(self.call('file_read', path=name)['ok'])
        self.assertNotIn('confidential', json.dumps(self.call('file_search')))
        self.assertEqual(len(self.call('file_list')['entries']), 3)

    def test_protected_root_cannot_be_used_as_project(self):
        result = files.execute(self.root, 'file_read', json.dumps({'path': 'README.md', 'offset': 0, 'limit': 100}), [self.root])
        self.assertFalse(result['ok'])
        nested = self.root / '.ssh'
        nested.mkdir()
        (nested / 'data.txt').write_text('confidential')
        result = files.execute(nested, 'file_read', json.dumps({'path': 'data.txt', 'offset': 0, 'limit': 100}))
        self.assertFalse(result['ok'])

    def test_binary_large_and_special_files_fail_without_blocking(self):
        (self.root / 'binary.bin').write_bytes(b'\x00abc')
        (self.root / 'large.txt').write_bytes(b'x' * (files.MAX_FILE_BYTES + 1))
        os.mkfifo(self.root / 'pipe')
        for name in ('binary.bin', 'large.txt', 'pipe', 'src'):
            self.assertFalse(self.call('file_read', path=name)['ok'])
        result = self.call('file_search')
        self.assertEqual(result['skipped_files'], 2)

    def test_utf16_and_empty_files(self):
        (self.root / 'utf16.txt').write_bytes('Hello 🚀'.encode('utf-16'))
        (self.root / 'empty.txt').touch()
        self.assertEqual(self.call('file_read', path='utf16.txt')['text'], 'Hello 🚀')
        self.assertEqual(self.call('file_read', path='empty.txt')['text'], '')

    def test_scan_limits_report_incomplete(self):
        with patch('file_tools.MAX_ENTRIES', 1):
            self.assertTrue(self.call('file_list')['scan_incomplete'])
        with patch('file_tools.MAX_SCAN_BYTES', 1):
            self.assertTrue(self.call('file_search')['scan_incomplete'])
        with patch('file_tools.MAX_DEPTH', 0):
            self.assertTrue(self.call('file_search')['scan_incomplete'])

    def test_invalid_arguments_fail_as_tool_results(self):
        for raw in ('{', '[]', 'null', '{"path":"README.md","offset":true,"limit":20}',
                    '{"path":"README.md","offset":0,"limit":0}'):
            self.assertFalse(files.execute(self.root, 'file_read', raw)['ok'])
        self.assertFalse(self.call('file_write')['ok'])

    def test_binary_files_count_towards_search_byte_budget(self):
        (self.root / '000.bin').write_bytes(b'\x00' * 100)
        with patch('file_tools.MAX_SCAN_BYTES', 100):
            result = self.call('file_search')
        self.assertEqual(result['matches'], [])
        self.assertTrue(result['scan_incomplete'])
