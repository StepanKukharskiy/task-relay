"""Controlled complete stage transitions; no live providers or channel sends."""
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import production_control as pc
import production_planning as planning
import production_selections as selections
from orchestrator.runtime import file_hash
from orchestrator.step_runner import execute
from orchestrator.storage import transaction
from tests import test_production_planning as fixture
from tests.test_blender_operations import operation
from tests import test_rhino_operations as host_fixture


class Tests(unittest.TestCase):
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    click=fixture.Tests.click

    def setUp(self):
        fixture.Tests.setUp(self)
        self.app=patch('host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture'))
        self.app.start()
        self.signature=patch('host_evidence.application_signature',return_value={'path':'/fixture/rhino'})
        self.signature.start()
        self.production=pc.Worker(self.state,lambda _:self.rt)

    def tearDown(self):
        self.production.close();self.signature.stop();self.app.stop();fixture.Tests.tearDown(self)

    def drain(self):
        for _ in range(30):
            self.bridge.flush(False);self.bridge.flush_media()
            if not self.state.db.execute("SELECT 1 FROM media_outbox WHERE status='pending'").fetchone():return
        self.fail('Controlled delivery did not drain')

    def start(self,row):
        self.drain();self.click(row['token'])

    def preparation(self):
        response=self.response();p,r=response['plan']['tasks']
        p['outputs']=[dict(path='delivery/'+name,purpose='Prepared '+name) for name in ('model.py','checks.json','render.json')]
        p['selection_outputs']=[o['path'] for o in p['outputs']]
        p['user_gate']='Select the exact script, checks and render manifest together'
        r['inputs']=[dict(from_task=p['id'],output=o['path'],path='candidate/'+Path(o['path']).name,
                         purpose='Review every set member',authority='Unaccepted candidate') for o in p['outputs']]
        return response

    def prepare(self,ident,response,**action):
        row=self.queue(ident,self.action(**action),text='Prepare, model and render the Rhino tower; keep Grasshopper paused.')
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row(ident);self.assertEqual(row['status'],'ready',row['error'])
        self.start(row);self.production.tick()
        return row

    def finish_preparation(self,run,blocked=False):
        aid=self.rt.task(run,'produce')['latest'];self.factory.finish(aid,decision='blocked' if blocked else 'delivered')
        ws=self.factory.sessions[aid]['workspace'];script,contract,manifest=self.prepared_files()
        (ws/'delivery/model.py').write_text(script)
        (ws/'delivery/checks.json').write_text(json.dumps({'provisional':True} if blocked else contract))
        (ws/'delivery/render.json').write_text(json.dumps(manifest))
        self.production.tick()
        if not blocked:
            review=self.rt.task(run,'review')['latest']
            self.factory.finish(review,decision='accept');self.production.tick()
        return aid

    def prepared_files(self):
        from scripts.rhino_workflow_fixture import CREATE, contract
        value=contract();value['expected_named_views']=['Overview']
        return CREATE,value,dict(version=1,engine='rhino_render',named_view='Overview',resolution=[64,64])

    def select(self,run,path=None):
        self.drain()
        cards=self.state.db.execute('SELECT * FROM production_selection_cards WHERE run=? ORDER BY rowid DESC',(run,)).fetchall()
        card=next(c for c in cards if path is None or self.rt.artifact(c['artifact'])['path']==path)
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        return card,mid

    def host_response(self,row,capability,artifacts):
        payload=json.loads(row['context']);known={s['artifact']:s for s in planning.source_catalog(payload)}
        inputs=[];parameters={}
        for aid,media,key in artifacts:
            source=known[aid];inputs.append({k:source[k] for k in ('artifact','path','purpose','authority')})
            inputs[-1]['media_type']=media
            if key:parameters[key]=source['sha256']
        if capability=='rhino.run_python':parameters.update(scene_sha256=None,permissions='unrestricted_host')
        host=operation(capability,inputs);host['execution']['parameters']=parameters
        host['limits']={'seconds':600,'tool_calls':1,'output_bytes':10000000 if capability=='rhino.render' else 100000000}
        host['user_gate']='Select the exact native model' if capability=='rhino.run_python' else 'Select the rendered image'
        review=self.response()['plan']['tasks'][1]
        review.update(review_of='app',dependencies=['app'],criteria=host['criteria'])
        review['inputs']=[dict(from_task='app',output=o['path'],path='candidate/'+Path(o['path']).name,
                              purpose='Review actual host output',authority='Unaccepted candidate',media_type=o['media_type']) for o in host['outputs']]
        return dict(decision='ready',message='Review exact host inputs before Start',input_basis={'mode':'new','artifacts':[]},
                    plan=dict(brief='Rhino host stage',tasks=[host,review]))

    def fake_host(self,*args):
        request=json.loads(Path(args[2]).read_text());out=Path(request['out'])
        if request['mode']!='render':return host_fixture.Tests.fake_run(self,*args)
        (out/'render.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'0000IHDR'+struct.pack('>II',64,64))
        sha=file_hash(out/'render.png')
        (out/'checks.json').write_text(json.dumps(dict(passed=True,engine='rhino_render',render_sha256=sha)))
        return dict(passed=True,worker=dict(details=dict(render_sha256=sha)))

    def finish_host(self,run):
        session=self.factory.sessions[self.rt.task(run,'app')['latest']]
        control=Path(session['session']['control']);control.mkdir(parents=True)
        with patch('task_relay.rhino_host.run',side_effect=self.fake_host):
            result=execute(session['frozen'],control)
            if result['outcome']!='completed':raise AssertionError('Host stage failed; inspect '+str(Path(session['frozen']['workspace'])/'delivery/execution.json'))
        session['status']={'status':'finished','exit_code':0,'reason':None,'usage':[]};self.production.tick()
        review=self.rt.task(run,'review')['latest'];frozen=self.factory.sessions[review]['frozen']
        for item in frozen['inputs']:
            if item.get('from_task')=='app':
                self.assertEqual(file_hash(Path(frozen['workspace'])/item['path']),item['sha256'])
        self.factory.finish(review,decision='accept');self.production.tick()

    def test_blocked_recovery_selection_set_model_render_review_and_delivery(self):
        self.prepare(1,self.preparation(),step_capabilities=['rhino.run_python','rhino.render'])
        blocked=self.finish_preparation('production-1',blocked=True)
        drafts=[self.rt.output('production-1','produce','delivery/'+p)['id'] for p in ('model.py','checks.json','render.json')]
        original={a:file_hash(self.rt.artifact(a)['blob']) for a in drafts}
        self.prepare(2,self.preparation(),step_capabilities=['rhino.run_python','rhino.render'],artifact_ids=drafts)
        recovery=self.factory.sessions[self.rt.task('production-2','produce')['latest']]['frozen']
        self.assertTrue(set(original.values())<={i['sha256'] for i in recovery['inputs']})
        self.finish_preparation('production-2')
        self.select('production-2')
        decisions=self.state.db.execute("SELECT artifact FROM production_decisions WHERE run='production-2'").fetchall()
        self.assertEqual(len(decisions),3)
        script=self.rt.output('production-2','produce','delivery/model.py')['id']
        contract=self.rt.output('production-2','produce','delivery/checks.json')['id']
        manifest=self.rt.output('production-2','produce','delivery/render.json')['id']
        row=self.queue(3,self.action(previous_run='production-2',step_capabilities=['rhino.run_python']))
        self.assertTrue({script,contract,manifest}<=set(json.loads(row['context'])['required_artifacts']))
        response=self.host_response(row,'rhino.run_python',[(script,'text/x-python','script_sha256'),(contract,'application/json','checks_sha256')])
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row(3)
        if row['status']!='ready':raise AssertionError(row['error'])
        self.start(row);self.production.tick()
        self.finish_host('production-3');self.select('production-3','delivery/candidate.3dm')
        native=self.rt.output('production-3','app','delivery/candidate.3dm')['id']
        row=self.queue(4,self.action(previous_run='production-3',step_capabilities=['rhino.render']))
        response=self.host_response(row,'rhino.render',[(native,'application/vnd.rhino',None),(manifest,'application/json','manifest_sha256')])
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row(4)
        if row['status']!='ready':raise AssertionError(row['error'])
        self.start(row);self.production.tick()
        self.finish_host('production-4');card,mid=self.select('production-4','delivery/render.png')
        before=len(self.factory.calls)
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        self.production.tick();self.assertEqual(len(self.factory.calls),before)
        self.assertEqual(self.rt.status('production-4')['status'],'completed')
        self.assertEqual(self.rt.task('production-1','produce')['latest'],blocked)
        self.assertEqual(self.rt.task('production-1','produce')['attempts'],1)
        self.assertEqual(original,{a:file_hash(self.rt.artifact(a)['blob']) for a in drafts})
        output=self.rt.output('production-4','app','delivery/render.png')
        deliveries=self.state.db.execute('SELECT status FROM media_outbox WHERE id=?',('production-output:'+output['id'],)).fetchall()
        self.assertEqual([d['status'] for d in deliveries],['sent'])
        self.assertEqual(self.state.db.execute('SELECT status FROM media_outbox WHERE id=?',('production-preview:'+output['id'],)).fetchone()['status'],'sent')

    def test_selection_set_waits_for_every_file_and_tamper_is_atomic(self):
        self.prepare(1,self.preparation(),step_capabilities=['rhino.run_python'])
        self.finish_preparation('production-1');self.bridge.flush(False);self.bridge.flush_media()
        card=self.state.db.execute('SELECT * FROM production_selection_cards').fetchone()
        mid=self.state.db.execute('SELECT message_id FROM production_selection_messages WHERE token=?',(card['token'],)).fetchone()[0]
        members=json.loads(card['members']);second=members[1]['artifact']
        with self.state.db:self.state.db.execute("UPDATE media_outbox SET status='queued' WHERE id=?",('production-output:'+second,))
        with self.assertRaisesRegex(ValueError,'every file'),transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        with self.state.db:self.state.db.execute("UPDATE media_outbox SET status='sent' WHERE id=?",('production-output:'+second,))
        blob=Path(self.rt.artifact(second)['blob']);blob.chmod(0o600);original=blob.read_bytes();blob.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'),transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        blob.write_bytes(original)
        from bridge import State,Bridge
        from orchestrator.runtime import Runtime
        dbpath=Path(self.state.db.execute('PRAGMA database_list').fetchone()[2])
        self.production.close();self.state.db.close()
        self.state=State(dbpath);self.bridge=Bridge(self.state,self.telegram,{})
        self.rt=Runtime(pc.root(self.state),self.factory,connection=self.state.db)
        self.production=pc.Worker(self.state,lambda _:self.rt)
        with patch.object(pc,'notice',side_effect=ValueError('Receipt failure')):
            with self.assertRaisesRegex(ValueError,'Receipt failure'),transaction(self.state.db):
                selections.apply(self.state,card['token'],7,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        with transaction(self.state.db):selections.apply(self.state,card['token'],7,mid)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],3)


    def test_incomplete_or_unreviewed_preparation_set_cannot_be_proposed(self):
        row=self.queue(1,self.action(step_capabilities=['rhino.run_python']))
        response=self.preparation();response['plan']['tasks'][0].pop('selection_outputs')
        with self.assertRaisesRegex(ValueError,'selection_outputs'):planning.validate_result(json.dumps(response),row)
        response=self.preparation();response['plan']['tasks'][1]['inputs'].pop()
        with self.assertRaisesRegex(ValueError,'independent review'):planning.validate_result(json.dumps(response),row)
        self.assertEqual(self.factory.calls,[])


if __name__=='__main__':unittest.main()
