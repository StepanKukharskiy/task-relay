"""Image grants survive native planner schemas; malformed grants fail clearly."""
import copy
import unittest
from orchestrator import browser_contract
from task_relay import planning_contract

class Tests(unittest.TestCase):
    def policy(self):
        return dict(profile='managed',session_source='settings',origins=['https://www.article.com'],
                    interaction_scope='Read product pages',max_tabs=2,max_actions=24,
                    uploads=[],downloads=[],image_sources=[dict(path='delivery/images.json',
                    subjects=[dict(id='f01-a',label='Yellow sofa',query='yellow velvet sofa')])])

    def test_native_schema_declares_nested_grant_and_subject_fields(self):
        schema=planning_contract.contract({})['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']['properties']['browser']
        policy=self.policy();planning_contract.validate(policy,schema)
        grant=schema['properties']['image_sources']['items']
        self.assertEqual(set(grant['required']),{'path','subjects'})
        self.assertEqual(set(grant['properties']['subjects']['items']['required']),{'id','label','query'})
        broken=copy.deepcopy(policy);broken['image_sources']=[{}]
        with self.assertRaisesRegex(ValueError,'path'):
            planning_contract.validate(broken,schema)

    def test_malformed_grants_fail_before_worker_file_resolution(self):
        task={'browser':self.policy(),'outputs':[dict(path='delivery/images.json',media_type='application/json')]}
        browser_contract.validate_files(task)
        task['browser']['image_sources']=[{}, {}, {}]
        with self.assertRaisesRegex(ValueError,'At most one'):
            browser_contract.validate_files(task)
        task['browser']['image_sources']=[{}]
        with self.assertRaisesRegex(ValueError,'path and subjects'):
            browser_contract.validate_files(task)
