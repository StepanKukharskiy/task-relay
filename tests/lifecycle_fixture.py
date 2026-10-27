"""Controlled transports; production owner/compiler/worker/review/export paths.

No accepted-state injection, factory.finish, live providers or native apps.
The factory models process observation only; the actual worker tool loop writes
the candidate and review receipts. Process launch is separately qualified.
"""
import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from orchestrator import contracts as c, executors, job_owner, worker_capabilities
from orchestrator.gemini_worker import execute
from orchestrator.runtime import Runtime
from orchestrator.workers import atomic
from task_relay.bridge import State
from task_relay import production_control, result_handoff
from tests.test_operation_session import Script, CONFIG
from tests.test_orchestrator import FakeFactory
from tests import test_owner_intents as owner

LIMITS = dict(seconds=1800, tool_calls=100, provider_requests=24,
              response_tokens=16384, output_bytes=100000000)
BACKEND = dict(type='gemini-agent', model='fixture')


def grant():
    return dict(delegation_version=4, coordination_version=1,
        review_inspection_version=1, execution_review_version=1,
        review_snapshot_version=1, work_diagnostics_version=1,
        owner_progress_version=1, worker_tools_version=3,
        correction_scope_version=1, graph_capacity_version=1,
        provider_cooldown=dict(version=1, max_retries=2, delays=[30,90], max_wait_seconds=180),
        workers=[worker_capabilities.entry(BACKEND)], operations=['text.bundle'],
        deliverables={'report':'text/plain'}, max_tasks=60, owner_turns=24,
        task_attempts=3, task_limits=copy.deepcopy(LIMITS))


class Lifecycle:
    source = owner.Tests.source
    invoke = owner.Tests.invoke
    session = owner.Tests.session

    def setUp(self):
        if hasattr(self,'persistent_home'):
            self.home=Path(self.persistent_home).resolve();self.home.mkdir(parents=True,exist_ok=True)
        else:
            self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
            self.home = Path(self.tmp.name).resolve()
        self.state = State(self.home/'state.sqlite')
        self.root = production_control.root(self.state)
        self.factory = FakeFactory()
        self.rt = Runtime(self.root, self.factory, connection=self.state.db)
        self.addCleanup(self.state.db.close); self.addCleanup(lambda:self.rt.close())
        self.grant = grant(); self.initial = copy.deepcopy(self.grant)
        checkpoint=self.home/'fixture-processes.json'
        if checkpoint.exists():
            saved=json.loads(checkpoint.read_text())
            self.factory.sessions=saved['sessions'];self.factory.calls=saved['calls']
            for session in self.factory.sessions.values():session['workspace']=Path(session['workspace'])
            self.evidence=saved['evidence'];self.other=saved['other']
            return
        self.evidence = self.source('Observed price: 10. Target: 3; supported: 1; gap: 2.', 'a/source.txt')
        self.other = self.source('Keep the explicit gap.', 'b/source.txt')
        job_owner.create(self.rt, 'job', 'Correct the price and disclose the gap; partial delivery authorized.',
                         BACKEND, [self.evidence,self.other], self.grant, concurrency=3)
        self.rt.tick('job')

    def tearDown(self):
        target = os.environ.get('TASK_RELAY_OFFLINE_EVIDENCE')
        if target:
            self.state.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
            shutil.copytree(self.home, Path(target)/self.id())

    def restart(self):
        self.rt.close(); self.rt = Runtime(self.root, self.factory, connection=self.state.db)

    def checkpoint_observers(self):
        # Fixture process observations only; production state and results remain
        # in the real database/worker journals, never rebuilt by the harness.
        (self.home/'fixture-processes.json').write_text(json.dumps(dict(
            sessions=self.factory.sessions,calls=self.factory.calls,evidence=self.evidence,other=self.other),default=str))

    def delegate(self, key, tasks, invalid=False):
        steps=[]
        if invalid:
            steps.append(('job_delegate',dict(request_id=key+'-bad',tasks=[dict(id='invalid',objective='Invalid shape',content={'unsupported':True})])))
        steps.append(('job_delegate',dict(request_id=key,tasks=tasks)))
        result, script=self.invoke(steps)
        self.assertEqual(result['outcome'],'yielded')
        if invalid:
            response=script.requests[-1]['contents'][-1]['parts'][0]['functionResponse']['response']
            self.assertEqual(response['validation']['effect'],'none')
            self.assertIsNone(self.rt.db.execute("SELECT 1 FROM production_tasks WHERE id='invalid'").fetchone())
        self.rt.tick('job')

    def work(self, ident, text, decision='delivered', collect=True, uncertain=False):
        self.rt.tick('job'); a=self.rt.task('job',ident)['latest']; s=self.factory.sessions[a]
        f=s['frozen']; control=Path(s['session']['control']); control.mkdir(parents=True,exist_ok=True)
        atomic(control/'launch.json',dict(credential_fingerprint=executors.fingerprint(CONFIG,f['backend'])))
        steps=[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]
        steps += [('file_write',dict(path=o['path'],text=text)) for o in f['outputs']]
        report=dict(summary=text,decision=decision,instruction='Correct the factual defect and missing gap.' if decision=='revise' else '',
            findings=[dict(category='uncertainty',code='unverified',message='Evidence remains uncertain',evidence='Missing observation')] if uncertain else [],
            checks={f'c{i}':dict(passed=decision!='revise',evidence=text) for i in range(1,len(f['criteria'])+1)})
        followup=f.get('review_followup')
        if followup:
            report['checks']['c'+str(followup['criterion'])]=dict(passed=decision!='revise',evidence={
                key:dict(verdict='unresolved' if decision=='revise' else 'resolved',reason=text,
                         inspected=[dict(path=p,location='Complete small text candidate') for p in followup['candidates']])
                for key in followup['findings']})
        script=Script(steps+[('finish',dict(report_json=c.encoded(report)))])
        with patch('orchestrator.gemini_worker.emit'):
            execute(f,control,script,lambda:(CONFIG,f['backend']))
        reads=[json.loads(p.read_text()) for p in control.glob('tool-*.json')]
        reads=[r for r in reads if r['name']=='file_read']
        self.assertEqual({r['arguments']['path'] for r in reads},{i['path'] for i in f['inputs']})
        self.assertTrue(all('error' not in r['result'] for r in reads))
        s['status']=dict(status='finished',exit_code=0,external_outcome='no_pending_response',pending_requests=[])
        if collect:self.rt.tick('job')
        return f

    def pair(self, ident, inputs):
        return [owner.worker(ident,inputs), dict(id=ident+'_review',objective='Check exact price and explicit count gap',review_of=ident)]

    def first_candidate(self):
        self.delegate('initial',self.pair('v1',[{'artifact':self.evidence['artifact']},{'artifact':self.other['artifact']}]),invalid=True)
        self.work('v1','Price: 99. No gap disclosed.',collect=False)

    def corrected(self,resume=False):
        if not resume:self.first_candidate()
        # Restart with a terminal worker receipt not yet collected.
        self.restart(); self.rt.tick('job')
        first=self.rt.output('job','v1','outputs/result.txt')
        self.work('v1_review','Price 99 contradicts observed price 10; explicit count gap missing.',decision='revise')
        self.assertNotEqual(self.rt.task('job','v1')['status'],'completed')
        old=Path(first['blob']).read_bytes()
        self.delegate('correction-1',self.pair('v2',[{'artifact':first['id']}]))
        self.work('v2','Price: 10. No gap disclosed.')
        second=self.rt.output('job','v2','outputs/result.txt')
        self.work('v2_review','Price fixed; target 3 and supported 1 still need a gap of 2.',decision='revise')
        self.delegate('correction-2',self.pair('v3',[{'artifact':second['id']}]))
        self.work('v3','Price: 10. Target: 3; supported: 1; gap: 2.')
        third=self.rt.output('job','v3','outputs/result.txt')
        self.work('v3_review','Observed price 10 and explicit gap of 2 checked against original evidence.',decision='accept')
        self.assertEqual(self.rt.task('job','v3')['status'],'completed')
        self.assertEqual(Path(first['blob']).read_bytes(),old)
        self.assertNotEqual(first['sha256'],second['sha256']);self.assertNotEqual(second['sha256'],third['sha256'])
        for ident,candidate in [('v1',first),('v2',second),('v3',third)]:
            f=self.factory.sessions[self.rt.task('job',ident+'_review')['latest']]['frozen']
            self.assertEqual(f['review_target'],candidate['attempt'])
            self.assertTrue(any(i['artifact']==candidate['id'] and i['sha256']==candidate['sha256'] for i in f['inputs']))
            self.assertEqual(len({i['path'] for i in f['inputs']}),len(f['inputs']))
            self.assertTrue(any(i['artifact']==self.evidence['artifact'] for i in f['inputs']))
        self.invariants()
        return third

    def invariants(self):
        plan=job_owner.original(self.rt,'job')
        self.assertEqual(plan['concurrency'],3)
        for key in ('task_limits','max_tasks','owner_turns','task_attempts','provider_cooldown'):
            self.assertEqual(plan['job_owner'][key],self.initial[key])
        self.assertEqual(self.grant,self.initial)
        self.assertEqual(len(self.factory.calls),len(set(self.factory.calls)))
        for s in self.factory.sessions.values():
            f=s['frozen']
            for k,v in f['limits'].items():self.assertLessEqual(v,LIMITS[k])
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)

    def export_partial(self, candidate, expected='uncertain'):
        status=self.rt.status('job');self.assertEqual(status['status'],expected)
        d=status['delivery'];self.assertFalse(d['complete']);self.assertFalse(d['user_acceptance'])
        self.assertEqual(next(a['review_status'] for a in d['candidates'] if a['artifact']==candidate['id']),'reviewed')
        calls=list(self.factory.calls)
        folder=result_handoff.sync(self.state,'job')
        marker=json.loads((folder/'.relay-workflow.json').read_text())
        self.assertEqual((folder/marker['paths'][candidate['id']]).read_bytes(),Path(candidate['blob']).read_bytes())
        self.assertIn('Partial delivery',result_handoff.saved_text(self.state,'job'))
        self.restart();self.rt.tick('job');self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['delivery'],d)
        self.assertEqual(self.factory.calls,calls)
        self.invariants()
        return d
