"""Small receipt fixtures; the audit cannot change or dispatch Relay work."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.audit_planner_contracts import audit


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('CREATE TABLE production_plans(id TEXT,status TEXT);'
                            'CREATE TABLE production_plan_calls(plan_id TEXT,number INTEGER,created REAL,error TEXT,prompt TEXT);')
            db.executemany('INSERT INTO production_plans VALUES (?,?)',[('old','ready'),('new','blocked')])
            rows=[('old',1,1,'Unsupported assignment field.','PRIVATE REQUEST'),
                  ('old',2,2,None,'PRIVATE REQUEST'),
                  ('new',1,3,'Gemini request failed (429)','PRIVATE REQUEST'),
                  ('new',2,4,'No eligible worker for code.execute.','PRIVATE REQUEST'),
                  ('new',3,5,'Unrecognized issue with /private/example','PRIVATE REQUEST')]
            db.executemany('INSERT INTO production_plan_calls VALUES (?,?,?,?,?)',rows)

    def test_counts_do_not_confuse_calls_plans_or_noncontract_failures(self):
        result=audit(self.path);groups={g['category']:g for g in result['groups']}
        self.assertEqual((result['planning_calls'],result['failed_calls'],result['plans_with_failed_calls']),(5,4,2))
        self.assertEqual(groups['response_shape']['current_plan_statuses'],{'ready':1})
        self.assertEqual(groups['provider_error']['failed_calls'],1)
        self.assertEqual(groups['capability_unavailable']['failed_calls'],1)
        self.assertEqual(len(groups['unclassified']['signature_sha256s']),1)

    def test_read_only_and_default_output_excludes_private_values(self):
        before=self.path.read_bytes();result=audit(self.path)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertNotIn('PRIVATE REQUEST',json.dumps(result))
        self.assertNotIn('/private/example',json.dumps(result))
        self.assertNotIn('plan_id',json.dumps(result))
        self.assertIn('/private/example',json.dumps(audit(self.path,details=True)))
        self.assertNotIn('PRIVATE REQUEST',json.dumps(audit(self.path,details=True)))

    def test_time_filter_keeps_unknown_failures_and_empty_window(self):
        result=audit(self.path,since=4)
        self.assertEqual((result['planning_calls'],result['failed_calls']),(2,2))
        self.assertEqual({g['category'] for g in result['groups']},{'capability_unavailable','unclassified'})
        self.assertEqual(audit(self.path,since=6)['groups'],[])

    def test_missing_and_unrelated_databases_are_not_created_or_migrated(self):
        absent=self.path.with_name('missing.sqlite')
        with self.assertRaisesRegex(ValueError,'no database was created'):audit(absent)
        self.assertFalse(absent.exists())
        other=self.path.with_name('other.sqlite')
        with closing(sqlite3.connect(other)) as db, db:db.execute('CREATE TABLE unrelated(x)')
        before=other.read_bytes()
        with self.assertRaisesRegex(ValueError,'no migration'):audit(other)
        self.assertEqual(other.read_bytes(),before)


if __name__=='__main__':unittest.main()
