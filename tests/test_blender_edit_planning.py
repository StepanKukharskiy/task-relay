import json
from pathlib import Path
import unittest
from unittest.mock import patch
from task_relay import production_planning as planning
from orchestrator import contracts as c,host_code
from tests import test_production_planning as fixture
from tests.test_blender_edit import inputs

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response

    def setup_plan(self):
        row=self.queue(action=self.action(step_capabilities=['blender.run_python']),text='Run the selected roof edit; preserve cameras, materials and other objects.')
        root=self.rt.root/'editing-inputs';root.mkdir()
        host=inputs(self.rt,root);host['user_gate']='Select the candidate scene'
        host['limits']={'seconds':600,'tool_calls':1,'output_bytes':100000000}
        payload=json.loads(row['context'])
        for item in host['inputs']:
            source=planning.source_entry(self.rt,item['artifact'],item['path'],item['purpose'],item['authority'])
            payload['sources'].append(source);payload['required_artifacts'].append(item['artifact'])
        self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),row['id']))
        review=self.response()['plan']['tasks'][1]
        review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,
            purpose='Independent output review',authority='Unaccepted candidate',media_type=o['media_type']) for o in host['outputs']]
        response=dict(decision='ready',message='Approve the exact script for host execution',plan=dict(brief='Edit roof candidate',tasks=[host,review]))
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        return row

    def test_delivered_exact_script_card_authorizes_only_after_documents_arrive(self):
        with patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture')),patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/blender'}):
            row=self.setup_plan();self.assertIn('No OS isolation',planning.preview(row))
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'complete editing script'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            self.state.db.commit()
            with self.state.db:
                self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            run=self.row()['run'];task=self.rt.task(run,'app')
            grant=host_code.approved(self.rt,run,'app',self.rt.spec(task))
            self.assertEqual(grant['decision']['source'],'delivered_plan_start')
            self.assertEqual(task['attempts'],0);self.assertEqual(self.factory.calls,[])
            with self.assertRaisesRegex(ValueError,'already handled'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')

    def test_changed_selected_script_stops_approval_and_leaves_no_run(self):
        with patch('task_relay.host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture')),patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/blender'}):
            row=self.setup_plan()
            script=next(i for i in json.loads(row['plan'])['tasks'][0]['inputs'] if i['media_type']=='text/x-python')
            path=Path(self.rt.artifact(script['artifact'])['blob']);path.chmod(0o600);path.write_text('print("changed")')
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'changed'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)

if __name__=='__main__':unittest.main()
