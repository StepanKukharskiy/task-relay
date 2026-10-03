import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orchestrator import contracts, execution, host_code
from orchestrator.grasshopper_contract import evaluate, validate_checks
from orchestrator.runtime import Runtime, file_hash
from orchestrator.step_runner import execute
from tests.test_blender_operations import operation
from tests.test_orchestrator import FakeFactory, plan


def checks():
    return dict(version=1, mode='create', expected_object_count=1,
                expected_outputs=[dict(object='Value', output=0, count=1)])


def snapshot():
    return dict(graph={'one':dict(type='panel', nickname='Value', name='Panel', inputs=[[]], output_ids=['one'])},
                outputs={'one':[1]}, errors=[], warnings=[])


def inputs(rt, root):
    items = []
    params = dict(scene_sha256=None, permissions='unrestricted_host')
    for name, data, media, key in (
        ('definition.py', '# controlled authoring fixture\n', 'text/x-python', 'script_sha256'),
        ('gh-checks.json', json.dumps(checks()), 'application/json', 'checks_sha256')):
        path = root/name
        path.write_text(data)
        aid = rt.register(path, 'Exact Grasshopper fixture', path=name)
        items.append(dict(artifact=aid, path=name, purpose='Controlled input', authority='Exact test version', media_type=media))
        params[key] = file_hash(path)
    result = operation('rhino.grasshopper', items)
    result['execution']['parameters'] = params
    return result


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.factory = FakeFactory()
        self.rt = Runtime(self.root/'runtime', self.factory)
        self.addCleanup(self.rt.close)
        library = self.root/'Grasshopper.dll'
        library.write_text('controlled library fixture')
        self.app = dict(available=True, executable='/fixture/rhino', evidence='controlled fixture', blocker=None,
                        major=8, version='8.11', grasshopper_libraries=[str(library)])
        for target, value in (('task_relay.host_apps.rhino', self.app),
                              ('task_relay.host_apps.grasshopper', self.app),
                              ('task_relay.host_evidence.application_signature', {'path':'/fixture/rhino'})):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.op = inputs(self.rt, self.root)

    def frozen(self):
        self.rt.create(plan([self.op]))
        with self.rt.transaction():
            host_code.authorize(self.rt, 'demo', 'app', {'source':'controlled_test_explicit_approval'})
        self.rt.tick('demo')
        session = self.factory.sessions[self.rt.task('demo','app')['latest']]
        control = Path(session['session']['control'])
        control.mkdir(parents=True)
        return session['frozen'], control

    def native(self, executable, script, request_path, timeout, platform):
        compile(Path(script).read_bytes(), str(script), 'exec')
        request = json.loads(Path(request_path).read_text())
        out = Path(request['out'])
        if request['mode'] == 'gh_build':
            Path(request['baseline']).write_text(json.dumps(snapshot()))
            for suffix in ('gh','ghx'):
                (out/('candidate.'+suffix)).write_text('controlled native '+suffix)
        hashes = {s:file_hash(out/('candidate.'+s)) for s in ('gh','ghx')}
        if request['mode'] == 'gh_verify':
            report = dict(passed=True, checks=checks(), before=snapshot(), after={s:snapshot() for s in hashes},
                          candidate_hashes=hashes, errors=[], warnings=[])
            (out/'checks.json').write_text(json.dumps(report))
        return dict(passed=True, returncode=0, worker=dict(details=dict(candidate_hashes=hashes)))

    def test_exact_approval_is_required_and_future_or_edit_inputs_are_rejected(self):
        self.rt.create(plan([self.op]))
        self.rt.tick('demo')
        self.assertEqual(self.rt.task('demo','app')['attempts'], 0)
        self.assertEqual(self.factory.calls, [])
        future = copy.deepcopy(self.op)
        future['inputs'][0].pop('artifact')
        future['inputs'][0].update(from_task='produce', output='definition.py')
        with self.assertRaisesRegex(ValueError, 'already registered'):
            contracts.assignment(future)
        edit = copy.deepcopy(self.op)
        edit['execution']['parameters']['scene_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'new definitions only'):
            contracts.assignment(edit)

    def test_both_candidates_verified_no_replay_and_lineage_unselected(self):
        frozen, control = self.frozen()
        with patch('task_relay.rhino_host.run', side_effect=self.native) as run:
            self.assertEqual(execute(frozen, control)['outcome'], 'completed')
            with self.assertRaisesRegex(ValueError, 'replay'):
                execute(frozen, control)
            self.assertEqual(run.call_count, 2)
        receipt = json.loads((Path(frozen['workspace'])/'delivery/execution.json').read_text())
        self.assertFalse(receipt['lineage']['selected'])
        self.assertEqual(set(receipt['lineage']['candidate_hashes']), {'gh','ghx'})

    def test_failed_build_and_uncertain_transport_do_not_verify_or_resubmit(self):
        frozen, control = self.frozen()
        with patch('task_relay.rhino_host.run', return_value=dict(passed=False, worker=None, timeout=True)) as run:
            self.assertEqual(execute(frozen, control)['outcome'], 'failed')
            with self.assertRaisesRegex(ValueError, 'replay'):
                execute(frozen, control)
            self.assertEqual(run.call_count, 1)

    def test_changed_library_invalidates_frozen_grant_before_launch(self):
        frozen, control = self.frozen()
        Path(self.app['grasshopper_libraries'][0]).write_text('changed library')
        with patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError, 'libraries changed'):
                execute(frozen, control)
            run.assert_not_called()

    def test_rhino7_grant_and_launcher_keep_selected_interpreter(self):
        self.app.update(major=7, version='7.32', interpreter='IronPython 2.7')
        script = self.root/'legacy.py'
        script.write_text('print "Rhino 7 fixture"\n')
        aid = self.rt.register(script, 'Exact IronPython script', path=script.name)
        self.op['inputs'][0].update(artifact=aid, path=script.name)
        self.op['execution']['parameters']['script_sha256'] = file_hash(script)
        frozen, control = self.frozen()
        self.assertEqual(frozen['host_code_authorization']['binding']['rhino_runtime']['major'], 7)
        def native(*args):
            request = json.loads(Path(args[2]).read_text())
            self.assertEqual(request['rhino_major'], 7)
            self.assertTrue(Path(args[1]).read_text().startswith('#! python 2\n'))
            return self.native(*args)
        with patch('task_relay.rhino_host.run', side_effect=native):
            self.assertEqual(execute(frozen, control)['outcome'], 'completed')

    def test_switch_from_rhino7_to_8_invalidates_authorization(self):
        self.app.update(major=7, version='7.32', interpreter='IronPython 2.7')
        frozen, control = self.frozen()
        self.app.update(major=8, version='8.35', interpreter='CPython 3')
        with patch('task_relay.rhino_host.run') as run:
            with self.assertRaisesRegex(ValueError, 'version changed'):
                execute(frozen, control)
            run.assert_not_called()

    def test_declared_checks_are_recomputed_not_trusted_from_passed_flag(self):
        frozen, control = self.frozen()
        def native(*args):
            result = self.native(*args)
            request = json.loads(Path(args[2]).read_text())
            if request['mode'] == 'gh_verify':
                path = Path(request['out'])/'checks.json'
                report = json.loads(path.read_text())
                report['after']['ghx']['outputs']['one'] = [0]
                path.write_text(json.dumps(report))
            return result
        with patch('task_relay.rhino_host.run', side_effect=native):
            result = execute(frozen, control)
        self.assertEqual(result['outcome'], 'failed')
        self.assertIn('Grasshopper checks failed', result['summary'])

    def test_changed_candidate_during_verification_is_rejected(self):
        frozen, control = self.frozen()
        def native(*args):
            request = json.loads(Path(args[2]).read_text())
            if request['mode'] == 'gh_verify':
                (Path(request['out'])/'candidate.ghx').write_text('changed')
            return self.native(*args)
        with patch('task_relay.rhino_host.run', side_effect=native):
            self.assertEqual(execute(frozen, control)['outcome'], 'failed')

    def test_warnings_require_quality_review(self):
        frozen, control = self.frozen()
        def native(*args):
            result = self.native(*args)
            request = json.loads(Path(args[2]).read_text())
            if request['mode'] == 'gh_verify':
                path = Path(request['out'])/'checks.json'
                report = json.loads(path.read_text())
                report['warnings'] = ['gh: Value: controlled warning']
                path.write_text(json.dumps(report))
            return result
        with patch('task_relay.rhino_host.run', side_effect=native):
            result = execute(frozen, control)
        self.assertEqual(result['outcome'], 'completed')
        self.assertTrue(result['findings'])


class ContractTests(unittest.TestCase):
    def test_rhino7_source_decodes_unicode_and_retains_traceback_line_numbers(self):
        from orchestrator import grasshopper_worker, rhino_worker
        with tempfile.TemporaryDirectory() as tmp, patch.dict('sys.modules',{'rhino_worker':rhino_worker}):
            path=Path(tmp)/'author.py'
            path.write_text('#! python 2\n# -*- coding: utf-8 -*-\nname = u"Панель α"\nraise ValueError(name)\n',encoding='utf-8')
            scope={}
            try:exec(grasshopper_worker.load_script(str(path),7),scope)
            except ValueError as error:
                self.assertEqual(str(error),'Панель α')
                self.assertEqual(error.__traceback__.tb_next.tb_lineno,4)
            else:self.fail('Expected the authored exception')
            self.assertEqual(scope['name'],'Панель α')

    def test_rhino7_reuses_loaded_assembly_and_rejects_other_installation(self):
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        from orchestrator import grasshopper_contract, grasshopper_worker, rhino_worker
        path='/fixture/Rhino7/Grasshopper.dll'
        selected=NS(IsDynamic=False,Location='/fixture/shadow/Grasshopper.dll',GetName=lambda:NS(Name='Grasshopper'))
        for loaded,resolved,expected in (([selected],selected,'solver is disabled'),
                                         ([],NS(Location='/fixture/Rhino8/Grasshopper.dll'),'differs from the selected')):
            loader=Mock(return_value=resolved);reference=Mock()
            system=NS(AppDomain=NS(CurrentDomain=NS(GetAssemblies=lambda:loaded)),Reflection=NS(Assembly=NS(LoadFrom=loader)))
            context=NS(doc=object())
            modules={'Rhino':NS(RhinoApp=NS(GetPlugInObject=lambda _:None)), 'System':system,
                     'clr':NS(AddReference=reference), 'scriptcontext':context,
                     'grasshopper_contract':grasshopper_contract, 'rhino_worker':rhino_worker,
                     'Grasshopper':NS(Kernel=NS(GH_Document=NS(EnableSolutions=False)))}
            with patch.dict('sys.modules',modules),patch.object(rhino_worker,'read_text',return_value=json.dumps(checks())),patch.object(
                    rhino_worker,'file_hash',side_effect=lambda p:'other' if 'Rhino8' in p else 'selected'):
                with self.assertRaisesRegex(ValueError,expected):
                    grasshopper_worker.perform(dict(checks='fixture',grasshopper_libraries=[path],rhino_major=7))
            if loaded:
                loader.assert_not_called();reference.assert_called_once_with(selected)
            else:reference.assert_not_called()

    def test_graph_loss_errors_and_ambiguous_outputs_fail(self):
        baseline = snapshot()
        for change in ('wire', 'count', 'runtime', 'ambiguous'):
            current = copy.deepcopy(baseline)
            if change == 'wire':current['graph']['one']['inputs'] = [['missing']]
            if change == 'count':current['outputs']['one'] = [0]
            if change == 'runtime':current['errors'] = ['missing component']
            if change == 'ambiguous':current['graph']['two'] = current['graph']['one']
            self.assertTrue(evaluate(current, checks(), baseline), change)
        self.assertEqual(evaluate(baseline, checks(), baseline), [])

    def test_schema_bounds_and_duplicates(self):
        validate_checks(checks())
        for field, value in (('version', True), ('mode','edit'), ('expected_object_count',1001),
                             ('expected_outputs', checks()['expected_outputs']*2)):
            invalid = checks()
            invalid[field] = value
            with self.assertRaises(ValueError):validate_checks(invalid)

    def test_discovery_binds_each_installed_bundle_and_never_launches(self):
        from task_relay.host_apps import grasshopper
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen') as launch:
            for major in (7,8):
                executable = Path(tmp)/('Rhino '+str(major)+'.app')/'Contents/MacOS/Rhinoceros'
                root = executable.parents[1]/'Frameworks/RhCore.framework/Versions/A/Resources/ManagedPlugIns/GrasshopperPlugin.rhp'
                libraries = [root/name for name in ('Grasshopper.dll','GH_IO.dll','Components/GhPython.gha')]
                for library in libraries:
                    library.parent.mkdir(parents=True, exist_ok=True)
                    library.write_text('controlled library')
                with patch('task_relay.host_apps.rhino', return_value=dict(available=True, blocker=None, major=major, executable=str(executable))):
                    result = grasshopper()
                    self.assertTrue(result['available'])
                    self.assertEqual(result['grasshopper_libraries'], [str(p) for p in libraries])
                    libraries[-1].unlink()
                    self.assertFalse(grasshopper()['available'])
            launch.assert_not_called()

    def test_unicode_names_and_runtime_messages_survive_snapshot_and_json(self):
        from types import SimpleNamespace as NS
        from orchestrator.grasshopper_worker import snapshot as native_snapshot
        obj = NS(InstanceGuid='one', ComponentGuid='panel', NickName='Панель α', Name='Панель',
                 Sources=[], VolatileDataCount=1, RuntimeMessages=lambda level:['Предупреждение'] if level=='warning' else [])
        class Objects(list):
            @property
            def Count(self):return len(self)
        gh = NS(Kernel=NS(GH_RuntimeMessageLevel=NS(Error='error', Warning='warning')))
        result = json.loads(json.dumps(native_snapshot(NS(Objects=Objects([obj])),gh)))
        expected = checks();expected['expected_outputs'][0]['object']='Панель α'
        validate_checks(expected)
        self.assertEqual(evaluate(result,expected),[])
        self.assertEqual(result['warnings'],['Панель α: Предупреждение'])


if __name__ == '__main__':unittest.main()
