import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator.evidence_workload import review_batches,record_cost,item_evidence
from orchestrator.source_fallback import collect,candidates
from orchestrator.browser_context import Archive
from task_relay.source_batches import bind_fallback


def page(url,text,sha='a'):
    return dict(url=url,requested_url=url,title='Candidate',text=text,sha256=sha*64,retrieved_at=1,content_type='text/html',total_characters=len(text),next_offset=None)

def pack(entries):return dict(version=1,kind='public_source_candidates',entries=entries,interpretation='Candidates only')

class Tests(unittest.TestCase):
    def test_workload_preserves_every_text_version_and_exact_offsets(self):
        a=page('https://shop.example/products/a','price $120\n'*24000)
        b=page(a['url'],'Updated price $125','b')
        source=pack([dict(query='a',target_ids=['A'],pages=[a,a,b])]);old=copy.deepcopy(source)
        cost=review_batches(source,8);self.assertLessEqual(cost['required_tool_calls'],8)
        self.assertEqual(cost['pages'],2);self.assertEqual(cost['aliases'],[dict(observation='page-0-1',duplicate_of='page-0-0')])
        rebuilt={}
        for batch in cost['batches']:
            for part in batch:
                original=a if part['observation']=='page-0-0' else b
                self.assertEqual(part['text'],original['text'][part['offset']:part['end']])
                rebuilt.setdefault(part['observation'],[]).append(part['text'])
        self.assertEqual(''.join(rebuilt['page-0-0']),a['text']);self.assertEqual(''.join(rebuilt['page-0-2']),b['text']);self.assertEqual(source,old)
        self.assertEqual(record_cost(10,10)['tool_calls'],23);self.assertEqual(record_cost(2)['tool_calls'],5)

    def test_item_windows_preserve_price_offsets_and_disclose_missing_mapping(self):
        text='Navigation '*300+'Chair $125; width 24 inches; US shipping.'
        ctx=dict(observations={'p1':dict(url='https://shop.example/p/chair',text=text)},observation_targets={'p1':['A']})
        value=item_evidence(ctx,'A');self.assertTrue(value['pages']);self.assertLessEqual(value['excerpt_characters'],12000)
        prices=[span for p in value['pages'] for excerpt in p['excerpts'] for span in excerpt['price_spans']]
        self.assertTrue(prices)
        for s in prices:self.assertEqual(text[s['start']:s['end']],s['text'])
        self.assertEqual(item_evidence(ctx,'B')['pages'],[])

    def test_old_file_and_source_results_are_archived_without_replay(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(Path(root));history=[]
            for name in ('file_read','sourcing_source_read'):
                for n in range(6):history.append(dict(role='user',parts=[dict(functionResponse=dict(name=name,id=str(n),response=dict(text='Price $125 '*1000,offset=n)))]))
            original=copy.deepcopy(history);view=archive.view(history)
            self.assertEqual(original,history);self.assertLess(len(json.dumps(view)),len(json.dumps(history))//3)
            ref=view[0]['parts'][0]['functionResponse']['response'];offset=0;chunks=[]
            while True:
                restored=archive.read(dict(evidence=ref['evidence'],offset=offset));chunks.append(restored['text'])
                if restored['next_offset'] is None:break
                offset=restored['next_offset']
            self.assertEqual(json.loads(''.join(chunks)),original[0]['parts'][0]['functionResponse']['response'])

    def test_rendered_fallback_preserves_source_and_keeps_failed_reads(self):
        source=pack([dict(query='chair',target_ids=['A'],pages=[],grounding=[dict(url='https://shop.example/products/a'),dict(url='https://shop.example/products/b'),dict(url='https://other.example/p/x')])])
        before=copy.deepcopy(source);calls=[]
        def renderer(url,domains,control):
            calls.append(url)
            if url.endswith('/a'):raise ValueError('Challenge; no product observed')
            return page(url,'Chair $125')
        with tempfile.TemporaryDirectory() as root:raw,validation=collect(source,['shop.example'],2,root,renderer)
        out=json.loads(raw);self.assertEqual(out['entries'][:1],before['entries']);self.assertEqual(source,before)
        self.assertEqual(calls,['https://shop.example/products/a','https://shop.example/products/b']);self.assertEqual({k:validation[k] for k in ('rendered','unavailable','search_requests','fetched')},dict(rendered=1,unavailable=1,search_requests=0,fetched=1));self.assertEqual(validation['eligible_remaining'],0)
        self.assertEqual(out['entries'][1]['errors'],['Challenge; no product observed']);self.assertEqual(out['entries'][2]['target_ids'],['A'])
        self.assertEqual(out['entries'][2]['pages'][0]['text'],'Chair $125')

    def test_duplicate_candidate_mappings_and_foreign_urls_are_not_lost(self):
        source=pack([dict(query=ident,target_ids=[ident],pages=[],grounding=[dict(url='https://shop.example/p/a'),dict(url='https://127.0.0.1/p/private')]) for ident in ('A','B')])
        selected=candidates(source,[]);self.assertEqual(len(selected),1);self.assertEqual(selected[0]['target_ids'],['A','B'])
        with tempfile.TemporaryDirectory() as root,self.assertRaisesRegex(ValueError,'1–12'):collect(source,[],13,root,lambda *_:self.fail('Must not render'))

    def test_compiler_wires_fallback_and_review_only_under_frozen_companion_scope(self):
        source=dict(id='source',execution=dict(capability='web.sources.prepared',parameters=dict(domains=['shop.example'])),outputs=[dict(path='delivery/source-pack.json')])
        review=dict(id='source_review',review_of='source',criteria=['Judge exact products'],inputs=[dict(from_task='source',output='delivery/source-pack.json',path='pages.json')],outputs=[dict(path='review.md')],dependencies=['source'])
        author=dict(id='catalog',inputs=[dict(from_task='source',output='delivery/source-pack.json')],dependencies=['source_review'],sourcing=dict(source_pack=dict(producer='source',output='delivery/source-pack.json')))
        proposal=dict(plan=dict(tasks=[source,review,author]),deliverable_map={'sources':dict(task='source',output='delivery/source-pack.json')})
        scope=dict(connector_companions_version=1,delivery_completion_policy_version=1,graph_operations=[dict(id='web.sources.prepared',companions={'web.sources.rendered':'observed-public-page-rendering-fallback'}),dict(id='web.sources.rendered',available=True,criteria=['Exact observed reads'],seconds=600)])
        options=dict(max_tasks=5,limits=dict(seconds=600,tool_calls=24,output_bytes=10000000))
        before=copy.deepcopy(proposal)
        self.assertEqual(bind_fallback(proposal,{},options),[]);self.assertEqual(before,proposal)
        self.assertEqual(len(bind_fallback(proposal,scope,options)),1);self.assertEqual(len(proposal['plan']['tasks']),5)
        self.assertEqual(author['inputs'][0]['from_task'],'source_rendered');self.assertEqual(author['sourcing']['source_pack']['producer'],'source_rendered')
        self.assertIn('source_rendered_review',author['dependencies']);self.assertEqual(proposal['deliverable_map']['sources']['task'],'source_rendered')
        self.assertEqual(bind_fallback(proposal,scope,options),[])

    def test_native_registered_fallback_exports_exact_pack_and_uncertain_reads_stay_held(self):
        from orchestrator import execution,step_runner
        from orchestrator.runtime import Runtime
        from orchestrator.adapters import RegisteredFactory
        from orchestrator.workers import atomic
        from tests.test_orchestrator import FakeFactory,pair
        source=pack([dict(query='chair',target_ids=['A'],pages=[],grounding=[dict(url='https://shop.example/p/chair')])])
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve();rt=Runtime(root/'runtime',FakeFactory());input_file=root/'source.json';input_file.write_text(json.dumps(source));aid=rt.register(input_file,'Synthetic observed candidates')
            graph=pair(max_attempts=1);task=graph['tasks'][0]
            task.update(execution=dict(capability='web.sources.rendered',version=1,parameters=dict(domains=['shop.example'],max_pages=1)),
                inputs=[dict(artifact=aid,path='source.json',purpose='Exact candidate fixture',authority='Unaccepted',media_type='application/json')],
                outputs=[dict(path='delivery/source-pack.json',purpose='Exact captures',media_type='application/json')],criteria=copy.deepcopy(execution.REGISTRY['web.sources.rendered']['criteria']),limits=dict(seconds=120,tool_calls=1,output_bytes=3000000))
            graph['tasks'][1]['inputs'][0].update(output='delivery/source-pack.json',media_type='application/json')
            graph['tasks'][1]['criteria']=copy.deepcopy(task['criteria'])
            rt.create(graph);rt.tick('demo');attempt=rt.db.execute('SELECT * FROM production_attempts').fetchone();frozen=json.loads(attempt['frozen']);control=root/'control';control.mkdir()
            with patch('task_relay.source_browser.render',return_value=page('https://shop.example/p/chair','Chair USD $125')) as renderer:
                details=step_runner.execute(frozen,control)
            self.assertEqual(renderer.call_count,1);self.assertEqual(details['outcome'],'completed')
            out=json.loads((Path(frozen['workspace'])/'delivery/source-pack.json').read_text());self.assertEqual(out['entries'][:1],source['entries']);self.assertEqual(out['entries'][1]['target_ids'],['A'])
            pending=control/'render-2';pending.mkdir();atomic(pending/'render-intent.json',dict(url='https://shop.example/p/other'))
            atomic(control/'done.json',dict(token=frozen['assignment_id'],exit_code=0,reason=None,usage=[]))
            observed=RegisteredFactory().inspect(dict(id=frozen['assignment_id'],control=str(control),execution=frozen['execution']))
            self.assertEqual(observed['status'],'uncertain');self.assertEqual(observed['pending_requests'],['render-2'])

    def test_render_receipt_grant_changes_do_not_replay_browser(self):
        from task_relay.source_browser import render
        from orchestrator.workers import atomic
        with tempfile.TemporaryDirectory() as root,patch('task_relay.orchestrator_web.public_addresses',return_value=['8.8.8.8']),patch('task_relay.source_browser.HOST.spawn') as spawn:
            root=Path(root);url='https://shop.example/p/chair';atomic(root/'render-intent.json',dict(url=url,domains=['shop.example'],seconds=45))
            with self.assertRaisesRegex(ValueError,'no confirmed outcome'):render(url,['shop.example'],root)
            atomic(root/'render-outcome.json',dict(requested_url=url,page=page(url,'Chair $125')))
            self.assertEqual(render(url,['shop.example'],root)['text'],'Chair $125')
            with self.assertRaisesRegex(ValueError,'grant changed'):render(url,[],root)
            spawn.assert_not_called()

    def test_infeasible_record_batch_is_rejected_before_worker_dispatch(self):
        from task_relay.sourcing_planning import budgets
        producer=dict(id='catalog',sourcing=dict(max_records=24,inventory=dict(source='inventory'),source_pack=dict(source='sources'),count_policy='target',options_per_item=1),limits=dict(tool_calls=6))
        plan=dict(backend=dict(type='gemini-agent',model='fixture'),tasks=[producer])
        with self.assertRaisesRegex(ValueError,'frozen allowance'):budgets(plan,2,dict(catalog=24))

    def test_unmapped_captures_remain_readable_without_claiming_correspondence(self):
        from orchestrator.sourcing_contract import source_read,tools
        from orchestrator.parameter_contracts import validate
        observations={'generic':dict(url='https://shop.example/p/chair',text='Candidate chair, $125 and width 24 inches.'),
                      'other':dict(url='https://shop.example/p/table',text='Mapped elsewhere $99')}
        ctx=dict(observations=observations,observation_targets={'generic':[],'other':['B']})
        original=copy.deepcopy(ctx);value=item_evidence(ctx,'A',maximum=80)
        self.assertEqual(value['mapped_pages'],0);self.assertEqual(value['unmapped_pages'],1)
        self.assertEqual([p['observation'] for p in value['pages']],['generic'])
        self.assertIn('independently assess',value['pages'][0]['correspondence'])
        self.assertEqual(ctx,original);self.assertLessEqual(value['excerpt_characters'],80)
        span=value['pages'][0]['excerpts'][0]['price_spans'][0]
        self.assertEqual(observations['generic']['text'][span['start']:span['end']],'$125')
        contract=dict(id='collection.options',version=1,parameters=dict(field_definitions={'name':'text'},identity_field='name',options_per_item=1,count_policy='target',max_records=1))
        declaration=next(t for t in tools(contract) if t['name']=='source_read')['parameters']
        args=dict(observation='generic',offset=0,limit=12000)
        validate(args,declaration,'read');self.assertEqual(source_read(ctx,args)['text'],observations['generic']['text'])
        with self.assertRaises(ValueError):validate(dict(args,limit=24000),declaration,'read')
        with self.assertRaisesRegex(ValueError,'1–12000'):source_read(ctx,dict(args,limit=24000))
        with self.assertRaisesRegex(ValueError,'not a URL'):source_read(ctx,dict(args,observation=observations['generic']['url']))
