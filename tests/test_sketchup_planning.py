import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from orchestrator import contracts as c
from task_relay import production_planning as planning
from tests import test_production_planning as fixture
from tests import test_blender_edit_planning as approvals
from tests.test_sketchup_operations import inputs, checks


class Tests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        self.app=patch('task_relay.host_apps.sketchup',return_value=dict(available=True,executable='/fixture/sketchup',version='26.0',evidence='fixture',blocker=None,interpreter='Ruby'));self.app.start()

    def tearDown(self):self.app.stop();fixture.Tests.tearDown(self)
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    start=fixture.Tests.start
    click=fixture.Tests.click

    def setup_plan(self):
        row=self.queue(action=self.action(step_capabilities=['sketchup.run_ruby']),text='Create a SketchUp box and return its native model and preview.')
        root=self.rt.root/'sketchup-inputs';root.mkdir()
        host=inputs(self.rt,root);host['user_gate']='Select SketchUp candidate'
        host['limits']=dict(seconds=600,tool_calls=1,output_bytes=100000000)
        payload=json.loads(row['context'])
        for item in host['inputs']:
            source=planning.source_entry(self.rt,item['artifact'],item['path'],item['purpose'],item['authority'])
            payload['sources'].append(source);payload['required_artifacts'].append(item['artifact'])
        self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),row['id']))
        review=self.response()['plan']['tasks'][1]
        review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,
            purpose='Review actual output',authority='Unaccepted candidate',media_type=o['media_type']) for o in host['outputs']]
        response=dict(decision='ready',message='Approve exact SketchUp Ruby',plan=dict(brief='SketchUp box',tasks=[host,review]))
        response['geometry_basis']={'mode':'procedural','artifacts':[],'checks':[]}
        self.prepared_response=copy.deepcopy(response)
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        return row

    test_atomic_start_requires_delivered_code_and_checks=approvals.Tests.test_delivered_exact_script_card_authorizes_only_after_documents_arrive
    def test_changed_script_cannot_create_a_run(self):
        with patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/sketchup'}):
            row=self.setup_plan()
            script=next(i for i in json.loads(row['plan'])['tasks'][0]['inputs'] if i['media_type']=='text/x-ruby')
            path=Path(self.rt.artifact(script['artifact'])['blob']);path.chmod(0o600);path.write_text('raise "changed"')
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],));self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'changed'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM production_runs').fetchone()[0],0)

    def test_ruby_attachment_and_independent_review_are_required(self):
        with patch('task_relay.host_evidence.application_signature',return_value={'path':'/fixture/sketchup'}):
            row=self.setup_plan()
            attachments=list(self.state.db.execute('SELECT filename FROM media_outbox WHERE event_id=?',(row['event_id'],)))
            self.assertIn('app-edit.rb',[a['filename'] for a in attachments])
            self.assertIn('HOST CODE',planning.preview(row))
            response=copy.deepcopy(self.prepared_response);response['plan']['tasks'][0].pop('user_gate')
            with self.assertRaisesRegex(ValueError,'selection gate'):planning.validate_result(json.dumps(response),row)

    def test_preparation_receives_portable_contract_and_selects_both_files(self):
        row=self.queue(action=self.action(step_capabilities=['sketchup.run_ruby']),text='Prepare a SketchUp script and checks, do not execute.')
        payload=json.loads(row['context'])
        sources={s['path']:s for s in payload['sources']}
        prefix='operation-support/sketchup.run_ruby/'
        root=self.rt.root/'portable';root.mkdir()
        for name in ('contract.json','sketchup_contract.py','host_script.py','validate.py'):
            source=sources[prefix+name];artifact=self.rt.artifact(source['artifact'])
            (root/name).write_bytes(Path(artifact['blob']).read_bytes())
        (root/'checks.json').write_text(json.dumps(checks()));(root/'model.rb').write_text('model = Sketchup.active_model\n')
        result=subprocess.run([sys.executable,'-E','-S',str(root/'validate.py'),str(root/'checks.json'),str(root/'model.rb')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        response=self.response();response['deferred_operations']={'sketchup.run_ruby':'Prepare reviewed code first'}
        producer,review=response['plan']['tasks']
        producer['outputs']=[dict(path='model.rb',purpose='Exact Ruby'),dict(path='checks.json',purpose='Exact checks')]
        producer['selection_outputs']=['model.rb','checks.json']
        review['inputs']=[dict(from_task='produce',output=n,path='candidate/'+n,purpose='Review',authority='Candidate') for n in ('model.rb','checks.json')]
        _,validated=planning.validate_result(json.dumps(response),row)
        for task in validated['tasks']:self.assertIn('frozen authoritative SketchUp contract',task['instruction'])
        producer['selection_outputs']=['model.rb']
        with self.assertRaisesRegex(ValueError,'script and checks together'):planning.validate_result(json.dumps(response),row)
