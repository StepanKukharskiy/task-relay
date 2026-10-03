"""Exact-whitespace correction before finish, without another native action."""
import json
import unittest
from pathlib import Path
from orchestrator import research_quality as q
from orchestrator.computer_review_inputs import capture_pack
from tests import test_computer_generation_recovery as fixture
from tests.test_gemini_executor import report
from tests import test_research_quality as quality

RAW='@Support\n My catalog needs help.\nSep 1\nhttps://x.com/fixture/status/1'
EXACT='@Support\n My catalog needs help.'
FLATTENED='@Support My catalog needs help.'

class Helper(fixture.Helper):
    def call(self,request):
        result=super().call(request);result['observation']['text']=RAW;return result


class Tests(unittest.TestCase):
    def test_whitespace_difference_is_rejected_with_exact_slice_not_normalized_acceptance(self):
        p={'evidence_path':'e.json','summary_path':'s.md','max_posts':5}
        post={'url':'https://x.com/fixture/status/1','observation':'o1','timestamp_text':'Sep 1','verbatim_text':FLATTENED}
        files={'e.json':json.dumps({'posts':[post]}).encode(),'s.md':b'[Observation] A catalog issue was reported.'}
        pack={'observations':[{'observation':'o1','text':RAW}]}
        with self.assertRaises(ValueError) as error:q.candidate(p,files.__getitem__,pack)
        self.assertIn('Post 1',str(error.exception));self.assertIn('verbatim_text differs in whitespace',str(error.exception))
        self.assertIn(json.dumps(EXACT),str(error.exception))
        post['verbatim_text']=EXACT;files['e.json']=json.dumps({'posts':[post]}).encode()
        self.assertEqual(q.candidate(p,files.__getitem__,pack)['post_count'],1)

    def test_word_or_punctuation_changes_do_not_receive_a_repair_suggestion(self):
        for quote in ('@Support My catalog is resolved.','@Support My catalog needs help!'):
            self.assertNotIn('Copy this exact',q.citation_problem('Quote',quote,RAW))

    def test_ambiguous_whitespace_variants_are_not_chosen_silently(self):
        raw='@Support\nMy catalog\n@Support\tMy catalog'
        self.assertNotIn('Copy this exact',q.citation_problem('Quote','@Support My catalog',raw))

    def test_reviewer_gets_exact_quote_correction_before_acceptance(self):
        f=quality.Tests();f.setUp();self.addCleanup(f.doCleanups)
        f.pack['observations'][0]['text']=f.pack['observations'][0]['text'].replace('I work with catalog files.','I work\nwith catalog files.')
        f.files['evidence.json']=json.dumps({'posts':[]}).encode()
        frozen,audit=f.frozen_review();f.save_audit(frozen,audit)
        with self.assertRaisesRegex(ValueError,'differs in whitespace'):q.validate_accept(report(frozen),frozen)
        for claim in audit['claims']:
            if claim['supports'][0]['observation']=='o1':claim['supports'][0]['quote']='I work\nwith catalog files.'
        f.save_audit(frozen,audit);q.validate_accept(report(frozen),frozen)


class WorkerTests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    prepare=fixture.Tests.prepare
    execute=fixture.Tests.execute

    def configure(self):
        self.frozen['outputs']=[{'path':'evidence.json','purpose':'Exact posts'},{'path':'summary.md','purpose':'Summary'}]
        self.frozen['research_delivery']={'version':1,'max_posts':5,'evidence_path':'evidence.json','summary_path':'summary.md'}

    def replies(self,*,tamper=False):
        from task_relay import computer_sessions as journal
        def generate(*args,**kwargs):
            n=self.client.request.call_count
            ident=self.helper.db.execute('SELECT id FROM relay_computer_assignments').fetchone()[0]
            a=journal.actions(self.helper.db,ident)[0]
            post={'url':'https://x.com/fixture/status/1','observation':a['id'],'timestamp_text':'Sep 1','verbatim_text':EXACT if n==4 else FLATTENED}
            if n in (1,4):return fixture.response('file_write',{'path':'evidence.json','text':json.dumps({'posts':[post]})})
            if n==2:return fixture.response('file_write',{'path':'summary.md','text':'[Observation] A catalog issue was reported.'})
            if tamper:
                if n==3:
                    path=Path(json.loads(a['receipt'])['folder'])/'page.txt';path.chmod(0o600);path.write_text('Changed source')
                r=report(self.frozen)
                if n>3:r.update(decision='blocked',summary='The capture changed; cannot validate.',checks=[])
                return fixture.response('finish',{'report_json':json.dumps(r)})
            return fixture.response('finish',{'report_json':json.dumps(report(self.frozen))})
        return generate

    def test_producer_repairs_line_breaks_in_same_attempt_without_native_replay(self):
        self.configure();result=self.execute(self.replies(),Helper)
        self.assertEqual(result['decision'],'delivered');self.assertEqual(len(self.helper.calls),1)
        self.assertEqual(self.client.request.call_count,5)
        error=json.loads((self.control/'tool-03-00.json').read_text())['result']['error']
        self.assertIn(json.dumps(EXACT),error)
        self.assertEqual(json.loads((self.ws/'evidence.json').read_text())['posts'][0]['verbatim_text'],EXACT)
        pack=capture_pack(self.helper.db,self.frozen,self.control/'computer-evidence')
        self.assertEqual(pack['observations'][0]['text'],RAW)

    def test_tampered_native_capture_never_becomes_success(self):
        self.configure();result=self.execute(self.replies(tamper=True),Helper)
        self.assertEqual(result['decision'],'blocked');self.assertEqual(len(self.helper.calls),1)
        self.assertIn('error',json.loads((self.control/'tool-03-00.json').read_text())['result'])

    def test_no_budget_extension_for_citation_repair(self):
        self.configure();self.frozen['limits']['provider_requests']=3
        with self.assertRaisesRegex(ValueError,'budget exhausted'):self.execute(self.replies(),Helper)
        self.assertEqual(self.client.request.call_count,3);self.assertEqual(len(self.helper.calls),1)
        self.assertFalse((self.ws/'.relay/result.json').exists())

class SupervisorTests(unittest.TestCase):
    setUp=quality.IntegrationTests.setUp

    def test_unobserved_post_is_rejected_before_reviewer_dispatch(self):
        self.factory.finish(self.aid)
        ws=Path(self.frozen['workspace'])
        post={'url':'https://x.com/fixture/status/1','observation':self.observation,
              'timestamp_text':'Sep 1','verbatim_text':'An invented catalog claim.'}
        (ws/'evidence.json').write_text(json.dumps({'posts':[post]}))
        (ws/'summary.md').write_text('[Observation] A catalog issue was reported.')
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','produce')['status'],'blocked')
        self.assertIsNone(self.rt.task('demo','review')['latest'])
        error=self.rt.db.execute('SELECT error FROM production_attempts WHERE id=?',(self.aid,)).fetchone()[0]
        self.assertIn('Post 1',error);self.assertIn('URL is absent',error);self.assertIn('verbatim_text',error)
