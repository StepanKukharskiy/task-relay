"""A catalog-verification job must not start with file-only research tools."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator import contracts, execution, worker_capabilities
from task_relay import gemini
from task_relay import external_evidence, planning_contract, production_planning as planning
from tests import test_production_planning as fixtures
from tests.test_general_browser import policy


REQUEST = ('Переведи детали с учётом артикулов. Добавь русское наименование, '
           'источник, подтверждающий значение артикула, и статус проверки.')
TARGETED_REQUEST = ('Research only the four unresolved Yamaha articles. Open exact '
                    'part-number search results or catalog listings; record observed URLs '
                    'and text for each article, then produce the workbook and report.')


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    action = fixtures.Tests.action
    queue = fixtures.Tests.queue
    row = fixtures.Tests.row
    response = fixtures.Tests.response

    def test_targeted_catalog_lookup_requires_a_mixed_research_stage(self):
        self.assertTrue(external_evidence.required(TARGETED_REQUEST))
        self.assertFalse(external_evidence.required('Summarize the provided article in a workbook.'))
        row = self.queue(text=TARGETED_REQUEST)
        self.assertTrue(json.loads(row['context'])['external_evidence_required'])

    def test_file_only_scope_stops_before_planner_or_worker_dispatch(self):
        row = self.queue(text=REQUEST)
        self.assertTrue(json.loads(row['context'])['external_evidence_required'])
        with patch.object(planning, 'generate') as generate:
            planning.Worker(self.state, generate).tick()
            generate.assert_not_called()
        current = self.row()
        self.assertEqual(current['status'], 'needs_input')
        self.assertEqual(current['calls'], 0)
        self.assertIn('research route', json.loads(current['result'])['message'])
        self.assertEqual(current['request'], REQUEST)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0], 0)

    def test_router_default_does_not_lock_out_browser_and_followup_can_refresh(self):
        first = self.queue(action=self.action(executor='codex-cli'), text=REQUEST)
        self.assertFalse(json.loads(first['options'])['executor_locked'])
        self.assertEqual(json.loads(first['context'])['executor_resolution']['omitted_inferred_default'], 'codex-cli')
        planning.Worker(self.state, lambda *_: self.fail('Planner should not run without a browser')).tick()
        browser = worker_capabilities.entry({'type':'gemini-browser','model':'fixture'})
        codex = worker_capabilities.entry({'type':'codex-cli','model':'fixture','reasoning':'high'})
        with patch.object(worker_capabilities, 'capture', return_value=[codex,browser]):
            second = self.queue(2, self.action(parent_id=first['id']),
                                text='Continue the saved request using a browser research worker.')
        self.assertFalse(json.loads(second['options'])['executor_locked'])
        self.assertIn('gemini-browser', [item['id'] for item in json.loads(second['options'])['worker_catalog']])

    def test_user_named_codex_stays_locked(self):
        row = self.queue(action=self.action(executor='codex-cli'), text=REQUEST+' Use Codex.')
        self.assertTrue(json.loads(row['options'])['executor_locked'])

    def test_file_only_plan_is_invalid_even_if_a_browser_profile_is_available(self):
        row = dict(self.queue(text=REQUEST))
        options = json.loads(row['options'])
        options['worker_catalog'].append(worker_capabilities.entry({'type':'gemini-browser','model':'fixture'}))
        payload = json.loads(row['context']); payload['options'] = options
        row['options'] = contracts.encoded(options); row['context'] = contracts.encoded(payload)
        with self.assertRaisesRegex(ValueError, 'browser.use, computer.use or web.sources research step'):
            planning.validate_result(json.dumps(self.response()), row)

    def test_reviewed_browser_evidence_can_feed_a_separate_file_worker(self):
        browser = worker_capabilities.entry({'type':'gemini-browser','model':'fixture'})
        codex = worker_capabilities.entry({'type':'codex-cli','model':'fixture','reasoning':'high'})
        with patch.object(worker_capabilities, 'capture', return_value=[codex,browser]):
            row = self.queue(text=REQUEST)
        value = self.response()
        table, table_review = value['plan']['tasks']
        research = copy.deepcopy(table)
        research.update(id='research',role='researcher',objective='Check articles in a public catalog',
                        instruction='Record exact article evidence and source URLs.',
                        outputs=[{'path':'evidence.txt','purpose':'Article evidence','media_type':'text/plain'}],
                        criteria=['Every claim names an observed exact article source.'],
                        max_attempts=1,browser=policy(interaction_scope=''),
                        worker={'requires':['files.text','browser.use']})
        research.pop('tools',None); research.pop('user_gate',None)
        research_review = copy.deepcopy(table_review)
        research_review.update(id='research_review',review_of='research',dependencies=['research'],
                               criteria=research['criteria'],inputs=[{'from_task':'research','output':'evidence.txt',
                                   'path':'candidate/evidence.txt','purpose':'Review exact sources',
                                   'authority':'Unselected candidate','media_type':'text/plain'}])
        table.update(id='table',dependencies=['research','research_review'],inputs=[{'from_task':'research',
                     'output':'evidence.txt','path':'sources/evidence.txt','purpose':'Verified research',
                     'authority':'Reviewed research output','media_type':'text/plain'},
                    {'from_task':'research_review','output':'review.md','path':'sources/research-review.md',
                     'purpose':'Independent evidence assessment','authority':'Independent research review'}])
        table_review.update(id='table_review',review_of='table',dependencies=['table'])
        table_review['inputs'][0]['from_task'] = 'table'
        value['plan']['tasks'] = [research,research_review,table,table_review]
        missing_browser=copy.deepcopy(value)
        missing_browser['plan']['tasks'][0]['browser']={}
        with self.assertRaisesRegex(ValueError, 'browser.profile: required field is missing'):
            planning.validate_result(json.dumps(missing_browser), row)
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertEqual(len(plan['tasks']), 4)
        self.assertEqual(plan['tasks'][0]['worker']['backend']['type'], 'gemini-browser')

    def test_browser_research_must_feed_file_producer(self):
        preparation = {'id':'prepare', 'inputs':[]}
        browser = {'id':'research', 'inputs':[], 'browser':{'origins':['https://example.test']},
                   'worker':{'requires':['files.text','browser.use']}}
        file_worker = {'id':'table', 'inputs':[]}
        payload = {'original_request':REQUEST,'options':{},'sources':[]}
        with self.assertRaisesRegex(ValueError, 'consume a declared output'):
            external_evidence.validate_plan({'tasks':[preparation,browser,file_worker]}, payload)
        browser['inputs'] = [{'from_task':'prepare','output':'articles.json'}]
        file_worker['inputs'] = [{'from_task':'research','output':'evidence.json'}]
        external_evidence.validate_plan({'tasks':[preparation,browser,file_worker]}, payload)

    def test_byte_identical_historical_sources_do_not_overfill_browser_worker(self):
        browser = worker_capabilities.entry({'type':'gemini-browser','model':'fixture'})
        codex = worker_capabilities.entry({'type':'codex-cli','model':'fixture','reasoning':'high'})
        with patch.object(worker_capabilities, 'capture', return_value=[codex,browser]):
            row = dict(self.queue(text='Read a public catalog and prepare a short source brief.'))
        source = self.root / 'source-pack.json'
        source.write_text('x' * 300000)
        first = self.rt.register(source, 'Earlier selected source pack', path='history-a/source-pack.json')
        second = self.rt.register(source, 'Same bytes captured again', path='history-b/source-pack.json')
        report = self.root / 'review.md'
        report.write_text('r' * 100000)
        first_report = self.rt.register(report, 'Earlier review', path='history-a/review.md')
        second_report = self.rt.register(report, 'Same review captured again', path='history-b/review.md')
        older = planning.source_entry(self.rt, first, 'history-a/source-pack.json',
                                      'Earlier selected source pack', 'Selected source')
        newer = planning.source_entry(self.rt, second, 'history-b/source-pack.json',
                                      'Same bytes captured again', 'Historical source')
        earlier_review = planning.source_entry(self.rt, first_report, 'history-a/review.md',
                                               'Earlier review', 'Selected source')
        later_review = planning.source_entry(self.rt, second_report, 'history-b/review.md',
                                             'Same review captured again', 'Historical source')
        payload = json.loads(row['context'])
        payload['sources'].extend([older,newer,earlier_review,later_review])
        payload['required_artifacts'].extend([first,second,first_report,second_report])
        row['context'] = contracts.encoded(payload)
        row['context_hash'] = contracts.digest(payload)
        value = self.response()
        producer = value['plan']['tasks'][0]
        producer['worker'] = {'requires':['files.text','browser.use']}
        producer['browser'] = policy(interaction_scope='')
        producer.setdefault('inputs',[]).append({k:older[k] for k in
            ('artifact','path','purpose','authority')})
        producer['max_attempts'] = 1
        producer.pop('tools',None)
        _, plan = planning.validate_result(json.dumps(value), row)
        inputs = [item for item in plan['tasks'][0]['inputs']
                  if Path(item['path']).name == 'source-pack.json']
        self.assertEqual([item['artifact'] for item in inputs], [first])
        reviews = [item for item in plan['tasks'][0]['inputs']
                   if Path(item['path']).name == 'review.md']
        self.assertEqual([item['artifact'] for item in reviews], [first_report])

    def test_registered_web_search_pack_must_feed_file_producer(self):
        search = {'id':'search', 'inputs':[],
                  'execution':{'capability':'web.sources','version':1,'parameters':{}}}
        table = {'id':'table', 'inputs':[]}
        payload = {'original_request':REQUEST,'options':{'step_capabilities':['web.sources']},'sources':[]}
        self.assertTrue(external_evidence.research_available(payload))
        with self.assertRaisesRegex(ValueError, 'consume a declared output'):
            external_evidence.validate_plan({'tasks':[search,table]}, payload)
        table['inputs'] = [{'from_task':'search','output':'delivery/source-pack.json'}]
        external_evidence.validate_plan({'tasks':[search,table]}, payload)

    def test_planner_accepts_reviewed_web_source_pack_handoff(self):
        with patch.object(gemini, 'read_config', return_value={'api_key':'fixture','models':{'text':'fixture-text'}}):
            row = dict(self.queue(text=REQUEST))
            operations = {item['id']:item for item in execution.catalog()}
        options = json.loads(row['options'])
        options['step_capabilities'] = ['web.sources']
        payload = json.loads(row['context'])
        payload['options'] = options
        payload['graph_operations'] = [operations['web.sources']]
        payload['response_contract'] = planning_contract.contract(options)
        row['options'] = contracts.encoded(options)
        row['context'] = contracts.encoded(payload)
        value = self.response()
        table, table_review = value['plan']['tasks']
        search = copy.deepcopy(table)
        search.update(id='search',role='research',objective='Collect exact article sources',
                      instruction='Search for this exact article in public sources.',
                      execution={'capability':'web.sources','version':1,'parameters':{
                          'queries':['ABC-9182 OEM material'],'domains':[]}},
                      inputs=[],outputs=[{'path':'delivery/source-pack.json',
                                           'purpose':'Public source candidates','media_type':'application/json'}],
                      criteria=copy.deepcopy(execution.REGISTRY['web.sources']['criteria']),
                      limits={'seconds':1800,'tool_calls':1,'output_bytes':2000000},
                      max_attempts=1,tools=[])
        search.pop('user_gate',None)
        source_input={'from_task':'search','output':'delivery/source-pack.json',
                      'path':'sources/source-pack.json','purpose':'Exact source candidates',
                      'authority':'Unverified public source pack','media_type':'application/json'}
        search_review = copy.deepcopy(table_review)
        search_review.update(id='search_review',review_of='search',dependencies=['search'],
                             inputs=[{**source_input,'path':'candidate/source-pack.json'}],
                             criteria=copy.deepcopy(search['criteria']))
        review_input={'from_task':'search_review','output':'review.md',
                      'path':'sources/source-review.md','purpose':'Independent source assessment',
                      'authority':'Independent research review'}
        table.update(id='table',dependencies=['search','search_review'],inputs=[source_input,review_input])
        table_review.update(id='table_review',review_of='table',dependencies=['table'])
        table_review['inputs'][0]['from_task'] = 'table'
        value['plan']['tasks'] = [search,search_review,table,table_review]
        missing_review=copy.deepcopy(value)
        missing_review['plan']['tasks'][2]['inputs']=[source_input]
        with self.assertRaisesRegex(ValueError, 'consume the independent research review'):
            planning.validate_result(json.dumps(missing_review), row)
        incomplete=copy.deepcopy(value)
        incomplete['plan']['tasks'][0]['execution']['parameters']={}
        with self.assertRaisesRegex(ValueError, 'queries: required field is missing'):
            planning.validate_result(json.dumps(incomplete), row)
        _, plan = planning.validate_result(json.dumps(value), row)
        self.assertEqual([task['id'] for task in plan['tasks']],
                         ['search','search_review','table','table_review'])
        self.assertEqual(plan['tasks'][0]['execution']['parameters']['model'],'fixture-text')
        self.assertEqual(plan['origin']['planner_field_bindings'][0]['source'],
                         'graph_operations.web.sources.configured_model')
        card = planning.preview({**row, 'plan': contracts.encoded(plan), 'result': '{}'})
        self.assertIn('Public source search:', card)
        self.assertIn('ABC-9182 OEM material', card)

    def test_web_source_schema_rejects_empty_parameters_before_model_check(self):
        options={'step_capabilities':['web.sources']}
        contract=planning_contract.contract(options)['schema']
        task=contract['properties']['plan']['anyOf'][0]['properties']['tasks']['items']
        execution_schema=task['properties']['execution']
        with self.assertRaisesRegex(ValueError, 'queries: required field is missing'):
            planning_contract.validate({'capability':'web.sources','version':1,'parameters':{}},
                                       execution_schema)
        planning_contract.validate({'capability':'web.sources','version':1,
                                    'parameters':{'queries':['ABC-9182 OEM material'],'domains':[]}},
                                   execution_schema)

    def test_blocked_search_plan_followup_gets_fresh_typed_contract(self):
        config={'api_key':'fixture','models':{'text':'fixture-text'}}
        with patch.object(gemini,'read_config',return_value=config):
            first=self.queue(action=self.action(step_capabilities=['web.sources']),text=REQUEST)
            with self.state.db:
                self.state.db.execute("UPDATE production_plans SET status='blocked',error=? WHERE id=?",
                                      ('Missing search parameters',first['id']))
            second=self.queue(2,self.action(parent_id=first['id']),
                              text='Retry the same source-verification plan.')
        self.assertEqual(json.loads(second['options'])['step_capabilities'],['web.sources'])
        payload=json.loads(second['context'])
        task_schema=payload['response_contract']['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']
        params=task_schema['properties']['execution']['properties']['parameters']
        self.assertEqual(params['required'],['queries','domains'])
        self.assertEqual(payload['graph_operations'][0]['configured_model'],'fixture-text')

    def test_selected_catalog_can_supply_evidence_without_live_browser(self):
        payload = {'original_request':REQUEST,'options':{},'sources':[
            {'path':'request-inputs/1/0/Yamaha-OEM-catalog.pdf'},
        ]}
        self.assertTrue(external_evidence.supplied(payload))
        external_evidence.validate_plan({'tasks':[{'id':'table','inputs':[]}]}, payload)
        self.assertFalse(external_evidence.required('Translate the supplied spreadsheet into Russian.'))

    def test_sequential_reviewed_file_pairs_accept_exact_copied_baseline(self):
        request=('Use one producer/reviewer pair to correct the saved evidence, then one '
                 'producer/reviewer pair to update and check the workbook.')
        row=dict(self.queue(text=request))
        original=self.root/'original.xlsx';original.write_bytes(b'exact workbook bytes')
        copied=self.root/'copy.xlsx';copied.write_bytes(original.read_bytes())
        first_id=self.rt.register(original,'Selected previous workbook',path='history/pilot.xlsx')
        copy_id=self.rt.register(copied,'Captured request copy',path='request/pilot.xlsx')
        payload=json.loads(row['context'])
        # The provider response here uses the legacy exact-input shape to keep
        # this regression focused on the graph and byte-identical baseline gate.
        payload.pop('response_contract',None)
        payload.pop('artifact_binding_version',None)
        payload['available_sources']=[planning.source_entry(self.rt,first_id,'history/pilot.xlsx',
                                      'Selected previous workbook','Prior output candidate')]
        payload['sources'].append(planning.source_entry(self.rt,copy_id,'request/pilot.xlsx',
                                  'Captured request copy','Selected source'))
        row['context']=contracts.encoded(payload)
        row['options']=contracts.encoded(payload['options'])
        value=self.response();first,first_review=value['plan']['tasks']
        first.pop('user_gate',None)
        second=copy.deepcopy(first);second.update(id='second',instruction='Update the workbook',
            outputs=[{'path':'final.txt','purpose':'Updated candidate'}],dependencies=['produce','review'],
            inputs=[{'artifact':copy_id,'path':'request/pilot.xlsx','purpose':'Baseline workbook',
                     'authority':'Selected source'},
                    {'from_task':'produce','output':'output.txt','path':'upstream/output.txt',
                     'purpose':'Corrected evidence','authority':'Unaccepted prior candidate'},
                    {'from_task':'review','output':'review.md','path':'upstream/review.md',
                     'purpose':'Evidence audit','authority':'Independent review'}])
        second_review=copy.deepcopy(first_review);second_review.update(id='second_review',
            review_of='second',dependencies=['second'],inputs=[{'from_task':'second',
            'output':'final.txt','path':'candidate/final.txt','purpose':'Check updated workbook',
            'authority':'Unaccepted candidate'}])
        value['plan']['tasks']=[first,first_review,second,second_review]
        value['input_basis']={'mode':'modify_existing','artifacts':[first_id]}
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual(len(plan['tasks']),4)
        self.assertEqual(plan['origin']['baseline_copies'][0]['bound_copy'],copy_id)
        unchained=copy.deepcopy(value)
        unchained['plan']['tasks'][2]['dependencies']=['produce']
        unchained['plan']['tasks'][2]['inputs']=[i for i in unchained['plan']['tasks'][2]['inputs']
                                               if i.get('from_task')!='review']
        # The copied-baseline exception requires a fully chained reviewed pair.
        with self.assertRaisesRegex(ValueError,'Every declared baseline'):
            planning.validate_result(json.dumps(unchained),row)
        copied.write_bytes(b'different workbook bytes')
        changed_id=self.rt.register(copied,'Different request copy',path='request/pilot.xlsx')
        bad=copy.deepcopy(value);bad['plan']['tasks'][2]['inputs'][0]['artifact']=changed_id
        old_source=planning.source_entry(self.rt,changed_id,'request/pilot.xlsx',
                                         'Different request copy','Selected source')
        changed_row=copy.deepcopy(row);changed_payload=json.loads(changed_row['context'])
        changed_payload['sources'].append(old_source)
        changed_row['context']=contracts.encoded(changed_payload)
        with self.assertRaisesRegex(ValueError,'Every declared baseline'):
            planning.validate_result(json.dumps(bad),changed_row)


if __name__ == '__main__':
    unittest.main()
