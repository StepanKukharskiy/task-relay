"""Offline canvas admission, shared connections and exact graph execution."""
import copy,json,os,sqlite3,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from task_relay import desktop_node_runs as runs,desktop_node_drafts as drafts,credentials
from orchestrator import executors,node_spec,contracts
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory

class Canvas(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.paths=SimpleNamespace(data=self.root,state=self.root/'state.sqlite')
        self.paths.state.touch();rt=Runtime(self.root/'orchestrator');rt.close()
        with sqlite3.connect(self.paths.state) as db:
            db.execute('CREATE TABLE outbox(id TEXT)');db.execute('CREATE TABLE relay_channel_bindings(kind TEXT,entity TEXT,after_row INT,channel TEXT,PRIMARY KEY(kind,entity))')
        def database(writable=False):
            db=sqlite3.connect(str(self.paths.state) if writable else self.paths.state.as_uri()+'?mode=ro',uri=not writable);db.row_factory=sqlite3.Row;return db
        for p in (patch.object(runs,'PATHS',self.paths),patch.object(drafts,'PATHS',self.paths),patch.object(runs,'_database',database),patch.object(executors,'available'),patch('orchestrator.execution.available')):
            p.start();self.addCleanup(p.stop)
        self.w={'schema_version':1,'kind':'workflow','inputs':{},'tasks':[
            dict(schema_version=3,id='write',operation='model',objective='Write a sentence',inputs={},input_definitions={},outputs=[dict(name='text',media_type='text/plain',purpose='Text')],model=dict(provider='gemini',id='first')),
            dict(schema_version=3,id='summary',operation='model',objective='Summarize',inputs={'article':{'task':'write','output':'text'}},input_definitions={'article':dict(type='artifact',label='Article',media_type='text/plain',required=True)},outputs=[dict(name='result',media_type='text/plain',purpose='Summary')],model=dict(provider='gemini',id='second'))]}
        self.saved=drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Offline graph',workflow=self.w))
        self.request=dict(id=self.saved['id'],revision=self.saved['revision'],values={},request_id=str(uuid.uuid4()))
    def command(self):
        p=runs.preview(self.request);return dict(**self.request,fingerprint=p['fingerprint'],allow_paid=True)
    def test_exact_models_saved_graph_and_composed_runtime_restart(self):
        p=runs.preview(self.request);self.assertEqual(p['paid_nodes'],['write','summary']);self.assertEqual(len(p['plan']['tasks']),2)
        chosen=[t['worker']['backend']['model'] for t in p['plan']['tasks']];self.assertEqual(chosen,['first','second'])
        command=self.command();receipt=runs.start(command);self.assertFalse(receipt['reused']);self.assertTrue(runs.start(command)['reused'])
        factory=FakeFactory();rt=Runtime(self.root/'orchestrator',factory)
        rt.tick(receipt['run']);a=rt.task(receipt['run'],'write')['latest'];factory.finish(a);rt.tick(receipt['run'])
        b=rt.task(receipt['run'],'summary')['latest'];self.assertIsNotNone(b)
        frozen=factory.sessions[b]['frozen'];self.assertEqual(frozen['worker']['backend']['model'],'second')
        self.assertEqual(frozen['inputs'][0]['sha256'],rt.output(receipt['run'],'write',p['plan']['tasks'][0]['outputs'][0]['path'])['sha256'])
        rt.close();rt=Runtime(self.root/'orchestrator',factory);factory.finish(b);rt.tick(receipt['run']);self.assertEqual(rt.status(receipt['run'])['status'],'completed');rt.close()
        self.assertEqual(len(factory.calls),2);self.assertTrue(runs.start(command)['reused'])
        self.assertEqual(drafts.dispatch('node-draft',{'id':self.saved['id']})['workflow'],self.w)
    def test_no_dispatch_without_paid_opt_in_or_on_stale_draft(self):
        c=self.command();c['allow_paid']=False
        with self.assertRaisesRegex(ValueError,'Paid API'):runs.start(c)
        changed=copy.deepcopy(self.w);changed['tasks'][0]['objective']='Changed'
        drafts.dispatch('node-draft-save',dict(id=self.saved['id'],revision=self.saved['revision'],title='Changed',workflow=changed))
        with self.assertRaisesRegex(ValueError,'Draft changed'):runs.start({**c,'allow_paid':True})
        with sqlite3.connect(self.paths.state) as db:self.assertEqual(db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
    def test_changed_command_identity_and_unregistered_run_are_not_replayed(self):
        c=self.command();r=runs.start(c)
        with self.assertRaisesRegex(ValueError,'another command'):runs.start({**c,'allow_paid':False})
        with self.assertRaisesRegex(ValueError,'explicitly admitted'):runs.advance({'run':'historical'})
        with sqlite3.connect(self.paths.state) as db:db.execute("UPDATE production_runs SET plan=json_set(plan,'$.brief','changed')")
        with self.assertRaisesRegex(ValueError,'contract changed'):runs.advance({'run':r['run']})
    def test_atomic_failure_rolls_back_admission(self):
        with patch('task_relay.relay_channels.bind',side_effect=ValueError('fixture interrupted')):
            with self.assertRaisesRegex(ValueError,'interrupted'):runs.start(self.command())
        with sqlite3.connect(self.paths.state) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM desktop_node_runs').fetchone()[0],0)
    def test_legacy_owner_cannot_silently_override_model(self):
        with self.assertRaisesRegex(ValueError,'explicit workflow admission'):node_spec.legacy_tasks({'tasks':self.w['tasks']},3)
    def test_no_hidden_nodes_in_public_read_summary(self):
        w=json.loads(Path('examples/reusable-summary.workflow.json').read_text());w['tasks'][1]['model']=dict(provider='codex',id='gpt-6.1-sol')
        with tempfile.TemporaryDirectory() as d:
            rt=Runtime(Path(d));p=runs.compile_plan(rt,w,{'article_url':'https://example.com'},'offline','Summary');rt.close()
        self.assertEqual([t['id'] for t in p['plan']['tasks']],['article','summary']);self.assertEqual(p['paid_nodes'],[])

class Connections(unittest.TestCase):
    def test_node_connection_validation_preserves_existing_keys_and_writes_locally(self):
        from task_relay import desktop_node_setup as setup,onboarding
        from task_relay.desktop_plans import DesktopPlanError
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            credentials.save(root/'gemini.json',{'api_key':'old-fixture','models':{'text':'text-default'}})
            before=(root/'gemini.json').read_bytes()
            with patch.object(setup,'PATHS',SimpleNamespace(data=root)),patch.object(onboarding,'setup_lock',return_value=nullcontext()):
                for key in ('','   ','secret\ninvalid'):
                    with self.assertRaisesRegex(DesktopPlanError,'single-line') as error:
                        setup.connect(dict(provider='gemini',key=key,model='image-fixture'))
                    self.assertNotIn('secret',str(error.exception))
                    self.assertEqual((root/'gemini.json').read_bytes(),before)
                    self.assertFalse((root/'.env').exists())
                with self.assertRaisesRegex(DesktopPlanError,'model'):
                    setup.connect(dict(provider='gemini',key='new-fixture',model=''))
                setup.connect(dict(provider='gemini',key='new-fixture',model='image-fixture'))
                config=credentials.private_json(root/'gemini.json')
                self.assertNotIn('api_key',config)
                self.assertEqual(config['models']['text'],'text-default')
                self.assertEqual(credentials.resolve(config['api_key_ref']),'new-fixture')
                self.assertEqual((root/'.env').stat().st_mode&0o777,0o600)
    def test_dotenv_literal_shared_private_no_shell_or_secret_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'.env';key='$(do-not-run) dollar$ quote\' #value'
            credentials.save_dotenv(p,'OPENAI_API_KEY',key);credentials.save_dotenv(p,'GEMINI_API_KEY','other')
            self.assertEqual(credentials.resolve(dict(source='dotenv',path=str(p),name='OPENAI_API_KEY')),key)
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            credentials.save_dotenv(p,'OPENAI_API_KEY','replacement');self.assertEqual(credentials.dotenv_values(p),dict(OPENAI_API_KEY='replacement',GEMINI_API_KEY='other'))
            p.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'private'):credentials.dotenv_values(p)
            p.chmod(0o600);p.write_text('KEY=secret\nKEY=secret\n')
            with self.assertRaisesRegex(ValueError,'duplicate') as cm:credentials.dotenv_values(p)
            self.assertNotIn('secret',str(cm.exception))
            link=Path(d).resolve()/'link';link.symlink_to(p)
            with self.assertRaisesRegex(ValueError,'symbolic'):credentials.save_dotenv(link,'KEY','new')
    def test_two_models_same_key_survive_default_changes_but_not_key_change(self):
        from task_relay import gemini
        with tempfile.TemporaryDirectory() as d:
            config={'api_key':'fixture'};default={'type':'gemini-agent','model':'first'}
            def receipt(provider='gemini',model=None):return Path(d)/((model or 'default')+'.json')
            with patch.object(executors,'receipt_path',receipt),patch.object(executors,'configured',return_value=(config,default)),patch.object(gemini.Client,'request',side_effect=lambda path,**kw:dict(name=path,supportedGenerationMethods=['generateContent'])):
                executors.probe('gemini','first');executors.probe('gemini','second')
                self.assertEqual(default['model'],'first','probe cannot mutate the configured backend')
                default['model']='third'
                for m in ('first','second'):self.assertEqual(executors.selected_configuration(dict(type='gemini-agent',model=m))[1]['model'],m)
                config['api_key']='changed'
                with self.assertRaisesRegex(ValueError,'Verify'):executors.selected_configuration(dict(type='gemini-agent',model='first'))
