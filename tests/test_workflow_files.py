"""Small committed text artifacts exercise folder export, recovery and ownership."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import hashlib
from task_relay import workflow_files as files, pipelines as pipe, relay_channels, job_state, job_record
from orchestrator.storage import transaction
from tests import test_pipelines as pipeline_fixtures


class Tests(unittest.TestCase):
    setUp=pipeline_fixtures.Tests.setUp
    tearDown=pipeline_fixtures.Tests.tearDown
    create=pipeline_fixtures.Tests.create
    stage=pipeline_fixtures.Tests.stage
    request=pipeline_fixtures.Tests.request
    def exported(self, root, aid):
        manifest=json.loads((root/'manifest.json').read_text())
        return root/next(a['copy_path'] for a in manifest['artifacts'] if a['id']==aid)

    def artifact(self,run,text):
        p=self.root/(run+'.txt');p.write_text(text)
        return self.rt.register(p,'Version of the requested result',run=run,path='delivery/result.txt')

    def setup_versions(self):
        p=self.create(planning_only=True)
        old=self.artifact('old-run','Earlier draft')
        new=self.artifact('new-run','Reviewed candidate')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target='new-run' WHERE pipeline=? AND id='outline'",(p['id'],))
            self.state.db.execute("INSERT INTO production_continuations(id,parent,child,request,baseline,files,status) VALUES (7,'old-run','new-run','Recover exactly','{}','[]','registered')")
        return p,old,new

    def test_export_retains_recovery_versions_and_does_not_select_or_dispatch(self):
        p,old,new=self.setup_versions()
        before=list(self.state.db.iterdump())
        root=files.sync(self.state,p['id'])
        self.assertEqual(list(self.state.db.iterdump()),before)
        self.assertEqual((self.exported(root,old)).read_text(),'Earlier draft')
        self.assertEqual((self.exported(root,new)).read_text(),'Reviewed candidate')
        self.assertEqual((root/'request.txt').read_text(),p['request'])
        self.assertIn(str(root),pipe.catalog(self.state)[0]['files_path'])
        readme=(root/'README.md').read_bytes();files.sync(self.state,p['id'])
        self.assertEqual((root/'README.md').read_bytes(),readme)
        copied=self.exported(root,new);copied.write_text('My inspection edits')
        with transaction(self.state.db):self.state.db.execute("UPDATE relay_pipelines SET status='paused' WHERE id=?",(p['id'],))
        files.sync(self.state,p['id'])
        self.assertEqual(copied.read_text(),'My inspection edits')
        self.assertEqual(Path(self.rt.artifact(new)['blob']).read_text(),'Reviewed candidate')
        (root/'README.md').write_text('My own index')
        with transaction(self.state.db):self.state.db.execute("UPDATE relay_pipelines SET status='active' WHERE id=?",(p['id'],))
        files.sync(self.state,p['id'])
        self.assertEqual((root/'README.md').read_text(),'My own index')

    def test_job_state_export_and_stage_context_are_read_only_and_exact(self):
        p,old,new=self.setup_versions()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE relay_pipeline_steps SET sources=? WHERE pipeline=? AND id=?',
                                  (json.dumps([{'artifact':new}]),p['id'],'outline'))
        before=list(self.state.db.iterdump())
        root=files.sync(self.state,p['id'])
        marker=json.loads((root/'.relay-workflow.json').read_text())
        exported=json.loads((root/'.relay/snapshots'/marker['snapshot']/'job-state.json').read_text())
        self.assertEqual(exported['schema'],job_state.SCHEMA)
        self.assertEqual(exported['version'],12)
        self.assertEqual(exported['presentations']['links'], [])
        self.assertEqual(exported['job']['objective'],p['request'])
        self.assertEqual({a['id'] for a in exported['artifacts']},{old,new})
        context=files.context_for_stage(self.state,p['id'],'outline')
        self.assertEqual([a['id'] for a in context['artifacts']],[new])
        self.assertEqual(context['stage']['sources'],[{'artifact':new}])
        self.assertEqual(list(self.state.db.iterdump()),before)

    def test_job_process_projects_exact_work_and_recovery_without_desktop(self):
        p = self.create(planning_only=True)
        artifact = self.artifact('run-fixture', 'Checked candidate')
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='plan_production',target='plan-fixture' WHERE pipeline=? AND id='outline'", (p['id'],))
            self.state.db.execute("""INSERT INTO production_plans
                (id,request_id,channel,request,options,context,context_hash,provider,model,status,
                 token,expires,run,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('plan-fixture', 42, 'telegram', 'Exact stage request', '{}', '{"sources":[]}',
                 'hash', 'fixture', 'fixture', 'started', 'token-fixture', 0, 'run-fixture', 1))
            self.state.db.execute("INSERT INTO production_plan_calls VALUES (?,?,?,?,?,?,?)",
                                  ('plan-fixture', 1, 'Exact planner input', 'Exact planner response', '{}', None, 1))
            self.state.db.execute("INSERT INTO production_runs VALUES (?,?,?)", ('run-fixture', '{}', 'active'))
            self.state.db.execute("INSERT INTO production_assignments VALUES (?,?,?,?,?)",
                                  ('assignment-fixture', 'run-fixture', 'producer', 1, '{"criteria":["check"]}'))
            self.state.db.execute("INSERT INTO production_tasks VALUES (?,?,?,?,?,?)",
                                  ('run-fixture', 'producer', 'assignment-fixture', 'completed', 1, 'attempt-fixture'))
            self.state.db.execute("""INSERT INTO production_attempts
                (id,run,task,assignment,state,resource,frozen,session,receipt,error)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ('attempt-fixture', 'run-fixture', 'producer', 'assignment-fixture', 'completed', None,
                 '{"inputs":[]}', '{}', '{"status":"finished","exit_code":0}', None))
            self.state.db.execute("INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (?,?,?,?,?,?)",
                                  (1, 'run-fixture', 'producer', 'attempt-fixture', 'checks_recorded',
                                   '{"passed":true,"checks":["exact bytes"]}'))
            self.state.db.execute("INSERT INTO production_decisions VALUES (?,?,?,?,?,?,?)",
                                  ('decision-fixture', 'run-fixture', 'producer', artifact,
                                   'Selection', 'Human chose this', 1))
            self.state.db.execute("INSERT INTO production_revisions VALUES (?,?,?,?,?,?,?,?)",
                                  (1, 'run-fixture', 'producer', 'Revise exact output', '{}', '[]', 'completed', None))
        before = list(self.state.db.iterdump())
        root = files.sync(self.state, p['id'])
        marker = json.loads((root / '.relay-workflow.json').read_text())
        json_view = json.loads((root / '.relay/snapshots' / marker['snapshot'] / 'job-state.json').read_text())
        process = json_view['process']
        self.assertTrue(process['complete'], process['gaps'])
        self.assertEqual({row['category'] for row in process['records']},
                     set(job_record.CATEGORIES) - {'exceptions', 'decision_controls',
                                                   'channel_history', 'change_plans'})
        self.assertEqual(next(row for row in process['coverage'] if row['category'] == 'exceptions')['state'], 'empty')
        self.assertEqual(next(row for row in process['coverage'] if row['category'] == 'channel_history')['state'], 'external')
        exact = next(row['data'] for row in process['records']
                     if row['source_table'] == 'production_attempts' and row['category'] == 'attempts')
        self.assertEqual(json.loads(exact['receipt'])['status'], 'finished')
        view = root / '.relay/job.sqlite'
        summary = job_record.inspect(view)
        self.assertEqual(summary['snapshot'], marker['snapshot'])
        self.assertTrue(summary['complete'])
        cli = subprocess.run([sys.executable, '-m', 'task_relay.job_record', str(view)],
                             check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(cli.stdout)['snapshot'], marker['snapshot'])
        with sqlite3.connect(view) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM process_records').fetchone()[0],
                             len(process['records']))
            self.assertEqual(db.execute('SELECT count(*) FROM process_gaps').fetchone()[0],
                             len(process['gaps']))
            saved = [json.loads(row[0]) for row in db.execute(
                "SELECT record FROM process_records WHERE source_table='production_events' AND category='checks'")]
            self.assertEqual(saved[0]['data'], '{"passed":true,"checks":["exact bytes"]}')
        self.assertEqual(list(self.state.db.iterdump()), before)

    def test_job_process_marks_missing_referenced_assignment_and_attempt(self):
        p = self.create(planning_only=True)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target='run-gap' WHERE pipeline=? AND id='outline'", (p['id'],))
            self.state.db.execute("INSERT INTO production_runs VALUES (?,?,?)", ('run-gap', '{}', 'active'))
            self.state.db.execute("INSERT INTO production_tasks VALUES (?,?,?,?,?,?)",
                                  ('run-gap', 'producer', 'assignment-gone', 'blocked', 1, 'attempt-gone'))
        root = files.sync(self.state, p['id'])
        summary = job_record.inspect(root / '.relay/job.sqlite')
        self.assertFalse(summary['complete'])
        self.assertEqual({gap['kind'] for gap in summary['gaps']},
                         {'missing_assignment', 'missing_latest_attempt', 'outside_job_scope'})
        self.assertEqual({row['category']: row['state'] for row in summary['coverage']}['attempts'], 'incomplete')

    def test_later_check_event_creates_new_complete_process_snapshot(self):
        p = self.create(planning_only=True)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target='run-check' WHERE pipeline=? AND id='outline'", (p['id'],))
            self.state.db.execute("INSERT INTO production_runs VALUES (?,?,?)", ('run-check', '{}', 'active'))
            self.state.db.execute("INSERT INTO production_assignments VALUES (?,?,?,?,?)",
                                  ('assignment-check', 'run-check', 'producer', 1, '{}'))
            self.state.db.execute("INSERT INTO production_tasks VALUES (?,?,?,?,?,?)",
                                  ('run-check', 'producer', 'assignment-check', 'completed', 1, 'attempt-check'))
            self.state.db.execute("""INSERT INTO production_attempts
                (id,run,task,assignment,state,resource,frozen,session,receipt,error)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ('attempt-check', 'run-check', 'producer', 'assignment-check', 'completed', None,
                 '{"inputs":[]}', '{}', '{"status":"finished","exit_code":0}', None))
        root = files.sync(self.state, p['id'])
        first = json.loads((root / '.relay-workflow.json').read_text())['snapshot']
        self.assertIn('missing_checks', {gap['kind'] for gap in job_record.inspect(root / '.relay/job.sqlite')['gaps']})
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_events(created,run,task,attempt,kind,data) VALUES (?,?,?,?,?,?)",
                                  (2, 'run-check', 'producer', 'attempt-check', 'checks_recorded', '{"passed":true}'))
        files.sync(self.state, p['id'])
        second = json.loads((root / '.relay-workflow.json').read_text())['snapshot']
        self.assertNotEqual(first, second)
        self.assertTrue(job_record.inspect(root / '.relay/job.sqlite')['complete'])
        self.assertIn('missing_checks', {gap['kind'] for gap in
                      job_record.inspect(root / '.relay/snapshots' / first / 'job.sqlite')['gaps']})

    def test_old_job_view_reports_missing_process_without_modifying_it(self):
        path = self.root / 'legacy-job.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.executemany('INSERT INTO meta VALUES (?,?)', [('job', 'old-job'), ('snapshot', 'old-snapshot')])
        before = path.read_bytes()
        result = job_record.inspect(path)
        self.assertFalse(result['complete'])
        self.assertEqual(result['gaps'][0]['kind'], 'legacy_process_missing')
        self.assertEqual(path.read_bytes(), before)

    def test_declared_dependencies_do_not_claim_semantic_use(self):
        report={'id':'job','title':'Job','request':'Change the source','status':'active','snapshot':'abc',
                'stages':[{'id':'revise','position':1,'status':'queued','sources':[{'artifact':'output'}],
                           'choices':[],'runs':['run'],'plans':[]}],
                'artifacts':[{'id':'source','attempt':None,'sha256':'a'},
                             {'id':'output','attempt':'attempt','sha256':'b'}],
                'productions':[{'run':'run','decisions':[],
                                'attempts':[{'id':'attempt','task':'producer','state':'finished','error':None,
                                             'receipt':{'status':'finished'},
                                             'frozen':{'inputs':[{'artifact':'source','sha256':'a','path':'input.txt'}]}}]}],
                'missing_artifacts':[], 'process': {'complete': True, 'records': [], 'coverage': [], 'gaps': []},
                'replacements':[{'scope':'job:1','heads':[],
                                 'outdated_outputs':[{'artifact':'source','reason':{'basis':'superseded'}}],
                                 'truncated':False}]}
        state=job_state.project(report)
        self.assertEqual(state['dependencies'][0]['basis'],'declared_input_potential_dependency')
        context=job_state.stage_context(state,'revise')
        self.assertEqual({a['id'] for a in context['artifacts']},{'source','output'})
        self.assertEqual(context['outdated_inputs'][0]['artifact'],'source')
        self.assertTrue(context['complete'])

    def test_recorded_replacement_warning_reaches_stage_context(self):
        p,_,new=self.setup_versions()
        with transaction(self.state.db):
            self.state.db.execute('UPDATE relay_pipeline_steps SET sources=? WHERE pipeline=? AND id=?',
                                  (json.dumps([{'artifact':new}]),p['id'],'outline'))
            self.state.db.execute('INSERT INTO production_runs VALUES (?,?,?)',
                                  ('new-run','{}','completed'))
            self.state.db.execute('INSERT INTO production_replacement_heads VALUES (?,?,?,?,?,?)',
                                  ('head','job:"new-run"','Choose result','decision',1,'["decision"]'))
            self.state.db.execute('INSERT INTO production_artifact_validity VALUES (?,?,?,?,?)',
                                  (new,'head','replacement',1,json.dumps({'basis':'superseded selection'})))
        view=files.job_state_for_pipeline(self.state,p['id'])
        self.assertEqual(view['replacements'][0]['outdated_outputs'][0]['artifact'],new)
        context=files.context_for_stage(self.state,p['id'],'outline')
        self.assertEqual(context['outdated_inputs'][0]['artifact'],new)

    def test_edited_job_snapshot_never_becomes_model_authority(self):
        p,_,_=self.setup_versions()
        root=files.sync(self.state,p['id'])
        marker=json.loads((root/'.relay-workflow.json').read_text())
        exported=root/'.relay/snapshots'/marker['snapshot']/'job-state.json'
        exported.write_text('{"objective":"forged"}')
        files.sync(self.state,p['id'])
        updated=json.loads((root/'.relay-workflow.json').read_text())
        self.assertNotEqual(updated['snapshot'],marker['snapshot'])
        self.assertEqual(exported.read_text(),'{"objective":"forged"}')
        context=files.context_for_stage(self.state,p['id'],'outline')
        self.assertEqual(context['job']['objective'],p['request'])

    def test_export_requires_commit_and_original_channel_and_rejects_symlinks(self):
        p,old,new=self.setup_versions()
        with transaction(self.state.db),self.assertRaisesRegex(ValueError,'commit'):
            files.sync(self.state,p['id'])
        self.assertFalse(files.folder_path(self.state,p['id']).exists())
        with self.assertRaisesRegex(ValueError,'channel'):
            files.sync(relay_channels.ScopedState(self.state,'messages'),p['id'])
        root=files.sync(self.state,p['id']);copy=self.exported(root,new)
        copy.unlink();target=self.root/'user-file.txt';target.write_text('Do not change')
        copy.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'symbolic'):
            files.sync(self.state,p['id'])
        self.assertEqual(target.read_text(),'Do not change')

    def test_changed_source_is_reported_without_losing_other_files(self):
        p,old,new=self.setup_versions()
        blob=Path(self.rt.artifact(old)['blob']);blob.chmod(0o600);blob.write_text('Unexpected source change')
        root=files.sync(self.state,p['id'])
        marker=json.loads((root/'.relay-workflow.json').read_text())
        manifest=json.loads((root/'.relay'/'snapshots'/marker['snapshot']/'manifest.json').read_text())
        self.assertEqual(manifest['copy_errors'][0]['artifact'],old)
        self.assertFalse((self.exported(root,old)).exists())
        self.assertEqual((self.exported(root,new)).read_text(),'Reviewed candidate')
        blob.write_text('Earlier draft')
        files.sync(self.state,p['id'])
        marker=json.loads((root/'.relay-workflow.json').read_text())
        manifest=json.loads((root/'.relay'/'snapshots'/marker['snapshot']/'manifest.json').read_text())
        self.assertEqual(manifest['copy_errors'],[])
        self.assertEqual((self.exported(root,old)).read_text(),'Earlier draft')

    def test_unowned_existing_directory_is_preserved(self):
        p=self.create(planning_only=True);root=files.folder_path(self.state,p['id'])
        root.mkdir(parents=True);(root/'existing.txt').write_text('User file')
        with self.assertRaisesRegex(ValueError,'ownership'):
            files.sync(self.state,p['id'])
        self.assertEqual([p.name for p in root.iterdir()],['existing.txt'])

    def test_linked_followup_has_folder_but_does_not_gain_workflow_authorization(self):
        p,old,new=self.setup_versions()
        followup=self.artifact('followup','Separate PDF request')
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO production_continuations(id,parent,child,request,baseline,files,status) VALUES (8,'new-run','followup','Make PDF','{}','[]','registered')")
        self.assertEqual(files.owner_for_run(self.state,'followup')['id'],p['id'])
        self.assertIsNone(pipe.owner_of_run(self.state,'followup'))
        root=files.sync(self.state,p['id'])
        self.assertEqual((self.exported(root,followup)).read_text(),'Separate PDF request')

    def test_generated_media_candidates_keep_exact_bytes_and_names(self):
        p=self.create(planning_only=True)
        media=self.root/'media-output';media.mkdir();source=media/'image.png';source.write_bytes(b'small fixture, no generation')
        aid='1'*20
        with transaction(self.state.db):
            self.state.db.execute("INSERT INTO artifacts(id,thread_id,job_id,role,path,filename,mime,sha256,size,created_at,active) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(aid,'thread','image-job','output',str(source),'image.png','image/png',hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_size,1,1))
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='generate_image',target='image-job' WHERE pipeline=? AND id='outline'",(p['id'],))
        with patch('task_relay.gemini.GENERATED',media):root=files.sync(self.state,p['id'])
        self.assertEqual((self.exported(root,'media-'+aid)).read_bytes(),source.read_bytes())

    def test_native_files_are_visible_by_stage_without_changing_bytes_or_acceptance(self):
        p=self.create(planning_only=True)
        ids=[]
        for name in ('candidate.3dm', 'scene.blend', 'preview.png'):
            source=self.root/name;source.write_text('native fixture '+name)
            ids.append(self.rt.register(source,'Requested output',run='native-run',path='delivery/'+name))
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET target_kind='production_run',target='native-run',sources=? WHERE pipeline=? AND id='outline'",(json.dumps([{'artifact':a} for a in ids]),p['id']))
        before=list(self.state.db.iterdump())
        root=files.sync(self.state,p['id'])
        for aid,name in zip(ids,('candidate.3dm','scene.blend','preview.png')):
            path=self.exported(root,aid)
            self.assertEqual(path,root/'01-outline'/'selected'/name)
            self.assertEqual(path.read_text(),'native fixture '+name)
        self.assertEqual(list(self.state.db.iterdump()),before)
        self.assertFalse((root/'files').exists())

    def test_new_selection_archives_old_version_without_overwriting_user_edits(self):
        p,old,new=self.setup_versions()
        def select(a):
            with transaction(self.state.db):
                self.state.db.execute("UPDATE relay_pipeline_steps SET sources=? WHERE pipeline=? AND id='outline'",(json.dumps([{'artifact':a}]),p['id']))
        select(old);root=files.sync(self.state,p['id'])
        current=self.exported(root,old)
        self.assertIn('/selected/',str(current))
        select(new);files.sync(self.state,p['id'])
        self.assertEqual(self.exported(root,new),current)
        self.assertEqual(current.read_text(),'Reviewed candidate')
        self.assertNotEqual(self.exported(root,old),current)
        self.assertEqual(self.exported(root,old).read_text(),'Earlier draft')
        current.write_text('User local changes')
        select(old);files.sync(self.state,p['id'])
        self.assertEqual(current.read_text(),'User local changes')
        self.assertEqual(self.exported(root,old).read_text(),'Earlier draft')
        self.assertEqual(self.exported(root,new).read_text(),'Reviewed candidate')

    def test_legacy_layout_moves_files_and_retains_user_edits_and_receipts(self):
        p,old,new=self.setup_versions();root=files.folder_path(self.state,p['id'])
        root.mkdir(parents=True)
        legacy=[]
        inodes={}
        for aid in (old,new):
            relative='files/'+aid+'/result.txt';dest=root/relative
            dest.parent.mkdir(parents=True);dest.write_bytes(Path(self.rt.artifact(aid)['blob']).read_bytes())
            inodes[aid]=dest.stat().st_ino
            legacy.append({'id':aid,'copy_path':relative})
        edited=root/'files'/old/'notes.txt';edited.write_text('My notes')
        manifest=root/'snapshots'/'legacy'/'manifest.json';manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'artifacts':legacy}))
        (root/'.relay-workflow.json').write_text(json.dumps({'workflow':p['id'],'snapshot':'legacy'}))
        before=list(self.state.db.iterdump());files.sync(self.state,p['id'])
        self.assertFalse((root/'files').exists())
        self.assertEqual((root/'.relay/legacy-layout/files'/old/'notes.txt').read_text(),'My notes')
        self.assertTrue((root/'.relay/legacy-layout/snapshots/legacy/manifest.json').is_file())
        for aid in (old,new):self.assertEqual(self.exported(root,aid).stat().st_ino,inodes[aid])
        self.assertEqual(list(self.state.db.iterdump()),before)

    def test_interrupted_promotion_resumes_from_staging(self):
        p,old,new=self.setup_versions();root=files.sync(self.state,p['id'])
        old_path=self.exported(root,new)
        with transaction(self.state.db):
            self.state.db.execute("UPDATE relay_pipeline_steps SET sources=? WHERE pipeline=? AND id='outline'",(json.dumps([{'artifact':new}]),p['id']))
        destination=root/'.relay/moving'/new;destination.parent.mkdir(parents=True)
        old_path.rename(destination)
        files.sync(self.state,p['id'])
        self.assertEqual(self.exported(root,new).read_text(),'Reviewed candidate')
        self.assertFalse(destination.exists())
