import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import production_planning as planning
from orchestrator import contracts as c,host_code
from tests import test_production_planning as fixture
from tests.test_rhino_operations import inputs
from tests import test_rhino_operations as rhino_operations
from tests import test_blender_edit_planning as blender_planning


class Tests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        self.rhino=patch('host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture'));self.rhino.start()

    def tearDown(self):self.rhino.stop();fixture.Tests.tearDown(self)
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    start=fixture.Tests.start
    click=fixture.Tests.click

    def test_preparation_contract_reaches_both_workers_and_rejects_provisional_checks(self):
        import production_control as pc
        from orchestrator.rhino_contract import validate_checks, validate_render
        cases=[('rhino.run_python',dict(mode='create',units='Meters',changed_objects=[],allow_additions=True,
                    expected_object_count=1,expected_dimensions={'Core':[8,8,160]},preview={'resolution':[320,240]}),
                {'mode':'create','units':'Meters','changed_objects':[],'allow_additions':True,
                    'expected_object_count':50,'expected_dimensions':{'x':38.4,'y':38.4,'z':160.3,'tolerance':0.02},
                    'preview':{'width':800,'height':600,'view':'Perspective','display_mode':'Shaded'}}),
               ('rhino.render',dict(version=1,engine='rhino_render',named_view='Overview',resolution=[320,240]),
                dict(version=1,engine='viewport',named_view='Overview',resolution=[320,240]))]
        for ident,(cap,valid,invalid) in enumerate(cases,1):
            with self.subTest(cap=cap):
                self.queue(ident=ident,action=self.action(step_capabilities=[cap]),text='Prepare a Rhino tower script and checks. Do not execute Rhino.')
                response=self.response();response['deferred_operations']={cap:'Prepare exact inputs for a separately approved host operation.'}
                producer,review=response['plan']['tasks']
                producer['outputs'].append({'path':'preparation.json','purpose':'Exact prepared manifest'})
                review['inputs'].append({'from_task':'produce','output':'preparation.json','path':'candidate/preparation.json','purpose':'Review prepared manifest','authority':'Candidate'})
                producer['selection_outputs']=[o['path'] for o in producer['outputs']]
                planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
                row=self.row(ident);self.assertEqual(row['status'],'ready',row['error'])
                self.start(row)
                run='production-'+str(ident)
                worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
                producer=self.rt.task(run,'produce')['latest']
                self.factory.finish(producer);worker.tick()
                reviewer=self.rt.task(run,'review')['latest']
                for attempt in (producer,reviewer):
                    frozen=self.factory.sessions[attempt]['frozen']
                    workspace=Path(frozen['workspace']);support=workspace/'operation-support'/cap
                    self.assertIn('frozen authoritative Rhino contract',frozen['instruction'])
                    contract=json.loads((support/'contract.json').read_text())
                    self.assertEqual(contract['id'],cap)
                    self.assertIn('checks_schema' if cap=='rhino.run_python' else 'render_schema',contract)
                    if cap=='rhino.run_python':
                        checks_file=workspace/'valid-checks.json';checks_file.write_text(json.dumps(valid))
                        script_file=workspace/'oversized.py';script_file.write_bytes(b'#'+b' '*100000)
                        result=subprocess.run([sys.executable,'-E','-S',str(support/'validate.py'),str(checks_file),str(script_file)],cwd=workspace,capture_output=True,text=True)
                        self.assertNotEqual(result.returncode,0)
                        self.assertIn('100001',result.stderr)
                    validator=validate_checks if cap=='rhino.run_python' else validate_render
                    for value,success in ((valid,True),(invalid,False)):
                        candidate=workspace/'contract-fixture.json';candidate.write_text(json.dumps(value))
                        result=subprocess.run([sys.executable,'-E','-S',str(support/'validate.py'),str(candidate)],
                            cwd=workspace,capture_output=True,text=True)
                        self.assertEqual(result.returncode==0,success,result.stderr)
                        if success:validator(value)
                        else:
                            with self.assertRaises(ValueError):validator(value)
                self.factory.finish(reviewer,decision='accept');worker.tick()

    def setup_plan(self,capability="rhino.run_python"):
        row=self.queue(action=self.action(step_capabilities=[capability]),text='Create a Rhino tower; leave Grasshopper paused.')
        root=self.rt.root/'rhino-inputs';root.mkdir()
        if capability=='rhino.render':
            from types import SimpleNamespace
            host=rhino_operations.Tests.render_op(SimpleNamespace(root=root,rt=self.rt))
        else:host=inputs(self.rt,root)
        host['user_gate']='Select the Rhino candidate'
        host['limits']={'seconds':600,'tool_calls':1,'output_bytes':10000000 if capability=='rhino.render' else 100000000}
        payload=json.loads(row['context'])
        for item in host['inputs']:
            source=planning.source_entry(self.rt,item['artifact'],item['path'],item['purpose'],item['authority'])
            payload['sources'].append(source);payload['required_artifacts'].append(item['artifact'])
        self.state.db.execute('UPDATE production_plans SET context=?,context_hash=? WHERE id=?',(c.encoded(payload),c.digest(payload),row['id']))
        review=self.response()['plan']['tasks'][1]
        review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,
            purpose='Independent output review',authority='Unaccepted candidate',media_type=o['media_type']) for o in host['outputs']]
        response=dict(decision='ready',message='Approve the exact Rhino script',plan=dict(brief='Rhino candidate creation',tasks=[host,review]))
        self.prepared_response=copy.deepcopy(response)
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        return row

    # The same delivered-script and atomic-Start boundary must hold for Rhino.
    test_exact_script_delivery_required_before_atomic_start=blender_planning.Tests.test_delivered_exact_script_card_authorizes_only_after_documents_arrive
    test_changed_selected_script_leaves_no_run=blender_planning.Tests.test_changed_selected_script_stops_approval_and_leaves_no_run

    def test_render_requires_delivered_manifest_then_atomic_start(self):
        with patch('host_evidence.application_signature',return_value={'path':'/fixture/rhino'}):
            row=self.setup_plan('rhino.render')
            spec=json.loads(row['plan'])['tasks'][0]
            self.assertEqual({i['media_type'] for i in spec['inputs'] if i['path'].endswith(('.3dm','.json'))},{'application/vnd.rhino','application/json'})
            response=copy.deepcopy(self.prepared_response);response['plan']['tasks'][0].pop('user_gate')
            with self.assertRaisesRegex(ValueError,'selection gate'):planning.validate_result(json.dumps(response),row)
            self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],));self.state.db.commit()
            with self.assertRaisesRegex(ValueError,'complete Rhino render manifest'):
                with self.state.db:
                    self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.state.db.execute('SELECT COUNT(*) FROM production_runs').fetchone()[0],0)
            self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],));self.state.db.commit()
            with self.state.db:
                self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            self.assertEqual(self.factory.calls,[])
            self.assertEqual(self.rt.task(self.row()['run'],'app')['attempts'],0)

    def test_rhino_modeling_requires_independent_review_and_selection(self):
        with patch('host_evidence.application_signature',return_value={'path':'/fixture/rhino'}):
            row=self.setup_plan();response=copy.deepcopy(self.prepared_response)
            response['plan']['tasks'][0].pop('user_gate')
            with self.assertRaisesRegex(ValueError,'selection gate'):planning.validate_result(json.dumps(response),row)

    def test_planning_preserves_request_and_exposes_no_gh_operation(self):
        from orchestrator.execution import catalog
        with patch('host_evidence.application_signature',return_value={'path':'/fixture/rhino'}):
            row=self.setup_plan()
        self.assertEqual(row['request'],'Create a Rhino tower; leave Grasshopper paused.')
        self.assertIn('Grasshopper is paused',planning.preview(row))
        ids={e['id'] for e in catalog()}
        self.assertTrue({'rhino.startup','rhino.inspect','rhino.run_python'} <= ids)
        self.assertFalse(any('grasshopper' in i for i in ids))

    def test_native_candidate_reaches_review_and_delivery_queue_once(self):
        import production_control as pc
        from orchestrator.step_runner import execute
        from orchestrator.runtime import file_hash
        with patch('host_evidence.application_signature',return_value={'path':'/fixture/rhino'}):
            row=self.setup_plan()
            with self.state.db:
                self.state.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(row['event_id'],))
                self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE event_id=?",(row['event_id'],))
            with self.state.db:
                self.state.db.execute('BEGIN IMMEDIATE');planning.apply(self.state,row['token'],'start')
            run=self.row()['run'];worker=pc.Worker(self.state,lambda _:self.rt);worker.tick()
            aid=self.rt.task(run,'app')['latest'];session=self.factory.sessions[aid]
            control=Path(session['session']['control']);control.mkdir(parents=True)
            with patch('task_relay.rhino_host.run',side_effect=lambda *args:rhino_operations.Tests.fake_run(self,*args)):
                self.assertEqual(execute(session['frozen'],control)['outcome'],'completed')
            session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[]}
            worker.tick()
            review=self.rt.task(run,'review')['latest']
            candidate=self.rt.output(run,'app','delivery/candidate.3dm')
            selected=next(i for i in self.factory.sessions[review]['frozen']['inputs'] if i.get('media_type')=='application/vnd.rhino')
            self.assertEqual(selected['sha256'],candidate['sha256'])
            self.factory.finish(review,decision='accept');worker.tick();worker.tick()
            self.assertEqual(self.rt.status(run)['status'],'awaiting_user')
            deliveries=self.state.db.execute('SELECT path,filename FROM media_outbox WHERE path=?',(candidate['blob'],)).fetchall()
            self.assertEqual(len(deliveries),1);self.assertTrue(deliveries[0]['filename'].endswith('.3dm'))
            self.assertEqual(file_hash(deliveries[0]['path']),candidate['sha256'])
            self.assertEqual(len(self.factory.calls),2)


if __name__=='__main__':unittest.main()
