import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from orchestrator.storage import transaction
from task_relay import opportunities as opp, pipelines, procedures, relay_channels
from tests import test_task_routing as fixtures


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request

    def history(self, ident, place='Iowa', ids=('research','report'), channel='telegram', status='completed', gates=None, overrides=None):
        scoped=relay_channels.ScopedState(self.state,channel)
        stages=[dict(id=s,instruction=f'Prepare {s} for {place} from exact supplied inputs.',route='conversation',
                     gate=(gates or {}).get(s,'none'),capabilities=[],deliverables={s:'Reviewed '+s}) for s in ids]
        for s in stages:s.update((overrides or {}).get(s['id'],{}))
        action=dict(kind='plan_pipeline',title=place+' study',planning_only=True,stages=stages)
        with transaction(self.state.db):
            self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
            pipelines.dispatch(scoped,dict(id=ident,prompt=f'Research {place} and create requested outputs. Preserve originals.',
                                           provider='gemini',model='fixture'),action,
                               {'capabilities':{'graph_operations':[{'id':c} for s in stages for c in s['capabilities']]}})
            p=self.state.db.execute('SELECT * FROM relay_pipelines WHERE request_id=?',(ident,)).fetchone()
            self.state.db.execute('UPDATE relay_pipelines SET status=? WHERE id=?',(status,p['id']))
            self.state.db.execute('UPDATE relay_pipeline_steps SET status=? WHERE pipeline=?',(status,p['id']))
            for i,s in enumerate(ids):
                self.state.db.execute('INSERT INTO relay_pipeline_events(pipeline,step,kind,detail,created) VALUES (?,?,?,?,?)',
                                      (p['id'],s,'queued','{}',ident*100+i*10))
                if status=='completed':
                    self.state.db.execute('INSERT INTO relay_pipeline_events(pipeline,step,kind,detail,created) VALUES (?,?,?,?,?)',
                                          (p['id'],s,'completed','{}',ident*100+i*10+5))
        return dict(self.state.db.execute('SELECT * FROM relay_pipelines WHERE id=?',(p['id'],)).fetchone())

    def analyze(self):return opp.analyze(self.state,now=100000)

    def scan(self, ident=800):
        with transaction(self.state.db):return opp.scan(self.state,ident,'Find automation opportunities')

    def human(self, ident, prompt, channel='telegram', error=None, internal=None):
        with self.state.db:
            self.state.db.execute('INSERT INTO relay_request_channels VALUES (?,?)',(ident,channel))
            self.state.db.execute('INSERT INTO orchestrator_chats(id,prompt,provider,model,status,created) VALUES (?,?,?,?,?,?)',
                                  (ident,prompt,'gemini','fixture','failed' if error else 'answered',ident))
            if error:self.state.db.execute('INSERT INTO orchestrator_chat_errors VALUES (?,?,?,?,?)',(ident,'interpretation','ValueError',error,ident))
            if internal:self.state.db.execute('INSERT INTO relay_pipeline_requests VALUES (?,?,?,?)',(ident,internal,'research','{}'))

    def test_repeated_project_structure_has_traceable_counts_without_acceptance_or_writes(self):
        a=self.history(1); b=self.history(2,'Arizona')
        before=self.state.db.total_changes
        report=self.analyze()
        self.assertEqual(self.state.db.total_changes,before)
        c=next(c for c in report['candidates'] if c['kind']=='workflow')
        self.assertEqual(c['summary']['occurrences'],2)
        self.assertEqual(c['summary']['completed'],2)
        self.assertEqual(c['summary']['user_choices'],0)
        self.assertEqual(c['summary']['selected_artifact_versions'],0)
        self.assertIsNone(c['summary']['planning_tokens'])
        self.assertEqual({e['pipeline_id'] for e in c['evidence']},{a['id'],b['id']})
        self.assertEqual({e['elapsed_seconds'] for e in c['evidence']},{15})
        self.assertIn('not acceptance',report['limitation'])
        self.assertEqual(len(c['draft_sources']),2)

    def test_shared_sequences_cross_different_workflows_and_keep_gates(self):
        self.history(1,ids=('research','model','render','deck'))
        self.history(2,ids=('intake','model','render','report'))
        self.history(3,ids=('intake','model','render','report'),gates={'model':'choice'})
        shared=[c for c in self.analyze()['candidates'] if c['kind']=='sequence']
        model=next(c for c in shared if [s['id'] for s in c['signature']]==['model','render'])
        self.assertEqual(model['summary']['occurrences'],2)
        self.assertIn('Complete exemplar',model['promotion'])
        self.assertTrue(all(e['stage_statuses'].keys()=={'model','render'} for e in model['evidence']))

    def test_operation_contracts_match_renamed_stages_without_changing_source_identity(self):
        for ident,ids in ((1,('visualization','deck')),(2,('photo','presentation'))):
            self.history(ident,ids=ids,overrides={
                ids[0]:dict(route='image',gate='selection'),
                ids[1]:dict(route='production',gate='selection',capabilities=['pptx.create'])})
        c=next(c for c in self.analyze()['candidates'] if c['kind']=='workflow')
        self.assertEqual(c['summary']['occurrences'],2)
        self.assertEqual({tuple(e['stages']) for e in c['evidence']},{('visualization','deck'),('photo','presentation')})
        for exemplar in c['draft_sources']:
            self.assertEqual(exemplar['sha256'],procedures.digest(procedures.source(self.state,exemplar['pipeline_id'])))

    def test_retry_events_do_not_inflate_independent_observations_or_imply_repair_success(self):
        a=self.history(1,status='blocked');b=self.history(2,status='blocked')
        with transaction(self.state.db):
            for p in (a,b):
                for _ in range(3):pipelines.event(self.state,p['id'],'research','blocked',{'error':'time_limit'})
                self.state.db.execute('INSERT INTO production_auto_repairs(pipeline,step,parent,baseline,status) VALUES (?,?,?,?,?)',
                                      (p['id'],'research','run-'+p['id'],'{}','awaiting_start'))
        candidates=self.analyze()['candidates']
        c=next(c for c in candidates if c['kind']=='failure' and 'stage research:' in c['signature'])
        self.assertEqual(c['summary']['occurrences'],2)
        self.assertEqual(c['summary']['failure_events'],6)
        self.assertEqual(c['summary']['repair_receipts'],2)
        self.assertEqual(c['summary']['completed'],0)
        self.assertEqual(c['draft_sources'],[])
        self.assertEqual(next(c for c in candidates if c['kind']=='workflow')['draft_sources'],[])

    def test_exact_human_requests_exclude_internal_jobs_other_channels_and_analysis_itself(self):
        p=self.history(1)
        self.human(20,'Create a report',error='Bad response')
        self.human(21,'Create  a report',error='Different bad response')
        self.human(22,'Create a report','messages')
        self.human(23,'Create a report',internal=p['id'])
        self.human(24,'Create a report')
        with self.state.db:self.state.db.execute('INSERT INTO capability_dispatches(job_id,action,executor,result,created) VALUES (?,?,?,?,?)',
                                               (24,'{"kind":"discover_opportunities"}','relay_opportunities','Analysis',24))
        report=self.analyze()
        request=next(c for c in report['candidates'] if c['kind']=='request')
        self.assertEqual(request['summary']['occurrences'],2)
        self.assertEqual({e['request_id'] for e in request['evidence']},{20,21})
        self.assertIsNone(request['summary']['completed'])
        self.assertEqual(report['coverage']['requests_analyzed'],2)
        failure=next(c for c in report['candidates'] if c['kind']=='failure')
        self.assertEqual(failure['summary']['occurrences'],2)
        self.assertEqual(len({e['error'] for e in failure['evidence']}),2)

    def test_usage_counts_only_linked_calls_and_keeps_unknowns(self):
        p=self.history(1);self.history(2)
        with self.state.db:
            for ident,ch in ((100,'telegram'),(101,'messages')):
                self.state.db.execute('INSERT INTO relay_pipeline_requests VALUES (?,?,?,?)',(ident,p['id'],'research','{}'))
                self.state.db.execute('''INSERT INTO production_plans(id,request_id,channel,request,options,context,context_hash,provider,model,status,expires,created,token)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',(str(ident),ident,ch,'Prepare','{}','{}','hash','gemini','fixture','ready',1000,1,'token-'+str(ident)))
            for plan,n,usage in (('100',1,{'totalTokenCount':25}),('100',2,{}),('101',1,{'totalTokenCount':9999})):
                self.state.db.execute('INSERT INTO production_plan_calls(plan_id,number,request,usage,created) VALUES (?,?,?,?,?)',
                                      (plan,n,'{}',json.dumps(usage),1))
        c=next(c for c in self.analyze()['candidates'] if c['kind']=='workflow')
        self.assertEqual(c['summary']['planning_calls'],2)
        self.assertEqual(c['summary']['measured_planning_calls'],1)
        self.assertEqual(c['summary']['planning_tokens'],25)
        self.assertIn('not a savings',c['savings'])

    def test_scan_snapshots_are_idempotent_and_promotion_only_drafts_exact_whole_exemplar(self):
        a=self.history(1);self.history(2,'Arizona')
        before=self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0]
        report=self.scan();again=self.scan()
        self.assertEqual(report,again)
        c=next(c for c in report['candidates'] if c['kind']=='workflow')
        with transaction(self.state.db):
            text=opp.command(self.state,'draft '+c['id']+' '+a['id']+' '+json.dumps({
                'name':'Study','parameters':[{'name':'location','example':'Iowa'}]}),801,'Save this opportunity as a draft')
        saved=self.state.db.execute('SELECT * FROM relay_procedures').fetchone()
        definition=json.loads(saved['definition'])
        self.assertEqual(saved['status'],'draft')
        self.assertEqual(definition['opportunity']['id'],c['id'])
        self.assertEqual(len(definition['template']['stages']),2)
        self.assertIn('Approve this exact template',text)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_opportunity_scans').fetchone()[0],1)

    def test_stale_exemplar_cross_channel_and_tampered_candidate_cannot_be_promoted(self):
        a=self.history(1);self.history(2)
        c=self.scan()['candidates'][0]
        other=relay_channels.ScopedState(self.state,'messages')
        with self.assertRaisesRegex(ValueError,'channel'):opp.load(other,c['id'])
        with transaction(self.state.db):pipelines.event(self.state,a['id'],None,'new_receipt',{'reason':'Changed'})
        with self.assertRaisesRegex(ValueError,'changed since'):opp.exemplar(self.state,c['id'],a['id'])
        self.assertEqual(opp.load(self.state,c['id'])['summary']['occurrences'],2)
        with self.state.db:self.state.db.execute("UPDATE relay_opportunity_candidates SET definition=replace(definition,'Iowa study','Changed title')")
        with self.assertRaisesRegex(ValueError,'evidence changed'):opp.load(self.state,c['id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_procedures').fetchone()[0],0)

    def test_failed_scan_storage_rolls_back_candidates(self):
        self.history(1);self.history(2)
        self.state.db.execute("CREATE TRIGGER fail_scan BEFORE INSERT ON relay_opportunity_scans BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.scan()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_opportunity_candidates').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_opportunity_scans').fetchone()[0],0)

    def test_tampered_report_is_rejected_but_a_new_scan_can_recover(self):
        self.history(1);self.history(2)
        self.scan()
        with self.state.db:self.state.db.execute("UPDATE relay_opportunity_scans SET report=replace(report,'Iowa study','Changed title')")
        with self.assertRaisesRegex(ValueError,'Saved analysis changed'):opp.latest(self.state)
        self.assertIn('error',opp.catalog(self.state)[0])
        self.scan(801)
        self.assertEqual(opp.latest(self.state)['coverage']['workflows_analyzed'],2)

    def test_limits_and_malformed_workflows_are_visible(self):
        self.history(1);self.history(2);bad=self.history(3)
        with self.state.db:self.state.db.execute("UPDATE relay_pipelines SET spec='invalid json' WHERE id=?",(bad['id'],))
        with patch.object(opp,'WORKFLOW_LIMIT',2):report=self.analyze()
        self.assertEqual(report['coverage']['workflows_total'],3)
        self.assertEqual(report['coverage']['workflows_analyzed'],1)
        self.assertEqual(report['coverage']['workflows_skipped'],1)
        self.assertEqual(report['candidates'],[])

    def test_cli_uses_read_only_database_and_does_not_require_new_schema(self):
        self.history(1);self.history(2)
        with self.state.db:
            self.state.db.execute('DROP TABLE relay_opportunity_scans')
            self.state.db.execute('DROP TABLE relay_opportunity_candidates')
            self.state.db.execute('DROP TABLE relay_procedure_runs')
        dbpath=self.state.db.execute('PRAGMA database_list').fetchone()[2]
        before=set(opp.tables(self.state.db))
        run=subprocess.run([sys.executable,'-B','-m','task_relay.opportunities','--database',dbpath,'--json'],
                           cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)
        report=json.loads(run.stdout)
        self.assertEqual(len(report['candidates']),1)
        self.assertEqual(set(opp.tables(self.state.db)),before)

    def test_chat_discovery_and_direct_inspection_start_no_work(self):
        self.history(1);self.history(2)
        before=self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0]
        self.request({'kind':'discover_opportunities'},'Analyze our history for opportunities',700)
        report=opp.latest(self.state)
        self.assertIsNotNone(report,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=700').fetchone()[0])
        c=report['candidates'][0]
        self.bridge.process({'update_id':701,'message':{'text':'/opportunities '+c['id'],
            'from':{'id':7},'chat':{'id':7,'type':'private'}}})
        self.assertEqual(opp.focused(self.state)['id'],c['id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_chats').fetchone()[0],1)

    def test_natural_draft_retains_the_candidate_evidence_and_requires_approval(self):
        a=self.history(1);self.history(2)
        c=self.scan()['candidates'][0]
        action=dict(kind='draft_procedure',opportunity_id=c['id'],pipeline_id=a['id'],name='Reusable study',
                    parameters=[dict(name='location',example='Iowa')])
        self.request(action,'Save the opportunity as a draft with location as a variable',700)
        saved=self.state.db.execute('SELECT * FROM relay_procedures').fetchone()
        self.assertIsNotNone(saved,self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=700').fetchone()[0])
        self.assertEqual(saved['status'],'draft')
        self.assertEqual(json.loads(saved['definition'])['opportunity']['sha256'],c['sha256'])
        with transaction(self.state.db):
            procedures.approve(self.state,dict(id=701,prompt='/procedures approve '+saved['id']),saved['id'])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_pipelines').fetchone()[0],2)

    def test_candidate_pagination_keeps_old_evidence_inspectable(self):
        for i in range(1,11):self.history(i)
        c=self.scan()['candidates'][0]
        page1=opp.describe(self.state,c['id']);page2=opp.describe(self.state,c['id'],2)
        self.assertIn('Evidence page 1/2',page1)
        self.assertIn('Evidence page 2/2',page2)
        self.assertTrue(all(e['pipeline_id'] in page1 or e['pipeline_id'] in page2 for e in c['evidence']))
        with self.assertRaises(ValueError):opp.describe(self.state,c['id'],3)


if __name__=='__main__':unittest.main()
