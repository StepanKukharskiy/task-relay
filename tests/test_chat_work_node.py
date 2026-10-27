"""Writing requests remain authored work; no provider or publication calls."""
import copy,json,unittest,uuid
from tests import test_same_canvas_rerun as fixture
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts
from orchestrator.workflow_proposal import record

class ChatWorkNode(unittest.TestCase):
    def setUp(self):
        self.f=fixture.SameCanvas();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def test_old_replies_readable_but_new_work_cannot_finish_as_chat_only(self):
        old=dict(message='Saved historical prose',workflow=None)
        self.assertEqual(record(old,{},{}),'reply')
        with self.assertRaisesRegex(ValueError,'Classify'):record(old,{},dict(reply_contract_version=2))
        with self.assertRaisesRegex(ValueError,'work request needs'):record(dict(old,kind='work'),{},dict(reply_contract_version=2))
        for kind in ('answer','clarification'):
            self.assertEqual(record(dict(old,kind=kind),{},dict(reply_contract_version=2)),'reply')
        with self.assertRaisesRegex(ValueError,'kind:work'):record(dict(message='Graph',kind='answer',workflow=self.f.saved['workflow']),{})
    def test_writing_correction_commits_one_editable_node_and_preserves_source(self):
        from orchestrator.operation_records import Store
        from orchestrator.gemini_worker import Files
        source='Stop adding features for their own sake. Do you use Level on your phone?'
        command=dict(request_id=str(uuid.uuid4()),question='Can you help me write a LinkedIn post from this text: '+source,title='Post',
            workflow=dict(schema_version=1,kind='workflow',inputs={},tasks=[]),model=dict(provider='codex',id='gpt-6.1-sol'))
        run=runs.compose_workflow(command)['run'];self.f.rt.tick(run);aid=self.f.rt.task(run,'compose')['latest']
        frozen=self.f.factory.sessions[aid]['frozen'];limits=copy.deepcopy(frozen['limits']);store=Store(frozen,self.f.rt.db)
        from orchestrator.workflow_proposal import REPLY_CONTRACT_VERSION
        self.assertEqual(store.context()['reply_contract_version'],REPLY_CONTRACT_VERSION)
        before=runs.composition_result(dict(request_id=command['request_id']))
        with self.assertRaisesRegex(ValueError,'work request needs'):
            store.submit(dict(request_key='chat-only',revision=0,records=[dict(kind='work',message='A polished post.',workflow=None)]),{})
        self.assertNotIn('workflow',runs.composition_result(dict(request_id=command['request_id'])))
        graph=dict(schema_version=1,kind='workflow',inputs={},tasks=[dict(schema_version=3,id='draft-post',operation='model',objective='Draft a conversational LinkedIn post from Source text. Do not publish it.',
            inputs={'source_text':{'value':source}},input_definitions={'source_text':dict(type='string',label='Source text',required=True)},
            outputs=[dict(name='post',media_type='text/markdown',purpose='LinkedIn post')])])
        store.submit(dict(request_key='node',revision=0,records=[dict(kind='work',message='One editable writing node is ready.',workflow=graph)]),{})
        preview=runs.composition_result(dict(request_id=command['request_id']));self.assertEqual(len(preview['workflow']['tasks']),1)
        self.f.factory.finish(aid);store.export(Files(frozen),complete=True);self.f.rt.tick(run)
        final=runs.composition_result(dict(request_id=command['request_id']));self.assertEqual(final['status'],'completed')
        node=final['workflow']['tasks'][0];self.assertEqual(node['inputs']['source_text']['value'],source);self.assertEqual(node['model'],command['model'])
        saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Draft LinkedIn post',workflow=final['workflow']))
        self.assertEqual(drafts.dispatch('node-draft',{'id':saved['id']})['workflow'],final['workflow'])
        self.assertEqual(frozen['limits'],limits);self.assertEqual(self.f.rt.task(run,'compose')['latest'],aid)
        self.assertEqual([r['id'] for r in self.f.rt.db.execute('SELECT id FROM production_tasks WHERE run=?',(run,))],['compose'])
