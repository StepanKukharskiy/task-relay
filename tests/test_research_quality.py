"""Small saved-source fixtures; no browser, provider or user decisions."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orchestrator import research_quality as q, contracts
from orchestrator.runtime import Runtime
from orchestrator.gemini_worker import save_review_report,Files
from tests.test_gemini_executor import graph,report
from tests.test_orchestrator import FakeFactory
from tests.test_computer_worker import policy
from tests.test_computer_sessions import SessionHelper
from task_relay import computer_sessions as journal
from task_relay.computer_worker_session import Session


def plan():
    p=graph();t,r=p['tasks']
    t.update(tools=['files','computer'],computer=policy(),instruction='Inspect up to five visible posts.',
        worker={'version':1,'requires':['files.text','computer.use'],'executor':'gemini-computer','backend':{'type':'gemini-computer','model':'fixture-model'}})
    t['outputs']=[{'path':'evidence.json','purpose':'Post evidence'},{'path':'summary.md','purpose':'Labeled profile claims'}]
    r['inputs']=[{'from_task':t['id'],'output':o['path'],'path':'candidate/'+o['path'],'purpose':o['purpose'],'authority':'Unaccepted research candidate'} for o in t['outputs']]
    return p


def posts(n):
    return [{'url':f'https://x.com/fixture/status/{i+1}','observation':'o1','timestamp_text':'Sep 1',
             'verbatim_text':'I work with catalog files.'} for i in range(n)]


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.plan=plan();q.bind(self.plan,'Inspect at most 5 posts.')
        self.policy=self.plan['tasks'][0]['research_delivery']
        self.files={'evidence.json':json.dumps({'posts':posts(5)}).encode(),
            'summary.md':b'# Profile summary\n[Observation] Works with catalog files.\n[Inference] Validation tools might help; actual interest is unknown.\n[Limitation] These captures are not a complete timeline.\n'}
        self.pack={'observations':[{'observation':'o1','text':'I work with catalog files. Sep 1\n'+'\n'.join(p['url'] for p in posts(7))}],
            'coverage_note':'These captures are not a complete timeline.'}

    def test_stricter_user_cap_is_frozen_and_review_has_audit(self):
        p=plan();q.bind(p,'Inspect no more than three recent posts.')
        self.assertEqual(p['tasks'][0]['research_delivery']['max_posts'],3)
        self.assertEqual(p['tasks'][0]['instruction'],'Inspect up to five visible posts.')
        contracts.plan(p)
        p['tasks'][1].pop('research_audit')
        with self.assertRaisesRegex(ValueError,'claim audit'):contracts.plan(p)

    def test_seven_posts_under_five_cap_cannot_finish(self):
        self.files['evidence.json']=json.dumps({'posts':posts(7)}).encode()
        with self.assertRaisesRegex(ValueError,'7 records, maximum 5'):
            q.check_delivery(self.plan['tasks'][0],self.files.__getitem__)

    def test_duplicate_posts_and_hidden_extra_post_are_rejected(self):
        for data in (posts(2)+posts(1),):
            self.files['evidence.json']=json.dumps({'posts':data}).encode()
            with self.assertRaisesRegex(ValueError,'Duplicate'):q.candidate(self.policy,self.files.__getitem__)
        self.files['evidence.json']=json.dumps({'posts':posts(5)}).encode()
        self.files['summary.md']+=b'[Observation] Extra https://x.com/fixture/status/6\n'
        with self.assertRaisesRegex(ValueError,'outside'):q.candidate(self.policy,self.files.__getitem__)

    def test_changed_excerpt_or_capture_id_cannot_substantiate_review(self):
        for key,value in [('verbatim_text','I use AI agents.'),('observation','invented'),('timestamp_text','Oct 1')]:
            data=posts(1);data[0][key]=value
            self.files['evidence.json']=json.dumps({'posts':data}).encode()
            with self.assertRaisesRegex(ValueError,'absent'):q.candidate(self.policy,self.files.__getitem__,self.pack)

    def test_unlabeled_or_heading_claims_cannot_bypass_audit(self):
        for text in ('Flat files prove automation interest.','# Uses AI every day','| Fact | I use AI |'):
            self.files['summary.md']=text.encode()
            with self.assertRaisesRegex(ValueError,'label'):q.candidate(self.policy,self.files.__getitem__)

    def frozen_review(self):
        research={**q.candidate(self.policy,self.files.__getitem__,self.pack),'audit_path':'delivery/research_audit.json'}
        pack={**self.pack,'research':research}
        raw=json.dumps(pack).encode();raw_hash=hashlib.sha256(raw).hexdigest()
        f=copy.deepcopy(self.plan['tasks'][1]);f.update(assignment_id='review-fixture',workspace=str(self.root))
        f['inputs']=[]
        for path,data in [('raw.json',raw),*self.files.items()]:
            (self.root/path).write_bytes(data)
            f['inputs'].append({'path':path,'sha256':hashlib.sha256(data).hexdigest(),'from_task':'produce'})
        f['computer_review']={'path':'raw.json','sha256':raw_hash,'research':research,'unexecuted_actions':[]}
        audit={k:research[k] for k in ('summary_sha256','evidence_sha256','post_count','max_posts')}
        audit.update(raw_sha256=raw_hash,claims=[{'claim':u['claim'],'verdict':'supported','reason':'Entire claim and label match the evidence; tooling need remains explicitly hypothetical.',
            'supports':[{'observation':'coverage' if u['kind']=='limitation' else 'o1','quote':self.pack['coverage_note'] if u['kind']=='limitation' else 'I work with catalog files.'}]} for u in research['units']])
        return f,audit

    def save_audit(self,f,audit):
        p=self.root/f['research_audit']['path'];p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(audit))

    def test_complete_audit_accepts_and_keeps_inference_explicit(self):
        f,a=self.frozen_review();self.save_audit(f,a)
        self.assertEqual(contracts.report(report(f),f)['decision'],'accept')
        self.assertEqual(f['computer_review']['research']['units'][1]['kind'],'inference')

    def test_blanket_pass_and_missing_claim_do_not_accept(self):
        for change in (lambda a:a.update(claims=[]),lambda a:a['claims'].pop(),lambda a:a['claims'].append(a['claims'][0])):
            f,a=self.frozen_review();change(a);self.save_audit(f,a)
            with self.assertRaisesRegex(ValueError,'every summary claim'):contracts.report(report(f),f)

    def test_invented_citation_wrong_hash_and_unsupported_inference_fail(self):
        for change in (lambda a:a['claims'][0]['supports'][0].update(quote='uses AI'),
                       lambda a:a.update(evidence_sha256='0'*64),
                       lambda a:a['claims'][1].update(verdict='unsupported'),
                       lambda a:a['claims'][0].update(supports=[])):
            f,a=self.frozen_review();change(a);self.save_audit(f,a)
            with self.assertRaises(ValueError):contracts.report(report(f),f)
            r=report(f);r.update(decision='revise',instruction='Remove the unsupported observed claim.')
            self.assertEqual(contracts.report(r,f)['decision'],'revise')

    def test_tampered_input_and_coverage_as_profile_fact_rejected(self):
        f,a=self.frozen_review();self.save_audit(f,a)
        (self.root/'summary.md').write_text('Changed')
        with self.assertRaisesRegex(ValueError,'input changed'):contracts.report(report(f),f)
        f,a=self.frozen_review();a['claims'][0]['supports']=[{'observation':'coverage','quote':self.pack['coverage_note']}];self.save_audit(f,a)
        with self.assertRaisesRegex(ValueError,'cannot substantiate'):contracts.report(report(f),f)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.factory=FakeFactory();self.rt=Runtime(Path(self.tmp.name)/'runtime',self.factory);self.addCleanup(self.rt.db.close)
        p=plan();q.bind(p,'Inspect at most five posts.');self.rt.create(p);self.rt.tick('demo')
        self.aid=self.rt.task('demo','produce')['latest'];self.frozen=self.factory.sessions[self.aid]['frozen']
        db=self.rt.db;db.execute('CREATE TABLE relay_pipelines(id TEXT PRIMARY KEY)');db.execute("INSERT INTO relay_pipelines VALUES ('job')");journal.initialize(db)
        ident=journal.approve(db,job='job',request_key='worker:'+self.aid,exact_request=self.frozen['instruction'],spec=policy()['spec'],
            helper=SessionHelper.identity,output_root=self.rt.root/'workers'/self.aid/'computer-evidence',actor='fixture')
        session=Session(db,ident,SessionHelper(db),self.rt.root/'workers'/self.aid,'fixture')
        session.call('initial','computer_observe',{'token':''});session.close(True)
        self.observation=journal.actions(db,ident)[0]['id']

    def deliver(self,n=0):
        self.factory.finish(self.aid)
        ws=Path(self.frozen['workspace']);(ws/'evidence.json').write_text(json.dumps({'posts':posts(n)}))
        (ws/'summary.md').write_text('[Observation] A supplier catalog issue was reported.\n')
        self.rt.tick('demo')

    def test_supervisor_blocks_over_cap_report_before_review_dispatch(self):
        self.deliver(7)
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertEqual(self.factory.calls,[self.aid])

    def test_runtime_binds_exact_claims_and_supervisor_rejects_blanket_accept(self):
        self.deliver();rid=self.rt.task('demo','review')['latest'];self.assertIsNotNone(rid)
        f=self.factory.sessions[rid]['frozen'];self.assertEqual(len(f['computer_review']['research']['units']),1)
        self.factory.finish(rid,decision='accept');self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','review')['status'],'blocked')
        self.assertNotEqual(self.rt.task('demo','produce')['status'],'awaiting_user')

    def test_complete_audit_reaches_user_gate_and_auto_review_markdown(self):
        self.deliver();rid=self.rt.task('demo','review')['latest'];f=self.factory.sessions[rid]['frozen']
        r=f['computer_review']['research'];files=Files(f)
        audit={k:r[k] for k in ('summary_sha256','evidence_sha256','post_count','max_posts')}
        audit.update(raw_sha256=f['computer_review']['sha256'],claims=[{'claim':1,'verdict':'supported','reason':'The whole observation matches the source.',
            'supports':[{'observation':self.observation,'quote':'Synthetic supplier catalog issue.'}]}])
        self.factory.finish(rid,decision='accept')
        files.call('file_write',{'path':r['audit_path'],'text':json.dumps(audit)})
        save_review_report(files,f,report(f))
        self.assertIn('review.md',files.written)
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')

    def test_reviewer_writes_sectioned_audit_within_original_request_budget(self):
        from unittest.mock import Mock
        from orchestrator.gemini_worker import execute
        from orchestrator import executors
        from orchestrator.workers import atomic
        from tests.test_gemini_executor import CONFIG
        from tests.test_computer_generation_recovery import response
        self.deliver();rid=self.rt.task('demo','review')['latest'];f=self.factory.sessions[rid]['frozen']
        r=f['computer_review']['research']
        audit={k:r[k] for k in ('summary_sha256','evidence_sha256','post_count','max_posts')}
        audit.update(raw_sha256=f['computer_review']['sha256'],claims=[{'claim':1,'verdict':'supported','reason':'The entire observation is directly supported.',
            'supports':[{'observation':self.observation,'quote':'Synthetic supplier catalog issue.'}]}])
        raw=json.dumps(audit);cut=len(raw)//2
        control=self.rt.root/'workers'/rid;control.mkdir(parents=True)
        atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(CONFIG,f['backend'])})
        model=Mock();model.request.side_effect=[response('file_write',{'path':r['audit_path'],'text':raw[:cut]}),
            response('file_append',{'path':r['audit_path'],'text':raw[cut:],'expected_bytes':len(raw[:cut].encode())}),
            response('finish',{'report_json':json.dumps(report(f))})]
        self.factory.finish(rid,decision='accept')
        result=execute(f,control,model,lambda:(CONFIG,f['backend']))
        self.assertEqual(result['decision'],'accept');self.assertEqual(model.request.call_count,3)
        for call in model.request.call_args_list:self.assertEqual(call.args[1]['generationConfig']['maxOutputTokens'],4096)
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','produce')['status'],'awaiting_user')


class WorkerTests(unittest.TestCase):
    from tests.test_computer_generation_recovery import Tests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    prepare=Fixture.prepare
    execute=Fixture.execute

    def test_worker_repairs_over_limit_locally_without_native_replay(self):
        from tests.test_computer_generation_recovery import response
        self.frozen['outputs']=plan()['tasks'][0]['outputs']
        self.frozen['research_delivery']={'version':1,'max_posts':5,'evidence_path':'evidence.json','summary_path':'summary.md'}
        finish=lambda:response('finish',{'report_json':json.dumps(report(self.frozen))})
        replies=[response('file_write',{'path':'evidence.json','text':json.dumps({'posts':posts(7)})}),
            response('file_write',{'path':'summary.md','text':'[Observation] A catalog issue was reported.\n'}),
            finish(),response('file_write',{'path':'evidence.json','text':json.dumps({'posts':[]})}),finish()]
        result=self.execute(replies)
        self.assertEqual(result['decision'],'delivered')
        self.assertIn('maximum 5',json.loads((self.control/'tool-03-00.json').read_text())['result']['error'])
        self.assertEqual(len(self.helper.calls),1)
        self.assertEqual(len(json.loads((self.ws/'evidence.json').read_text())['posts']),0)
        self.assertIn('hard ceiling',self.client.request.call_args_list[0].args[1]['systemInstruction']['parts'][0]['text'])
