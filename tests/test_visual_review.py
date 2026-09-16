"""Exact screenshot pixels and stopped review recovery; no providers or browsers."""
import base64,copy,hashlib,json,sqlite3
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
import unittest
from orchestrator import contracts as c,executors
from orchestrator.browser_worker import run
from orchestrator.gemini_worker import Files
from orchestrator.workers import atomic
from orchestrator.storage import transaction
from task_relay.general_browser import Session
from task_relay import production_visual_review as recovery,production_control as pc
from tests.test_browser_screenshots import capture_graph,png,CaptureDriver
from tests.test_gemini_executor import CONFIG,report
from tests import test_production_planning as fixtures,test_browser_screenshots as capture_tests


class PixelTests(unittest.TestCase):
    setUp=capture_tests.Tests.setUp;tearDown=capture_tests.Tests.tearDown
    def test_exact_granted_pixels_reach_each_provider_without_live_page_review(self):
        for provider in ('gemini','openai','qwen'):
            ws=self.root/provider;ws.mkdir();(ws/'.relay').mkdir();control=ws/'control';control.mkdir()
            f=c.assignment(capture_graph()['tasks'][1]);f.update(workspace=str(ws),assignment_id='review-pixels',backend={'type':provider+'-browser','model':'fixture-model'})
            raw=png();(ws/'selected.png').write_bytes(raw)
            f['inputs']=[dict(path='selected.png',media_type='image/png',sha256=hashlib.sha256(raw).hexdigest())]
            f['browser']['visual_inputs']=['selected.png']
            config=CONFIG if provider=='gemini' else {'api_key':'fixture-only','model':'fixture-model'}
            atomic(control/'launch.json',{'credential_fingerprint':executors.fingerprint(config,f['backend'])})
            seen=[]
            class Client:
                def request(self,endpoint,payload,**kwargs):
                    seen.append(copy.deepcopy(payload));args=report(f)
                    if provider=='gemini':return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'finish','args':args}}]}}]}
                    call={'name':'finish','arguments':json.dumps(args)}
                    if provider=='openai':return {'id':'fixture','status':'completed','output':[{'type':'function_call','call_id':'1',**call}]}
                    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'1','type':'function','function':call}]}}]}
            driver=CaptureDriver()
            with sqlite3.connect(':memory:') as db:
                result=run(f,control,db,self.root,client=Client(),config_reader=lambda:(config,f['backend']),driver_context=nullcontext(driver))
            self.assertEqual(result['decision'],'accept');self.assertEqual(driver.pages,{})
            self.assertIn(base64.b64encode(raw).decode(),json.dumps(seen))
            self.assertEqual(len(seen),1)
            self.assertTrue((ws/'review.md').is_file())

    def test_visual_permission_cannot_reference_undeclared_file(self):
        f=copy.deepcopy(self.frozen);f['browser']['visual_inputs']=['private.png']
        with self.assertRaisesRegex(ValueError,'exact declared PNG'):Files(f)


class RecoveryTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    def stopped(self):
        p=capture_graph();p['tasks'][0].pop('user_gate',None)
        self.rt.create(p);self.rt.tick('demo')
        task=self.rt.task('demo','produce');record=self.factory.sessions[task['latest']];f=record['frozen']
        with sqlite3.connect(':memory:') as db:
            session=Session(db,f['assignment_id'],f['browser'],CaptureDriver(),Files(f))
            page=session.call('open','browser_open',{'url':'https://example.test/map'})
            session.call('capture','browser_screenshot',dict(tab=page['tab'],observation=page['observation'],path='map.png',purpose='Fixture capture'))
        atomic(Path(f['workspace'])/'.relay/result.json',report(f));record['status']={'status':'finished','exit_code':0}
        self.rt.tick('demo');review=self.rt.task('demo','review')['latest']
        self.factory.sessions[review]['status']={'status':'finished','exit_code':1,'external_outcome':'no_pending_response','pending_requests':[],'browser':{'actions':[],'uncertain_actions':[]}}
        self.rt.tick('demo')
        return task['latest'],review

    def propose(self):
        with self.state.db:
            self.state.db.execute('BEGIN IMMEDIATE')
            recovery.propose(self.state,{'id':99,'prompt':'Continue the same workflow.'},'demo')
        row=self.state.db.execute('SELECT * FROM production_visual_review_cards').fetchone()
        return row

    def deliver(self,row):
        with self.state.db:
            self.state.db.execute('INSERT INTO outbox(id,text,sent) VALUES (?,?,1)',(row['event_id'],'Fixture delivered card'))
            recovery.remember(self.state,row['event_id'],7,9)

    def test_start_keeps_candidate_old_attempt_and_resumes_only_review(self):
        producer,old=self.stopped();row=self.propose()
        before=dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone())
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'delivered'):recovery.apply(self.state,row['token'],7,9)
        self.deliver(row)
        with transaction(self.state.db):
            recovery.apply(self.state,row['token'],7,9)
            recovery.apply(self.state,row['token'],7,9)
        self.assertEqual(dict(self.state.db.execute('SELECT * FROM production_attempts WHERE id=?',(old,)).fetchone()),before)
        self.assertEqual(self.rt.task('demo','produce')['latest'],producer)
        self.rt.tick('demo');latest=self.rt.task('demo','review')['latest']
        self.assertNotEqual(old,latest)
        frozen=self.factory.sessions[latest]['frozen']
        self.assertEqual(frozen['review_target'],producer)
        self.assertEqual(frozen['browser']['visual_inputs'],['candidate/map.png'])
        self.assertEqual(self.rt.task('demo','review')['attempts'],2)
        self.factory.finish(latest,decision='accept');self.factory.sessions[latest]['status']['browser']={'actions':[]}
        self.rt.tick('demo');self.assertEqual(self.rt.task('demo','produce')['status'],'completed')
        self.assertEqual(len(self.factory.calls),3)

    def test_changed_receipt_invalidates_card(self):
        producer,old=self.stopped();row=self.propose();self.deliver(row)
        with self.state.db:
            self.state.db.execute("UPDATE production_attempts SET state='uncertain' WHERE id=?",(old,))
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'uncertain'):recovery.apply(self.state,row['token'],7,9)
        self.assertEqual(self.rt.task('demo','produce')['latest'],producer)
