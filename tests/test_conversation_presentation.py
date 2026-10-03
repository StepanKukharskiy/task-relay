"""Receipt-backed answer presentation and honest, non-authorizing claim evidence."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from task_relay import orchestrator_advice as advice, orchestrator_chat as chat, desktop_workspace, desktop_plans
from tests import test_shared_orchestrator as fixture


class EvidenceTests(unittest.TestCase):
    def test_claim_states_come_from_observed_pages_without_a_verified_verdict(self):
        evidence={'sources':[{'url':'https://docs.example/read','kind':'page'},
                             {'url':'https://docs.example/search','kind':'search_result'}],'partial':False}
        def claim(urls):return {'statement':'A controller can display text.','source_urls':urls}
        values=[claim([]),claim(['https://docs.example/read']),claim(['https://docs.example/search']),
                claim(['https://docs.example/invented']),{'statement':'A different claim.','source_urls':['https://docs.example/read']},
                {**claim(['https://docs.example/read']),'state':'verified'}]
        result=advice.claim_evidence(values,'A controller can display text.',evidence)
        self.assertEqual([r['state'] for r in result],['generated','page_linked','search_reference','unresolved','unresolved'])
        self.assertEqual(result[3]['source_urls'],[])
        self.assertFalse(result[4]['matches_answer'])
        self.assertEqual(advice.source_summary(None,evidence)['state'],'pages_read')
        # Losing the hash-checked read must downgrade a previously linked claim.
        missing={'sources':[],'partial':True}
        self.assertEqual(advice.claim_evidence([values[1]],'A controller can display text.',missing)[0]['state'],'unresolved')
        self.assertEqual(advice.source_summary(None,missing)['label'],'Sources: incomplete')

    def test_source_status_and_compact_options_never_promote_search_to_verification(self):
        evidence={'sources':[{'url':'https://docs.example/search','kind':'search_result'}],'partial':False}
        text=advice.render(fixture.REPLY['research_advice'],evidence)
        self.assertIn('Sources: search references only',text)
        self.assertNotIn('Research is optional',text)
        self.assertNotIn('Questions for source checking',text)
        self.assertIn('Want to take this further?',advice.render_options(fixture.OPTIONS))
        self.assertNotIn('Next options Relay can help',advice.render_options(fixture.OPTIONS))
        definition=advice.response_definition(fixture.REQUEST,advice.option_tools({'snapshot':{'capabilities':fixture.CATALOG}}))
        self.assertEqual(set(definition['parameters']['properties']['claim_sources']['items']['properties']),{'statement','source_urls'})


class PresentationTests(unittest.TestCase):
    setUp=fixture.SharedTests.setUp
    create_conversation=fixture.SharedTests.create_conversation

    def answer(self,fail_notice=False):
        self.create_conversation()
        with patch.object(chat,'provider',return_value=('gemini','fixture')):desktop_plans.process_requests(self.state)
        value=copy.deepcopy(fixture.REPLY)
        value['claim_sources']=[{'statement':'A small controller could provide a fun interface for an external assistant.','source_urls':[]}]
        raw=json.dumps(value)
        with patch.object(chat,'snapshot',return_value={'capabilities':fixture.CATALOG,'production_runs':[],'codex_tasks':[],'uploaded_files':[]}), patch.object(chat.gemini,'DATA',self.paths.data), patch.object(chat.gemini,'read_config',return_value={'api_key':'fixture'}), patch.object(chat.gemini,'Client') as client:
            client.return_value.request.return_value={'candidates':[{'content':{'parts':[{'text':raw}]}}]}
            if fail_notice:
                original_notice=chat.queue_notice
                notices=0
                def notice(*args):
                    nonlocal notices
                    notices+=1
                    if notices==1:raise RuntimeError('Controlled outbox failure')
                    return original_notice(*args)
                with patch.object(chat,'queue_notice',side_effect=notice):chat.Worker(self.state).tick()
                self.assertEqual(notices,2)
            else:chat.Worker(self.state).tick()
            client.return_value.request.assert_called_once()
        return value,raw,dict(self.state.db.execute('SELECT * FROM orchestrator_chats').fetchone())

    def test_compact_answer_and_projection_are_atomic_without_execution(self):
        value,raw,row=self.answer()
        self.assertEqual(row['status'],'answered',row['answer'])
        self.assertEqual(row['response'],raw);self.assertEqual(row['prompt'],fixture.REQUEST)
        self.assertIn('Want to take this further?',row['answer']);self.assertIn('Sources: not checked yet',row['answer'])
        self.assertNotIn('Research is optional',row['answer'])
        view=desktop_workspace.chat_detail(str(row['id']),self.paths)
        self.assertEqual(view['answer'],row['answer']);self.assertEqual(view['display_answer'],value['answer'])
        self.assertEqual(view['next_options'],fixture.OPTIONS);self.assertEqual(view['claims'][0]['state'],'generated')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM capability_dispatches').fetchone()[0],0)
        receipt=self.state.get('orchestrator-presentation:'+str(row['id']))
        self.assertEqual(receipt['response_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        with self.state.db:
            receipt['answer_sha256']='changed';receipt['body']='Unproven body';self.state.put('orchestrator-presentation:'+str(row['id']),receipt)
        self.assertEqual(desktop_workspace.chat_detail(str(row['id']),self.paths)['display_answer'],row['answer'])

    def test_outbox_failure_does_not_commit_a_presentation_or_replay(self):
        value,raw,row=self.answer(fail_notice=True)
        self.assertEqual(row['status'],'failed')
        self.assertIsNone(self.state.get('orchestrator-presentation:'+str(row['id'])))
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1,'Only the failure notice commits after rollback')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_plans').fetchone()[0],0)

    def test_legacy_suffix_requires_complete_identity_and_retains_exact_saved_reply(self):
        value=copy.deepcopy(fixture.REPLY);value['answer']='A plain answer with a literal heading:\nNext options Relay can help with:'
        evidence={'sources':[],'partial':False}
        exact=value['answer']+advice.legacy_render_options(value['next_options'])+advice.legacy_render(value['research_advice'],evidence)
        with self.state.db:
            self.state.db.execute("INSERT INTO orchestrator_chats(id,prompt,provider,model,created,status,response,answer) VALUES (1,?,'gemini','fixture',1,'answered',?,?)",(fixture.REQUEST,json.dumps(value),exact))
        view=desktop_workspace.chat_detail('1',self.paths)
        self.assertEqual(view['answer'],exact);self.assertEqual(view['display_answer'],value['answer'])
        with self.state.db:self.state.db.execute('UPDATE orchestrator_chats SET answer=? WHERE id=1',(exact+'\nAnother saved line.',))
        changed=desktop_workspace.chat_detail('1',self.paths)
        self.assertEqual(changed['display_answer'],changed['answer'])
