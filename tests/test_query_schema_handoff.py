"""Frozen contract validation and bounded recovery of a missing review input."""
import json
import unittest
from orchestrator import web_sources
from tests import test_orchestrator as runtime_fixtures

class FrozenQuerySchema(unittest.TestCase):
    def test_frozen_checker_runs_without_relay_and_rejects_duplicate_fields(self):
        ns={'__name__':'frozen'};exec(web_sources.prepared_validator_source(),ns)
        text=json.dumps({'version':1,'targets':[{'id':'item-1','queries':['blue chair USA price'],'required_options':3}]})
        queries,_=ns['prepared_document']([{'path':'queries.json','sha256':'a'*64,'text':text}])
        self.assertEqual(queries,['blue chair USA price'])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            ns['prepared_document']([{'path':'queries.json','sha256':'a'*64,'text':'{"version":1,"version":2}'}])
        with self.assertRaises(ValueError):ns['validate_prepared']({'version':1,'targets':[{'id':'item-1','queries':['blue chair'],'required_options':True}]})

class ReviewInputRecovery(unittest.TestCase):
    setUp=runtime_fixtures.Tests.setUp
    tearDown=runtime_fixtures.Tests.tearDown
    latest=runtime_fixtures.Tests.latest
    finish=runtime_fixtures.Tests.finish
    def stopped(self):
        self.rt.create(runtime_fixtures.pair(max_attempts=2));self.rt.tick('demo');self.finish()
        producer=self.latest();review=self.latest('review');self.finish('review',decision='blocked')
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        return producer,review
    def test_supply_exact_schema_without_replaying_producer_or_rewriting_old_attempt(self):
        producer,review=self.stopped()
        before=dict(self.rt.db.execute('select * from production_attempts where id=?',(review,)).fetchone())
        schema=self.root/'validate.py';schema.write_text('SCHEMA_VERSION = 1\n')
        artifact=self.rt.register(schema,'Authoritative schema fixture')
        item={'artifact':artifact,'path':'support/validate.py','purpose':'Exact schema','authority':'Controlled contract','media_type':'text/x-python'}
        self.rt.retry_review('demo','review','Validate the unchanged candidate with the exact supplied schema.',source='explicit_contract_recovery',additional_inputs=[item])
        self.rt.tick('demo');new=self.latest('review')
        self.assertNotEqual(new,review);self.assertEqual(self.latest(),producer)
        self.assertEqual(before,dict(self.rt.db.execute('select * from production_attempts where id=?',(review,)).fetchone()))
        self.assertEqual((self.factory.sessions[new]['workspace']/'support/validate.py').read_text(),'SCHEMA_VERSION = 1\n')
        self.finish('review',decision='accept');self.assertEqual(len(self.factory.calls),3)
    def test_uncertain_outcome_does_not_dispatch_recovery(self):
        _,review=self.stopped()
        row=self.rt.db.execute('select receipt from production_attempts where id=?',(review,)).fetchone();receipt=json.loads(row[0]);receipt['external_outcome']='unknown'
        with self.rt.db:self.rt.db.execute('update production_attempts set receipt=? where id=?',(json.dumps(receipt),review))
        with self.assertRaisesRegex(ValueError,'uncertain replay'):self.rt.retry_review('demo','review','Recover')
        self.assertEqual(len(self.factory.calls),2)

class PlanningSchemaHandoff(unittest.TestCase):
    from tests.test_production_planning import Tests as PlanningFixture
    setUp=PlanningFixture.setUp
    tearDown=PlanningFixture.tearDown
    request=PlanningFixture.request
    action=PlanningFixture.action
    queue=PlanningFixture.queue
    row=PlanningFixture.row
    def test_new_scope_carries_authoritative_checker_as_required_frozen_input(self):
        from unittest.mock import patch
        from task_relay import gemini
        config={'api_key':'fixture','models':{'text':'fixture-text'}}
        with patch.object(gemini,'read_config',return_value=config):
            row=self.queue(action=self.action(step_capabilities=['web.sources']),text='Research items after extraction using prepared sources.')
        payload=json.loads(row['context'])
        support=[s for s in payload['sources'] if s.get('operation_support')=='web.sources.prepared']
        self.assertEqual({s['path'] for s in support},{'operation-support/web.sources.prepared/contract.json','operation-support/web.sources.prepared/validate.py'})
        self.assertTrue({s['artifact'] for s in support}<=set(payload['required_artifacts']))
        checker=next(s for s in support if s['path'].endswith('validate.py'))
        text=next(s['text'] for s in payload['source_texts'] if s['artifact']==checker['artifact'])
        ns={'__name__':'frozen'};exec(text,ns)
        self.assertEqual(ns['validate_prepared']({'version':1,'targets':[{'id':'chair','queries':['chair USA'],'required_options':3}]}),['chair USA'])
