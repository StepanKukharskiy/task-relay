import json
from pathlib import Path
import unittest

from tests import test_task_routing as fixture
from task_relay import routing_inputs as inputs
from task_relay import production_control as pc
from task_relay import orchestrator_chat as chat
from orchestrator.runtime import file_hash


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    click=fixture.Tests.click

    def guides(self):
        folder=self.root/'pipeline/projects/test-linkedin';folder.mkdir(parents=True)
        for name in ('AGENTS.md','about-me.md','audience.md','CONTENT_PRODUCTION_GUIDE.md'):
            (folder/name).write_text('Original guide: '+name)
        return folder

    def research(self,ident,name):
        path=pc.root(self.state).parent/'production-guides'/str(ident)/name
        path.parent.mkdir(parents=True);path.write_text('Research source '+name)
        with self.state.db:
            self.state.db.execute("INSERT INTO production_uploads(id,run,file_id,filename,caption,declared_size,status,path,sha256,bytes) VALUES (?,'video','local-research',?,'',?,'used',?,?,?)",(ident,name,path.stat().st_size,str(path),file_hash(path),path.stat().st_size))
            self.state.db.execute('INSERT INTO production_folder_files VALUES (?,?,?,?)',('video',name,file_hash(path),ident))
        return path

    def test_chosen_codex_task_receives_both_sources_and_guides(self):
        self.guides();self.research(-1,'history.md');self.research(-2,'market.md')
        prompt='Use 2 of my research docs for video to create a LinkedIn post.'
        self.request({'kind':'discover_guides'},prompt)
        self.bridge.flush(False)
        choice=self.state.db.execute('SELECT * FROM orchestrator_guide_choices').fetchone()
        self.bridge.process({'update_id':89,'callback_query':{'id':'g','data':'guides:'+choice['token']+':all','from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}})
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Choose destination','action':{'kind':'choose_task','task_ids':['t0','t1'],'research_ids':[-1,-2]}})).tick()
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone()
        manifest=json.loads(row['input_manifest'])
        self.assertEqual(len(manifest),3)
        self.bridge.flush(False);self.click('1');self.worker.tick()
        manifest=json.loads(self.state.db.execute('SELECT input_manifest FROM task_routes').fetchone()[0])
        sent=self.calls[0][1];self.assertIn(prompt,sent)
        for d in manifest:
            self.assertIn(d['path'],sent);self.assertEqual(file_hash(Path(d['path'])),d['sha256'])
        self.assertEqual(self.calls[0][0],'t1')
        receipt=chat.snapshot(self.state,None)['routed_requests'][0]
        self.assertTrue(receipt['inputs_sent']);self.assertEqual(len(receipt['included_inputs']),3)

    def test_known_guides_do_not_turn_an_empty_original_handoff_into_attachment_proof(self):
        self.guides()
        with self.state.db:inputs.guide_paths(str(self.root),'LinkedIn',self.state)
        self.request({'kind':'route_task','task_id':'t0'},'Inspect this project.')
        self.worker.tick()
        receipt=chat.snapshot(self.state,None)['routed_requests'][0]
        self.assertEqual(receipt['status'],'submitted')
        self.assertFalse(receipt['inputs_sent']);self.assertEqual(receipt['included_inputs'],[])

    def test_remembered_guide_location_refreshes_content_for_next_request(self):
        folder=self.guides()
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            first=inputs.propose_guides(self.state,{'id':91,'prompt':'Draft a LinkedIn post'},str(self.root))['guides']
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM project_guide_profiles').fetchone()[0],1)
        (folder/'CONTENT_PRODUCTION_GUIDE.md').write_text('Updated voice direction')
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            second=inputs.propose_guides(self.state,{'id':92,'prompt':'Draft a LinkedIn post'},str(self.root))['guides']
        old=next(d for d in first if d['name'].endswith('CONTENT_PRODUCTION_GUIDE.md'))
        new=next(d for d in second if d['name'].endswith('CONTENT_PRODUCTION_GUIDE.md'))
        self.assertNotEqual(old['sha256'],new['sha256'])
        self.assertIn('Original',Path(old['path']).read_text())
        self.assertEqual(Path(new['path']).read_text(),'Updated voice direction')

    def test_tampered_frozen_source_stops_before_codex_submission(self):
        self.research(-1,'history.md')
        self.request({'kind':'route_task','task_id':'t0','research_ids':[-1]},'Use my research document.')
        row=self.state.db.execute('SELECT * FROM task_routes').fetchone();d=json.loads(row['input_manifest'])[0]
        path=Path(d['path']);path.chmod(0o600);path.write_text('tampered')
        self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.state.db.execute('SELECT status FROM task_routes').fetchone()[0],'failed')

    def test_ambiguous_research_blocks_and_removed_cached_guide_is_not_reused(self):
        self.research(-1,'history.md');self.research(-2,'market.md');self.research(-3,'extra.md')
        self.request({'kind':'route_task','task_id':'t0'},'Use 2 research docs to draft a post.')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM task_routes').fetchone()[0],0)
        folder=self.guides()
        with self.state.db:inputs.guide_paths(str(self.root),'LinkedIn',self.state)
        (folder/'CONTENT_PRODUCTION_GUIDE.md').unlink()
        self.assertEqual(inputs.guide_paths(str(self.root),'LinkedIn',self.state),[])


if __name__=='__main__':unittest.main()
