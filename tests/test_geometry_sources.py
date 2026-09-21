import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from orchestrator import contracts as c, source_fidelity
from orchestrator.runtime import file_hash
from task_relay import geometry_sources, production_planning as planning, routing_inputs
from tests import test_production_planning as fixture
from tests.test_orchestrator import pair


class PlanningTests(unittest.TestCase):
    def setUp(self):
        fixture.Tests.setUp(self)
        del self.fail  # Shared routing fixture's flag shadows unittest.fail.
        app=patch('task_relay.host_apps.rhino',return_value=dict(available=True,executable='/fixture/rhino',evidence='fixture'))
        app.start();self.addCleanup(app.stop)
        self.source=self.root/'survey.dxf'
        self.source.write_text('0\nSECTION\n2\nENTITIES\n0\nPOINT\n5\nA1\n10\n2\n20\n3\n30\n4\n0\nENDSEC\n0\nEOF\n')

    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response
    click=fixture.Tests.click
    start=fixture.Tests.start

    def prepare(self,with_source=True):
        action=self.action(step_capabilities=['rhino.run_python'])
        action.update(project=str(self.root),project_files=['survey.dxf'] if with_source else [])
        row=self.queue(action=action,text='Build relief from survey.dxf. Do not replace the survey with a synthetic slope.')
        response=self.response();response['deferred_operations']={'rhino.run_python':'Prepare exact script/data first.'}
        producer,review=response['plan']['tasks']
        producer['outputs'].append({'path':'source-audit.json','purpose':'Extracted source geometry audit'})
        producer['selection_outputs']=[o['path'] for o in producer['outputs']]
        review['inputs'].append(dict(from_task='produce',output='source-audit.json',path='candidate-audit.json',purpose='Review extraction',authority='Unaccepted audit'))
        context=json.loads(row['context'])
        sources=[s for s in context['sources'] if s.get('project_file')]
        response['geometry_basis']=dict(mode='source_derived',kind='terrain',artifacts=[s['artifact'] for s in sources],
            checks=[dict(metric=k,tolerance=0 if k=='missing_source_entities' else .05,unit='count' if k=='missing_source_entities' else 'm')
                    for k in sorted(geometry_sources.TERRAIN_METRICS)])
        return row,response,sources

    def test_summary_only_or_missing_geometry_declaration_cannot_start(self):
        row,response,_=self.prepare(False)
        with self.assertRaisesRegex(ValueError,'original source'):
            planning.validate_result(json.dumps(response),row)
        response.pop('geometry_basis')
        with self.assertRaisesRegex(ValueError,'geometry_basis'):
            planning.validate_result(json.dumps(response),row)
        # A contract or the user-request snapshot cannot stand in for the DXF.
        source=json.loads(row['context'])['sources'][0]
        response['geometry_basis']=dict(mode='source_derived',artifacts=[source['artifact']],checks=[dict(metric='error',tolerance=0,unit='m')])
        with self.assertRaisesRegex(ValueError,'original source'):
            planning.validate_result(json.dumps(response),row)
        self.assertEqual(self.factory.calls,[])

    def test_exact_project_file_reaches_both_workers_and_generic_accept_is_blocked(self):
        row,response,sources=self.prepare();source=sources[0]
        original=self.source.read_bytes()
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.assertEqual(row['status'],'ready',row['error'])
        self.assertIn('contour_deviation ≤ 0.05 m',planning.preview(row))
        self.source.write_text('changed after proposal')
        self.start(row);self.rt.tick('production-1')
        author=self.rt.task('production-1','produce')['latest']
        self.factory.finish(author);self.rt.tick('production-1')
        reviewer=self.rt.task('production-1','review')['latest']
        for attempt in (author,reviewer):
            frozen=self.factory.sessions[attempt]['frozen']
            copied=Path(frozen['workspace'])/source['path']
            self.assertEqual(copied.read_bytes(),original)
            self.assertEqual(file_hash(copied),source['sha256'])
        self.factory.finish(reviewer,decision='accept');self.rt.tick('production-1')
        self.assertEqual(self.rt.task('production-1','review')['status'],'blocked')
        self.assertNotEqual(self.rt.task('production-1','produce')['status'],'awaiting_user')

    def test_selected_cad_cannot_be_reclassified_as_procedural(self):
        row,response,_=self.prepare()
        response['geometry_basis']=dict(mode='procedural',artifacts=[],checks=[])
        with self.assertRaisesRegex(ValueError,'Selected CAD sources'):
            planning.validate_result(json.dumps(response),row)

    def test_valid_preparation_audit_reaches_selection_without_native_execution(self):
        _,response,sources=self.prepare();source=sources[0]
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.start(row);self.rt.tick('production-1')
        self.factory.finish(self.rt.task('production-1','produce')['latest']);self.rt.tick('production-1')
        reviewer=self.rt.task('production-1','review')['latest']
        self.factory.finish(reviewer,decision='accept')
        frozen=self.factory.sessions[reviewer]['frozen']
        path=Path(frozen['workspace'])/'.relay/result.json';result=json.loads(path.read_text())
        result['checks'][-1]['evidence']=json.dumps(dict(sources=frozen['source_fidelity']['sources'],
            source_observations={source['artifact']:'Read DXF point handle A1 at (2,3,4). Audited source use; native execution deferred.'}))
        path.write_text(json.dumps(result));self.rt.tick('production-1')
        self.assertEqual(self.rt.task('production-1','produce')['status'],'awaiting_user')
        self.assertEqual(len(self.factory.calls),2)
        self.assertFalse(any(s['frozen'].get('execution') for s in self.factory.sessions.values()))

    def test_terrain_cannot_use_only_count_and_bounding_box_checks(self):
        row,response,_=self.prepare()
        response['geometry_basis']['checks']=[dict(metric='bounding_box',tolerance=.01,unit='m')]
        with self.assertRaisesRegex(ValueError,'Terrain review requires'):
            planning.validate_result(json.dumps(response),row)

    def test_changed_frozen_source_blocks_start_and_clarification_keeps_version(self):
        row,response,sources=self.prepare();source=sources[0]
        planning.Worker(self.state,lambda *_:(json.dumps(response),{})).tick()
        row=self.row();self.source.write_text('new source revision')
        child=self.queue(2,self.action(parent_id=row['id']),text='Retain the original survey version.')
        inherited=next(s for s in json.loads(child['context'])['sources'] if s['artifact']==source['artifact'])
        self.assertEqual(inherited['sha256'],source['sha256'])
        blob=Path(self.rt.artifact(source['artifact'])['blob']);blob.chmod(0o600);blob.write_text('tampered')
        self.start(row)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(self.factory.calls,[])

    def test_project_paths_reject_traversal_symlinks_private_files_and_overflow(self):
        project=str(self.root)
        for paths in (['../survey.dxf'],['/survey.dxf'],['.hidden.dxf'],['survey.dxf']*2):
            with self.subTest(paths=paths),self.assertRaises(ValueError):routing_inputs.validate_project_files(paths,project)
        with self.assertRaises(ValueError):routing_inputs.validate_project_files(['survey.dxf'],None)
        link=self.root/'linked.dxf';link.symlink_to(self.source)
        with self.assertRaises((ValueError,OSError)):routing_inputs.freeze_project_files(self.state,{'id':91},project,['linked.dxf'])
        with patch.object(routing_inputs,'MAX_PROJECT_BYTES',10),self.assertRaisesRegex(ValueError,'byte limit'):
            routing_inputs.freeze_project_files(self.state,{'id':92},project,['survey.dxf'])
        self.assertFalse((self.state.media_dir.parent/'route-inputs/92/project-files/0/survey.dxf').exists())


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.source=dict(artifact='source1',sha256='a'*64,path='survey.dxf',purpose='Survey',authority='Source')
        tasks=pair()['tasks'];tasks[0]['inputs']=[self.source.copy()]
        # Binding a native producer requires candidate comparisons, unlike a
        # preparation audit. No native application or provider runs in this test.
        tasks[0]['execution']={'capability':'rhino.run_python'}
        geometry=dict(mode='source_derived',artifacts=['source1'],checks=[dict(metric='contour_deviation',tolerance=.05,unit='m')])
        geometry_sources.bind(tasks,geometry,{'source1':self.source})
        self.frozen=tasks[1];self.frozen.update(assignment_id='review1')
        self.frozen['inputs'][-1]['sha256']=self.source['sha256']
        self.data=dict(sources=[dict(artifact='source1',sha256='a'*64)],source_observations={'source1':'Handle A1: transformed contour at Z=4 m; extracted from source DXF.'},
            comparisons=[dict(metric='contour_deviation',error=.01,evidence='Sampled original contour against reopened candidate triangles: max |dz|=0.01 m.')])

    def result(self,data=None):
        result=dict(assignment_id='review1',summary='Independent source comparison',decision='accept',instruction='',
            checks=[dict(criterion=i,passed=True,evidence='checked') for i in range(1,len(self.frozen['criteria'])+1)])
        result['checks'][-1]['evidence']=json.dumps(self.data if data is None else data)
        return result

    def test_measured_within_tolerance_is_accepted(self):
        c.report(self.result(),self.frozen)

    def test_wrong_geometry_missing_measurement_or_wrong_version_cannot_pass(self):
        cases=[]
        for error in (float('nan'),float('inf'),True,-.01):
            data=copy.deepcopy(self.data);data['comparisons'][0]['error']=error;cases.append(data)
        data=copy.deepcopy(self.data);data['sources'][0]['sha256']='b'*64;cases.append(data)
        data=copy.deepcopy(self.data);data['comparisons']=[];cases.append(data)
        data=copy.deepcopy(self.data);data['source_observations']={};cases.append(data)
        data=copy.deepcopy(self.data);data['comparisons'][0]['metric']='bounding_box';cases.append(data)
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ValueError):c.report(self.result(data),self.frozen)
        result=self.result();result['checks'][-1]['evidence']='ACCEPT: valid 3dm, correct object count and bounding box'
        with self.assertRaisesRegex(ValueError,'structured'):c.report(result,self.frozen)

    def test_measured_difference_is_user_review_findings_not_execution_failure(self):
        data=copy.deepcopy(self.data);data['comparisons'][0]['error']=1.5
        result=c.report(self.result(data),self.frozen)
        from orchestrator.outcomes import disposition
        self.assertEqual(disposition(result['findings']),'user_review')
        self.assertIn('1.5',result['findings'][0]['message'])

    def test_exceeded_tolerance_allows_revise_and_missing_tools_allow_blocked(self):
        result=self.result();result.update(decision='revise',instruction='Rebuild using the actual contour elevations.')
        result['checks'][-1].update(passed=False,evidence='Source contour deviation exceeds tolerance.')
        c.report(result,self.frozen)
        result.update(decision='blocked',checks=[],summary='Candidate reader unavailable; could not measure saved mesh.')
        c.report(result,self.frozen)

    def test_hash_is_bound_to_actual_frozen_input_not_only_report(self):
        self.frozen['inputs'][-1]['sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'delivered source'):c.report(self.result(),self.frozen)


if __name__=='__main__':unittest.main()
