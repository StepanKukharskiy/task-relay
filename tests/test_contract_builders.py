"""Procedural artifact/stage/report boundaries using controlled text fixtures."""
import copy
import json
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, report_builder
from task_relay import production_planning as planning, workflow_builder, pipelines
from tests import test_production_planning as fixtures


class BindingTests(unittest.TestCase):
    def setUp(self):
        fixtures.Tests.setUp(self);del self.fail
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response
    start=fixtures.Tests.start
    click=fixtures.Tests.click

    def compact(self):
        value=self.response()
        value['plan']['tasks'][0]['outputs'].append(dict(path='sources.txt',purpose='Sources supporting the brief'))
        for task in value['plan']['tasks']:
            task.pop('inputs',None);task.pop('dependencies',None);task.pop('selection_outputs',None)
            task['input_bindings']=[]
        return value

    def test_review_wiring_and_selection_preserve_exact_outputs(self):
        row=self.queue();value=self.compact();original=copy.deepcopy(value)
        result,plan=planning.validate_result(json.dumps(value),row)
        producer,review=plan['tasks']
        self.assertEqual(review['dependencies'],[producer['id']])
        bound=[i for i in review['inputs'] if 'from_task' in i]
        self.assertEqual([i['output'] for i in bound],[o['path'] for o in producer['outputs']])
        self.assertEqual(producer['selection_outputs'],[o['path'] for o in producer['outputs']])
        self.assertEqual(value,original);self.assertIn('artifact_bindings',plan['origin'])
        schema=json.loads(row['context'])['response_contract']['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']
        self.assertIn('input_bindings',schema['required'])
        self.assertTrue({'inputs','dependencies','selection_outputs'}.isdisjoint(schema['properties']))
        self.assertNotIn('input_bindings',result['plan']['tasks'][0])
        self.assertEqual(self.factory.calls,[])

    def test_selected_source_binds_frozen_alias_authority_and_hash(self):
        row=self.queue();payload=json.loads(row['context']);src=payload['sources'][0]
        value=self.compact();value['plan']['tasks'][0]['input_bindings']=[{'source':src['artifact']}]
        _,plan=planning.validate_result(json.dumps(value),row)
        item=next(i for i in plan['tasks'][0]['inputs'] if i.get('artifact')==src['artifact'])
        self.assertEqual(item['path'],src['path']);self.assertEqual(item['authority'],src['authority'])
        self.assertEqual(plan['origin']['artifact_bindings']['tasks'][0]['input_versions'],[dict(artifact=src['artifact'],sha256=src['sha256'])])

    def test_unknown_sources_outputs_and_metadata_override_fail(self):
        row=self.queue()
        cases=[{'source':'missing'}, {'producer':'produce','output':'missing.txt'},
               {'source':'missing','authority':'trusted'}, {'source':'missing','sha256':'a'*64}]
        for ref in cases:
            value=self.compact();value['plan']['tasks'][1]['input_bindings']=[ref]
            with self.subTest(ref=ref),self.assertRaises(ValueError):planning.validate_result(json.dumps(value),row)
        for key in ('inputs','dependencies','selection_outputs'):
            value=self.compact();value['plan']['tasks'][0][key]=[]
            with self.assertRaisesRegex(ValueError,'cannot be combined|unsupported field'):planning.validate_result(json.dumps(value),row)

    def test_duplicate_bindings_and_dependency_cycles_are_rejected(self):
        row=self.queue();value=self.compact();producer,review=value['plan']['tasks']
        ref={'producer':producer['id'],'output':producer['outputs'][0]['path']}
        review['input_bindings']=[ref,ref]
        with self.assertRaisesRegex(ValueError,'Duplicate'):planning.validate_result(json.dumps(value),row)
        review['input_bindings']=[];producer['after']=[review['id']]
        with self.assertRaises(ValueError):planning.validate_result(json.dumps(value),row)

    def test_raw_request_and_compilation_receipt_survive_worker(self):
        self.queue();value=self.compact();raw=json.dumps(value)
        planning.Worker(self.state,lambda *_:(raw,{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertEqual(self.state.db.execute('SELECT response FROM production_plan_calls').fetchone()[0],raw)
        self.assertTrue(json.loads(row['plan'])['origin']['artifact_bindings'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_typed_workflow_dispatch_preserves_raw_intent_and_canonical_spec(self):
        value=WorkflowTests().action()
        self.request(value,'Research the facts, then prepare the brief; planning only.',1)
        row=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['status'],'planned')
        self.assertNotIn('stage_details',json.loads(row['spec']))
        receipt=self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='workflow_compiled'").fetchone()
        self.assertEqual(json.loads(receipt[0])['request'],value)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_runtime_collects_typed_report_without_selecting_outputs(self):
        from pathlib import Path
        from task_relay import production_control as pc
        self.queue();value=self.compact()
        planning.Worker(self.state,lambda *_:(json.dumps(value),{})).tick()
        self.start(self.row());production=pc.Worker(self.state,lambda _:self.rt);production.tick()
        for task in ('produce','review'):
            attempt=self.rt.task('production-1',task)['latest'];self.factory.finish(attempt)
            frozen=self.factory.sessions[attempt]['frozen']
            self.assertEqual(frozen['report_contract']['version'],1)
            result=dict(summary='Controlled file check',decision='accept' if task=='review' else 'delivered',instruction='',findings=[],
                checks={'c'+str(i):dict(passed=True,evidence='Verified small fixture output.') for i in range(1,len(frozen['criteria'])+1)})
            path=Path(frozen['workspace'])/'.relay/result.json';path.write_text(json.dumps(result))
            production.tick()
            raw=self.state.db.execute("SELECT data FROM production_events WHERE attempt=? AND kind='first_response'",(attempt,)).fetchone()
            self.assertEqual(json.loads(json.loads(raw[0])['text']),result)
        self.assertEqual(self.rt.status('production-1')['status'],'awaiting_user')



class WorkflowTests(unittest.TestCase):
    def test_saved_text_worker_ability_compiles_without_granting_operations(self):
        value=self.action();stage=value['stage_details'][1]
        stage['capabilities']=['files.text'];original=copy.deepcopy(value)
        compiled,receipt=workflow_builder.build(value,{})
        pipelines.validate(compiled,{})
        self.assertEqual(compiled['stages'][1]['capabilities'],[])
        self.assertEqual(receipt['implicit_worker_abilities'],[
            dict(stage='brief',capability='files.text',reason='baseline_agent_ability')])
        self.assertEqual(value,original);self.assertEqual(receipt['request'],original)
        self.assertTrue(compiled['planning_only'])
        self.assertEqual(compiled['stages'][1]['gate'],'selection')
        self.assertEqual(compiled['stages'][1]['instruction'],stage['instruction'])

    def test_worker_permissions_and_unknown_operations_are_not_dropped(self):
        for caps in (['code.execute'],['files.binary'],['images.view'],['made.up'],['files.text','files.text']):
            value=self.action();value['stage_details'][1]['capabilities']=caps
            with self.subTest(caps=caps),self.assertRaises(ValueError):workflow_builder.build(value,{})
        value=self.action();value['stage_details'][0]['capabilities']=['files.text']
        with self.assertRaises(ValueError):workflow_builder.build(value,{})

    def test_advertised_schema_excludes_worker_abilities_and_uncaptured_operations(self):
        schema=workflow_builder.schema(['rhino3dm.run_python'])
        stage=schema['properties']['stage_details']['items']['properties']
        self.assertEqual(stage['capabilities']['items']['enum'],['rhino3dm.run_python'])
        self.assertEqual(stage['outputs']['additionalProperties']['anyOf'][1]['properties']['operation']['enum'],['rhino3dm.run_python'])

    def action(self):
        return dict(kind='plan_pipeline',title='Source-grounded brief',planning_only=True,stage_details=[
            dict(id='research',instruction='Establish the facts.',route='conversation',gate='choice',capabilities=[],
                 outputs={'facts':dict(description='Evidence-backed facts',format='text')},uses=[]),
            dict(id='brief',instruction='Prepare the brief from the selected findings.',route='production',gate='selection',capabilities=[],
                 outputs={'brief':dict(description='Brief',format='markdown')},
                 uses=[dict(stage='research',output='facts',consumer='context')])])

    def test_stage_media_and_edges_are_derived_without_changing_gates(self):
        value=self.action();original=copy.deepcopy(value)
        compiled,receipt=workflow_builder.build(value,{})
        pipelines.validate(compiled,{})
        self.assertEqual(compiled['stages'][1]['handoff']['inputs'],[dict(stage='research',deliverable='facts',consumer='context',media_type='text/plain')])
        self.assertEqual([s['gate'] for s in compiled['stages']],['choice','selection'])
        self.assertEqual(receipt['request'],original);self.assertEqual(value,original)

    def test_no_metadata_injection_conversion_or_forward_reference(self):
        for alteration in ('metadata','conversion','forward'):
            value=self.action()
            if alteration=='metadata':value['stage_details'][0]['outputs']['facts']['media_type']='image/png'
            if alteration=='conversion':value['stage_details'][0]['outputs']['facts']['format']='3dm'
            if alteration=='forward':value['stage_details'][0]['uses']=[dict(stage='brief',output='brief',consumer='context')]
            with self.subTest(alteration=alteration),self.assertRaises(ValueError):workflow_builder.build(value,{})

    def test_companions_are_derived_but_missing_selection_is_not_filled(self):
        value=self.action();stage=value['stage_details'][0]
        stage.update(route='production',gate='selection')
        stage['outputs']={'script':dict(description='Script',format='python',together='code'),
                          'checks':dict(description='Checks',format='json',together='code')}
        value['stage_details'][1]['uses']=[dict(stage='research',output='script',consumer='context')]
        with self.assertRaisesRegex(ValueError,'companion'):workflow_builder.build(value,{})
        value['stage_details'][1]['uses'].append(dict(stage='research',output='checks',consumer='context'))
        compiled,_=workflow_builder.build(value,{})
        self.assertEqual(compiled['stages'][0]['handoff']['outputs']['script']['companions'],['checks'])

    def test_document_format_is_an_explicit_requirement_not_a_tool_grant(self):
        value=self.action();value['stage_details'][1]['outputs']['brief']['format']='pdf'
        compiled,_=workflow_builder.build(value,{})
        stage=compiled['stages'][1]
        self.assertEqual(stage['handoff']['outputs']['brief']['media_type'],'application/pdf')
        self.assertEqual(stage['capabilities'],[])
        self.assertEqual(stage['gate'],'selection')

    def test_registered_port_selection_rejects_drift_and_unknown_port(self):
        from orchestrator.execution import REGISTRY
        spec=copy.deepcopy(REGISTRY['rhino3dm.run_python']);snap={'capabilities':{'graph_operations':[dict(spec,id='rhino3dm.run_python',available=True)]}}
        value=self.action();stage=value['stage_details'][1];stage['capabilities']=['rhino3dm.run_python']
        stage['outputs']={'model':dict(description='Native candidate',operation='rhino3dm.run_python',port='delivery/candidate.3dm')}
        compiled,_=workflow_builder.build(value,snap)
        self.assertEqual(compiled['stages'][1]['handoff']['outputs']['model']['media_type'],'application/vnd.rhino')
        stage['outputs']['model']['port']='invented'
        with self.assertRaisesRegex(ValueError,'exact captured'):workflow_builder.build(value,snap)
        stage['outputs']['model']['port']='delivery/candidate.3dm'
        snap['capabilities']['graph_operations'][0]['outputs']['delivery/candidate.3dm']='image/png'
        with self.assertRaisesRegex(ValueError,'changed'):workflow_builder.build(value,snap)
        stage['outputs']['model']=dict(description='Native candidate',format='3dm')
        with self.assertRaisesRegex(ValueError,'changed'):workflow_builder.build(value,snap)


class ReportTests(unittest.TestCase):
    def frozen(self,review=True):
        value=dict(assignment_id='active-assignment',criteria=['Read exact files.','Compare the result.'])
        if review:value['review_of']='producer'
        value['report_contract']=report_builder.freeze(value)
        return value

    def details(self):
        return dict(summary='Inspected the exact candidate.',decision='accept',instruction='',findings=[],checks={
            'c1':dict(passed=True,evidence='Read the supplied file.'),
            'c2':dict(passed=True,evidence='Compared the saved result to the request.')})

    def test_form_binds_assignment_and_criterion_numbers(self):
        frozen=self.frozen();raw=self.details();original=copy.deepcopy(raw)
        result=c.report(raw,frozen)
        self.assertEqual(result['assignment_id'],'active-assignment')
        self.assertEqual([i['criterion'] for i in result['checks']],[1,2]);self.assertEqual(raw,original)
        self.assertNotIn('assignment_id',frozen['report_contract']['schema']['properties'])

    def test_wrong_identity_unknown_and_missing_criteria_fail(self):
        frozen=self.frozen()
        bad=self.details();bad['assignment_id']='another-assignment'
        with self.assertRaisesRegex(ValueError,'unsupported'):c.report(bad,frozen)
        for key in ('c1','c3'):
            bad=self.details()
            if key=='c1':del bad['checks'][key]
            else:bad['checks'][key]=bad['checks']['c1']
            with self.assertRaises(ValueError):c.report(bad,frozen)
        with self.assertRaises(ValueError):c.report(self.details(),dict(frozen,report_contract={'version':999}))
        legacy=dict(frozen);del legacy['report_contract']
        with self.assertRaises(ValueError):c.report(self.details(),legacy)

    def test_blocked_can_leave_slots_unchecked_but_accept_cannot(self):
        frozen=self.frozen();value=self.details();value['checks']['c1']=None
        with self.assertRaisesRegex(ValueError,'blocked'):c.report(value,frozen)
        value['decision']='blocked';result=c.report(value,frozen)
        self.assertEqual([i['criterion'] for i in result['checks']],[2])
        value=self.details();value['checks']['c1']['passed']=False
        with self.assertRaises(ValueError):c.report(value,frozen)
        with self.assertRaises(ValueError):c.report(self.details(),self.frozen(review=False))

    def fidelity(self):
        from tests.test_geometry_sources import ReportTests as fixture
        f=fixture();f.setUp();frozen=f.frozen
        frozen['report_contract']=report_builder.freeze(frozen)
        value=self.details();value['checks']={'c'+str(i):dict(passed=True,evidence='Read and inspected.') for i in range(1,len(frozen['criteria'])+1)}
        slot='c'+str(frozen['source_fidelity']['criterion'])
        value['checks'][slot]['evidence']=dict(sources={'s1':dict(observed_sha256='a'*64,observation='Read survey entities, coordinates, units and transform.')},
            measurements={'contour_deviation':dict(error=.01,evidence='Measured saved candidate against survey geometry.')})
        return frozen,value,slot

    def test_typed_fidelity_binds_versions_and_keeps_measured_quality_concerns(self):
        frozen,value,slot=self.fidelity();result=c.report(value,frozen)
        evidence=json.loads(result['checks'][-1]['evidence'])
        self.assertEqual(evidence['sources'],frozen['source_fidelity']['sources'])
        value['checks'][slot]['evidence']['measurements']['contour_deviation']['error']=.2
        result=c.report(value,frozen)
        self.assertEqual(result['findings'][0]['category'],'quality')
        self.assertEqual(json.loads(result['checks'][-1]['evidence'])['comparisons'][0]['error'],.2)

    def test_missing_measurements_and_wrong_observed_hash_never_pass(self):
        for kind in ('missing','hash','nan','negative'):
            frozen,value,slot=self.fidelity();evidence=value['checks'][slot]['evidence']
            if kind=='missing':evidence['measurements']={}
            elif kind=='hash':evidence['sources']['s1']['observed_sha256']='b'*64
            else:evidence['measurements']['contour_deviation']['error']=float('nan') if kind=='nan' else -1
            with self.subTest(kind=kind),self.assertRaises(ValueError):c.report(value,frozen)


class ProviderReportTests(unittest.TestCase):
    def setUp(self):
        from tests.test_gemini_executor import Tests
        Tests.setUp(self)
    def tearDown(self):
        from tests.test_gemini_executor import Tests
        Tests.tearDown(self)

    def test_finish_uses_frozen_form_and_retains_raw_details(self):
        from orchestrator.gemini_worker import execute
        from tests.test_gemini_executor import CONFIG,BACKEND
        self.frozen.update(review_of='producer',outputs=[dict(path='review.md',purpose='Independent review')])
        from tests.test_gemini_executor import Tests
        Tests.input(self,'candidate.txt','Controlled candidate for the report fixture.',from_task='producer')
        self.frozen['report_contract']=report_builder.freeze(self.frozen)
        details=dict(summary='Controlled independent review',decision='accept',instruction='',findings=[],checks={
            'c'+str(i):dict(passed=True,evidence='Read the controlled fixture.') for i in range(1,len(self.frozen['criteria'])+1)})
        from unittest.mock import Mock
        envelope={'report_json':json.dumps(details)}
        client=Mock();client.request.return_value={'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[
            {'functionCall':{'name':'finish','args':envelope}}]}}]}
        result=execute(self.frozen,self.control,client,lambda:(CONFIG,BACKEND))
        payload=client.request.call_args.args[1]
        declaration=next(t for t in payload['tools'][0]['functionDeclarations'] if t['name']=='finish')
        self.assertEqual(declaration['parameters']['required'],['report_json'])
        self.assertNotIn('parametersJsonSchema',declaration)
        self.assertEqual(result['assignment_id'],self.frozen['assignment_id'])
        self.assertEqual(json.loads((self.ws/'.relay/result.json').read_text()),details)
        self.assertIn('Controlled independent review',(self.ws/'review.md').read_text())
        record=json.loads((self.control/'tool-01-00.json').read_text())
        self.assertEqual(record['arguments'],envelope)

    def test_report_transport_does_not_relax_frozen_validation(self):
        from orchestrator.gemini_worker import gemini_report_arguments
        self.frozen['report_contract']=report_builder.freeze(self.frozen)
        good=dict(summary='Actual observations',decision='delivered',instruction='',findings=[],checks={
            'c'+str(i):dict(passed=True,evidence='Observed fixture.') for i in range(1,len(self.frozen['criteria'])+1)})
        self.assertEqual(c.report(gemini_report_arguments({'report_json':json.dumps(good)}),self.frozen)['decision'],'delivered')
        for change in ('missing','extra','unchecked','wrong_role'):
            bad=copy.deepcopy(good)
            if change=='missing':bad['checks'].pop('c1')
            if change=='extra':bad['assignment_id']='injected'
            if change=='unchecked':bad['checks']['c1']=None
            if change=='wrong_role':bad['decision']='accept'
            with self.subTest(change=change),self.assertRaises(ValueError):
                c.report(gemini_report_arguments({'report_json':json.dumps(bad)}),self.frozen)
        for bad in ({'report_json':'[]'},{'report_json':'{'},{'report_json':{}},{'report_json':'{}','checks':{}}):
            with self.assertRaises(ValueError):gemini_report_arguments(bad)

    def test_codex_uses_same_form_without_prompting_for_identity(self):
        from orchestrator.workers import CodexFactory
        self.frozen['report_contract']=report_builder.freeze(self.frozen)
        with patch('task_relay.app_access.require'),patch('task_relay.host_apps.catalog',return_value=[]),patch('orchestrator.workers.prepare_supervisor',return_value='fixture'),patch('orchestrator.workers.supervisor_support',return_value={}):
            CodexFactory(executable='/fixture/codex').create(self.control/'codex',self.ws,self.frozen,dict(type='codex-cli',model='fixture',reasoning='high'))
        schema=json.loads((self.control/'codex/schema.json').read_text())
        self.assertEqual(schema,self.frozen['report_contract']['schema'])
        self.assertNotIn('using assignment_id',(self.control/'codex/prompt.txt').read_text())


if __name__=='__main__':unittest.main()
