"""Confirmed setup recovery; synthetic receipts only, no provider or browser."""
import copy
import json
import unittest

from orchestrator.storage import transaction
from task_relay import completion_recovery as recovery, public_photo_recovery as public
from tests import test_delivery_completion as fixtures
from tests.test_browser_images import graph


class Tests(unittest.TestCase):
    setUp = fixtures.Tests.setUp
    tearDown = fixtures.Tests.tearDown
    request = fixtures.Tests.request
    stage = fixtures.Tests.stage
    step = fixtures.Tests.step
    create = fixtures.Tests.create
    action = fixtures.Tests.action

    def prepare(self):
        p=self.create();value=graph();value['id']='photos'
        producer=value['tasks'][0]
        producer.update(max_attempts=1)
        producer['limits']=dict(seconds=1200,tool_calls=24,provider_requests=24,output_bytes=500000)
        producer['browser'].update(profile='managed',session_source='settings',
                                   interaction_scope='Read only: public photo pages. No accounts, purchases or uploads.')
        # The independent file reviewer does not inherit browser identity.
        reviewer=value['tasks'][1]
        reviewer.pop('browser');reviewer['tools']=['files','shell']
        reviewer['worker']=dict(version=1,executor='codex-cli',requires=['files.text'],
                                backend=dict(type='codex-cli',model='fixture',reasoning='high'))
        self.rt.create(value);self.rt.tick('photos')
        aid=self.rt.task('photos',producer['id'])['latest']
        receipt=dict(status='finished',exit_code=1,reason=public.SIGN_IN_STOP,
                     api_requests=0,tool_calls=0,pending_requests=[],external_outcome='no_pending_response',
                     browser=dict(actions=[],uncertain_actions=[]))
        self.factory.sessions[aid]['status']=receipt;self.rt.tick('photos')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='running',target_kind='production_run',target='photos' WHERE pipeline=? AND id='outline'",(p['id'],))
        return p,self.step(p,'outline'),aid,producer['id']

    def test_native_continuation_preserves_failure_and_dispatches_only_after_commit(self):
        p,s,old,tid=self.prepare()
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone())
        calls=list(self.factory.calls)
        with transaction(self.state.db):self.assertTrue(recovery.begin(self.state,p,s,'photos'))
        self.assertEqual(calls,self.factory.calls)
        self.assertEqual(before,dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone()))
        self.assertEqual(self.rt.task('photos',tid)['attempts'],1)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],1)
        self.rt.tick('photos');new=self.rt.task('photos',tid)['latest']
        self.assertNotEqual(new,old);self.assertEqual(self.rt.task('photos',tid)['attempts'],2)
        f=self.factory.sessions[new]['frozen'];prior=json.loads(before['frozen'])
        self.assertNotIn('session_source',f['browser'])
        self.assertTrue(f['browser']['profile'].startswith('public-photo-'))
        for key in ('origins','image_sources','interaction_scope','max_actions','uploads','downloads'):
            self.assertEqual(f['browser'][key],prior['browser'][key])
        for key in ('backend','inputs','outputs','criteria'):
            self.assertEqual(f[key],prior[key])
        self.assertEqual(f['limits']['seconds'],600)
        with transaction(self.state.db):self.assertFalse(recovery.begin(self.state,p,s,'photos'))

    def test_unknown_effect_or_missing_grant_cannot_add_attempt(self):
        p,s,old,tid=self.prepare()
        receipt=json.loads(self.state.db.execute('SELECT receipt FROM production_attempts WHERE id=?',(old,)).fetchone()[0])
        for change in (dict(api_requests=1),dict(tool_calls=1),dict(pending_requests=['unknown']),
                       dict(browser=dict(actions=[dict(status='observed')],uncertain_actions=[])),
                       dict(reason='Other failure'),dict(exit_code=0)):
            with self.subTest(change=change),transaction(self.state.db):
                self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps({**receipt,**change}),old))
                self.assertFalse(recovery.begin(self.state,p,s,'photos'))
        with transaction(self.state.db):
            self.state.db.execute('UPDATE production_attempts SET receipt=? WHERE id=?',(json.dumps(receipt),old))
            self.state.db.execute('DELETE FROM completion_recovery_grants WHERE pipeline=?',(p['id'],))
            self.assertFalse(recovery.begin(self.state,p,s,'photos'))
        self.assertEqual(self.rt.task('photos',tid)['attempts'],1)

    def test_no_profile_switch_for_account_or_extra_output_work(self):
        p,s,old,tid=self.prepare()
        a=self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone()
        frozen=json.loads(a['frozen']);receipt=json.loads(a['receipt'])
        for change in (dict(interaction_scope='Read only: use signed-in account'),dict(uploads=['secret.txt'])):
            candidate=copy.deepcopy(frozen);candidate['browser'].update(change)
            self.assertFalse(public.confirmed(candidate,receipt))
        candidate=copy.deepcopy(frozen);candidate['outputs'].append(dict(path='report.md',media_type='text/markdown'))
        self.assertFalse(public.confirmed(candidate,receipt))

    def test_rollback_leaves_no_new_assignment_or_dispatch(self):
        p,s,old,tid=self.prepare();task=self.rt.task('photos',tid);calls=list(self.factory.calls)
        with self.assertRaisesRegex(ValueError,'rollback'),transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'photos'))
            raise ValueError('rollback')
        self.assertEqual(self.rt.task('photos',tid),task);self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM completion_recoveries').fetchone()[0],0)

    def test_dispatch_rechecks_committed_authority(self):
        p,s,old,tid=self.prepare();calls=list(self.factory.calls)
        with transaction(self.state.db):
            self.assertTrue(recovery.begin(self.state,p,s,'photos'))
            self.state.db.execute('DELETE FROM completion_recovery_grants WHERE pipeline=?',(p['id'],))
        self.rt.tick('photos')
        self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.task('photos',tid)['latest'],old)
        self.assertEqual(self.rt.task('photos',tid)['attempts'],1)
        self.assertEqual(self.rt.task('photos',tid)['status'],'blocked')
