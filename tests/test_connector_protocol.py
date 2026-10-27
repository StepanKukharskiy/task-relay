"""Registry-wide structural checks and controller recovery; no live transports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import connector_protocol as protocol, execution, handoff_contracts as handoff
from orchestrator.runtime import Runtime
from tests.test_orchestrator import FakeFactory, plan, task
from tests.test_mixed_execution import operation


def stage(ident, capability, inputs=()):
    ports=protocol.interface(capability)['outputs']['ports']
    outputs={('result' if port=='*' else port):dict(media_type=media) for port,media in ports.items()}
    return dict(id=ident,route='production',capabilities=[capability],deliverables={p:p for p in outputs},
        handoff=dict(inputs=list(inputs),outputs=outputs))


class RegistryTests(unittest.TestCase):
    def test_every_registered_directed_port_pair_uses_the_compiler_boundary(self):
        report=protocol.conformance()
        self.assertEqual(set(report['interfaces']),set(execution.REGISTRY))
        expected=sum(len(x['outputs']['ports']) for x in report['interfaces'].values())*len(execution.REGISTRY)
        self.assertEqual(len(report['pairs']),expected)
        for pair in report['pairs']:
            with self.subTest(**pair):
                source=stage('source',pair['producer'])
                port='result' if pair['port']=='*' else pair['port']
                media=source['handoff']['outputs'][port]['media_type']
                target=stage('target',pair['consumer'],[dict(stage='source',deliverable=port,media_type=media,consumer=pair['consumer'])])
                if pair['status']=='incompatible':
                    with self.assertRaises(handoff.ContractError):handoff.compile_workflow([source,target],required=True)
                else:
                    result=handoff.compile_workflow([source,target],required=True)
                    self.assertEqual(result['edge_checks'][0]['status'],'requires_runtime_validation')
                    self.assertIn('bound_parameters_and_content',result['edge_checks'][0]['runtime_checks'])

    def test_same_mime_does_not_accept_different_content_contract_or_capacity(self):
        target=protocol.interface('pptx.create')
        source=dict(media_type='application/json',content_contract={'id':'a','version':1})
        self.assertEqual(protocol.edge(source,target,content_contract={'id':'a','version':2})['status'],'incompatible')
        self.assertEqual(protocol.edge(source,target,max_bytes=target['inputs']['max_bytes']+1)['status'],'incompatible')
        self.assertEqual(protocol.edge(source,target)['status'],'requires_runtime_validation')

    def test_saved_definition_drift_is_rejected_even_without_version_bump(self):
        captured=protocol.capture('text.bundle')
        saved=dict(id='text.bundle',**copy.deepcopy(execution.REGISTRY['text.bundle']),connector_interface=captured)
        for field,value in [('permissions','Expanded authority'),('criteria',['Different review']),('input_bytes',1)]:
            with self.subTest(field=field),patch.dict(execution.REGISTRY['text.bundle'],{field:value}):
                with self.assertRaisesRegex(ValueError,'changed since capture'):handoff.operation('text.bundle',saved)
        handoff.operation('text.bundle',saved)
        self.assertEqual(saved['connector_interface'],captured)

    def test_new_registry_entries_must_declare_effect_scope(self):
        for key in ('permissions','cancellation','external_requests'):
            spec=copy.deepcopy(execution.REGISTRY['text.bundle']);spec.pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):protocol.interface('text.bundle',spec)

    def test_receipt_uncertainty_wins_over_success_and_cancellation(self):
        for evidence in ({'pending_requests':['request-1']},{'external_outcome':'unknown'},
                         {'browser':{'uncertain_actions':['click-1']}},{'computer':{'uncertain_actions':['action-1']}},
                         {'operation':{'outcome':'uncertain'}}):
            for code in (0,-15):
                raw=dict(status='finished',exit_code=code,reason=None,**evidence)
                normalized=protocol.receipt(raw)
                self.assertEqual(normalized['status'],'uncertain')
                self.assertEqual(normalized['connector_receipt']['original'],raw)
                self.assertEqual(normalized['connector_receipt']['raw_sha256'],protocol.digest(raw))
                self.assertFalse(normalized['connector_receipt']['acceptance'])
        self.assertEqual(protocol.receipt(dict(status='finished',exit_code=0))['connector_receipt']['effect'],'unspecified')


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.factory=FakeFactory();self.rt=Runtime(self.root/'runtime',self.factory)

    def tearDown(self):self.rt.close();self.temp.cleanup()

    def test_admission_freezes_contract_and_restart_refuses_changed_dispatch(self):
        source=self.root/'input.txt';source.write_text('Small exact input')
        artifact=self.rt.register(source,'Fixture',path='input.txt')
        spec=operation('produce','text.bundle',[dict(artifact=artifact,path='input.txt',purpose='Source',authority='Data only',media_type='text/plain')])
        self.rt.create(plan([spec]));saved=self.rt.spec(self.rt.task('demo','produce'))
        self.assertEqual(saved['connector_interface'],protocol.capture('text.bundle'))
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory)
        with patch.dict(execution.REGISTRY['text.bundle'],permissions='Different execution scope'):
            status=self.rt.tick('demo')
        self.assertEqual(self.factory.calls,[])
        self.assertEqual(status['attempts'],[])
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.rt.spec(self.rt.task('demo','produce')),saved)

    def test_unresolved_terminal_effect_survives_restart_then_collects_same_attempt(self):
        self.rt.create(plan());self.rt.tick('demo');aid=self.factory.calls[0]
        self.factory.finish(aid)
        raw=self.factory.sessions[aid]['status'];raw['pending_requests']=['request-1']
        status=self.rt.tick('demo')
        self.assertEqual(status['artifacts'],[])
        self.assertEqual(self.rt.task('demo','produce')['status'],'uncertain')
        self.rt.close();self.rt=Runtime(self.root/'runtime',self.factory);self.rt.tick('demo')
        self.assertEqual(self.factory.calls,[aid])
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        status=self.rt.tick('demo')
        self.assertEqual(status['status'],'completed')
        self.assertEqual(len(status['attempts']),1)
        self.assertEqual(self.factory.calls,[aid])
        events=[json.loads(r[0]) for r in self.rt.db.execute("SELECT data FROM production_events WHERE kind='dispatch_uncertain'")]
        self.assertEqual(events[0]['connector_receipt']['original'],raw)

    def test_malformed_receipt_holds_one_task_without_stopping_independent_work(self):
        self.rt.create(plan([task('a'),task('b')]))
        self.rt.tick('demo');a=self.rt.task('demo','a')['latest'];b=self.rt.task('demo','b')['latest']
        self.factory.sessions[a]['status']={'status':'finished','browser':None}
        self.factory.finish(b);self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','a')['status'],'uncertain')
        self.assertEqual(self.rt.task('demo','b')['status'],'completed')
        self.assertEqual(len(self.factory.calls),2)


if __name__=='__main__':unittest.main()
