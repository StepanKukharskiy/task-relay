"""A stage-wide schema catalog must not invent an unbound worker prerequisite."""
import json
import unittest
from task_relay import production_planning as planning
from tests import test_production_planning as fixtures
from orchestrator import contracts as c


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def test_query_checker_guidance_follows_exact_worker_bindings(self):
        row=dict(self.queue())
        payload=json.loads(row['context']);options=json.loads(row['options'])
        support=[]
        for name in ('validate.py','contract.json'):
            path=self.state.media_dir.parent/name;path.write_text('{}' if name.endswith('.json') else '# fixture')
            aid=self.rt.register(path,'Controlled query-support fixture')
            entry=planning.source_entry(self.rt,aid,'operation-support/web.sources.prepared/'+name,'Frozen support','Fixture data')
            payload['sources'].append(entry);support.append(entry)
        options['required_artifacts']=[]
        row.update(context=c.encoded(payload),context_hash=c.digest(payload),options=c.encoded(options))
        value=self.response()
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertTrue(all('authoritative query-schema checks' not in t['instruction'] for t in plan['tasks']))
        # Binding stage-wide support is not a prepared query-document handoff.
        for task in value['plan']['tasks']:
            task['inputs']=task.get('inputs',[])+[{k:s[k] for k in ('artifact','path','purpose','authority')} for s in support]
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertTrue(all('authoritative query-schema checks' not in t['instruction'] for t in plan['tasks']))

    def test_actual_prepared_query_handoff_selects_only_its_author_and_reviews(self):
        from tests.test_prepared_research import Tests as Prepared
        graph=Prepared.graph(self)
        graph['tasks'].append({'id':'catalog','inputs':[{'from_task':'queries','output':'queries.json'}],'outputs':[{'path':'catalog.json'}]})
        # Real prepared handoff validation checks the exact query/source review edges.
        planning.validate_prepared_research(graph)
        self.assertEqual(planning.prepared_query_workers(graph),{'queries','review_queries','review_search'})
        graph['tasks'][2]['execution']['capability']='web.sources'
        self.assertEqual(planning.prepared_query_workers(graph),set())


if __name__=='__main__':unittest.main()

class OptionalRouteTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def test_optional_source_route_freezes_checker_and_binds_actual_query_workers(self):
        import copy
        from unittest.mock import patch
        from task_relay import gemini
        from orchestrator import execution
        from tests.test_mixed_execution import operation,upstream
        with patch.object(gemini,'read_config',return_value={'api_key':'fixture','models':{'text':'fixture-text'}}):
            row=dict(self.queue(action=self.action(research_mode='sources',deliverables={'catalog':'Checked catalog'})))
        payload=json.loads(row['context'])
        support=[s for s in payload['sources'] if s.get('operation_support')=='web.sources.prepared']
        inventory=self.state.media_dir.parent/'inventory.md';inventory.write_text('Observed item chair: rounded timber frame')
        aid=self.rt.register(inventory,'Observed inventory fixture')
        item=planning.source_entry(self.rt,aid,'inventory.md','Observed inventory','Controlled source')
        payload['sources'].append(item);payload['required_artifacts'].append(aid)
        row.update(context=c.encoded(payload),context_hash=c.digest(payload))
        self.assertEqual({s['path'].split('/')[-1] for s in support},{'validate.py','contract.json'})
        value=self.response();author,review=value['plan']['tasks'];author.pop('user_gate',None)
        author['criteria']=['Query JSON parses and retains exact requested item IDs.']
        review['criteria']=list(author['criteria'])
        author['outputs'][0].update(path='queries.json',media_type='application/json')
        review['inputs'][0].update(output='queries.json',media_type='application/json');review.pop('user_gate',None)
        source=operation('sources','web.sources.prepared',[upstream(author['id'],'queries.json')],[author['id'],review['id']])
        source['execution']['parameters']={'domains':[],'model':'fixture-text'}
        source.update(limits={'seconds':600,'tool_calls':1,'output_bytes':2000000},max_attempts=1)
        source['outputs']=[dict(path='delivery/source-pack.json',purpose='Exact page evidence',media_type='application/json')]
        audit=copy.deepcopy(review);audit.update(id='source-review',review_of='sources',dependencies=['sources'],inputs=[upstream('sources','delivery/source-pack.json'),upstream(author['id'],'queries.json')],criteria=copy.deepcopy(execution.REGISTRY['web.sources.prepared']['criteria']))
        catalog=copy.deepcopy(author);catalog.update(id='catalog',dependencies=['sources','source-review'],inputs=[upstream('sources','delivery/source-pack.json'),upstream('source-review',audit['outputs'][0]['path'])],outputs=[dict(path='catalog.json',purpose='Checked catalog',media_type='application/json')])
        catalog_review=copy.deepcopy(review);catalog_review.update(id='catalog-review',review_of='catalog',dependencies=['catalog'],inputs=[upstream('catalog','catalog.json'),upstream('sources','delivery/source-pack.json')])
        value['deliverable_map']={'catalog':dict(task='catalog',output='catalog.json')}
        value['plan']['tasks']=[author,review,source,audit,catalog,catalog_review]
        for task in value['plan']['tasks']:
            for item in task.get('inputs',[]):
                if item.get('from_task') in (author['id'],'sources','catalog'):item['media_type']='application/json'
        _,graph=planning.validate_result(json.dumps(value),row)
        query_ids=planning.prepared_query_workers(graph)
        for task in graph['tasks']:
            paths={i['path'] for i in task['inputs']}
            if task['id'] in query_ids:
                if task.get('operation_contract',{}).get('id')=='operation.preparation':
                    self.assertFalse({s['path'] for s in support}&paths)
                    self.assertEqual(task['operation_contract']['parameters']['target'],'web.sources.prepared')
                    self.assertNotIn('authoritative query-schema checks',task['instruction'])
                    continue
                self.assertTrue({s['path'] for s in support}<=paths)
                self.assertIn('authoritative query-schema checks',task['instruction'])
        checker=next(s for s in support if s['path'].endswith('validate.py'))
        namespace={'__name__':'frozen'};exec(next(t['text'] for t in payload['source_texts'] if t['artifact']==checker['artifact']),namespace)
        self.assertEqual(namespace['validate_prepared']({'version':1,'targets':[{'id':'chair','queries':['chair US'],'required_options':3}]}),['chair US'])
