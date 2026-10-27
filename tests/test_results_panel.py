"""Compact presentation and verified Open adapter tests; no native/model calls."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import operation_definition as definitions,owner_intents
from task_relay import desktop_workspace as workspace
from task_relay.host import Host,UnsupportedHost
from tests.test_desktop_workspace import WorkspaceTests


class Results(unittest.TestCase):
    def setUp(self):
        WorkspaceTests.setUp(self)
    ready=WorkspaceTests.ready

    def native_fixture(self):
        view=self.ready()
        aid=view['selection_groups'][0]['members'][0]['id']
        artifact=self.rt.artifact(aid)
        attempt=artifact['attempt']
        frozen=json.loads(self.state.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(attempt,)).fetchone()[0])
        frozen.update(execution=dict(capability='blender.mesh_scene',version=1,parameters={}),
                      outputs=owner_intents.native_outputs('blender.mesh_scene'))
        with self.state.db:
            self.state.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(frozen),attempt))
            self.state.db.execute("UPDATE production_artifacts SET path='delivery/scene.blend' WHERE id=?",(aid,))
        return aid,artifact['sha256']

    def test_labels_roles_live_in_existing_presentation_not_execution(self):
        before=copy.deepcopy(definitions.definition('blender.mesh_scene'))
        p=definitions.presentation('blender.mesh_scene')['outputs']
        self.assertEqual(p['scene']['label'],'Blender model')
        self.assertEqual(p['scene']['open_with'],'Blender')
        self.assertEqual(p['preview']['role'],'preview')
        self.assertEqual(p['scene-script']['role'],'technical')
        self.assertEqual(p['execution']['role'],'technical')
        self.assertEqual(definitions.definition('blender.mesh_scene'),before)
        for op in ('gemini.image','rhino.document','rhino3dm.create','pptx.create','web.fetch','images.gallery'):
            with self.subTest(op=op):
                ports=definitions.presentation(op)['outputs']
                self.assertTrue(all(p['label'] and p['role'] in ('primary','preview','technical') for p in ports.values()))
                self.assertFalse(any(p['label'].startswith('Registered operation') for p in ports.values()))

    def test_canvas_and_results_share_names_without_changing_ports(self):
        spec=dict(execution=dict(capability='blender.mesh_scene'),
                  outputs=owner_intents.native_outputs('blender.mesh_scene'))
        original=copy.deepcopy(spec)
        labels={p['path']:workspace._port_presentation(spec,p)['label'] for p in spec['outputs']}
        self.assertEqual(labels['delivery/scene.blend'],'Blender model')
        self.assertEqual(labels['delivery/preview.png'],'Render preview')
        self.assertEqual(spec,original)
        aid,_=self.native_fixture()
        file=self.rt.artifact(aid)
        self.assertEqual(workspace._result_presentation(self.state.db,file)['display_name'],
                         labels[file['path']])
        self.assertEqual(workspace._result_presentation(self.state.db,file)['output_port'],'scene')
        self.assertIsNone(workspace._port_presentation(spec,dict(path='elsewhere/scene.blend')).get('output_port'))
        assignment=self.state.db.execute("SELECT assignment FROM production_tasks WHERE run=? AND id=?",
                                         (file['run'],file['task'])).fetchone()[0]
        saved=json.loads(self.state.db.execute("SELECT spec FROM production_assignments WHERE id=?",(assignment,)).fetchone()[0])
        saved.update(spec)
        with self.state.db:self.state.db.execute("UPDATE production_assignments SET spec=? WHERE id=?",(json.dumps(saved),assignment))
        before=list(self.state.db.iterdump())
        view=workspace.detail(file['run'],self.paths)
        ports=next(t for t in view['tasks'] if t['id']==file['task'])['planned_outputs']
        self.assertEqual({p['path']:p['label'] for p in ports},labels)
        self.assertEqual(list(self.state.db.iterdump()),before)

    def test_open_uses_exact_declared_artifact_and_preserves_original(self):
        aid,sha=self.native_fixture()
        original=Path(self.rt.artifact(aid)['blob']).read_bytes()
        with patch('task_relay.host.HOST.open_result') as opened:
            result=workspace.open_artifact(dict(artifact=aid,sha256=sha),self.paths)
            opened.assert_called_once_with('Blender',result['path'])
            self.assertEqual(Path(result['path']).read_bytes(),original)
            self.assertEqual(Path(self.rt.artifact(aid)['blob']).read_bytes(),original)
        with patch('task_relay.host.HOST.open_result') as opened:
            for value in (dict(artifact=aid,sha256='bad'),dict(artifact=aid,sha256=sha,application='Anything')):
                with self.assertRaises(ValueError):workspace.open_artifact(value,self.paths)
            opened.assert_not_called()
        blob=Path(self.rt.artifact(aid)['blob']);blob.chmod(0o600);blob.write_text('tampered')
        with patch('task_relay.host.HOST.open_result') as opened:
            with self.assertRaisesRegex(ValueError,'changed'):workspace.open_artifact(dict(artifact=aid,sha256=sha),self.paths)
            opened.assert_not_called()

    def test_renaming_an_unrelated_output_cannot_grant_native_open(self):
        view=self.ready();aid=view['selection_groups'][0]['members'][0]['id']
        a=self.rt.artifact(aid)
        with self.state.db:self.state.db.execute("UPDATE production_artifacts SET path='delivery/scene.blend' WHERE id=?",(aid,))
        with patch('task_relay.host.HOST.open_result') as opened:
            with self.assertRaisesRegex(ValueError,'no supported'):workspace.open_artifact(dict(artifact=aid,sha256=a['sha256']),self.paths)
            opened.assert_not_called()

    def test_saved_markdown_links_are_exact_read_only_and_public(self):
        import hashlib
        view=self.ready();aid=view['selection_groups'][0]['members'][0]['id']
        item=self.rt.artifact(aid);blob=Path(item['blob']);blob.chmod(0o600)
        url='https://www.perplexity.ai/search/saved-thread?a=1&b=2#answer'
        content=('[Research]('+url.replace('&','&amp;')+')\n').encode()
        blob.write_bytes(content);sha=hashlib.sha256(content).hexdigest()
        with self.state.db:
            self.state.db.execute("UPDATE production_artifacts SET path='answer.md',sha256=?,bytes=? WHERE id=?",(sha,len(content),aid))
        value=dict(artifact=aid,sha256=sha,url=url);before=list(self.state.db.iterdump())
        self.assertEqual(workspace.artifact_link(value,self.paths),{'url':url})
        for wrong in ['https://www.perplexity.ai/search/saved-thread', 'https://other.example/answer',
                      'file:///etc/passwd','javascript:alert(1)','https://localhost/a','https://127.0.0.1/a',
                      'https://user:password@example.com/a']:
            with self.subTest(url=wrong),self.assertRaises(ValueError):
                workspace.artifact_link(dict(value,url=wrong),self.paths)
        with self.assertRaisesRegex(ValueError,'version'):
            workspace.artifact_link(dict(value,sha256='wrong'),self.paths)
        self.assertEqual(list(self.state.db.iterdump()),before)
        blob.write_bytes(content+b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):
            workspace.artifact_link(value,self.paths)

    def test_saved_link_outside_displayed_preview_cannot_be_opened(self):
        preview=dict(media_type='text/markdown',text='Only this link: https://example.com/article-longer')
        with patch.object(workspace,'artifact_preview',return_value=preview):
            with self.assertRaisesRegex(ValueError,'not in'):
                workspace.artifact_link(dict(artifact='a',sha256='hash',url='https://example.com/article'))

    def test_host_uses_fixed_application_and_disables_embedded_scripts(self):
        with patch('task_relay.host.Path.is_dir',return_value=True),patch('task_relay.host.subprocess.run') as run:
            run.return_value.returncode=0
            Host('darwin').open_result('Blender','/tmp/cup model.blend')
            self.assertEqual(run.call_args.args[0],['/usr/bin/open','-n','-a','/Applications/Blender.app','--args','--disable-autoexec',str(Path('/tmp/cup model.blend').resolve())])
            with self.assertRaises(ValueError):Host('darwin').open_result('Arbitrary','/tmp/x.blend')
        with self.assertRaises(UnsupportedHost):Host('linux').open_result('Blender','/tmp/x.blend')
