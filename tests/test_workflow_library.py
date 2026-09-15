import copy
import json
import unittest
from unittest.mock import patch

from task_relay import workflow_library as library, production_planning as planning
from tests import test_production_planning as fixtures


class CatalogTests(unittest.TestCase):
    def test_all_starters_have_independent_versioned_stages(self):
        catalog=library.catalog()
        self.assertEqual(len(catalog),5)
        for w in catalog:
            frozen=library.freeze(w['id'])
            self.assertEqual(frozen['stage'],w['stages'][0]['id'])
            self.assertEqual(len({s['id'] for s in w['stages']}),len(w['stages']))
            for s in w['stages']:
                self.assertTrue(all(s[k] for k in ('tools','inputs','outputs','review','instructions')))
            w['stages'][0]['instructions']='local edit'
            self.assertNotEqual(w,library.definition(w['id']))
        self.assertIn('not install',library.describe('carousel-reel'))
        with self.assertRaises(ValueError):library.freeze('carousel-reel','unknown')


class PlanningTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request
    action=fixtures.Tests.action
    queue=fixtures.Tests.queue
    row=fixtures.Tests.row
    response=fixtures.Tests.response

    def test_starter_flows_through_planner_without_starting_production(self):
        original='Prepare the data-presentation workflow analysis stage. Do not produce slides yet.'
        row=self.queue(action=self.action(starter_workflow='data-presentation'),text=original)
        payload=json.loads(row['context'])
        self.assertEqual(payload['original_request'],original)
        frozen=payload['starter_workflow'];self.assertEqual(frozen['stage'],'analysis')
        seen=[]
        def respond(*args):
            seen.append(args)
            return json.dumps(self.response()),{'total_tokens':12}
        planning.Worker(self.state,respond).tick()
        self.assertEqual(self.row()['status'],'ready',self.row()['error'])
        self.assertEqual(json.loads(self.row()['context'])['starter_workflow'],frozen)
        origin=planning.plan_origin(payload,self.response()['plan'],row['request_id'])
        self.assertEqual(origin['template_id'],'data-presentation')
        self.assertEqual(origin['template_version'],frozen['sha256'])
        self.assertEqual(origin['starter_stage'],'analysis')
        self.assertIn('stage analysis',planning.preview(self.row()))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertTrue(seen)

    def test_revision_retains_frozen_version_after_catalog_update(self):
        row=self.queue(action=self.action(starter_workflow='carousel-reel'))
        frozen=json.loads(row['context'])['starter_workflow']
        with self.state.db:self.state.db.execute("UPDATE production_plans SET status='needs_input'")
        changed=copy.deepcopy(library.WORKFLOWS)
        for w in changed:
            if w['id']=='carousel-reel':w['version']+=1;w['stages'][0]['instructions']='changed default'
        with patch.object(library,'WORKFLOWS',changed):
            revised=self.queue(ident=2,action=self.action(parent_id=row['id']),text='Preserve all exact cards.')
        self.assertEqual(json.loads(revised['context'])['starter_workflow'],frozen)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)

    def test_invalid_stage_is_rejected_before_planning(self):
        action=self.action(starter_workflow='research-report',starter_stage='render-video')
        with self.assertRaises(ValueError):planning.validate_action(action,{})

    def test_telegram_catalog_is_read_only(self):
        self.bridge.process({'update_id':71,'message':{'text':'/templates',
            'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],0)
        self.assertTrue(any('research-report' in s[1] for s in self.telegram.sent))
