"""A corrected typed worker reads its exact prior candidate; no provider/network calls."""
import copy,json
from unittest.mock import Mock,patch
from orchestrator import artifact_roles,agent_loop,executors
from tests import test_sourcing_records as fixture

class Tests(fixture.unittest.TestCase):
    setUp=fixture.Tests.setUp
    input=fixture.Tests.input
    assignment=fixture.Tests.assignment
    save=fixture.Tests.save
    option=fixture.Tests.option
    item=fixture.Tests.item

    def bound(self):
        f=copy.deepcopy(self.frozen);f['id']='producer'
        prior=self.input('prior.json',dict(finding='Replace unsupported dimension; prior amount is not accepted.'))
        f['inputs'].append(prior)
        for i in f['inputs']:i['media_type']='application/json'
        for o in f['outputs']:o['media_type']='text/markdown' if o['path'].endswith('.md') else 'application/json'
        artifact_roles.bind(f,None,[]);self.save(f)
        control=self.root/'control';control.mkdir(exist_ok=True)
        (control/'launch.json').write_text(fixture.contracts.encoded(dict(credential_fingerprint=executors.fingerprint(fixture.CONFIG,fixture.BACKEND))))
        return f,control

    def test_prior_version_text_is_readable_during_bounded_fragment_lifecycle(self):
        f,control=self.bound();prior=(self.root/'prior.json').read_bytes()
        script=Mock();script.request.side_effect=[
            fixture.response('file_read',dict(path='prior.json',offset=0,limit=2000)),
            fixture.response('operation_submit',dict(request_key='one',revision=0,records=[self.item()])),
            fixture.response('operation_submit',dict(request_key='two',revision=1,records=[self.item('item-b',0)])),
            fixture.response('finish',dict(summary='Exact prior correction inspected; two evidence-bound entries saved.',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Exact prior text read; fields bound to saved observations.')}))]
        result=agent_loop.execute(f,control,script,lambda:(fixture.CONFIG,fixture.BACKEND))
        self.assertEqual(result['decision'],'delivered')
        receipt=json.loads((control/'tool-01-00.json').read_text())['result']
        self.assertEqual(receipt['text'],prior.decode())
        self.assertEqual((self.root/'prior.json').read_bytes(),prior)
        names={d['name'] for d in script.request.call_args_list[0].args[1]['tools'][0]['functionDeclarations']}
        self.assertIn('file_read',names)
        self.assertTrue({'file_write','file_append','python_run'}.isdisjoint(names))
        self.assertEqual(len(json.loads((self.root/f['operation_contract']['output']).read_text())['items']),2)

    def test_missing_declared_reader_stops_before_model_request(self):
        f,control=self.bound();script=Mock();original=agent_loop.definitions
        def hidden(*args,**kwargs):return [t for t in original(*args,**kwargs) if t['name']!='file_read']
        with patch.object(agent_loop,'definitions',hidden),self.assertRaisesRegex(ValueError,'absent from worker tools'):
            agent_loop.execute(f,control,script,lambda:(fixture.CONFIG,fixture.BACKEND))
        script.request.assert_not_called()

    def test_legacy_fragment_scope_is_not_silently_expanded(self):
        self.assertNotIn('file_read',{t['name'] for t in agent_loop.definitions(self.frozen)})
