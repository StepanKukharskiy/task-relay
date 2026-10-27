"""Authoring persists the node document, never a run or a replacement for a saved run."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from task_relay import desktop_node_drafts as drafts

class Drafts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);p=patch.object(drafts,'PATHS',SimpleNamespace(data=self.root));p.start();self.addCleanup(p.stop)
        self.workflow=json.loads(Path('examples/reusable-summary.workflow.json').read_text())
    def save(self,w=None,**kw):
        return drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Article summary',workflow=w or self.workflow,**kw))
    def test_save_reload_exact_document_and_missing_values_without_execution(self):
        original=copy.deepcopy(self.workflow);saved=self.save()
        self.assertFalse(saved['execution_authorized']);self.assertIn('workflow.article_url',saved['missing_inputs'])
        loaded=drafts.dispatch('node-draft',{'id':saved['id']})
        self.assertEqual(loaded['workflow'],original);self.assertEqual(self.workflow,original)
        self.assertEqual(drafts.dispatch('node-drafts',{})['items'][0]['id'],saved['id'])
        self.assertFalse((self.root/'state.sqlite').exists())
    def test_stale_save_is_rejected_and_current_document_preserved(self):
        old=self.save();changed=copy.deepcopy(self.workflow);changed['tasks'][1]['objective']='A different summary'
        updated=drafts.dispatch('node-draft-save',dict(id=old['id'],revision=old['revision'],title='Changed',workflow=changed))
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):
            drafts.dispatch('node-draft-save',dict(id=old['id'],revision=old['revision'],title='Overwrite',workflow=self.workflow))
        self.assertEqual(drafts.dispatch('node-draft',{'id':old['id']})['revision'],updated['revision'])
    def test_listing_uses_saved_file_activity_without_rewriting_legacy_draft(self):
        saved=self.save();path=self.root/'node-drafts'/(saved['id']+'.json')
        original=path.read_bytes();os.utime(path,(1000,2000))
        listed=drafts.dispatch('node-drafts',{})['items'][0]
        self.assertEqual(listed['stamp'],2000)
        self.assertEqual(path.read_bytes(),original)
    def test_bad_connection_type_cycle_and_unknown_operation_do_not_replace_draft(self):
        old=self.save()
        for change in ('port','type','cycle','operation'):
            w=copy.deepcopy(self.workflow)
            if change=='port':w['tasks'][1]['inputs']['article']['output']='invented'
            if change=='type':w['tasks'][1]['input_definitions']['article']['media_type']='image/png'
            if change=='cycle':w['tasks'][0]['dependencies']=['summary']
            if change=='operation':w['tasks'][0]['operation']='not.registered'
            with self.subTest(change=change),self.assertRaises(ValueError):
                drafts.dispatch('node-draft-save',dict(id=old['id'],revision=old['revision'],title='Bad',workflow=w))
        self.assertEqual(drafts.dispatch('node-draft',{'id':old['id']})['workflow'],self.workflow)
    def test_paths_and_extra_authority_are_rejected(self):
        for ident in ('../state.sqlite','',34):
            with self.assertRaises(ValueError):drafts.dispatch('node-draft',{'id':ident})
        with self.assertRaises(ValueError):drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Bad',workflow=self.workflow,run=True))
    def test_incomplete_registered_input_is_saved_but_not_ready(self):
        w=copy.deepcopy(self.workflow);w['tasks']=w['tasks'][:1];w['tasks'][0]['inputs']={};w['inputs']={}
        result=self.save(w);self.assertEqual(result['missing_inputs'],['article.url'])
