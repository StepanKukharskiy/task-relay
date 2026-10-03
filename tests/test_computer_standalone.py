"""Standalone Safari ownership with scripted provider and native launch."""
import json
import unittest
from unittest.mock import patch
from task_relay import job_ownership,computer_sessions
from tests.test_computer_launch import LaunchHelper,managed
from tests.test_computer_worker import Tests as WorkerFixture


class Tests(unittest.TestCase):
    setUp=WorkerFixture.setUp
    tearDown=WorkerFixture.tearDown
    prepare=WorkerFixture.prepare
    execute=WorkerFixture.execute

    def standalone(self):
        db=self.prepare()
        db.execute('DELETE FROM relay_pipeline_steps')
        db.execute('DELETE FROM relay_pipelines')
        db.execute('CREATE TABLE production_plans(id TEXT,run TEXT,parent_id TEXT,channel TEXT,request_id INTEGER,request TEXT,status TEXT)')
        db.execute("INSERT INTO production_plans VALUES ('plan','run',NULL,'telegram',1,'Read synthetic pages','started')")
        db.execute('CREATE TABLE production_runs(id TEXT)')
        db.execute("INSERT INTO production_runs VALUES ('run')")
        db.execute('CREATE TABLE relay_channel_bindings(kind TEXT,entity TEXT,channel TEXT,after_row INTEGER)')
        for table in ('production_stage_links','production_continuations'):
            db.execute('CREATE TABLE '+table+'(parent TEXT,child TEXT)')
        self.frozen['computer']=managed()
        return db

    def test_approved_standalone_launches_with_existing_export_identity(self):
        db=self.standalone();helper=LaunchHelper(db)
        self.assertEqual(self.execute(db,helper)['decision'],'delivered')
        owner=db.execute('SELECT * FROM relay_standalone_jobs').fetchone()
        self.assertEqual(owner['id'],job_ownership.standalone_id('plan'))
        self.assertEqual(owner['root_plan'],'plan')
        self.assertEqual(owner['last_run'],'run')
        self.assertEqual(db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],0)
        for table in computer_sessions.TABLES:
            self.assertEqual({r[0] for r in db.execute('SELECT job FROM '+table)},{owner['id']})
        self.assertEqual(json.loads(db.execute('SELECT request FROM relay_computer_actions ORDER BY ordinal').fetchone()[0])['operation'],'launch')
        before=len(helper.calls)
        with self.assertRaisesRegex(ValueError,'replay'):self.execute(db,helper)
        self.assertEqual(len(helper.calls),before)
        self.assertEqual(db.execute('SELECT count(*) FROM relay_standalone_jobs').fetchone()[0],1)

    def test_unapproved_plan_never_launches_or_calls_provider(self):
        db=self.standalone();db.execute("UPDATE production_plans SET status='ready'")
        helper=LaunchHelper(db)
        with self.assertRaisesRegex(ValueError,'approved standalone'):self.execute(db,helper)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])

    def test_ancestor_pipeline_cannot_be_reclassified_as_standalone(self):
        db=self.standalone()
        db.execute("UPDATE production_plans SET parent_id='root'")
        db.execute("INSERT INTO production_plans VALUES ('root',NULL,NULL,'telegram',0,'Original request','superseded')")
        db.execute("INSERT INTO relay_pipeline_steps VALUES ('pipeline','plan_production','root')")
        helper=LaunchHelper(db)
        with self.assertRaisesRegex(ValueError,'saved pipeline owns'):self.execute(db,helper)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])
        self.assertEqual(db.execute('SELECT count(*) FROM relay_computer_assignments').fetchone()[0],0)

    def test_failed_assignment_rolls_back_new_owner(self):
        db=self.standalone();job_ownership.initialize(db);helper=LaunchHelper(db)
        with patch.object(computer_sessions,'approve',side_effect=ValueError('assignment rejected')):
            with self.assertRaisesRegex(ValueError,'assignment rejected'):self.execute(db,helper)
        self.assertEqual(db.execute('SELECT count(*) FROM relay_standalone_jobs').fetchone()[0],0)
        self.assertEqual(helper.calls,[]);self.assertEqual(self.model.calls,[])
