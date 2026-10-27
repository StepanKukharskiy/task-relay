"""Normal desktop intake, stage closure and immutable omission recovery."""
import hashlib
import io
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import uuid

from orchestrator import contracts as c
from task_relay import desktop_plans,orchestrator_chat,pipelines,production_planning,workflow_attachments
from task_relay.relay_paths import Paths
from tests import test_delivery_completion as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    stage=fixtures.Tests.stage
    step=fixtures.Tests.step
    response=fixtures.Tests.response

    def native(self, suffix='.txt', raw=b'Exact source selected by the user.\n', omit=False):
        paths=Paths(Path(self.tmp.name)/'app',self.state.media_dir.parent,
                    Path(self.tmp.name)/'projects',Path(self.tmp.name)/'generated')
        original=Path(self.tmp.name)/('reference'+suffix);original.write_bytes(raw)
        with self.state.db:
            self.state.put('health:desktop-plans',dict(interface_version=1,orchestrator_entry_version=1,last_success=time.time()))
        request=str(uuid.uuid4())
        desktop_plans.create('Read my attached source and deliver the reviewed file.','',None,None,request,
                             paths,files=[str(original)],entry_mode='conversation',research_mode='none')
        desktop_plans.process_requests(self.state)
        action=fixtures.Tests.action(self)
        # Reproduce an older deployed omission without bypassing the entry path.
        if omit:
            with patch.object(workflow_attachments,'capture',return_value=([],None)):
                orchestrator_chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Saved workflow.',action=action))).tick()
        else:
            orchestrator_chat.Worker(self.state,lambda *_:json.dumps(dict(answer='Saved workflow.',action=action))).tick()
        pipeline=self.state.db.execute('SELECT * FROM relay_pipelines').fetchone()
        self.assertIsNotNone(pipeline,dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone()))
        self.assertEqual(pipeline['channel'],'desktop')
        return pipeline,original,raw

    def test_native_attachment_survives_intake_and_reaches_first_and_later_stage(self):
        pipeline,original,raw=self.native()
        original.write_bytes(b'Changed external original after submission')
        pipelines.tick(self.state)
        first=self.step(pipeline,'outline')
        context=json.loads(self.state.db.execute('SELECT context FROM production_plans WHERE id=?',(first['target'],)).fetchone()[0])
        source=next(s for s in context['sources'] if s.get('workflow_artifact'))
        self.assertEqual(source['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(production_planning.verify_artifact(self.rt,source).read_bytes(),raw)
        # Stage completion is controlled; only attachment closure is under test.
        with self.state.db:pipelines.complete(self.state,pipeline,first,[],'Controlled previous result')
        pipelines.tick(self.state)
        second=self.step(pipeline,'finish')
        inputs=pipelines.request_context(self.state,second['request_id'])['inputs']['sources']
        self.assertTrue(any(s['sha256']==source['sha256'] for s in inputs))
        self.assertEqual(self.factory.calls,[])

    def test_static_non_png_image_keeps_original_and_recorded_pixel_copy(self):
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(100,120),(50,130,180)).save(out,format='WEBP',lossless=True)
        pipeline,_,raw=self.native('.webp',out.getvalue());pipelines.tick(self.state)
        first=self.step(pipeline,'outline')
        inputs=pipelines.request_context(self.state,first['request_id'])['inputs']['sources']
        self.assertEqual(len(inputs),2)
        self.assertIn(hashlib.sha256(raw).hexdigest(),{s['sha256'] for s in inputs})
        png=next(s for s in inputs if s['media_type']=='image/png')
        with Image.open(io.BytesIO(raw)) as before,Image.open(png['path']) as after:
            self.assertEqual(before.convert('RGBA').tobytes(),after.convert('RGBA').tobytes())
        row=self.state.db.execute("SELECT detail FROM relay_pipeline_events WHERE kind='request_attachments_bound'").fetchone()
        receipt=json.loads(row[0])['bindings'][0]
        self.assertEqual(receipt['decoded']['decoded_from']['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['decoded']['sha256'],png['sha256'])

    def test_omitted_attachment_recovers_once_without_resetting_old_plan_or_calls(self):
        pipeline,original,raw=self.native(omit=True);pipelines.tick(self.state)
        first=self.step(pipeline,'outline');old_id=first['target']
        production_planning.Worker(self.state,lambda *_:(c.encoded(dict(decision='needs_input',message='Required source absent.',plan=None)),{})).tick()
        before=dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old_id,)).fetchone())
        calls=[tuple(row) for row in self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(old_id,))]
        original.write_bytes(b'External newer source must never be selected')
        pipelines.tick(self.state)
        successor_id=self.step(pipeline,'outline')['target'];self.assertNotEqual(successor_id,old_id)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(old_id,)).fetchone()),before)
        self.assertEqual([tuple(row) for row in self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(old_id,))],calls)
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(successor_id,)).fetchone()
        self.assertEqual(successor['parent_id'],old_id);self.assertEqual(successor['options'],before['options'])
        context=json.loads(successor['context']);source=next(s for s in context['sources'] if s.get('workflow_artifact'))
        self.assertEqual(production_planning.verify_artifact(self.rt,source).read_bytes(),raw)
        production_planning.Worker(self.state,lambda *_:(c.encoded(dict(decision='needs_input',message='Different essential information absent.',plan=None)),{})).tick()
        pipelines.tick(self.state);self.assertEqual(self.step(pipeline,'outline')['target'],successor_id)
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='request_attachments_recovered'").fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_changed_capture_stops_before_a_successor_or_execution(self):
        pipeline,_,_=self.native(omit=True);pipelines.tick(self.state)
        first=self.step(pipeline,'outline')
        production_planning.Worker(self.state,lambda *_:(c.encoded(dict(decision='needs_input',message='Missing input.',plan=None)),{})).tick()
        manifest=json.loads(self.state.db.execute('SELECT manifest FROM desktop_plan_inputs').fetchone()[0])
        captured=Path(manifest[0]['path']);captured.chmod(0o600);captured.write_bytes(b'corrupted captured source')
        pipelines.tick(self.state)
        self.assertEqual(self.state.db.execute('SELECT status FROM relay_pipelines').fetchone()[0],'blocked')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def blocked_empty_descriptor(self):
        from task_relay import planning_contract
        pipeline,_,_=self.native();pipelines.tick(self.state)
        stage=self.step(pipeline,'outline');value=self.response()
        value['deliverable_map']={'outline':dict(task='produce',output='output.txt')}
        for task in value['plan']['tasks']:
            task.pop('user_gate',None)
            for output in task['outputs']:output.update(media_type='text/plain',handoff={})
        original_prepare=planning_contract.prepare;original_contract=planning_contract.contract
        def old_contract(*args,**kwargs):
            result=original_contract(*args,**kwargs)
            shape=result['schema']['properties']['plan']['anyOf'][0]['properties']['tasks']['items']
            shape['properties']['outputs']['items']['properties']['handoff']={'type':'object'}
            return result
        def old_prepare(result,payload,options,**kwargs):
            return original_prepare(result,{**payload,'connector_companions_version':0},options,**kwargs)
        with patch.object(planning_contract,'contract',side_effect=old_contract),patch.object(planning_contract,'prepare',side_effect=old_prepare):
            worker=production_planning.Worker(self.state,lambda *_:(c.encoded(value),{}))
            worker.tick();worker.tick()
        row=dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone())
        self.assertEqual(row['status'],'blocked',row['error'])
        with self.state.db:
            self.state.db.execute("UPDATE relay_pipeline_steps SET status='blocked' WHERE pipeline=? AND id='outline'",(pipeline['id'],))
            self.state.db.execute("UPDATE relay_pipelines SET status='blocked' WHERE id=?",(pipeline['id'],))
        return pipeline,row

    def test_controller_recompiles_completed_reply_and_continues_without_another_model_call(self):
        pipeline,row=self.blocked_empty_descriptor()
        calls=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(row['id'],))]
        pipelines.tick(self.state)
        stage=self.step(pipeline,'outline');self.assertNotEqual(stage['target'],row['id'])
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(row['id'],)).fetchone()),row)
        self.assertEqual([tuple(r) for r in self.state.db.execute('SELECT * FROM production_plan_calls WHERE plan_id=?',(row['id'],))],calls)
        successor=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(stage['target'],)).fetchone()
        self.assertEqual(successor['calls'],0);self.assertEqual(successor['status'],'started')
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='planning_compiler_recovered'").fetchone()[0],1)
        self.assertEqual(self.factory.calls,[])

    def test_paused_workflow_is_not_resumed_by_compiler_recovery(self):
        pipeline,row=self.blocked_empty_descriptor()
        with self.state.db:self.state.db.execute("UPDATE relay_pipelines SET status='paused' WHERE id=?",(pipeline['id'],))
        pipelines.tick(self.state);self.assertEqual(self.step(pipeline,'outline')['target'],row['id'])
        self.assertEqual(self.state.db.execute("SELECT count(*) FROM relay_pipeline_events WHERE kind='planning_compiler_recovered'").fetchone()[0],0)


if __name__=='__main__':unittest.main()
