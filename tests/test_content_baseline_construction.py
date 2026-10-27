"""Shared exact baseline construction with controlled text records only."""
import copy,json,unittest
from pathlib import Path
from orchestrator import owner_intents,sourcing_contract,operation_contracts
from orchestrator.runtime import Runtime
from tests import test_owner_intents as owner,test_sourcing_records as records
from tests.test_browser_fallback_lifecycle import retain_evidence

class Baselines(unittest.TestCase):
    create=owner.Tests.create;source=owner.Tests.source;session=owner.Tests.session
    invoke=owner.Tests.invoke;run_worker=owner.Tests.run_worker;tearDown=retain_evidence
    def setUp(self):
        owner.Tests.setUp(self)
        self.helper=records.Tests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        base=self.helper.complete_catalog();base['contract']['id']='collection.options'
        self.params=dict(options_per_item=3,count_policy='target',max_records=2,
            field_definitions={k:'price' if k=='price' else 'text' for k in sourcing_contract.FIELDS},identity_field='name_variant')
        base['parameters'].update(self.params);self.base=base
        self.inv=self.source((self.helper.root/'inventory.json').read_text(),'inventory.json','application/json')
        self.pack=self.source((self.helper.root/'sources.json').read_text(),'sources.json','application/json')
        self.old=self.source(operation_contracts.encoded(base)+'\n','old.json','application/json')
        newer=copy.deepcopy(base);newer['items'][1]['gap']='New retained gap';newer['records'][1]['gap']='New retained gap'
        self.new=self.source(operation_contracts.encoded(newer)+'\n','new.json','application/json')
        # A confirmed controlled upstream capture; no real network transport.
        a=self.rt.artifact(self.pack['artifact']);receipt=dict(status='finished',operation=dict(output_sha256=a['sha256'],validation=dict(fetched=1)))
        self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',('capture','prior','sources','prior','completed',None,json.dumps(dict(execution=dict(capability='web.sources'))),'{}',json.dumps(receipt),None))
        self.rt.db.execute('UPDATE production_artifacts SET attempt=?,path=? WHERE id=?',('capture','delivery/source-pack.json',a['id']))
        self.grant.update(delegation_version=4,coordination_version=1,owner_progress_version=1)
        self.grant['task_limits'].update(tool_calls=24,provider_requests=24,output_bytes=3000000)
        self.create(inputs=[self.inv,self.pack,self.old,self.new]);self.rt.tick('job')
    def args(self,placement='inside'):
        t=dict(id='repair',objective='Correct the chosen saved record',inputs=[{'artifact':self.old['artifact']},{'artifact':self.new['artifact']},{'artifact':self.pack['artifact']}],
            content=dict(family='collection.options',sources=dict(inventory_path={'artifact':self.inv['artifact']},source_pack_path={'artifact':self.pack['artifact']}),parameters=copy.deepcopy(self.params)))
        if placement=='inside':t['content']['baseline']={'artifact':self.new['artifact']}
        elif placement=='outside':t['baseline']={'artifact':self.new['artifact']}
        return dict(request_id='repair',tasks=[t])
    def test_omitted_parameters_inherit_exact_baseline_before_workload_and_review(self):
        args=self.args();args['tasks'][0]['content'].pop('parameters')
        original=copy.deepcopy(args);receipt=self.session().delegate(args)
        spec=self.rt.spec(self.rt.task('job','repair'));params=spec['operation_contract']['parameters']
        self.assertEqual({k:params[k] for k in self.params},self.params)
        self.assertEqual(params['base_catalog_path'],next(i['path'] for i in spec['inputs'] if i.get('artifact')==self.new['artifact']))
        self.assertEqual(spec['limits'],self.grant['task_limits']);self.assertEqual(args,original)
        self.assertTrue(any(self.rt.spec(t).get('review_of')=='repair' for t in self.rt.status('job')['tasks']))
        events=[json.loads(r[0]) for r in self.rt.db.execute("select data from production_events where kind='owner_compilation_evidence'")]
        self.assertIn('inherited_parameters',json.dumps(events));self.assertNotIn('selection_policy',params)

    def test_named_correction_graph_inherits_baseline_and_survives_reload(self):
        from orchestrator import node_spec
        node=dict(schema_version=3,id='repair',objective='Correct the exact catalog',operation='collection.options',inputs={
            'inventory_path':{'artifact':self.inv['artifact']},'source_pack_path':{'artifact':self.pack['artifact']},
            'baseline':{'artifact':self.new['artifact']},'parameters':{'value':{'options_per_item':3}}})
        saved=json.dumps(node_spec.capture(node),sort_keys=True)
        node=node_spec.check_capture(json.loads(saved))
        session=self.session()
        args=node_spec.legacy_tasks({'tasks':[node]},3,self.grant,artifact=lambda ident:owner_intents.artifact_descriptor(session,ident))
        session.delegate(dict(request_id='named-repair',**args))
        before=self.rt.spec(self.rt.task('job','repair'))
        self.assertEqual({k:before['operation_contract']['parameters'][k] for k in self.params},self.params)
        self.assertEqual(before['limits'],self.grant['task_limits'])
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.assertEqual(self.rt.spec(self.rt.task('job','repair')),before)
        self.assertEqual(node_spec.check_capture(json.loads(saved)),node)

    def test_matching_subset_inherits_rest_but_every_conflict_commits_nothing(self):
        for key,bad in [('max_records',1),('identity_field','name'),('field_definitions',{'name':'text'}),('selection_policy','visual'),('invented',1)]:
            args=self.args();args['tasks'][0]['content']['parameters']={key:bad}
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'preserve baseline semantic'):
                self.session().delegate(args)
            self.assertEqual(len(self.rt.status('job')['tasks']),1)
        args=self.args();args['tasks'][0]['content']['parameters']={'options_per_item':3}
        self.session().delegate(args)
        p=self.rt.spec(self.rt.task('job','repair'))['operation_contract']['parameters']
        self.assertEqual({k:p[k] for k in self.params},self.params)

    def test_numerically_equal_but_wrongly_typed_choices_reject_without_admission(self):
        for key,value in [('max_records',2.0),('options_per_item',3.0),('max_records',True)]:
            args=self.args();args['tasks'][0]['content']['parameters']={key:value}
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'semantic parameter types'):
                self.session().delegate(args)
            self.assertEqual(len(self.rt.status('job')['tasks']),1)

    def test_no_baseline_missing_choices_and_ambiguous_baselines_never_inherit(self):
        args=self.args('none');args['tasks'][0]['content'].pop('parameters')
        with self.assertRaisesRegex(ValueError,'content.baseline'):self.session().delegate(args)
        args['tasks'][0]['inputs']=[{'artifact':self.pack['artifact']}]
        with self.assertRaisesRegex(ValueError,'content choices'):self.session().delegate(args)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)

    def test_registry_added_parameter_is_inherited_without_another_manual_mapping(self):
        from unittest.mock import patch
        from orchestrator.record_lifecycle import inherit_parameters
        family=copy.deepcopy(operation_contracts.identity({'id':'collection.options','version':1}))
        family['planning_interface']['schema']['properties']['future_policy']={'type':'string'}
        family['planning_interface']['schema']['required'].append('future_policy')
        intent=dict(family={'id':'collection.options','version':1},parameters={})
        with patch('orchestrator.operation_contracts.identity',return_value=family):
            with self.assertRaisesRegex(ValueError,'baseline content choices'):inherit_parameters(intent,self.params)
            proof=inherit_parameters(intent,{**self.params,'future_policy':'preserved'})
        self.assertEqual(intent['parameters']['future_policy'],'preserved')
        self.assertEqual(proof['parameters_sha256'],operation_contracts.digest(intent['parameters']))

    def test_explicit_baseline_drives_worker_review_restart_and_raw_intent(self):
        args=self.args('outside');original=copy.deepcopy(args);s=self.session();receipt=s.delegate(args)
        self.assertEqual(args,original);self.assertEqual(s.delegate(args),receipt)
        self.rt.tick('job');spec=self.rt.spec(self.rt.task('job','repair'));p=spec['operation_contract']['parameters']
        self.assertEqual(next(i['artifact'] for i in spec['inputs'] if i['path']==p['base_catalog_path']),self.new['artifact'])
        self.assertEqual(spec['limits'],self.grant['task_limits'])
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        self.run_worker('repair',lambda f:[('source_find',dict(observation='',query='Walnut desk',offset=0,limit=20)),('operation_amend',dict(request_key='fix',revision=0,expected_record_sha256=operation_contracts.digest(self.base['records'][0]),record=dict(item='item-a',options=[],gap='Unsupported variant removed after comparison; preserve source.')))])
        aid=self.rt.task('job','repair')['latest'];artifact=self.rt.output('job','repair','outputs/result.json');value=json.loads(Path(artifact['blob']).read_text())
        self.assertEqual(value['items'][0]['options'],[])
        self.assertEqual(json.loads(Path(self.rt.artifact(self.old['artifact'])['blob']).read_text()),self.base)
        reviewer=next(t['id'] for t in self.rt.status('job')['tasks'] if t['id'].startswith('repair_review'))
        rf=self.factory.sessions[self.rt.task('job',reviewer)['latest']]['frozen'];ctx=sourcing_contract.context(rf,lambda p:(Path(rf['workspace'])/p).read_bytes())
        self.assertEqual(ctx['catalog_sha256'],artifact['sha256'])
        judgments=[dict(item=k,item_sha256=operation_contracts.digest(v),verdict='supported',reason='Exact corrected fixture and retained sources checked') for k,v in ctx['items'].items()]
        self.run_worker(reviewer,lambda f:[('file_read',dict(path=f['operation_contract']['parameters']['catalog_path'],offset=0,limit=24000))]+[('operation_submit',dict(request_key='review-'+str(n),revision=n,records=[v])) for n,v in enumerate(judgments)],decision='accept')
        self.assertEqual(self.rt.task('job','repair')['status'],'completed')
        event=json.loads(self.rt.db.execute("select data from production_events where kind='owner_intents_compiled'").fetchone()[0]);self.assertEqual(event['intent'],original)
        self.assertEqual(self.factory.calls.count(aid),1)
        # A rejected review need not turn the collected candidate into a
        # scheduling dependency: baseline is an exact version, not a gate.
        self.rt.db.execute("UPDATE production_tasks SET status='awaiting_review' WHERE run='job' AND id='repair'")
        again=self.args();again['request_id']='again';t=again['tasks'][0];t['id']='repair_again'
        t['content']['baseline']={'task':'repair','output':'result'}
        # Carry the exact composed source emitted by that candidate.
        retained=self.rt.output('job','repair',p['source_pack_output'])
        t['inputs'].append({'artifact':retained['id']})
        self.session().delegate(again);spec=self.rt.spec(self.rt.task('job','repair_again'))
        self.assertNotIn('repair',spec['dependencies'])
        self.rt.tick('job');self.assertIn(self.rt.task('job','repair_again')['status'],('launching','running'))
    def test_explicit_and_implicit_selection_exclude_inherited_catalogs(self):
        args=self.args('none');args['tasks'][0]['inputs']=[{'artifact':self.new['artifact']},{'artifact':self.pack['artifact']}]
        task=owner_intents.compile(self.session(),args)[0]
        task['inputs'].append(copy.deepcopy(self.old)) # ancestor supplied by closure, not direct intent
        task['limits']=copy.deepcopy(self.grant['task_limits'])
        receipt=sourcing_contract.prepare_recovery(task,self.session())
        self.assertEqual(receipt['baseline'],self.new['artifact'])
    def test_ambiguous_direct_candidates_reject_without_admission(self):
        with self.assertRaisesRegex(ValueError,'content.baseline'):self.session().delegate(self.args('none'))
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
    def test_conflicting_and_incompatible_explicit_choices_never_fall_back(self):
        args=self.args();args['tasks'][0]['baseline']={'artifact':self.old['artifact']}
        with self.assertRaisesRegex(ValueError,'conflicting baseline'):self.session().delegate(args)
        args=self.args();args['tasks'][0]['content']['baseline']={'artifact':self.inv['artifact']}
        with self.assertRaisesRegex(ValueError,'not a compatible sealed'):self.session().delegate(args)
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
    def test_pending_and_uncertain_baselines_reject(self):
        args=self.args();args['tasks'][0]['content']['baseline']={'task':'repair','output':'result'}
        with self.assertRaisesRegex(ValueError,'completed collected'):self.session().delegate(args)
        a=self.rt.artifact(self.new['artifact']);self.rt.db.execute('INSERT INTO production_attempts VALUES (?,?,?,?,?,?,?,?,?,?)',('unknown','prior','baseline','prior','uncertain',None,'{}','{}',None,'Unknown effect'))
        self.rt.db.execute('UPDATE production_artifacts SET attempt=? WHERE id=?',('unknown',a['id']))
        with self.assertRaisesRegex(ValueError,'active or uncertain'):self.session().delegate(self.args())
    def test_semantic_scope_and_missing_grant_reject(self):
        args=self.args();args['tasks'][0]['content']['parameters']['options_per_item']=4
        with self.assertRaisesRegex(ValueError,'preserve baseline semantic'):self.session().delegate(args)
        s=self.session();s.grant.pop('coordination_version')
        with self.assertRaisesRegex(ValueError,'granted registered recovery'):owner_intents.compile(s,self.args())
    def test_wire_declarations_match_both_placements_and_catalog(self):
        from orchestrator.parameter_contracts import validate
        for placement in ('inside','outside'):
            args=self.args(placement);validate(args,owner_intents.delegation_schema(4),'wire');owner_intents.validate_delegation(args,4)
        value=owner_intents.catalog(self.grant,[],True);self.assertIn('baseline',value['content']['collection.options'])
        self.assertNotIn('baseline',value['content']['collection.subjects'])
        with self.assertRaises(ValueError):owner_intents.validate_delegation(self.args(),3)
    def test_tampered_baseline_and_forged_compiler_selection_commit_nothing(self):
        args=self.args();args['tasks'][0]['record_recovery_selection']={'baseline':self.old}
        with self.assertRaises(ValueError):self.session().delegate(args)
        a=self.rt.artifact(self.new['artifact']);p=Path(a['blob']);p.chmod(0o600);p.write_text('{}')
        with self.assertRaisesRegex(ValueError,'bytes changed'):self.session().delegate(self.args())
        self.assertEqual(len(self.rt.status('job')['tasks']),1)
    def test_equal_bytes_different_identities_still_require_a_choice(self):
        # Two independently registered equal catalogs must not silently collapse.
        old=self.rt.artifact(self.old['artifact']);new=self.rt.artifact(self.new['artifact'])
        self.rt.db.execute('UPDATE production_artifacts SET blob=?,sha256=?,bytes=? WHERE id=?',(old['blob'],old['sha256'],old['bytes'],new['id']))
        with self.assertRaisesRegex(ValueError,'content.baseline'):self.session().delegate(self.args('none'))
        receipt=self.session().delegate(self.args());self.assertIn('repair',receipt['queued'])

if __name__=='__main__':unittest.main()
