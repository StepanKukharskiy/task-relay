"""Actual scheduler/owner admission with small text fixtures, no live providers."""
import json,unittest
from pathlib import Path
from orchestrator.runtime import Runtime
from tests import test_owner_intents as fixture


class Tests(unittest.TestCase):
    from tests.test_browser_fallback_lifecycle import retain_evidence as tearDown
    create=fixture.Tests.create
    invoke=fixture.Tests.invoke
    session=fixture.Tests.session
    run_worker=fixture.Tests.run_worker
    def setUp(self):
        fixture.Tests.setUp(self)
        self.grant['delegation_version']=4

    def start(self,decision='accept'):
        self.create();self.rt.tick('job')
        self.invoke([('job_delegate',dict(request_id='first',tasks=[fixture.worker('write'),dict(id='review',objective='Review exact text',review_of='write')]))])
        self.run_worker('write',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Useful exact retained text.'))])
        if decision in ('revise','uncertain'):
            self.rt.tick('job');aid=self.rt.task('job','review')['latest']
            self.factory.finish(aid,decision='revise' if decision=='revise' else 'accept')
            if decision=='uncertain':
                path=Path(self.factory.sessions[aid]['frozen']['workspace'])/'.relay/result.json'
                report=json.loads(path.read_text());report['findings']=[dict(category='uncertainty',code='saved_source',
                    message='Saved source claim remains unverified',evidence='Missing correlated observation')]
                path.write_text(json.dumps(report))
            self.rt.tick('job')
        else:self.run_worker('review',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Independent exact candidate review.'))],decision=decision)
        return self.rt.output('job','write','outputs/result.txt')

    def stop(self):
        session=self.session()
        for n in range(3):
            result=session.call('job_delegate',dict(request_id='bad-'+str(n),tasks=[dict(id='bad',objective='Invalid contract',content=dict(unsupported=True))]))
            self.assertEqual(result['validation']['effect'],'none')
        with self.assertRaisesRegex(ValueError,'no automatic wake') as error:session.check_progress(3,3)
        aid=self.rt.task('job','owner')['latest']
        self.factory.sessions[aid]['status']=dict(status='finished',exit_code=1,reason=str(error.exception),external_outcome='no_pending_response',pending_requests=[])
        self.rt.tick('job');return self.rt.status('job')

    def test_rejected_proposals_return_exact_reviewed_work_and_attention_after_restart(self):
        a=self.start();s=self.stop();self.assertEqual(s['status'],'blocked')
        delivery=s['delivery'];self.assertEqual(delivery['status'],'partial');self.assertFalse(delivery['complete']);self.assertFalse(delivery['user_acceptance'])
        self.assertEqual([(x['artifact'],x['review_status']) for x in delivery['candidates']],[(a['id'],'reviewed')])
        self.assertIn('proposal correction allowance',delivery['attention'][0]['reason'].lower())
        calls=list(self.factory.calls);count=self.rt.db.total_changes
        self.rt.db.execute('PRAGMA query_only=ON')
        self.assertEqual(self.rt.status('job')['delivery'],delivery);self.assertEqual(self.rt.db.total_changes,count)
        self.rt.db.execute('PRAGMA query_only=OFF');self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.assertEqual(self.rt.status('job')['delivery'],delivery);self.rt.tick('job');self.assertEqual(self.factory.calls,calls)
        self.assertEqual(self.rt.db.execute("SELECT count(*) FROM production_events WHERE kind='owner_delivery_verified'").fetchone()[0],0)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def test_rejected_review_is_a_labeled_candidate_not_success(self):
        a=self.start('revise');s=self.stop();c=s['delivery']['candidates'][0]
        self.assertEqual(c['artifact'],a['id']);self.assertEqual(c['review_status'],'requires_attention')
        self.assertEqual(c['reviews'][0]['decision'],'revise')
        self.assertTrue(s['delivery']['attention'])

    def test_unrelated_or_stale_review_does_not_approve_candidate(self):
        self.start();s=self.stop();aid=self.rt.task('job','review')['latest']
        row=self.rt.db.execute('SELECT frozen FROM production_attempts WHERE id=?',(aid,)).fetchone();f=json.loads(row[0]);f['review_target']='different'
        self.rt.db.execute('UPDATE production_attempts SET frozen=? WHERE id=?',(json.dumps(f),aid))
        self.assertEqual(self.rt.status('job')['delivery']['candidates'][0]['review_status'],'unreviewed')

    def test_missing_and_tampered_files_are_not_advertised(self):
        a=self.start();self.stop();blob=Path(a['blob']);raw=blob.read_bytes();blob.chmod(0o600);blob.write_bytes(b'tampered')
        self.assertNotIn('delivery',self.rt.status('job'))
        blob.write_bytes(raw);self.assertIn('delivery',self.rt.status('job'));blob.unlink()
        self.assertNotIn('delivery',self.rt.status('job'))

    def test_settlement_waits_but_finished_uncertain_review_does_not_withhold_candidate(self):
        self.start();self.stop();aid=self.rt.task('job','review')['latest']
        self.rt.db.execute("UPDATE production_tasks SET status='running' WHERE run='job' AND id='review'")
        self.rt.db.execute("UPDATE production_attempts SET state='running' WHERE id=?",(aid,))
        s=self.rt.status('job');self.assertEqual(s['status'],'active');self.assertIn('settlement',s);self.assertNotIn('delivery',s)
        self.rt.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run='job' AND id='review'")
        self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(aid,))
        s=self.rt.status('job');self.assertEqual(s['status'],'uncertain')
        self.assertEqual(s['delivery']['candidates'][0]['review_status'],'requires_attention')

    def uncertain_peer(self,drain=False):
        tasks=[fixture.worker('unknown')]+([fixture.worker('slow')] if drain else [])
        self.invoke([('job_delegate',dict(request_id='peer',tasks=tasks))]);self.rt.tick('job')
        aid=self.rt.task('job','unknown')['latest']
        self.factory.sessions[aid]['status']=dict(status='uncertain',reason='External effect has no correlated receipt')
        self.rt.tick('job');return aid

    def test_uncertain_peer_exports_reviewed_file_without_replay_or_resolution_after_restart(self):
        a=self.start();aid=self.uncertain_peer();s=self.rt.status('job');calls=list(self.factory.calls)
        self.assertEqual(s['status'],'uncertain');d=s['delivery']
        self.assertEqual([(v['artifact'],v['review_status']) for v in d['candidates']],[(a['id'],'reviewed')])
        self.assertFalse(d['complete']);self.assertFalse(d['user_acceptance'])
        self.assertEqual(d['attention'][0]['attempt'],aid);self.assertEqual(d['attention'][0]['state'],'uncertain')
        count=self.rt.db.total_changes;self.rt.db.execute('PRAGMA query_only=ON')
        self.assertEqual(self.rt.status('job')['delivery'],d);self.assertEqual(self.rt.db.total_changes,count)
        self.rt.db.execute('PRAGMA query_only=OFF');self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.rt.tick('job');self.rt.tick('job');self.assertEqual(self.rt.status('job')['delivery'],d)
        self.assertEqual(self.factory.calls,calls);self.assertEqual(self.rt.task('job','unknown')['latest'],aid)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        # A changed or missing completed candidate is still unavailable.
        blob=Path(a['blob']);blob.chmod(0o600);blob.write_text('tampered')
        self.assertNotIn('delivery',self.rt.status('job'))

    def test_uncertain_semantic_review_remains_attention_not_acceptance(self):
        a=self.start('uncertain');s=self.rt.status('job');c=s['delivery']['candidates'][0]
        self.assertEqual(s['status'],'uncertain');self.assertEqual(c['artifact'],a['id'])
        self.assertEqual(c['review_status'],'requires_attention')
        self.assertEqual(c['reviews'][0]['findings'][0]['category'],'uncertainty')
        self.assertEqual(c['reviews'][0]['state'],'uncertain')
        # An earlier acceptance cannot erase an exact unresolved review judgment.
        self.assertEqual(c['reviews'][0]['decision'],'accept')

    def test_uncertain_producer_never_publishes_its_collected_file(self):
        self.start();self.stop();aid=self.rt.task('job','write')['latest']
        self.rt.db.execute("UPDATE production_tasks SET status='uncertain' WHERE run='job' AND id='write'")
        self.rt.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(aid,))
        self.assertNotIn('delivery',self.rt.status('job'))

    def test_uncertain_run_waits_for_dispatched_independent_worker_to_drain(self):
        self.start();self.uncertain_peer(drain=True);s=self.rt.status('job');calls=list(self.factory.calls)
        self.assertIn('settlement',s);self.assertNotIn('delivery',s)
        aid=self.rt.task('job','slow')['latest'];self.factory.finish(aid);self.rt.tick('job')
        s=self.rt.status('job');self.assertEqual(s['status'],'uncertain');self.assertIn('delivery',s)
        self.assertEqual({c['task'] for c in s['delivery']['candidates']},{'write','slow'})
        self.assertEqual(self.factory.calls,calls)

    def test_no_candidate_does_not_claim_delivery_and_missing_roles_stay_visible(self):
        self.grant['deliverables']['extra']='application/json';self.create();self.rt.tick('job');self.assertNotIn('delivery',self.stop())

    def test_partial_format_does_not_fill_missing_requested_deliverable(self):
        self.grant['deliverables']['extra']='application/json';self.start();s=self.stop()
        self.assertEqual(s['delivery']['missing_formats'],{'extra':'application/json'})


class ExportTests(unittest.TestCase):
    from tests import test_production_control as app
    from tests import test_job_owner_loop as owner_fixture
    create=Tests.create
    invoke=Tests.invoke
    session=Tests.session
    run_worker=Tests.run_worker
    start=Tests.start
    stop=Tests.stop
    uncertain_peer=Tests.uncertain_peer
    tearDown=app.Tests.tearDown
    def setUp(self):
        self.app.Tests.setUp(self);self.state.media_dir=self.state.media_dir.resolve();self.root=self.rt.root
        from orchestrator import worker_capabilities
        self.grant=dict(delegation_version=4,workers=[worker_capabilities.entry(self.owner_fixture.BACKEND)],operations=[],deliverables={'report':'text/plain'},max_tasks=10,
            task_limits=dict(seconds=300,tool_calls=12,provider_requests=12,response_tokens=4096,output_bytes=200000),task_attempts=2,owner_turns=6)

    def test_partial_status_export_and_terminal_handoff_keep_review_labels(self):
        from task_relay import result_handoff,production_status,production_control as pc
        a=self.start('revise');self.stop();calls=list(self.factory.calls)
        root=result_handoff.sync(self.state,'job')
        report=json.loads((root/'manifest.json').read_text());self.assertEqual(report['status'],'partial');self.assertEqual(report['execution_status'],'blocked')
        self.assertIn('candidate requires corrections',(root/'README.md').read_text())
        text=result_handoff.saved_text(self.state,'job');self.assertIn('Partial delivery',text);self.assertIn('requires_attention',text)
        _,card=production_status.current(self.state,'job');self.assertIn('Partial delivery',card)
        with self.state.db:self.state.put('production-enabled:job',pc.runtime_digest(self.rt,'job'))
        worker=pc.Worker(self.state,lambda _:self.rt);worker.tick();worker.tick()
        rows=self.state.db.execute("SELECT id,text FROM outbox WHERE id LIKE 'production:job:result:%'").fetchall();self.assertEqual(len(rows),1)
        self.assertIn('Partial delivery',rows[0]['text'])
        media=self.state.db.execute('SELECT caption FROM media_outbox WHERE event_id=?',(rows[0]['id'],)).fetchall()
        self.assertTrue(media);self.assertTrue(all('requires_attention' in m[0] for m in media))
        self.assertEqual(calls,self.factory.calls)
        marker=json.loads((root/'.relay-workflow.json').read_text());copy=root/marker['paths'][a['id']];copy.write_text('User edits')
        self.assertNotIn(str(copy),result_handoff.saved_text(self.state,'job'))

    def test_uncertain_partial_export_and_handoff_are_exact_and_deduplicated(self):
        from task_relay import result_handoff,production_status,production_control as pc
        a=self.start();unknown=self.uncertain_peer();calls=list(self.factory.calls)
        root=result_handoff.sync(self.state,'job');report=json.loads((root/'manifest.json').read_text())
        self.assertEqual(report['status'],'partial');self.assertEqual(report['execution_status'],'uncertain')
        self.assertIn('External effect has no correlated receipt',(root/'README.md').read_text())
        marker=json.loads((root/'.relay-workflow.json').read_text())
        self.assertEqual((root/marker['paths'][a['id']]).read_bytes(),Path(a['blob']).read_bytes())
        self.assertIn('reviewed',result_handoff.saved_text(self.state,'job'))
        self.assertIn('Partial delivery',production_status.current(self.state,'job')[1])
        with self.state.db:self.state.put('production-enabled:job',pc.runtime_digest(self.rt,'job'))
        w=pc.Worker(self.state,lambda _:self.rt);w.tick();w.tick()
        rows=self.state.db.execute("SELECT id,text FROM outbox WHERE id LIKE 'production:job:result:%'").fetchall()
        self.assertEqual(len(rows),1);self.assertIn('Partial delivery',rows[0]['text'])
        self.assertIn('no correlated receipt',rows[0]['text'])
        media=self.state.db.execute('SELECT caption FROM media_outbox WHERE event_id=?',(rows[0]['id'],)).fetchall()
        self.assertTrue(media);self.assertTrue(all('reviewed' in x[0] for x in media))
        self.assertEqual(self.factory.calls,calls);self.assertEqual(self.rt.task('job','unknown')['latest'],unknown)
        self.assertEqual(self.rt.task('job','unknown')['status'],'uncertain')
