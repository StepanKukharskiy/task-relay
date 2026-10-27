"""Local fixture controller for a real common-launcher exit-75 restart."""
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.lifecycle_fixture import Lifecycle
from tests.test_owner_intents import worker
from orchestrator.workers import atomic
from task_relay.runtime_process import require_source_only


class Case(Lifecycle,unittest.TestCase):pass


def main():
    require_source_only();directory=Path(sys.argv[1]);case=Case()
    case.persistent_home=directory/'job';case.setUp()
    try:
        receipt=directory/'restart-committed.json'
        if not receipt.exists():
            case.first_candidate();case.checkpoint_observers()
            atomic(receipt,dict(run='lifecycle'))
            return 75
        final=case.corrected(resume=True)
        case.delegate('peers',[worker('unknown'),worker('slow')])
        aid=case.rt.task('job','unknown')['latest']
        case.factory.sessions[aid]['status']=dict(status='uncertain',reason='Fixture effect missing a correlated receipt')
        case.rt.tick('job');case.assertIn('settlement',case.rt.status('job'))
        calls=list(case.factory.calls)
        case.work('slow','Unreviewed but complete peer file.')
        delivery=case.export_partial(final)
        case.assertEqual(calls,case.factory.calls)
        atomic(directory/'final.json',dict(status=case.rt.status('job')['status'],delivery=delivery,
            dispatches=case.factory.calls,complete=False,controlled=True))
        return 0
    finally:case.doCleanups()


if __name__=='__main__':raise SystemExit(main())
