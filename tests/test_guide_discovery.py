import json
from pathlib import Path
from unittest.mock import patch
import unittest

import guide_discovery
import task_routing
import orchestrator_chat
from tests import test_task_routing as fixture


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    click=fixture.Tests.click

    def guide(self,name='docs/solver-validation-guide.md',text='# Solver validation\nCheck floor geometry and room coverage.'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        return path

    def row(self):
        return self.state.db.execute('SELECT * FROM task_routes ORDER BY id DESC LIMIT 1').fetchone()

    def test_topics_are_not_limited_to_linkedin(self):
        for topic in ('solver','video','recipe','security'):
            self.guide(f'guides/{topic}.md',f'# {topic.title()} production\nFollow this process.')
            result=guide_discovery.discover(str(self.root),f'Create a {topic}',self.state)
            self.assertEqual([g['name'] for g in result['guides']],[f'guides/{topic}.md'])

    def test_guide_may_match_content_without_matching_filename(self):
        self.guide('docs/workflow-guide.md','# Standard procedure\nFor floor solvers, verify room coverage.')
        self.assertEqual(len(guide_discovery.discover(str(self.root),'Investigate floor room coverage')['guides']),1)

    def test_only_authorized_guides_enter_handoff_once(self):
        path=self.guide()
        self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.assertEqual(self.row()['status'],'guides_pending')
        self.assertEqual(json.loads(self.row()['input_manifest']),[])
        self.worker.tick();self.assertEqual(self.calls,[])
        self.click('use-guides');self.assertEqual(self.row()['status'],'guides_pending')
        self.bridge.flush(False)
        self.click('use-guides',user=8);self.assertEqual(self.row()['status'],'guides_pending')
        # Approval applies to the displayed saved version, not a later edit.
        path.write_text('A different guide after the card was made.')
        self.click('use-guides');self.click('use-guides');self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.calls),1)
        record=json.loads(self.row()['input_manifest'])[0]
        self.assertIn('Check floor',Path(record['path']).read_text())
        self.assertIn(record['path'],self.calls[0][1])
        self.assertEqual(self.row()['guide_decision'],'use-guides')

    def test_decline_or_cancel_never_applies_guide(self):
        self.guide()
        self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.bridge.flush(False);self.click('skip-guides');self.worker.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(json.loads(self.row()['input_manifest']),[])
        self.assertNotIn('REGISTERED INPUTS',self.calls[0][1])
        self.request({'kind':'route_task','task_id':'t1'},'Inspect solver room coverage.',ident=2)
        self.bridge.flush(False)
        row=self.row()
        self.bridge.process({'update_id':91,'callback_query':{'id':'c2','data':'route:'+row['token']+':cancel','from':{'id':7},'message':{'chat':{'id':7,'type':'private'}}}})
        self.worker.tick();self.assertEqual(len(self.calls),1)
        self.assertEqual(self.row()['status'],'cancelled')

    def test_destination_selection_precedes_guide_confirmation(self):
        self.guide()
        self.request({'kind':'choose_task','task_ids':['t0','t1']},'Inspect solver room coverage.')
        self.assertIsNone(self.row()['guide_proposal'])
        self.bridge.flush(False);self.click('1')
        self.assertEqual(self.row()['status'],'guides_pending')
        self.click('use-guides');self.worker.tick();self.assertEqual(self.calls,[])
        self.assertIsNone(task_routing.controls(self.state,'orchestrator:1'))
        self.bridge.flush(False);self.click('use-guides');self.worker.tick()
        self.assertEqual(self.calls[0][0],'t1')

    def test_shared_codex_delegate_has_guide_buttons(self):
        self.guide()
        self.request({'kind':'delegate_task','task_id':'t0','provider':'codex','required_capabilities':['file_read']},'Inspect solver room coverage.')
        self.assertEqual(self.row()['status'],'guides_pending')
        controls=task_routing.controls(self.state,'capability-request:1')
        self.assertEqual(controls['inline_keyboard'][0][0]['text'],'Use guides')
        self.bridge.flush(False);self.click('use-guides');self.worker.tick()
        self.assertEqual(len(self.calls),1)

    def test_select_one_of_multiple_guides_and_ask_again_next_time(self):
        self.guide()
        self.guide('docs/solver-style-guide.md','# Solver style\nNaming rules for solver code.')
        self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        proposal=json.loads(self.row()['guide_proposal'])['guides']
        self.assertEqual(len(proposal),2)
        self.bridge.flush(False);self.click('guide-1');self.worker.tick()
        manifest=json.loads(self.row()['input_manifest'])
        self.assertEqual([d['name'] for d in manifest],[proposal[1]['name']])
        self.request({'kind':'route_task','task_id':'t1'},'Inspect solver room coverage.',ident=2)
        self.assertEqual(self.row()['status'],'guides_pending')
        manifest=json.loads(self.row()['input_manifest'])
        self.assertEqual([d for d in manifest if d['role']=='project guide'],[])
        self.assertEqual([d['role'] for d in manifest],['conversation context and drafts'])

    def test_pending_guide_reserves_only_its_task_until_expiry(self):
        self.guide();self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.assertIn('guide choice',task_routing.task_conflict(self.state,'t0'))
        self.assertIsNone(task_routing.task_conflict(self.state,'t1'))
        with self.state.db:self.state.put('selected','t0')
        self.bridge.submit_text({},'yes',80,7)
        self.assertEqual(self.calls,[])
        self.assertIn('guide choice',self.telegram.sent[-1][1])
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=0')
        self.assertIsNone(task_routing.task_conflict(self.state,'t0'))

    def test_expiry_and_changed_destination_stop_approval(self):
        self.guide();self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.bridge.flush(False)
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=0')
        self.click('use-guides');self.worker.tick();self.assertEqual(self.calls,[])
        with self.state.db:self.state.db.execute('UPDATE task_routes SET expires=9999999999')
        Path(self.tasks[0]['rollout_path']).write_text('changed')
        self.click('use-guides');self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.row()['status'],'guides_pending')

    def test_tampered_proposal_cannot_be_approved(self):
        self.guide();self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.bridge.flush(False)
        path=Path(json.loads(self.row()['guide_proposal'])['guides'][0]['path'])
        path.chmod(0o600);path.write_text('tampered')
        self.click('use-guides');self.worker.tick();self.assertEqual(self.calls,[])
        self.assertEqual(self.row()['status'],'guides_pending')

    def test_native_instructions_and_private_or_symlink_guides_are_not_optional_candidates(self):
        self.guide('AGENTS.md','# Solver instructions')
        self.guide('private/solver-guide.md')
        self.guide('outputs/solver-guide.md')
        source=self.guide('source.md')
        (self.root/'solver-guide.md').symlink_to(source)
        result=guide_discovery.discover(str(self.root),'Inspect solver room coverage.')
        self.assertEqual(result['guides'],[])
        self.assertTrue(result['warnings'])

    def test_incomplete_search_is_disclosed_and_does_not_silently_dispatch(self):
        with patch('guide_discovery.os.walk',return_value=[(str(self.root),[],['file']*5001)]):
            self.request({'kind':'route_task','task_id':'t0'},'Inspect solver room coverage.')
        self.assertEqual(self.row()['status'],'guides_pending')
        self.worker.tick();self.assertEqual(self.calls,[])
        snapshot=orchestrator_chat.snapshot(self.state,None)['routed_requests'][0]
        self.assertTrue(snapshot['guide_search_warnings'])
        self.assertFalse(snapshot['inputs_sent'])


if __name__=='__main__':unittest.main()
