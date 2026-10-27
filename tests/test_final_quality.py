import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from orchestrator import contracts as c,final_quality as quality,report_builder
from orchestrator.runtime import Runtime
from tests import intake_fixtures as intake,test_operation_session as loop
from tests.test_orchestrator import pair,FakeFactory

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.graph=pair();self.contract=intake.work([intake.outcome('result',format='.txt')])
        quality.bind(self.graph,{'result':dict(task='produce',output='output.txt')},self.contract,target_gaps=True)
        self.review=copy.deepcopy(self.graph['tasks'][1]);c.plan(self.graph)
        (self.root/'candidate.txt').write_text('Reference: terracotta textured fabric. Option: gray smooth fabric. {"@context":"https://schema.org"}')
        self.review.update(assignment_id='fixture',workspace=str(self.root))
        self.review['inputs'][0].update(artifact='candidate',sha256=hashlib.sha256((self.root/'candidate.txt').read_bytes()).hexdigest())
        self.review['report_contract']=report_builder.freeze(self.review)

    def evidence(self,frozen=None,defect=None):
        frozen=frozen or self.review;candidate=next(iter(frozen['final_quality']['checks'].values()))['candidate']
        return {dimension:dict(verdict='defect' if dimension==defect else 'satisfied',
            reason=('Gray smooth material contradicts the terracotta textured reference' if dimension==defect else 'Inspected the exact candidate against the requested outcome'),
            inspected=[dict(path=candidate,location='Item 1, field and final displayed text')]) for dimension in quality.DIMENSIONS}

    def report(self,frozen=None,defect=None,decision='accept',passed=True):
        frozen=frozen or self.review
        return dict(summary='Reviewed exact candidate',decision=decision,instruction='Replace unsuitable option and remove raw source payload' if decision=='revise' else '',findings=[],
            checks={'c1':dict(passed=True,evidence='File contains text'),
                    'c2':dict(passed=passed,evidence=self.evidence(frozen,defect))})

    def test_defects_cannot_be_passed_or_disguised_as_advisories(self):
        for dimension in quality.DIMENSIONS:
            with self.subTest(dimension=dimension):
                raw=self.report(defect=dimension);raw['findings']=[dict(category='advisory',code='disclosed',message='Difference is disclosed',evidence='Candidate')]
                with self.assertRaisesRegex(ValueError,'defects require'):
                    c.report(report_builder.build(raw,self.review),self.review)
                correction=self.report(defect=dimension,decision='revise',passed=False)
                self.assertEqual(c.report(report_builder.build(correction,self.review),self.review)['decision'],'revise')

    def test_missing_dimensions_foreign_paths_and_changed_versions_reject_acceptance(self):
        for change in ('dimension','path','bytes'):
            with self.subTest(change=change):
                raw=self.report()
                if change=='dimension':del raw['checks']['c2']['evidence']['usability']
                elif change=='path':raw['checks']['c2']['evidence']['evidence']['inspected'][0]['path']='unbound-source.txt'
                else:(self.root/'candidate.txt').write_text('A different candidate')
                with self.assertRaises(ValueError):c.report(report_builder.build(raw,self.review),self.review)

    def test_explicit_target_gap_is_permitted_without_weakening_fit_or_usability(self):
        raw=self.report();raw['checks']['c2']['evidence']['requirements']['verdict']='disclosed_gap'
        self.assertEqual(c.report(report_builder.build(raw,self.review),self.review)['decision'],'accept')
        for dimension in ('reference_fit','evidence','usability'):
            invalid=copy.deepcopy(raw);invalid['checks']['c2']['evidence'][dimension]['verdict']='disclosed_gap'
            with self.assertRaises(ValueError):report_builder.build(invalid,self.review)
        self.review['final_quality']['checks']['2']['target_gaps']=False;self.review['report_contract']=report_builder.freeze(self.review)
        with self.assertRaises(ValueError):report_builder.build(raw,self.review)

    def test_visual_fit_requires_declared_reference_and_actual_candidate(self):
        (self.root/'reference.txt').write_text('Terracotta, strong texture')
        self.review['inputs'].append(dict(path='reference.txt',artifact='reference',sha256=hashlib.sha256((self.root/'reference.txt').read_bytes()).hexdigest(),visual_reference=True))
        self.review['final_quality']['checks']['2']['reference_required']=True;self.review['report_contract']=report_builder.freeze(self.review)
        raw=self.report()
        with self.assertRaisesRegex(ValueError,'supplied visual reference'):c.report(report_builder.build(raw,self.review),self.review)
        raw['checks']['c2']['evidence']['reference_fit']['inspected'].append(dict(path='reference.txt',location='Original item 1'))
        self.assertEqual(c.report(report_builder.build(raw,self.review),self.review)['decision'],'accept')
        raw['checks']['c2']['evidence']['usability']['inspected']=[dict(path='reference.txt',location='Source')]
        with self.assertRaisesRegex(ValueError,'actual delivered candidate'):c.report(report_builder.build(raw,self.review),self.review)

    def test_registered_inspection_evidence_cannot_be_skipped_or_swapped(self):
        (self.root/'preview.txt').write_text('Exact rendered page observations')
        self.review['inputs'].append(dict(path='preview.txt',artifact='preview',sha256=hashlib.sha256((self.root/'preview.txt').read_bytes()).hexdigest()))
        self.review['final_quality']['checks']['2']['inspection_inputs']=['preview.txt']
        self.review['report_contract']=report_builder.freeze(self.review)
        raw=self.report()
        with self.assertRaisesRegex(ValueError,'registered review evidence'):c.report(report_builder.build(raw,self.review),self.review)
        raw['checks']['c2']['evidence']['usability']['inspected'].append(dict(path='preview.txt',location='Page 1'))
        self.assertEqual(c.report(report_builder.build(raw,self.review),self.review)['decision'],'accept')
        (self.root/'preview.txt').write_text('A preview of another version')
        with self.assertRaisesRegex(ValueError,'frozen version'):c.report(report_builder.build(raw,self.review),self.review)

    def test_actual_worker_rejects_false_pass_then_corrects_current_version_through_controller(self):
        graph=copy.deepcopy(self.graph);graph['backend']=dict(type='gemini-agent',model='fixture')
        for task in graph['tasks']:task.update(tools=['files'],limits=dict(seconds=600,tool_calls=6,provider_requests=6,output_bytes=200000))
        factory=FakeFactory();rt=Runtime(self.root/'runtime',factory);self.addCleanup(rt.db.close);rt.create(graph)
        f=SimpleNamespace(rt=rt,factory=factory);helper=loop.Tests()
        delivered=dict(summary='Candidate written',decision='delivered',instruction='',findings=[],checks={'c1':dict(passed=True,evidence='Output written')})
        rt.tick('demo');first=rt.task('demo','produce')['latest']
        helper.run_worker(f,first,loop.Script([('file_write',dict(path='output.txt',text='Gray option; raw JSON-LD leaked into the client text')),('finish',dict(report_json=json.dumps(delivered)))]))
        rt.tick('demo');review=rt.task('demo','review')['latest'];frozen=factory.sessions[review]['frozen']
        bad=self.report(frozen,defect='usability');good=self.report(frozen,defect='usability',decision='revise',passed=False)
        result,control=helper.run_worker(f,review,loop.Script([('finish',dict(report_json=json.dumps(bad))),('finish',dict(report_json=json.dumps(good)))]))
        self.assertEqual(result['decision'],'revise');rt.tick('demo')
        self.assertNotEqual(rt.task('demo','produce')['status'],'completed')
        # Restart the persistent owner between rejection and corrected delivery.
        rt=Runtime(rt.root,factory,connection=rt.db);f.rt=rt
        second=rt.task('demo','produce')['latest'];self.assertNotEqual(first,second)
        helper.run_worker(f,second,loop.Script([('file_write',dict(path='output.txt',text='Terracotta textured alternative. Current price unknown, explicitly labeled.')),('finish',dict(report_json=json.dumps(delivered)))]))
        rt.tick('demo');review2=rt.task('demo','review')['latest'];frozen2=factory.sessions[review2]['frozen']
        self.assertEqual(frozen2['review_target'],second)
        result,_=helper.run_worker(f,review2,loop.Script([('finish',dict(report_json=json.dumps(self.report(frozen2))))]))
        self.assertEqual(result['decision'],'accept');self.assertEqual(rt.tick('demo')['status'],'completed')
        self.assertEqual(rt.task('demo','produce')['attempts'],2)
        self.assertEqual(rt.task('demo','review')['attempts'],2)
