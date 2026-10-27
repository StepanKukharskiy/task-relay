import copy
import unittest
from orchestrator import contracts, job_owner
from tests import test_owner_compilation as fixture
from tests.test_owner_intents import worker

class Tests(unittest.TestCase):
    def test_explicit_graph_exceeds_legacy_size_but_never_its_frozen_grant(self):
        case=fixture.Tests();case.setUp()
        try:
            case.grant.update(graph_capacity_version=1,max_tasks=36)
            case.create();case.rt.tick('job');session=case.session()
            receipt=session.delegate(dict(request_id='large',tasks=[worker('task-'+str(i)) for i in range(16)]))
            self.assertEqual(len(receipt['queued']),32) # producer + mandatory reviewer
            self.assertEqual(len(case.rt.status('job')['tasks']),33)
            self.assertEqual(len(case.factory.calls),1) # commit does not dispatch
            before=copy.deepcopy(case.rt.status('job')['tasks'])
            with self.assertRaisesRegex(ValueError,'remaining job slots|remaining job task capacity'):
                session.delegate(dict(request_id='over',tasks=[worker('extra-'+str(i)) for i in range(3)]))
            self.assertEqual(case.rt.status('job')['tasks'],before)
            restored=case.session()
            self.assertEqual(restored.snapshot()['remaining_task_slots'],4)
            replay=restored.delegate(dict(request_id='large',tasks=[worker('task-'+str(i)) for i in range(16)]))
            self.assertEqual(set(replay['queued']),set(receipt['queued']))
            self.assertEqual(replay['receipt'],receipt['receipt'])
            self.assertEqual(len(case.rt.status('job')['tasks']),33)
            self.assertEqual(job_owner.original(case.rt,'job')['job_owner']['max_tasks'],36)
        finally:case.tearDown()

    def test_larger_capacity_requires_explicit_new_policy(self):
        case=fixture.Tests();case.setUp()
        try:
            case.grant['max_tasks']=36
            with self.assertRaisesRegex(ValueError,'29 explicitly granted'):case.create()
        finally:case.tearDown()

if __name__=='__main__':unittest.main()
