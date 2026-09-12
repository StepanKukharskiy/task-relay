import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bridge import State,Bridge
from tests.test_bridge import TelegramFake
import reference_packs as refs
import orchestrator_chat as chat


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.project=self.root/'project';self.project.mkdir()
        self.state=State(self.root/'state.sqlite');self.telegram=TelegramFake();self.bridge=Bridge(self.state,self.telegram,{})
        self.mock=patch.object(refs,'projects',return_value=[str(self.project)]);self.mock.start()
        with self.state.db:self.state.put('chat_id',7);self.state.put('user_id',7)
        (self.project/'AGENTS.md').write_text('Read the production guides; no new authorization.')
        (self.project/'CONTENT_GUIDE.md').write_text('Quiet documentary voice.')
        self.folder=self.production('drawing/draft-04')
        self.worker=refs.Worker(self.state)

    def tearDown(self):
        self.mock.stop();self.state.db.close();self.tmp.cleanup()

    def production(self,name):
        p=self.project/name;p.mkdir(parents=True)
        (p/'BRIEF.md').write_text('Drawing film 65 seconds. Same structure.')
        (p/'hyperframes.json').write_text('{}')
        (p/'index.html').write_text('<img src="assets/picture.png">')
        (p/'assets').mkdir();(p/'assets/picture.png').write_bytes(b'original image')
        return p

    def queue(self,prompt='Use the drawing video draft-04; preserve my complete story.\nNo rendering.',ident=1):
        with self.state.db:refs.enqueue(self.state,{'id':ident,'prompt':prompt},str(self.project))
        return prompt

    def ready(self):
        self.queue();self.worker.tick();self.worker.tick()
        return self.state.db.execute('SELECT * FROM reference_packs').fetchone()

    def click(self,index='0',owner=7):
        r=self.state.db.execute('SELECT * FROM reference_packs').fetchone()
        refs.callback(self.bridge,{'callback_query':{'id':'cb','data':'refs:'+r['token']+':'+index,'from':{'id':owner},'message':{'chat':{'id':7,'type':'private'}}}})

    def test_unique_source_collects_guides_request_hashes_without_runs(self):
        r=self.ready();self.assertEqual(r['status'],'ready')
        m=json.loads(Path(r['manifest']).read_text())
        self.assertEqual(m['original_request'],r['request'])
        self.assertTrue(any(f['source'].endswith('CONTENT_GUIDE.md') for f in m['files']))
        image=next(f for f in m['files'] if f['source'].endswith('picture.png'))
        (self.folder/'assets/picture.png').write_bytes(b'edited source')
        self.assertEqual(Path(image['registered_copy']).read_bytes(),b'original image')
        import sqlite3
        rt=sqlite3.connect(self.root/'state.sqlite')
        self.assertEqual(rt.execute('SELECT count(*) FROM production_runs').fetchone()[0],0);rt.close()
        self.assertIn(r['manifest'],refs.handoff(self.state,r['id']))

    def test_reference_registration_and_delivery_receipt_rollback_together(self):
        self.queue('Use my drawing video.');self.worker.tick()
        original=self.worker.notice
        def fail(ident,kind,text):
            if kind=='ready':raise ValueError('fail before shared commit')
            return original(ident,kind,text)
        with patch.object(self.worker,'notice',side_effect=fail):self.worker.tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'failed')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM media_outbox').fetchone()[0],0)

    def test_ambiguous_versions_require_owner_and_complete_card(self):
        self.production('drawing/draft-05');self.queue('Use my drawing video.')
        self.worker.tick();self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'choosing')
        self.click();self.worker.tick();self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'choosing')
        self.bridge.flush(False);self.click(owner=8)
        self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'choosing')
        self.click('1');self.click('0');self.worker.tick()
        r=self.state.db.execute('SELECT * FROM reference_packs').fetchone();self.assertEqual(r['status'],'ready')
        self.assertTrue(json.loads(r['selected'])['folder'].endswith('draft-05'))

    def test_explicit_version_does_not_pick_portrait(self):
        self.production('drawing/draft-04-vertical');self.queue();self.worker.tick()
        r=self.state.db.execute('SELECT * FROM reference_packs').fetchone()
        self.assertEqual(r['status'],'queued');self.assertEqual(json.loads(r['selected'])['folder'],str(self.folder))

    def test_missing_links_and_excluded_secrets_are_reported(self):
        (self.folder/'index.html').write_text('<img src="missing.png"><a href="../secret.key">secret</a>')
        (self.folder/'.env').write_text('NEVER COPY')
        (self.folder/'node_modules').mkdir();(self.folder/'node_modules/a.js').write_text('dependency')
        (self.folder/'assets/link.png').symlink_to(self.project/'AGENTS.md')
        r=self.ready();m=json.loads(Path(r['manifest']).read_text())
        self.assertTrue(m['requires_review']);self.assertTrue(any('missing.png' in a['path'] for a in m['unresolved']))
        self.assertFalse(any('.env' in a['source'] or 'node_modules' in a['source'] or 'link.png' in a['source'] for a in m['files']))
        self.assertTrue(m['omitted'])

    def test_hyperframes_subcomposition_assets_resolve_from_root(self):
        (self.folder/'compositions').mkdir();(self.folder/'compositions/scene.html').write_text('<img src="assets/picture.png">')
        spec=refs.inventory(self.project,refs.candidate(self.project,self.folder))
        self.assertFalse(spec['unresolved'])

    def test_changed_brief_and_limits_fail_before_copy(self):
        self.queue();self.worker.tick();(self.folder/'BRIEF.md').write_text('changed')
        self.worker.tick();self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'failed')
        with patch.object(refs,'MAX_FILES',1):
            with self.assertRaises(ValueError):refs.inventory(self.project,refs.candidate(self.project,self.folder))

    def test_interrupted_collection_never_retries_automatically(self):
        self.queue()
        with self.state.db:self.state.db.execute("UPDATE reference_packs SET status='collecting'")
        self.worker.tick();self.assertEqual(self.state.db.execute('SELECT status FROM reference_packs').fetchone()[0],'failed')
        self.assertFalse((self.root/'orchestrator').exists())

    def test_tampered_manifest_and_unknown_model_project_are_rejected(self):
        r=self.ready();p=Path(r['manifest']);p.chmod(0o600);p.write_text('{}')
        with self.assertRaises(ValueError):refs.handoff(self.state,r['id'])
        with self.assertRaises(ValueError):chat.interpret(json.dumps({'answer':'x','action':{'kind':'collect_references','project':'/etc'}}),{'reference_projects':[str(self.project)]})

    def test_documents_and_reply_mapping(self):
        r=self.ready();self.bridge.flush()
        self.assertEqual(len(self.telegram.media),2)
        self.assertTrue(self.state.db.execute('SELECT 1 FROM orchestrator_messages WHERE focus=?',(r['id'],)).fetchone())

    def test_ready_pack_is_bound_to_real_routing_prompt(self):
        import task_routing
        r=self.ready();path=self.root/'task.jsonl'
        path.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':'old'}})+'\n')
        tasks=[dict(id='planner',name='Planner',cwd=str(self.project),rollout_path=str(path),updated_at=1)]
        calls=[]
        class Desktop:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ready_owner(self,tid):return 'owner'
            def start(self,tid,prompt,owner):calls.append(prompt)
        with patch('bridge.local_tasks',return_value=tasks):
            c=task_routing.catalog(self.state)
            with self.state.db:task_routing.register(self.state,{'id':2,'prompt':'Plan the next film; do not render.'},c,False,reference_pack_id=r['id'])
            task_routing.Worker(self.state,Desktop).tick()
        self.assertEqual(len(calls),1)
        self.assertIn('Plan the next film; do not render.',calls[0]);self.assertIn(r['manifest'],calls[0])
        manifest=json.loads(Path(r['manifest']).read_text())
        self.assertEqual(manifest['original_request'],r['request'])

    def test_duplicate_collection_does_not_duplicate_registered_assets(self):
        first=self.ready();before=json.loads(Path(first['manifest']).read_text())
        self.queue(ident=3);self.worker.tick();self.worker.tick()
        second=self.state.db.execute('SELECT * FROM reference_packs WHERE job_id=3').fetchone()
        after=json.loads(Path(second['manifest']).read_text())
        a={f['source']:f['artifact'] for f in before['files'] if '/REQUEST.md' not in f['source']}
        b={f['source']:f['artifact'] for f in after['files'] if '/REQUEST.md' not in f['source']}
        self.assertEqual(a,b)

    def test_pack_can_reach_linked_planner_without_expanding_execution_scope(self):
        import workflows,workflow_protocol
        r=self.ready()
        data=dict(name='demo',cwd=str(self.project),strategy_id='planner',executor_id='executor',
                  strategy_title='Planner',executor_title='Executor',status='paused',phase='done',accepted=0,step_limit=1,attempts=0)
        with self.state.db:self.state.db.execute('INSERT INTO workflows(name,data) VALUES (?,?)',('demo',json.dumps(data)))
        snap=chat.snapshot(self.state,None)
        action={'kind':'plan','workflow':'demo','items':None,'direction':'Inspect missing inputs only.','reference_pack_id':r['id']}
        chat.interpret(json.dumps({'answer':'Plan','action':action}),snap)
        source={'text':'Plan using this reference pack; no production.','reference_context':refs.handoff(self.state,r['id'])}
        workflows.command(self.bridge,'plan demo Inspect missing inputs only.',999,source_request=source)
        d,_=workflows.read(self.state,'demo');prompt=workflow_protocol.prompt(d,'planning','marker')
        self.assertIn(r['manifest'],prompt);self.assertIn('READ-ONLY PLANNING',prompt)
        self.assertEqual(d['attempts'],0)

    def test_external_file_reference_is_not_collected(self):
        external=self.root/'external.md';external.write_text('outside project')
        (self.folder/'index.html').write_text('<a href="'+str(external)+'">outside</a>')
        spec=refs.inventory(self.project,refs.candidate(self.project,self.folder))
        self.assertTrue(any(m['reason'].startswith('Reference is outside') for m in spec['unresolved']))
        self.assertFalse(any(f['source']==str(external) for f in spec['files']))
