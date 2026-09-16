import json
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_production_control as fixtures
from task_relay import production_control as pc
from task_relay import production_continuations as cont
from task_relay import production_folders as folders
from task_relay import orchestrator_chat as chat


class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp
    tearDown=fixtures.Tests.tearDown
    message=fixtures.Tests.message
    click=fixtures.Tests.click
    worker=fixtures.Tests.worker
    stage_card=fixtures.Tests.stage_card
    finish_stage=fixtures.Tests.finish_stage
    blocked_revision=fixtures.Tests.blocked_revision

    def test_continue_retries_only_failed_api_review_within_approved_budget(self):
        from tests.test_orchestrator import pair
        from orchestrator import executors
        value=pair(max_attempts=2);value['id']='api-review';value['backend']={'type':'gemini-agent','model':'fixture'}
        for task in value['tasks']:task.update(tools=['files'],limits=executors.GEMINI_LIMITS.copy())
        self.rt.create(value);self.rt.tick('api-review')
        producer=self.rt.task('api-review','produce')['latest'];self.factory.finish(producer);self.rt.tick('api-review')
        first=self.rt.task('api-review','review')['latest']
        self.factory.sessions[first]['status']={'status':'finished','exit_code':1,'external_outcome':'no_pending_response','pending_requests':[]}
        self.rt.tick('api-review')
        with self.rt.transaction():text=cont.enqueue(self.state,{'id':799,'prompt':'Continue the same independent review.'},'api-review')
        self.assertIn('Review recovery scheduled',text)
        self.assertEqual(self.rt.task('api-review','produce')['latest'],producer)
        self.rt.tick('api-review');second=self.rt.task('api-review','review')['latest']
        self.assertNotEqual(first,second);self.assertEqual(self.rt.task('api-review','review')['attempts'],2)
        self.factory.finish(second,decision='accept');self.rt.tick('api-review')
        self.assertEqual(self.rt.status('api-review')['status'],'completed')
        self.assertEqual(len(self.factory.calls),3)

    def queue(self, ident=700, text='Continue the script using the supplied research.', parent='demo'):
        self.message('/orchestrator '+text,ident)
        action={'kind':'continue_production','workflow':parent,'items':None,'direction':'Update using research'}
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'Continuing.','action':action})).tick()
        return self.state.db.execute('SELECT * FROM production_continuations WHERE parent=?',(parent,)).fetchone()

    def test_three_consecutive_continuations_keep_unique_paths_and_all_versions(self):
        self.blocked_revision()
        parent='demo';requests=[];drafts=[]
        original_tasks=[dict(r) for r in self.rt.db.execute("SELECT * FROM production_tasks WHERE run='demo'")]
        for number in range(3):
            prior=self.rt.task(parent,'produce')['latest']
            drafts.append('artifact from '+prior)
            request='Continue preparation with script direction '+str(number)
            requests.append(request)
            row=self.queue(800+number,request,parent)
            worker=self.worker();worker.tick();child=row['child']
            for tid in ('produce','review'):
                spec=self.rt.spec(self.rt.task(child,tid))
                paths=[i['path'] for i in spec['inputs']]+[o['path'] for o in spec['outputs']]
                self.assertEqual(len(paths),len(set(paths)))
                values={i['path']:Path(self.rt.artifact(i['artifact'])['blob']).read_text() for i in spec['inputs'] if 'artifact' in i}
                self.assertEqual(values['continuation/REQUEST.txt'],request)
                self.assertEqual(values['previous-stage/produce/output.txt'],drafts[-1])
                self.assertTrue(set(requests+drafts).issubset(set(values.values())))
                for i in spec['inputs']:
                    if i['path'].startswith('continuation-history/'):
                        self.assertIn('Historical prior-stage input',i['authority'])
                self.assertEqual(spec['max_attempts'],1)
            self.factory.finish(self.rt.task(child,'produce')['latest']);worker.tick()
            self.factory.finish(self.rt.task(child,'review')['latest'],decision='accept');worker.tick()
            self.assertEqual(self.rt.status(child)['status'],'awaiting_user')
            self.assertFalse(self.state.get('production-enabled:'+child))
            parent=child
        self.assertEqual(original_tasks,[dict(r) for r in self.rt.db.execute("SELECT * FROM production_tasks WHERE run='demo'")])
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_continuations').fetchone()[0],3)

    def test_continuation_preserves_parent_passes_exact_inputs_and_stops_at_review(self):
        self.blocked_revision()
        parent_tasks=[dict(r) for r in self.rt.db.execute("SELECT * FROM production_tasks WHERE run='demo'")]
        with patch.object(folders,'base_folder',return_value=Path(self.temp.name).resolve()/'research-home'):
            with self.state.db:folders.create(self.state,'demo')
            source=folders.folder(self.state,'demo')/'research'/'market.md'
            source.write_text('Dated primary sources for the market comparison.')
            original='Continue the script using the supplied research.\nKeep the duration and human judgment.'
            row=self.queue(text=original)
            self.assertEqual(row['status'],'queued')
            worker=self.worker();worker.tick()
            child=row['child']
            self.assertEqual(folders.folder(self.state,child),folders.folder(self.state,'demo'))
            self.assertEqual(folders.view(self.state,child)['imported_files'],1)
            for tid in ('produce','review'):
                spec=self.rt.spec(self.rt.task(child,tid))
                self.assertEqual(spec['max_attempts'],1)
                values={i['path']:self.rt.artifact(i['artifact']) for i in spec['inputs'] if 'artifact' in i}
                self.assertTrue(Path(values['continuation/REQUEST.txt']['blob']).read_text().startswith(original))
                self.assertTrue(any(p.endswith('market.md') for p in values))
                self.assertTrue(any(p.startswith('previous-stage/') for p in values))
                self.assertIn('story.md',values)
            self.factory.finish(self.rt.task(child,'produce')['latest']);worker.tick()
            self.factory.finish(self.rt.task(child,'review')['latest'],decision='accept');worker.tick()
            self.assertEqual(self.rt.status(child)['status'],'awaiting_user')
            self.assertFalse(self.state.get('production-enabled:'+child))
            self.assertEqual(parent_tasks,[dict(r) for r in self.rt.db.execute("SELECT * FROM production_tasks WHERE run='demo'")])
            self.assertEqual(self.state.db.execute('SELECT count(*) FROM orchestrator_proposals WHERE job_id=700').fetchone()[0],0)
            self.assertTrue(any(row['child'] in m[0] for m in self.state.db.execute('SELECT text FROM outbox')))

    def test_duplicate_request_and_repeated_old_parent_do_not_create_more_work(self):
        self.blocked_revision();row=self.queue()
        self.queue(701);self.worker().tick();self.worker().tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_continuations').fetchone()[0],1)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)
        self.assertEqual(self.rt.task(row['child'],'produce')['attempts'],1)

    def test_runtime_commit_recovered_without_duplicate_registration(self):
        self.blocked_revision();row=self.queue()
        with self.rt.transaction():cont.build(self.rt,row,self.state)
        before=self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0]
        cont.apply(self.worker())
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],before)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_continuations').fetchone()[0],'registered')
        self.assertTrue(self.state.get('production-enabled:'+row['child']))

    def test_continuation_and_relay_receipt_rollback_together(self):
        self.blocked_revision();row=self.queue()
        before=self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0]
        real=self.state.put
        def fail(key,value):
            if key=='production-enabled:'+row['child']:raise RuntimeError('crash before shared commit')
            return real(key,value)
        with patch.object(self.state,'put',side_effect=fail),self.assertRaises(RuntimeError):cont.apply(self.worker())
        self.assertEqual(self.state.db.execute('SELECT status FROM production_continuations').fetchone()[0],'queued')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],before)
        cont.apply(self.worker())
        self.assertEqual(self.state.db.execute('SELECT status FROM production_continuations').fetchone()[0],'registered')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],2)

    def test_changed_parent_fails_without_new_stage_or_dispatch(self):
        self.blocked_revision();self.queue();calls=len(self.factory.calls)
        with self.rt.transaction():
            self.rt.db.execute("UPDATE production_tasks SET status='cancelled' WHERE run='demo' AND id='produce'")
        cont.apply(self.worker())
        self.assertEqual(self.state.db.execute('SELECT status FROM production_continuations').fetchone()[0],'failed')
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(len(self.factory.calls),calls)

    def test_changed_guide_rolls_back_stage_and_registered_artifacts(self):
        self.blocked_revision()
        guide=pc.root(self.state).parent/'production-guides'/'99'/'market.md'
        guide.parent.mkdir(parents=True);guide.write_text('source')
        import hashlib
        with self.state.db:self.state.db.execute("INSERT INTO production_uploads(id,run,file_id,filename,caption,declared_size,status,path,sha256,bytes) VALUES (99,'demo','local','market.md','research',6,'ready',?,?,6)",(str(guide.resolve()),hashlib.sha256(b'source').hexdigest()))
        self.queue();before=self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0]
        guide.write_text('changed')
        cont.apply(self.worker())
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],before)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],1)
        self.assertEqual(self.state.db.execute('SELECT status FROM production_continuations').fetchone()[0],'failed')

    def test_live_parent_and_planning_question_do_not_launch(self):
        self.click(self.stage_card()['token']);self.worker().tick()
        self.assertIsNone(self.queue())
        self.assertIn('active or uncertain',self.state.db.execute('SELECT answer FROM orchestrator_chats WHERE id=700').fetchone()[0])
        self.message('/orchestrator How would continuation work? Do not start.',701)
        chat.Worker(self.state,lambda *_:json.dumps({'answer':'One bounded successor when requested.','action':None})).tick()
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_continuations').fetchone()[0],0)


if __name__=='__main__':unittest.main()
