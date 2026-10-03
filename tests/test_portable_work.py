"""Portable export/reuse and failure boundaries using small text fixtures."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from task_relay import portable_work as p
from task_relay import web_plugin as web


SKILL = {'files': [{'path': 'SKILL.md', 'content': '''---
name: country-competitor-research
description: Research competitors in a user-specified country using supplied criteria and evidence.
---

Use for country competitor research. Require country and comparison criteria.
Read [checks](references/checks.md). Report source coverage and unknowns.
Do not invent missing competitors or promote a country finding into a general rule.
'''}, {'path': 'references/checks.md', 'content': 'Check each claim against a supplied source. Keep missing evidence visible.'}]}
BODY = '''# Competition / Example country

## Objective
Prepare a sourced competitor report.

## Current conclusions
- The comparison criteria are drafted; competitor facts are still unverified.

## Decisions and proposals
- [Proposal] Use the three drafted criteria. No acceptance was supplied.

## Evidence
- User-supplied brief; no external sources selected yet.

## Artifact references
- comparison.md v1; not included in this snapshot.

## Unresolved questions
- [Open] Which competitors qualify?
- [Open] Which sources support the comparison?

## Next actions
- Verify competitors against the supplied criteria.
'''
WORK = {'work_id': 'competition-example', 'title': 'Competition / Example country', 'markdown': BODY}


def proposal():
    return p.propose('Make this useful discussion reusable.', skill=SKILL, work=WORK)


class PortableTests(unittest.TestCase):
    def test_independent_exports_round_trip_and_new_chat_needs_no_original_context(self):
        values = proposal()
        self.assertFalse(values['saved'])
        self.assertEqual(len(values['candidates']), 2)
        selected = []
        for candidate in values['candidates']:
            export = p.review_export(web.compact_document(candidate), True)
            self.assertFalse(export['stored_on_server'])
            selected.append(p.import_file(export['filename'], export['data_base64']))
            self.assertEqual(selected[-1]['files'], candidate['files'])
        context = p.prepare_reuse('Research a different country.', selected)
        packet = json.loads(context['packet'])
        self.assertEqual(packet['new_request'], 'Research a different country.')
        self.assertIn('comparison.md v1', context['packet'])
        self.assertIn('No acceptance was supplied', context['packet'])
        self.assertIn('references/checks.md', context['packet'])
        self.assertNotIn('Make this useful discussion reusable.', packet['new_request'])

    def test_snapshot_update_keeps_exact_base_and_separates_skill_improvement(self):
        base_skill, base_work = proposal()['candidates']
        original = base_work['files'][0]['content']
        new = {**WORK, 'markdown': BODY.replace('[Open] Which competitors qualify?', '[Resolved] Which competitors qualify? Criteria were clarified; facts still need checking.')}
        updated = p.propose('Update this work only.', 'update_work', work=new,
                            bases=[web.compact_document(base_work)])['candidates'][0]
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['based_on_sha256'], base_work['sha256'])
        self.assertEqual(base_work['files'][0]['content'], original)
        self.assertEqual(updated['request'], 'Update this work only.')
        self.assertIn('[Proposal]', updated['files'][0]['content'])
        self.assertEqual(base_skill['files'], SKILL['files'])
        exported = p.review_export(web.compact_document(updated), True, web.compact_document(base_work))
        self.assertTrue(exported['filename'].endswith('-r002.relay.md'))
        self.assertEqual(p.import_file(exported['filename'], exported['data_base64'])['based_on_sha256'], base_work['sha256'])
        with self.assertRaises(p.PortableError):
            p.propose('Improve Skill', 'improve_skill', skill=SKILL, work=new, bases=[web.compact_document(base_skill)])

    def test_changed_review_cannot_forge_work_lineage(self):
        base = proposal()['candidates'][1]
        update = p.propose('Update', 'update_work', work=WORK, bases=[web.compact_document(base)])['candidates'][0]
        edit = web.compact_document(update)
        edit['files'][0]['content'] = edit['files'][0]['content'].replace('revision: 2', 'revision: 8')
        with self.assertRaises(p.PortableError):
            p.review_export(edit, True, web.compact_document(base))
        with self.assertRaises(p.PortableError):
            p.propose('Update', 'update_work', work={**WORK, 'work_id': 'another-job'}, bases=[web.compact_document(base)])

    def test_export_requires_review_and_invalid_edits_do_not_change_prior_file(self):
        candidate = proposal()['candidates'][0]
        with self.assertRaises(p.PortableError):
            p.review_export(candidate, False)
        exact = p.review_export(candidate, True)
        malformed = {'kind': 'skill', 'files': [{'path': 'SKILL.md', 'content': 'A draft without metadata.'}]}
        with self.assertRaises(p.PortableError):
            p.review_export(malformed, True)
        self.assertEqual(p.review_export(candidate, True)['data_base64'], exact['data_base64'])

    def test_standard_skill_preserves_optional_metadata_resources_and_never_runs_scripts(self):
        files = [dict(f) for f in SKILL['files']]
        files[0]['content'] = files[0]['content'].replace('---\n\nUse', 'metadata:\n  author: Example\n---\n\nUse')
        files.append({'path': 'scripts/check.py', 'content': 'raise RuntimeError("This script must never run during import/export")\n'})
        item = p.skill_document(files)
        exported = p.review_export(item, True)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported['data_base64']))) as archive:
            self.assertIn('country-competitor-research/SKILL.md', archive.namelist())
            self.assertIn(b'author: Example', archive.read('country-competitor-research/SKILL.md'))
        self.assertEqual(p.import_file(exported['filename'], exported['data_base64'])['files'], item['files'])

    def test_zip_paths_duplicates_links_and_bombs_are_rejected_without_extraction(self):
        for paths in [('../outside',), ('country-competitor-research/../../outside',),
                      ('country-competitor-research/SKILL.md', 'country-competitor-research/SKILL.md')]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    for path in paths:
                        z.writestr(path, SKILL['files'][0]['content'])
            with self.subTest(paths=paths), self.assertRaises(p.PortableError):
                p.import_file('skill.zip', base64.b64encode(buffer.getvalue()).decode())
        for huge, link in [(True, False), (False, True)]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                entry = zipfile.ZipInfo('country-competitor-research/SKILL.md')
                entry.compress_type = zipfile.ZIP_DEFLATED
                if link: entry.external_attr = 0o120777 << 16
                z.writestr(entry, 'x' * (p.MAX_BYTES + 1) if huge else SKILL['files'][0]['content'])
            with self.assertRaises(p.PortableError):
                p.import_file('skill.zip', base64.b64encode(buffer.getvalue()).decode())

    def test_ambiguous_headers_and_cross_job_context_fail_without_silent_loss(self):
        skill = SKILL['files'][0]['content']
        for bad in [skill.replace('name: country', 'name: duplicate\nname: country'),
                    skill.replace('description: Research', 'description: &anchor Research'),
                    skill.replace('description: Research', 'metadata: ' + '[' * 80 + '0' + ']' * 80 + '\ndescription: Research'),
                    skill.replace('name: country', 'name: ../../country')]:
            with self.assertRaises(p.PortableError):
                p.skill_document([{'path': 'SKILL.md', 'content': bad}])
        docs = proposal()['candidates']
        with self.assertRaises(p.PortableError):
            p.prepare_reuse('Continue', [docs[1], docs[1]])
        with self.assertRaises(p.PortableError):
            p.prepare_reuse('Continue', docs, max_chars=1000)
        self.assertEqual(docs[0]['files'], SKILL['files'])

    def test_no_desktop_db_or_provider_is_touched_and_calls_do_not_retain_users(self):
        with patch('sqlite3.connect', side_effect=AssertionError('Web plugin opened a database')):
            first = asyncio.run(web.call('relay_propose_reusable', {'request': 'Make reusable', 'work': WORK}))
            fresh = asyncio.run(web.call('relay_open_reusable', {}))
        self.assertEqual(len(first['candidates']), 1)
        self.assertEqual(fresh['documents'], [])
        with self.assertRaises(Exception):
            asyncio.run(web.call('relay_propose_reusable', {'request': 'Save', 'work': WORK, 'transcript': ['private full chat']}))

    def test_selected_file_url_cannot_fetch_local_services(self):
        for url in ['http://localhost/private', 'https://127.0.0.1/private',
                    'https://files.oaiusercontent.com.evil.example/file', 'https://user:secret@files.oaiusercontent.com/file']:
            with self.subTest(url=url), self.assertRaises(p.PortableError):
                asyncio.run(web.read_selected_file({'download_url': url, 'file_id': 'selected'}))

    def test_selected_chatgpt_file_import_and_expired_or_oversized_links(self):
        import httpx
        original_client = httpx.AsyncClient
        exported = p.review_export(proposal()['candidates'][1], True)
        data = base64.b64decode(exported['data_base64'])
        selected = {'download_url': 'https://files.openai.com/selected', 'file_id': 'file-explicit'}
        def read(status, body):
            def client(**kwargs):
                self.assertFalse(kwargs['follow_redirects'])
                self.assertFalse(kwargs['trust_env'])
                return original_client(**kwargs, transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, content=body)))
            with patch('httpx.AsyncClient', side_effect=client):
                return asyncio.run(web.read_selected_file(selected))
        document = read(200, data)
        self.assertEqual(document['sha256'], exported['sha256'])
        for status, body in [(302, b''), (403, b''), (200, b'a' * (p.MAX_BYTES + 1))]:
            with self.assertRaises(p.PortableError):
                read(status, body)

    def test_stdio_discovery_and_export_protocol_from_another_directory(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def run():
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'task_relay.web_plugin'], cwd=tempfile.gettempdir(),
                env={'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    initialized = await client.initialize()
                    self.assertEqual(initialized.serverInfo.version, web.VERSION)
                    tools = (await client.list_tools()).tools
                    self.assertEqual(len(tools), 6)
                    self.assertFalse(any(t.name == 'relay_commit_change' for t in tools))
                    save = next(t for t in tools if t.name == 'relay_review_export')
                    self.assertEqual(save.meta['ui']['visibility'], ['app'])
                    selected = next(t for t in tools if t.name == 'relay_import_selected_file')
                    self.assertEqual(selected.meta['openai/fileParams'], ['file'])
                    proposed = await client.call_tool('relay_propose_reusable', {'request': 'Make reusable', 'skill': SKILL, 'work': WORK})
                    self.assertFalse(proposed.isError)
                    self.assertFalse(proposed.structuredContent['saved'])
                    item = proposed.structuredContent['candidates'][0]
                    saved = await client.call_tool('relay_review_export', {'document': web.compact_document(item), 'confirmed': True})
                    self.assertFalse(saved.isError)
                    self.assertNotIn('data_base64', json.dumps(saved.structuredContent))
                    imported = await client.call_tool('relay_import_portable_file', {'filename': saved.meta['export']['filename'], 'data_base64': saved.meta['export']['data_base64']})
                    self.assertEqual(imported.structuredContent['documents'][0]['files'], item['files'])
                    resource = await client.read_resource(web.UI_URI)
                    self.assertEqual(resource.contents[0].meta['openai/ui']['availableDisplayModes'], ['inline', 'fullscreen'])
                    self.assertEqual(resource.contents[0].meta['openai/ui']['preferredDisplayMode'], 'inline')
                    self.assertIn('Make this reusable', resource.contents[0].text)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
