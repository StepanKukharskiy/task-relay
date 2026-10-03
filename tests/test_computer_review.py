"""Fresh scripted reviewer calls exercise version binding and no-replay recovery."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from task_relay import computer_review as review, computer_evidence as packs, job_delete, workflow_files


class Reviewer:
    execution_mode='scripted_fixture'
    def __init__(self, case, hook=None):
        self.case=case;self.hook=hook;self.calls=0
        self.identity={'provider':'gemini','model':'gemini-fixture-review','max_output_tokens':2048}
    def call(self, payload):
        self.calls+=1
        with closing(sqlite3.connect(self.case.evidence.fixture.paths.state)) as db:
            assert db.execute("SELECT count(*) FROM relay_computer_reviews WHERE state='submitted' AND resolved=0").fetchone()[0]==1
        source=payload['observations'][0]
        output={'findings':[{'claim_id':'visible','verdict':'supported','reason':'Supported only within this visible text.',
                  'citations':[{'file':source['file'],'quote':source['text']}]},
                 {'claim_id':'complete','verdict':'insufficient','reason':'Unseen replies are outside this pack.','citations':[]}],
                'limitations':['Visible text only; screenshots and external truth were not reviewed.']}
        if self.hook:self.hook(payload,output)
        return {'text':json.dumps(output),'complete':True,'usage':{'totalTokenCount':100}}


class ReviewTests(unittest.TestCase):
    def test_cli_requires_explicit_provider_execution(self):
        import io
        from contextlib import redirect_stdout
        from task_relay.computer_use import main
        ident=self.prepare()
        with patch.object(review,'GeminiReviewer') as adapter,redirect_stdout(io.StringIO()) as output:
            code=main(['review-run','--database',str(self.evidence.fixture.paths.state.resolve()),'--id',ident])
        self.assertEqual(code,1);self.assertIn('--allow-provider-call',output.getvalue())
        adapter.assert_not_called();self.assertEqual(review._get(self.db,ident)['state'],'prepared')

    def setUp(self):
        from tests.test_computer_evidence import EvidenceTests
        self.evidence=EvidenceTests();self.evidence.setUp();self.addCleanup(self.evidence.doCleanups)
        self.evidence.complete();self.pack=self.evidence.export();self.rt=self.evidence.rt;self.db=self.rt.db
        self.claims=[{'id':'visible','text':'The saved page contains synthetic catalog text.','scope':'visible_text'},
                     {'id':'complete','text':'Every reply was captured.','scope':'beyond_pack'}]
    def prepare(self, key='review'):
        return review.prepare(self.rt,pack_id=self.pack['id'],request_key=key,exact_request='Check both claims using only saved text.',
                              actor='fixture user',model='gemini-fixture-review',max_tokens=2048,claims=self.claims)

    def test_fresh_context_exact_citations_and_completed_duplicate(self):
        ident=self.prepare();worker=Reviewer(self);result=review.run(self.rt,ident,worker)
        self.assertEqual(result['state'],'completed');self.assertFalse(result['report']['images_reviewed'])
        self.assertEqual(result['report']['findings'][1]['verdict'],'insufficient')
        self.assertEqual(result['report']['acceptance'],'not_requested')
        self.assertEqual(result['inputs'][0]['artifact'],self.pack['artifact'])
        before=list(self.db.iterdump());review.run(self.rt,ident,None)
        self.assertEqual(before,list(self.db.iterdump()));self.assertEqual(worker.calls,1)
        self.assertEqual(self.prepare(),ident)
        self.claims[0]['text']='Different claim'
        with self.assertRaises(ValueError):self.prepare()

    def test_lost_reply_never_replays_and_prepared_alternate_cannot_bypass(self):
        ident=self.prepare();alternate=self.prepare('alternate')
        def fail(p,r):raise TimeoutError('lost reviewer reply')
        worker=Reviewer(self,fail)
        with self.assertRaises(TimeoutError):review.run(self.rt,ident,worker)
        self.assertEqual(review._get(self.db,ident)['state'],'uncertain')
        with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
        with self.assertRaises(ValueError):review.run(self.rt,alternate,worker)
        with self.assertRaises(ValueError):self.prepare('bypass')
        review.resolve(self.rt,ident,actor='user',note='Keep earlier outcome unknown; do not replay.')
        self.assertEqual(review._get(self.db,ident)['state'],'uncertain')
        self.assertTrue(review._get(self.db,ident)['resolved'])
        with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
        self.assertEqual(worker.calls,1)
        self.assertEqual(review.run(self.rt,alternate,Reviewer(self))['state'],'completed')

    def test_fabricated_citations_and_scope_overreach_preserve_invalid_reply(self):
        for mode in ('quote','scope'):
            ident=self.prepare(mode)
            def invalid(p,r):
                if mode=='quote':r['findings'][0]['citations'][0]['quote']='fabricated source passage'
                else:r['findings'][1]['verdict']='supported'
            worker=Reviewer(self,invalid)
            with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
            row=review._get(self.db,ident);self.assertEqual(row['state'],'invalid');self.assertIsNotNone(row['response'])
            with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
            self.assertEqual(worker.calls,1)

    def test_pack_corruption_blocks_dispatch_and_provider_identity_is_frozen(self):
        ident=self.prepare();worker=Reviewer(self);worker.identity['model']='changed-model'
        with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
        self.assertEqual(worker.calls,0)
        path=Path(self.rt.artifact(self.pack['artifact'])['blob']);path.chmod(0o600);path.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):review.run(self.rt,ident,Reviewer(self))
        self.assertEqual(review._get(self.db,ident)['state'],'prepared')

    def test_string_limitations_preserve_invalid_response_without_replay(self):
        ident=self.prepare()
        def invalid(p,r):r['limitations']='Only frozen visible text was reviewed.'
        worker=Reviewer(self,invalid)
        with self.assertRaisesRegex(ValueError,'bounded review limitations'):
            review.run(self.rt,ident,worker)
        saved=review._get(self.db,ident)
        self.assertEqual(saved['state'],'invalid');self.assertIsNone(saved['artifact'])
        self.assertIsInstance(json.loads(json.loads(saved['response'])['text'])['limitations'],str)
        with self.assertRaisesRegex(ValueError,'bounded review limitations'):
            review.run(self.rt,ident,worker)
        self.assertEqual(review._get(self.db,ident)['response'],saved['response'])
        self.assertEqual(worker.calls,1)

    def test_provider_rejection_retains_diagnostics_without_replay(self):
        from task_relay.gemini import ProviderError
        ident=self.prepare()
        detail={'message':'Invalid argument','status':'INVALID_ARGUMENT','field_violations':[
            {'field':'generation_config.response_json_schema','description':'Unsupported constraint'}]}
        def reject(p,r):raise ProviderError(400,detail=detail)
        worker=Reviewer(self,reject)
        with self.assertRaises(ProviderError):review.run(self.rt,ident,worker)
        row=review.inspect(self.rt,ident)
        diagnostic=json.loads(row['error'])
        self.assertEqual(diagnostic['detail'],detail)
        self.assertEqual(diagnostic['provider_status'],400)
        self.assertFalse(diagnostic['provider_uncertain'])
        self.assertEqual(row['state'],'uncertain');self.assertIsNone(row['response'])
        with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
        self.assertEqual(worker.calls,1)

    def test_registration_recovery_uses_saved_response_without_provider(self):
        ident=self.prepare();worker=Reviewer(self);register=self.rt.register
        def fail(*args,**kwargs):register(*args,**kwargs);raise OSError('crash after insertion')
        with patch.object(self.rt,'register',side_effect=fail):
            with self.assertRaises(OSError):review.run(self.rt,ident,worker)
        self.assertEqual(review._get(self.db,ident)['state'],'responded')
        self.assertEqual(self.db.execute("SELECT count(*) FROM production_artifacts WHERE task='computer_review'").fetchone()[0],0)
        result=review.run(self.rt,ident,None)
        self.assertEqual(result['state'],'completed');self.assertEqual(worker.calls,1)
        path=Path(self.rt.artifact(result['artifact'])['blob']);path.chmod(0o600);path.write_bytes(b'changed')
        with self.assertRaises(ValueError):review.inspect(self.rt,ident)

    def test_cancel_prepared_review_does_not_call_provider(self):
        ident=self.prepare();worker=Reviewer(self)
        self.assertEqual(review.resolve(self.rt,ident,actor='user',note='Cancel before dispatch.')['state'],'cancelled')
        with self.assertRaises(ValueError):review.run(self.rt,ident,worker)
        self.assertEqual(worker.calls,0)

    def test_gemini_adapter_has_no_tools_or_history_and_records_truncation(self):
        ident=self.prepare();payload=review.inspect(self.rt,ident)['payload']
        with patch('task_relay.gemini.read_config',return_value={'api_key':'fixture-key'}),patch('task_relay.gemini.Client') as client:
            client.return_value.request.return_value={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}],'usageMetadata':{'totalTokenCount':2}}
            worker=review.GeminiReviewer('gemini-fixture-review',2048);result=worker.call(payload)
            self.assertFalse(result['complete'])
            args,kwargs=client.return_value.request.call_args
            self.assertNotIn('tools',args[1]);self.assertEqual(len(args[1]['contents']),1)
            self.assertEqual(args[1]['generationConfig']['maxOutputTokens'],2048)
            self.assertEqual(kwargs['timeout'],120);self.assertEqual(kwargs['max_response_bytes'],200000)
            self.assertNotIn('snapshot',payload);self.assertFalse(payload['images_reviewed'])

    def test_provider_schema_uses_frozen_contract_and_preserves_legacy_requests(self):
        ident=self.prepare();payload=review.inspect(self.rt,ident)['payload']
        schema=copy.deepcopy(payload['response_json_schema'])
        with patch('task_relay.gemini.read_config',return_value={'api_key':'fixture-key'}),patch('task_relay.gemini.Client') as client,patch.object(review,'RESPONSE_SCHEMA',{'type':'string'}):
            client.return_value.request.return_value={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{}'}]}}]}
            worker=review.GeminiReviewer('gemini-fixture-review',2048)
            worker.call(review.inspect(self.rt,ident)['payload'])
            body=client.return_value.request.call_args.args[1]
            self.assertEqual(body['generationConfig']['responseJsonSchema'],schema)
            self.assertEqual(schema['properties']['limitations']['type'],'array')
            self.assertEqual(schema['properties']['limitations']['items']['type'],'string')
            self.assertNotIn('response_json_schema',json.loads(body['contents'][0]['parts'][0]['text']))
            legacy=copy.deepcopy(payload);del legacy['response_json_schema']
            worker.call(legacy)
            self.assertNotIn('responseJsonSchema',client.return_value.request.call_args.args[1]['generationConfig'])

    def test_job_ownership_and_declared_review_artifact(self):
        from tests.test_job_delete import PID,OTHER
        ident=self.prepare();fixture=self.evidence.fixture
        self.assertTrue(any('review needs reconciliation' in b for b in job_delete.preview(PID,fixture.paths)['blockers']))
        result=review.run(self.rt,ident,Reviewer(self))
        report=workflow_files._snapshot(self.evidence.state,PID)
        self.assertEqual(report['computer_reviews'][0]['id'],ident)
        self.assertIn(result['artifact'],[a['id'] for a in report['artifacts']])
        workflow_files.sync(self.evidence.state,PID)
        fixture.pipeline(pid=OTHER,request=2)
        with self.db:self.db.execute("INSERT INTO relay_pipeline_steps(pipeline,position,id,status,sources) VALUES (?,0,'consume','pending',?)",(OTHER,json.dumps(result['inputs'])))
        self.assertTrue(any('cites an output' in b for b in job_delete.preview(PID,fixture.paths)['blockers']))
        with self.db:self.db.execute('DELETE FROM relay_pipeline_steps WHERE pipeline=?',(OTHER,))
        state=job_delete.preview(PID,fixture.paths);self.assertFalse(state['blockers'],state['blockers'])
        job_delete.delete(PID,state['digest'],fixture.paths)
        self.assertEqual(self.db.execute('SELECT count(*) FROM relay_computer_reviews').fetchone()[0],0)
