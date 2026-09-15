import json
from pathlib import Path
from unittest.mock import patch
import unittest

from task_relay import production_folders as pf
from task_relay import production_control as pc
from task_relay import orchestrator_chat as chat
from tests import test_production_control as fixtures


class Tests(unittest.TestCase):
    message=fixtures.Tests.message
    click=fixtures.Tests.click
    worker=fixtures.Tests.worker
    stage_card=fixtures.Tests.stage_card
    finish_stage=fixtures.Tests.finish_stage
    revision_card=fixtures.Tests.revision_card
    def setUp(self):
        fixtures.Tests.setUp(self)
        self.base=Path(self.temp.name).resolve()/'Productions'
        self.patch=patch.object(pf,'base_folder',return_value=self.base);self.patch.start()
    def tearDown(self):
        self.patch.stop();fixtures.Tests.tearDown(self)

    def action(self,kind,ident=200):
        self.message('/orchestrator Create a research folder for demo',ident)
        result=dict(answer='Requested.',action=dict(kind=kind,workflow='demo',items=None,direction=''))
        chat.Worker(self.state,lambda *_:json.dumps(result)).tick()
        return self.state.db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(ident,)).fetchone()

    def test_create_routes_without_worker_or_card_and_survives_repeated_request(self):
        job=self.action('create_production_folder')
        self.assertEqual(job['status'],'answered')
        path=self.base/'demo'
        self.assertTrue((path/'research').is_dir())
        self.assertIn(str(path/'research'),job['answer'])
        (path/'README.md').write_text('My edited instructions')
        self.action('create_production_folder',201)
        self.assertEqual((path/'README.md').read_text(),'My edited instructions')
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals').fetchone()[0],0)
        self.assertEqual(pc.inspect(self.state)[0]['research_folder']['path'],str(path))
        self.bridge.flush(False)
        self.assertTrue(self.state.db.execute("SELECT 1 FROM orchestrator_messages WHERE focus='demo'").fetchone())

    def test_existing_unlinked_directory_and_symlink_are_not_adopted(self):
        path=self.base/'demo';path.mkdir(parents=True)
        (path/'mine.txt').write_text('keep')
        with self.assertRaises(ValueError):pf.create(self.state,'demo')
        self.assertEqual((path/'mine.txt').read_text(),'keep')
        other=self.base/'other';other.mkdir()
        link=self.base/'link';link.symlink_to(other,target_is_directory=True)
        with patch.object(pf,'base_folder',return_value=link):
            with self.assertRaises(ValueError):pf.create(self.state,'demo')

    def test_import_copies_bytes_deduplicates_and_retains_editable_original(self):
        self.action('create_production_folder')
        source=self.base/'demo/research/market.md';source.write_text('Market evidence, URL and date')
        job=self.action('import_production_research',201)
        self.assertEqual(job['status'],'answered')
        row=self.state.db.execute('SELECT * FROM production_uploads').fetchone()
        self.assertEqual(Path(row['path']).read_text(),source.read_text())
        source.write_text('Updated evidence')
        self.assertEqual(Path(row['path']).read_text(),'Market evidence, URL and date')
        self.action('import_production_research',202)
        self.action('import_production_research',203)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_uploads').fetchone()[0],2)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM production_uploads WHERE status='ready'").fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_revision_automatically_snapshots_linked_research_for_both_workers(self):
        worker=self.finish_stage()
        with self.state.db:pf.create(self.state,'demo')
        source=self.base/'demo/research/evidence.txt';source.write_text('Checked research')
        card=self.revision_card('Use the research in my folder',200)
        self.assertIsNotNone(card)
        self.click(card['token']);worker.tick()
        for tid in ('produce','review'):
            files=self.rt.spec(self.rt.task('demo',tid))['inputs']
            self.assertTrue(any(f['path'].endswith('evidence.txt') for f in files))
        self.assertEqual(source.read_text(),'Checked research')

    def test_import_rejects_links_and_oversized_batch_without_partial_staging(self):
        with self.state.db:pf.create(self.state,'demo')
        root=self.base/'demo/research'
        outside=self.base/'outside.txt';outside.write_text('outside')
        link=root/'linked.txt';link.symlink_to(outside)
        with self.assertRaises(ValueError):pf.import_research(self.state,'demo')
        link.unlink()
        for i in range(11):(root/f'{i}.txt').write_text('research')
        with self.assertRaises(ValueError):pf.import_research(self.state,'demo')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_uploads').fetchone()[0],0)

    def test_unknown_production_and_model_supplied_paths_are_rejected(self):
        snap=chat.snapshot(self.state,'demo')
        for action in (dict(kind='create_production_folder',workflow='unknown',items=None,direction=''),
                       dict(kind='create_production_folder',workflow='demo',items=None,direction='',path='/tmp/arbitrary')):
            with self.assertRaises(ValueError):chat.interpret(json.dumps(dict(answer='a',action=action)),snap)
