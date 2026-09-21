"""A retry of an old review must not strand a newer draft without a reason."""
import json
import unittest
from pathlib import Path

from orchestrator import executors
from orchestrator.storage import transaction
from task_relay import production_control as pc,production_visual_review as recovery
from task_relay import production_continuations as continuations
from tests import test_production_planning as fixture
from tests.test_orchestrator import pair
from tests import test_visual_review as visual_fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    deliver=visual_fixture.RecoveryTests.deliver

    def stopped(self):
        plan=pair(gate='Select the reviewed draft',max_attempts=2)
        plan['backend']={'type':'gemini-agent','model':'fixture'}
        for task in plan['tasks']:task.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
        self.rt.create(plan);self.rt.tick('demo')
        first=self.rt.task('demo','produce')['latest'];self.factory.finish(first);self.rt.tick('demo')
        crashed=self.rt.task('demo','review')['latest']
        self.factory.sessions[crashed]['status']={'status':'finished','exit_code':1,'reason':'Fixture file writer failure',
            'external_outcome':'no_pending_response','pending_requests':[]}
        self.rt.tick('demo');self.rt.retry_review('demo','review','Retry review of this same candidate');self.rt.tick('demo')
        reviewed=self.rt.task('demo','review')['latest'];self.factory.finish(reviewed,decision='revise')
        self.factory.sessions[reviewed]['status'].update(external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('demo');second=self.rt.task('demo','produce')['latest']
        self.factory.finish(second);self.rt.tick('demo')
        return first,second,reviewed

    def propose(self):
        with transaction(self.state.db):
            text=continuations.enqueue(self.state,{'id':99,'prompt':'Continue this production. Review the corrected draft.'},'demo')
        self.assertIn('ONE additional review',text)
        return self.state.db.execute('SELECT * FROM production_visual_review_cards').fetchone()

    def test_card_explains_new_candidate_never_reviewed_even_with_legacy_event(self):
        first,second,reviewed=self.stopped()
        for legacy in (False,True):
            if legacy:
                with self.state.db:self.state.db.execute("UPDATE production_events SET data='{}' WHERE kind='attempt_limit'")
            view=pc.inspect(self.state,'demo')[0];review=next(t for t in view['tasks'] if t['id']=='review')
            self.assertIn('Review attempt allowance exhausted (2/2)',review['error'])
            self.assertIn('current candidate has not been reviewed',review['error'])
            self.assertEqual(review['review_target'],first)
            self.assertEqual(self.rt.task('demo','produce')['latest'],second)

    def test_explicit_start_reviews_only_new_exact_candidate_once(self):
        _,second,old=self.stopped();before=[dict(a) for a in self.state.db.execute('SELECT * FROM production_attempts ORDER BY id')]
        row=self.propose()
        self.assertEqual(self.rt.task('demo','review')['attempts'],2)
        self.assertEqual(len(self.factory.calls),4)
        with self.assertRaisesRegex(ValueError,'delivered'),transaction(self.state.db):recovery.apply(self.state,row['token'],7,9)
        self.deliver(row)
        with transaction(self.state.db):
            recovery.apply(self.state,row['token'],7,9)
            recovery.apply(self.state,row['token'],7,9)
        self.assertEqual(before,[dict(a) for a in self.state.db.execute('SELECT * FROM production_attempts ORDER BY id')])
        self.rt.tick('demo');new=self.rt.task('demo','review')['latest']
        frozen=self.factory.sessions[new]['frozen']
        self.assertEqual(frozen['review_target'],second)
        self.assertEqual(Path(frozen['workspace'],'candidate.txt').read_text(),'artifact from '+second)
        self.assertEqual(self.rt.task('demo','produce')['attempts'],2)
        self.assertEqual(self.rt.task('demo','review')['attempts'],3)
        self.factory.finish(new,decision='accept');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')
        self.assertEqual(len(self.factory.calls),5)

    def test_changed_candidate_or_uncertain_state_cannot_use_old_card(self):
        _,second,old=self.stopped();row=self.propose();self.deliver(row)
        with self.state.db:self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(old,))
        with self.assertRaisesRegex(ValueError,'uncertain'),transaction(self.state.db):recovery.apply(self.state,row['token'],7,9)
        with self.state.db:self.state.db.execute("UPDATE production_attempts SET state='completed' WHERE id=?",(old,))
        artifact=self.rt.output('demo','produce','output.txt');path=Path(artifact['blob']);path.chmod(0o600);path.write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'),transaction(self.state.db):recovery.apply(self.state,row['token'],7,9)
        self.assertEqual(len(self.factory.calls),4)
