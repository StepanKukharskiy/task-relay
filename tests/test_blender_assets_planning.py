import json
from pathlib import Path
import unittest
from unittest.mock import patch
import production_planning as planning
from orchestrator import contracts as c
from tests import test_production_planning as fixture
from tests.test_blender_assets import inputs

class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    def ready_assets(self):
        row=self.queue(action=self.action(step_capabilities=['blender.import_asset']),text='Pack the selected scene and texture into a portable candidate.')
        root=self.rt.root/'asset-inputs';root.mkdir();host,manifest=inputs(self.rt,root)
        host['user_gate']='Select portable candidate';host['limits']={'seconds':600,'tool_calls':1,'output_bytes':100000000}
        payload=json.loads(row['context'])
        for item in host['inputs']:
            source=planning.source_entry(self.rt,item['artifact'],item['path'],item['purpose'],item['authority'])
            payload['sources'].append(source);payload['required_artifacts'].append(item['artifact'])
        self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),row['id']))
        review=self.response()['plan']['tasks'][1];review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,purpose='Review exact output',authority='Unselected candidate',media_type=o['media_type']) for o in host['outputs']]
        value=dict(decision='ready',message='Portable candidate for review',plan=dict(brief='Pack selected texture',tasks=[host,review]))
        planning.Worker(self.state,lambda *_:(json.dumps(value),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error']);return row
    def test_exact_manifest_delivery_gates_start_and_binary_inputs_are_retained(self):
        with patch('host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture')):
            row=self.ready_assets();plan=json.loads(row['plan']);host=plan['tasks'][0]
            self.assertEqual(sum(i['media_type']=='image/png' for i in host['inputs']),1)
            self.assertIn('No downloads or persistent links',planning.preview(row))
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],));self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'complete asset manifest'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],));self.state.db.commit()
            with self.state.db:
                self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.rt.task(self.row()['run'],'app')['attempts'],0)
            self.assertEqual(self.factory.calls,[])
    def test_selected_asset_changed_after_card_cannot_start(self):
        with patch('host_apps.blender',return_value=dict(available=True,executable='/fixture/blender',evidence='fixture')):
            row=self.ready_assets();host=json.loads(row['plan'])['tasks'][0]
            item=next(i for i in host['inputs'] if i['media_type']=='image/png');p=Path(self.rt.artifact(item['artifact'])['blob']);p.chmod(0o600);p.write_bytes(b'changed')
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],));self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],));self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'changed'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('select count(*) from production_runs').fetchone()[0],0)

if __name__=='__main__':unittest.main()
