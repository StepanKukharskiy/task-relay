#!/usr/bin/env python3
"""Explicit local qualification of a small embedded GhPython definition.

No provider, channel, installation or user selection. Uses the normal exact-code
grant and Rhino host adapter, with an isolated runtime and retained receipts.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPT = '''# -*- coding: utf-8 -*-
from Grasshopper.Kernel import GH_ParamAccess
from Grasshopper.Kernel.Special import GH_NumberSlider, GH_Panel
from Grasshopper.Kernel.Parameters import Param_ScriptVariable, Param_GenericObject, Param_String
from Grasshopper.Kernel.Types import GH_String
from Grasshopper.Kernel.Data import GH_Path
from GhPython.Component import ZuiPythonComponent
from System.Drawing import PointF

slider = GH_NumberSlider()
slider.CreateAttributes()
slider.NickName = 'Scale'
slider.Slider.Minimum = System.Decimal(0)
slider.Slider.Maximum = System.Decimal(10)
slider.SetSliderValue(System.Decimal(3))
slider.Attributes.Pivot = PointF(40, 60)
ghdoc.AddObject(slider, False)

template = Param_String()
template.CreateAttributes()
template.NickName = 'Embedded template'
template.PersistentData.Append(GH_String('2'), GH_Path(0))
template.Attributes.Pivot = PointF(40, 130)
ghdoc.AddObject(template, False)

component = ZuiPythonComponent()
component.CreateAttributes()
component.NickName = u'Generator \u03b1'
component.Attributes.Pivot = PointF(280, 80)
component.HiddenOutOutput = True
for param in list(component.Params.Input): component.Params.UnregisterInputParameter(param, True)
for param in list(component.Params.Output): component.Params.UnregisterOutputParameter(param, True)
for name, source in [('Scale', slider), ('Template', template)]:
    param = Param_ScriptVariable()
    param.Name = name
    param.NickName = name
    param.Access = GH_ParamAccess.item
    component.Params.RegisterInputParam(param)
    param.AddSource(source)
result = Param_GenericObject()
result.Name = 'Point'
result.NickName = 'Point'
result.Access = GH_ParamAccess.item
component.Params.RegisterOutputParam(result)
component.Params.OnParametersChanged()
component.Code = 'import Rhino\\nPoint = Rhino.Geometry.Point3d(float(Scale), float(Template), 0)'
ghdoc.AddObject(component, False)

panel = GH_Panel()
panel.CreateAttributes()
panel.NickName = 'Result'
panel.Attributes.Pivot = PointF(520, 80)
panel.AddSource(result)
ghdoc.AddObject(panel, False)
'''
CHECKS = dict(version=1, mode='create', expected_object_count=4,
              expected_outputs=[dict(object='Generator \u03b1', output=0, count=1), dict(object='Result', output=0, count=1)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='store_true', required=True, help='Execute this fixed local Rhino/Grasshopper fixture')
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory under outputs/')
    parser.add_argument('--rhino-version', choices=('7','8'), help='Select the exact Rhino major for this process only')
    args = parser.parse_args()
    if args.rhino_version:os.environ['TASK_RELAY_RHINO_VERSION'] = args.rhino_version
    folder = args.output.resolve()
    if not folder.is_relative_to(ROOT/'outputs'):
        parser.error('Keep qualification records under outputs/')
    folder.mkdir(parents=True, exist_ok=False)
    from orchestrator import host_code
    from orchestrator.runtime import Runtime, file_hash
    from orchestrator.step_runner import execute
    from tests.test_orchestrator import FakeFactory, plan
    from tests.test_blender_operations import operation
    from task_relay.host_apps import grasshopper
    from task_relay.rhino_host import require_available
    app = grasshopper()
    if not app['available']:raise ValueError(app['blocker'])
    require_available(app['executable'])
    factory = FakeFactory()
    rt = Runtime(folder/'runtime', factory)
    report = dict(scope='Controlled local native fixture; no installed-service/provider/channel qualification or user selection', passed=False)
    try:
        items = []
        params = dict(scene_sha256=None, permissions='unrestricted_host')
        for name, data, media, key in (
            ('definition.py', SCRIPT, 'text/x-python', 'script_sha256'),
            ('checks.json', json.dumps(CHECKS), 'application/json', 'checks_sha256')):
            path = folder/name
            path.write_text(data)
            aid = rt.register(path, 'Fixed local Grasshopper qualification', path=name)
            items.append(dict(artifact=aid, path=name, purpose='Fixed small fixture', authority='Explicit local qualification', media_type=media))
            params[key] = file_hash(path)
        op = operation('rhino.grasshopper', items)
        op['execution']['parameters'] = params
        rt.create(plan([op]))
        with rt.transaction():
            host_code.authorize(rt, 'demo', 'app', dict(source='explicit_local_qualification_fixed_fixture', script_scope='scripts/qualify_grasshopper.py'))
        rt.tick('demo')
        attempt = rt.task('demo','app')['latest']
        if not attempt:raise ValueError('Qualification could not dispatch: '+str(rt.status('demo')))
        session = factory.sessions[attempt]
        control = Path(session['session']['control'])
        control.mkdir(parents=True)
        report['result'] = execute(session['frozen'], control)
        report['delivery'] = str(Path(session['frozen']['workspace'])/'delivery')
        report['passed'] = report['result']['outcome'] == 'completed'
        session['status'] = dict(status='finished', exit_code=0 if report['passed'] else 1)
        rt.tick('demo', dispatch=False)
        report['runtime_status'] = rt.status('demo')
    finally:
        rt.close()
        (folder/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':raise SystemExit(main())
