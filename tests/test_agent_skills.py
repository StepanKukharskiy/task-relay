"""Bundled skill publication using temporary homes; no agents or network."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from task_relay import agent_skills as skills
from task_relay.host import Host


class AgentSkillsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.primary = self.root / '.agents/skills'
        self.legacy = self.root / '.codex/skills'
        self.host = Host()
        self.enterContext(patch.object(self.host, 'agent_skill_roots', return_value=[self.primary, self.legacy]))
        self.source = self.root / 'bundle'
        for name in skills.NAMES:
            path = self.source / name / 'SKILL.md'; path.parent.mkdir(parents=True)
            path.write_text('---\nname: ' + name + '\n---\nBundled instructions\n')

    def sync(self):
        return skills.sync(host=self.host, source=self.source)

    def test_first_open_installs_both_offline_and_reopening_is_idempotent(self):
        self.assertTrue(self.sync()['ready'])
        self.assertTrue(all(not r['changed'] for r in self.sync()['skills']))
        for name in skills.NAMES:
            self.assertEqual((self.primary/name/'SKILL.md').read_bytes(), (self.source/name/'SKILL.md').read_bytes())

    def test_app_update_updates_owned_exact_copy_and_preserves_personal_edits(self):
        self.sync()
        edited = self.primary / 'relay-author/SKILL.md'
        edited.write_text('Personal instructions')
        for name in skills.NAMES:
            (self.source/name/'SKILL.md').write_text('New bundled version')
        result = self.sync()
        self.assertFalse(result['ready'])
        self.assertEqual((self.primary/'relay-manage/SKILL.md').read_text(), 'New bundled version')
        self.assertEqual(edited.read_text(), 'Personal instructions')

    def test_existing_legacy_exact_copy_is_adopted_without_duplicate(self):
        name = 'relay-manage'
        path = self.legacy/name/'SKILL.md'; path.parent.mkdir(parents=True)
        path.write_bytes((self.source/name/'SKILL.md').read_bytes())
        self.assertTrue(self.sync()['ready'])
        self.assertFalse((self.primary/name).exists())
        (self.source/name/'SKILL.md').write_text('Updated instructions')
        self.assertTrue(self.sync()['ready'])
        self.assertEqual(path.read_text(), 'Updated instructions')

    def test_unknown_and_additional_files_are_preserved(self):
        path = self.primary/'relay-manage'; path.mkdir(parents=True)
        (path/'notes.txt').write_text('Keep me')
        self.assertFalse(self.sync()['ready'])
        self.assertEqual((path/'notes.txt').read_text(), 'Keep me')
        self.assertFalse((path/'SKILL.md').exists())

    def test_interrupted_write_recovers_only_recorded_content(self):
        self.sync()
        original = skills.write
        for name in skills.NAMES:
            (self.source/name/'SKILL.md').write_text('Next version')
        def interrupted(root, name, raw):
            if name.endswith('/SKILL.md'):
                raise OSError('interrupted')
            return original(root, name, raw)
        with patch.object(skills, 'write', side_effect=interrupted):
            self.assertFalse(self.sync()['ready'])
        self.assertTrue(self.sync()['ready'])
        self.assertEqual((self.primary/'relay-manage/SKILL.md').read_text(), 'Next version')

    def test_edit_after_interruption_is_not_overwritten(self):
        path = self.primary/'relay-manage'; path.mkdir(parents=True)
        raw = (self.source/'relay-manage/SKILL.md').read_bytes()
        skills.save(self.primary, {'version':1,'skills':{'relay-manage':{'sha256':None,'pending_sha256':skills.digest(raw)}}})
        (path/'SKILL.md').write_text('Edited before recovery')
        self.assertFalse(self.sync()['ready'])
        self.assertEqual((path/'SKILL.md').read_text(), 'Edited before recovery')

    def test_symlink_and_corrupt_receipt_do_not_overwrite(self):
        outside = self.root/'outside'; outside.mkdir()
        self.primary.mkdir(parents=True)
        (self.primary/'relay-manage').symlink_to(outside, target_is_directory=True)
        self.assertFalse(self.sync()['ready'])
        self.assertEqual(list(outside.iterdir()), [])
        (self.primary/skills.RECEIPT).write_text('{broken')
        self.assertFalse(self.sync()['ready'])
        self.assertEqual((self.primary/skills.RECEIPT).read_text(), '{broken')

    def test_host_uses_standard_home_and_retains_custom_codex_location(self):
        with patch('pathlib.Path.home', return_value=self.root), patch.dict('os.environ', {'CODEX_HOME':str(self.root/'custom-codex')}):
            self.assertEqual(Host().agent_skill_roots(), [self.primary, self.root/'custom-codex/skills', self.legacy])

    def test_older_app_does_not_downgrade_a_newer_managed_skill(self):
        self.sync()
        with patch.object(skills, '__version__', '0.0.1'):
            self.assertFalse(self.sync()['ready'])
        self.assertTrue(self.sync()['ready'])
