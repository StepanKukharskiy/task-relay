import unittest
from task_relay.source_batches import validate
from task_relay.completion_recovery import browser_subset

class Tests(unittest.TestCase):
    def test_resolved_api_capacity_includes_export_and_finish(self):
        task=dict(browser=dict(image_sources=[dict(subjects=[dict(id=str(i)) for i in range(5)])]),limits=dict(tool_calls=24,provider_requests=24))
        validate({'tasks':[task]})
        task['browser']['image_sources'][0]['subjects'].append({'id':'six'})
        with self.assertRaisesRegex(ValueError,'split subjects'):validate({'tasks':[task]})
        task['browser']['image_sources'][0]['subjects'].pop();task['limits']['provider_requests']=8
        with self.assertRaisesRegex(ValueError,'resolved'):validate({'tasks':[task]})

    def test_source_batch_rejects_more_work_than_native_page_budget(self):
        task=dict(execution=dict(capability='web.sources',parameters=dict(queries=['q'+str(i) for i in range(21)])))
        with self.assertRaisesRegex(ValueError,'native external'):validate({'tasks':[task]})
        task['execution']['parameters']['queries'].pop();validate({'tasks':[task]})

    def test_missing_photo_subset_cannot_expand_browser_authority(self):
        import copy
        original=dict(origins=['https://example.test'],max_actions=24,image_sources=[dict(path='images.json',subjects=[dict(id='one'),dict(id='two')])])
        candidate=copy.deepcopy(original);candidate['image_sources'][0]['subjects'].pop()
        self.assertTrue(browser_subset(candidate,original))
        candidate['origins'].append('https://elsewhere.test');self.assertFalse(browser_subset(candidate,original))
        candidate=copy.deepcopy(original);candidate['image_sources'][0]['subjects'].append(dict(id='new'))
        self.assertFalse(browser_subset(candidate,original))
