"""Completed native review findings survive correction routing; no native work runs."""
import json
from pathlib import Path
import unittest
from tests import test_rhino_handoffs as fixture
from tests.test_blender_operations import operation
from task_relay import production_planning as planning, production_status as status
from task_relay import production_review_corrections as correction
from orchestrator.storage import transaction


class Tests(unittest.TestCase):
    for name in ('setUp','tearDown','request','action','queue','row','response','click','drain','start',
                 'preparation','prepare','finish_preparation','prepared_files','select','host_response'):
        locals()[name]=getattr(fixture.Tests,name)

    def rejected(self,quality=False):
        self.prepare(1,self.preparation(),step_capabilities=['rhino.run_python'])
        self.finish_preparation('production-1');self.select('production-1')
        script=self.rt.output('production-1','produce','delivery/model.py')['id']
        checks=self.rt.output('production-1','produce','delivery/checks.json')['id']
        row=self.queue(2,self.action(previous_run='production-1',step_capabilities=['rhino.run_python','rhino.inspect']))
        response=self.host_response(row,'rhino.run_python',[(script,'text/x-python','script_sha256'),(checks,'application/json','checks_sha256')])
        app,review=response['plan']['tasks']
        inspect=operation('rhino.inspect',[{'from_task':'app','output':'delivery/candidate.3dm','path':'model.3dm','purpose':'Inspect candidate','authority':'Unaccepted','media_type':'application/vnd.rhino'}])
        inspect.update(id='inspect',dependencies=['app'],limits={'seconds':120,'tool_calls':1,'output_bytes':2000000})
        review['dependencies'].append('inspect');review['inputs'].append({'from_task':'inspect','output':'delivery/inspection.json','path':'inventory.json','purpose':'Independent native inventory','authority':'Evidence'})
        response['plan']['tasks']=[app,inspect,review]
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row(2);self.assertEqual(row['status'],'ready',row['error']);self.start(row);self.production.tick()
        for tid in ('app','inspect'):
            aid=self.rt.task('production-2',tid)['latest'];self.assertIsNotNone(aid)
            self.factory.finish(aid)
            self.factory.sessions[aid]['status'].update(operation={'outcome':'completed'})
            self.production.tick()
        aid=self.rt.task('production-2','review')['latest'];self.factory.finish(aid,decision='revise')
        path=self.factory.sessions[aid]['workspace']/'.relay/result.json';result=json.loads(path.read_text())
        result.update(summary='Model exists; saved camera needs correction.',instruction='Correct only the saved camera target. Preserve geometry and input checks.')
        if quality:
            from orchestrator.outcomes import quality as finding
            result['findings']=[finding('camera_framing','Camera framing crops the model','delivery/preview.png compared to native inventory')]
        path.write_text(json.dumps(result));self.production.tick()
        return 'production-2'

    def test_quality_feedback_prepares_exact_correction_without_replaying_native_work(self):
        from task_relay import production_control as pc
        run=self.rejected(quality=True);before=self.rt.status(run);calls=len(self.factory.calls)
        self.assertEqual(before['status'],'awaiting_user')
        self.assertEqual(correction.details(self.state,run)['kind'],'quality_feedback')
        self.assertIn('accept these exact outputs as-is',correction.text(self.state,run))
        view=next(v for v in pc.inspect(self.state) if v['name']==run)
        self.assertEqual(pc.revision_target(view)['id'],'app')
        feedback='Please show the full terrain and keep its current dimensions.'
        with transaction(self.state.db):ident=correction.propose(self.state,run,feedback=feedback)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone()
        plan=json.loads(row['plan'])
        self.assertIn(feedback,plan['tasks'][0]['instruction'])
        self.assertIn(feedback,row['request'])
        self.assertTrue(all(not t.get('execution') for t in plan['tasks']))
        self.assertEqual(self.rt.status(run),before);self.assertEqual(len(self.factory.calls),calls)

    def test_native_rejection_finishes_review_and_preserves_completed_inspection(self):
        run=self.rejected();before=len(self.factory.calls)
        self.assertEqual(self.rt.task(run,'app')['status'],'blocked')
        self.assertEqual(self.rt.task(run,'inspect')['status'],'completed')
        self.assertEqual(self.rt.task(run,'review')['status'],'completed')
        self.production.tick();self.assertEqual(len(self.factory.calls),before)
        _,text=status.current(self.state,run)
        self.assertIn('saved camera',text);self.assertIn('Next action:',text);self.assertIn('Plan correction',text)
        self.assertNotIn('Downstream work already started',text)
        terminal=self.state.db.execute("SELECT text FROM outbox WHERE id LIKE ? ORDER BY rowid DESC LIMIT 1",('production:'+run+':result:%',)).fetchone()[0]
        self.assertIn('Plan correction',terminal);self.assertIn('saved camera',terminal)
        buttons=status.controls(self.state,'production:'+run+':status:test')['inline_keyboard']
        self.assertTrue(any(b['text']=='Plan correction' for row in buttons for b in row))

    def test_proposal_is_idempotent_preparation_only_and_old_receipts_are_unchanged(self):
        run=self.rejected();before=self.rt.status(run);calls=len(self.factory.calls)
        with transaction(self.state.db):ident=correction.propose(self.state,run)
        with transaction(self.state.db):self.assertEqual(correction.propose(self.state,run),ident)
        self.assertEqual(self.rt.status(run),before);self.assertEqual(len(self.factory.calls),calls)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone();plan=json.loads(row['plan'])
        self.assertEqual(row['status'],'ready');self.assertTrue(all(not t.get('execution') for t in plan['tasks']))
        self.assertEqual(len(plan['tasks']),2);self.assertIn('rhino.run_python',plan['deferred_operations'])
        self.assertIn('Start preparation',json.dumps(planning.controls(self.state,row['event_id'])))
        self.assertIn('verification REPORT',plan['tasks'][0]['instruction'])
        self.start(row);self.production.tick()
        self.assertIn(self.rt.task(plan['id'],'prepare_correction')['status'],('launching','running'))
        self.assertEqual(self.rt.task(run,'app')['attempts'],1)

    def test_legacy_collection_error_is_explained_without_rewriting_it(self):
        run=self.rejected();review=self.rt.task(run,'review')
        with self.state.db:
            self.state.db.execute("UPDATE production_tasks SET status='awaiting_review' WHERE run=? AND id='app'",(run,))
            self.state.db.execute("UPDATE production_tasks SET status='blocked' WHERE run=? AND id='review'",(run,))
            self.state.db.execute("UPDATE production_attempts SET state='blocked',error=? WHERE id=?",('Downstream work already started; create a new explicit workflow',review['latest']))
        old=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(review['latest'],)).fetchone())
        _,text=status.current(self.state,run);self.assertIn('saved camera',text);self.assertNotIn('Downstream work already started',text)
        with transaction(self.state.db):correction.propose(self.state,run)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(review['latest'],)).fetchone()),old)

    def test_stale_target_and_uncertain_work_do_not_offer_recovery(self):
        run=self.rejected()
        aid=self.rt.task(run,'app')['latest']
        with self.state.db:self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(aid,))
        self.assertIsNone(correction.details(self.state,run))
        with transaction(self.state.db),self.assertRaises(ValueError):correction.propose(self.state,run)

    def test_changed_baseline_cannot_start_prepared_correction(self):
        run=self.rejected()
        with transaction(self.state.db):ident=correction.propose(self.state,run)
        row=self.state.db.execute('SELECT * FROM production_plans WHERE id=?',(ident,)).fetchone();self.drain()
        with self.state.db:self.state.put('production-control-epoch:'+run,1)
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'state changed'):
            planning.apply(self.state,row['token'],'start')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs WHERE id=?',('production-'+str(row['request_id']),)).fetchone()[0],0)

    def test_only_a_delivered_authenticated_button_can_propose_correction(self):
        run=self.rejected();self.drain()
        mid=self.state.db.execute('SELECT message_id FROM orchestrator_messages WHERE focus=? ORDER BY rowid DESC LIMIT 1',(run,)).fetchone()[0]
        def click(user,message):
            status.callback(self.bridge,{'callback_query':{'id':'correction-'+str(user)+'-'+str(message),
                'data':status.token(run,'prodcorrect'),'from':{'id':user},
                'message':{'message_id':message,'chat':{'id':7,'type':'private'}}}})
        before=self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0]
        click(8,mid);click(7,mid+99999)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],before)
        click(7,mid);click(7,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],before+1)
        row=self.state.db.execute("SELECT * FROM production_plans WHERE json_extract(context,'$.review_correction_origin.run')=?",(run,)).fetchone()
        self.assertEqual(row['status'],'ready');self.assertIsNone(row['run'])
