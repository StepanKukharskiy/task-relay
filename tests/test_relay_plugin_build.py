"""Connection packaging boundaries, using small local text-work fixtures."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import subprocess
import os
import unittest
import zipfile
from unittest.mock import patch

from scripts.build_relay_plugin import build_remote, build, build_skills
from scripts.prepare_relay_chatgpt import prepare
from task_relay import work_state as ws


class PluginBuildTests(unittest.TestCase):
    def test_skills_only_archive_excludes_historical_servers_and_account_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'release'
            receipt = build_skills(out)
            with zipfile.ZipFile(out.with_suffix('.zip')) as archive:
                names = archive.namelist()
                manifest = json.loads(archive.read('relay-work/plugin.json'))
                self.assertEqual(manifest['name'], 'relay-work')
                self.assertFalse(any('mcp.json' in name or '.app.json' in name or
                                     '/hosted/' in name or '/server/' in name for name in names))
                self.assertEqual(archive.read('relay-work/skills/make-reusable/SKILL.md'),
                    (Path(__file__).resolve().parents[1] / 'plugins/relay/skills/make-reusable/SKILL.md').read_bytes())
                self.assertNotIn('review', manifest['extensions']['com.openai'])
            self.assertFalse(receipt['installed'])
            self.assertFalse(receipt['published'])
            self.assertFalse((out / 'build-receipt.json').exists())
            with self.assertRaises(ValueError): build_skills(out)
    def test_web_profile_requires_no_database_and_packages_its_workflow_skill(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'web'
            receipt = build(out, sys.executable)
            config = json.loads((out / 'mcp.json').read_text())['mcpServers']['relay']
            self.assertEqual(config['args'], ['-m', 'task_relay.web_plugin'])
            self.assertEqual(receipt['mode'], 'stateless-web-development')
            self.assertTrue((out / 'skills/make-reusable/SKILL.md').is_file())
            self.assertFalse(any(p.suffix == '.sqlite' for p in out.rglob('*')))
            with self.assertRaises(ValueError):
                build(Path(folder) / 'bad', sys.executable, projects=['work:local'])
    def test_tunnel_restart_reuses_exact_setup_and_refuses_changed_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder).resolve()
            db = ws.connect(folder / 'state.sqlite')
            pid = ws.create(db, 'Example', 'Keep this text work.')
            db.close()
            out = folder / 'connection'
            prepare(out, sys.executable, folder / 'state.sqlite', pid)
            client = folder / 'tools with spaces' / 'fixture-client'
            client.parent.mkdir()
            client.write_text(f'#!{sys.executable}\n' + '''import sys,json
from pathlib import Path
args=sys.argv[1:]
with Path('calls.jsonl').open('a') as log:log.write(json.dumps(args)+'\\n')
if args[0]=='init':
 directory=Path(args[args.index('--profile-dir')+1]);directory.mkdir()
 (directory/'task-relay.yaml').write_text('fixture local profile')
''')
            client.chmod(0o755)
            command = [sys.executable, str(out / 'start-tunnel.py'), '--client', str(client.relative_to(folder)), '--tunnel-id', 'tunnel_fixture123']
            env = {**os.environ, 'CONTROL_PLANE_API_KEY': 'fixture-private-runtime-key'}
            for _ in range(2):
                subprocess.run(command, cwd=folder, env=env, check=True, capture_output=True)
            calls = [json.loads(r) for r in (out / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual([r[0] for r in calls], ['init', 'doctor', 'run', 'doctor', 'run'])
            changed = subprocess.run([*command[:-1], 'tunnel_other123'], cwd=folder, env=env, capture_output=True)
            self.assertNotEqual(changed.returncode, 0)
            (out / 'tunnel-profile' / 'task-relay.yaml').write_text('unexpected edited profile')
            changed_file = subprocess.run(command, cwd=folder, env=env, capture_output=True)
            self.assertNotEqual(changed_file.returncode, 0)
            self.assertEqual(len((out / 'calls.jsonl').read_text().splitlines()), 5)

    def test_remote_zip_excludes_local_runtime_data_and_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'remote.v1'
            receipt = build_remote(out, 'https://mcp.task-relay.dev/mcp')
            with zipfile.ZipFile(str(out) + '.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'plugin.json', 'mcp.json', 'README.md', 'assets/logo.png',
                    'skills/make-reusable/SKILL.md', 'skills/make-reusable/references/work-snapshots.md'})
                mcp = json.loads(archive.read('mcp.json'))
                self.assertEqual(mcp['mcpServers']['relay'], {'type': 'streamable-http', 'url': 'https://mcp.task-relay.dev/mcp'})
                self.assertNotIn(b'/Users/', archive.read('README.md'))
                self.assertNotIn('apps', json.loads(archive.read('plugin.json'))['extensions']['com.openai'])
            self.assertFalse(receipt['endpoint_checked'])
            self.assertFalse(receipt['published'])
            original = Path(str(out) + '.zip').read_bytes()
            with self.assertRaises(ValueError):
                build_remote(out, 'https://mcp.task-relay.dev/mcp')
            self.assertEqual(Path(str(out) + '.zip').read_bytes(), original)

    def test_invalid_remote_endpoints_do_not_create_a_package(self):
        endpoints = ['http://mcp.task-relay.dev/mcp', 'https://user:secret@mcp.task-relay.dev/mcp',
            'https://mcp.task-relay.dev/mcp?token=secret', 'https://mcp.task-relay.dev/mcp#secret',
            'https://localhost/mcp', 'https://127.0.0.1/mcp', 'https://example.com/mcp',
            'https://mcp.task-relay.dev:invalid/mcp', 'https://mcp.task-relay.dev/other']
        with tempfile.TemporaryDirectory() as folder:
            for i, endpoint in enumerate(endpoints):
                with self.subTest(endpoint=endpoint):
                    out = Path(folder) / str(i)
                    with self.assertRaises(ValueError):
                        build_remote(out, endpoint)
                    self.assertFalse(out.exists())

    def test_preparation_cannot_create_missing_database_or_grant_unknown_project(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder).resolve() / 'missing.sqlite'
            out = Path(folder) / 'connection'
            with self.assertRaises(FileNotFoundError):
                prepare(out, sys.executable, missing, 'work:missing')
            self.assertFalse(missing.exists())
            db = ws.connect(missing)
            ws.create(db, 'Example', 'Keep this text work.')
            db.close()
            with self.assertRaises(ValueError):
                prepare(out, sys.executable, missing, 'work:missing')
            self.assertFalse(out.exists())

    def test_scoped_tunnel_launcher_operates_from_another_working_directory(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix='relay connection ') as folder:
            path = Path(folder).resolve() / 'state.sqlite'
            db = ws.connect(path)
            pid = ws.create(db, 'Example', 'Keep this text work.')
            other = ws.create(db, 'Other', 'Keep this private.')
            before = list(db.execute('SELECT * FROM work_projects'))
            db.close()
            out = Path(folder) / 'connection'
            secret = 'fixture-runtime-key-private'
            with patch.dict('os.environ', {'CONTROL_PLANE_API_KEY': secret}):
                receipt = prepare(out, sys.executable, path, pid)
            self.assertFalse(receipt['database_mutated'])
            self.assertFalse(receipt['tunnel_started'])
            async def inspect():
                params = StdioServerParameters(command=sys.executable,
                    args=[str(out / 'serve.py')], cwd=tempfile.gettempdir())
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        projects = (await client.call_tool('relay_list_work', {})).structuredContent['projects']
                        self.assertEqual([p['id'] for p in projects], [pid])
                        denied = await client.call_tool('relay_open_work', {'project_id': other})
                        self.assertTrue(denied.isError)
            asyncio.run(inspect())
            with closing(sqlite3.connect(path)) as current:
                self.assertEqual([tuple(r) for r in before], list(current.execute('SELECT * FROM work_projects')))
            compile((out / 'start-tunnel.py').read_text(), 'start-tunnel.py', 'exec')
            for generated in out.rglob('*'):
                if generated.is_file():
                    self.assertNotIn(secret.encode(), generated.read_bytes())


if __name__ == '__main__':
    unittest.main()
