#!/usr/bin/env python3
"""Run Blender regressions and optionally real, isolated registered host pipelines."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

MODULES = [
    'test_blender_qualification',
    'test_blender_operations','test_blender_mesh','test_blender_inspection',
    'test_blender_edit','test_blender_assets','test_blender_animation',
    'test_blender_planning','test_blender_edit_planning','test_blender_assets_planning',
    'test_blender_animation_planning','test_planning_baselines','test_review_resume',
    'test_mixed_execution','test_mixed_planning','test_worker_factory',
    'test_production_planning','test_production_status','test_production_selections',
    'test_production_lifecycle','test_artifact_handoff',
]


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.rows=[];self.started={}
    def startTest(self,test):
        self.started[test.id()]=time.monotonic();super().startTest(test)
    def record(self,test,status,detail=None):
        self.rows.append(dict(test=test.id(),status=status,detail=detail,
                             seconds=round(time.monotonic()-self.started.get(test.id(),time.monotonic()),3)))
    def addSuccess(self,test):super().addSuccess(test);self.record(test,'passed')
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,'failed',self._exc_info_to_string(err,test))
    def addError(self,test,err):super().addError(test,err);self.record(test,'error',self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,'skipped',reason)
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err:self.record(subtest,'failed',self._exc_info_to_string(err,test))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true',help='Also run real Blender/ffmpeg with synthetic fixtures; no provider calls or live messages')
    parser.add_argument('--output',type=Path,help='New evidence directory (must not exist)')
    parser.add_argument('--only',choices=['controlled','host'],help='Run one phase while investigating a failure; host still requires --host')
    parser.add_argument('--case',help='One real-host test method; requires --host --only host')
    args=parser.parse_args()
    if args.only=='host' and not args.host:parser.error('--only host requires --host')
    if args.case and (not args.host or args.only!='host' or not args.case.startswith('test_')):
        parser.error('--case requires --host --only host and a test_ method name')
    output=(args.output or ROOT/'outputs/blender-qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')).resolve()
    output.mkdir(parents=True,exist_ok=False)
    from orchestrator.execution import REGISTRY
    from tests.test_blender_pipeline_live import COVERAGE
    registry={k:v for k,v in REGISTRY.items() if k.startswith('blender.')}
    if set(registry)!=set(COVERAGE):
        raise SystemExit('Update host qualification coverage for changed Blender registry: '+str(set(registry)^set(COVERAGE)))
    report=dict(started=datetime.now(timezone.utc).isoformat(),command=sys.argv,host=platform.platform(),
                python=sys.version,real_host_requested=args.host,selected_case=args.case,registry=registry,
                coverage=COVERAGE,phases=[],limitations=[
                    'LLM responses and channel transports are controlled fixtures; no live model/Telegram/Messages qualification.',
                    'Small native fixtures exercise supported modes; maximum-size rendering and every numeric combination are not load-tested.',
                    'Results qualify this host only; no Windows/Linux inference from macOS.'])
    report['source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for pattern in ('orchestrator/*.py','task_relay/production_*.py','tests/test_blender*.py') for p in ROOT.glob(pattern)}
    def save():
        (output/'report.json').write_text(json.dumps(report,indent=2))
        lines=['# Blender qualification', '', 'Command: `'+ ' '.join(sys.argv)+'`', '',
               '| Phase | Tests | Failures/errors | Skips |', '| --- | ---: | ---: | ---: |']
        for phase in report['phases']:
            lines.append(f"| {phase['name']} | {phase['tests']} | {phase['failures']} | {phase['skips']} |")
        lines+=['','## Limitations','']+['- '+x for x in report['limitations']]
        for phase in report['phases']:
            problems=[r for r in phase['results'] if r['status']!='passed']
            if problems:lines+=['','## '+phase['name']+' findings','']+['- '+r['test']+': '+r['status']+' — '+str(r['detail']) for r in problems]
        (output/'report.md').write_text('\n'.join(lines)+'\n')
    save();failed=False
    phases=[('controlled',['tests.'+m for m in MODULES])]
    if args.host:
        os.environ['RELAY_BLENDER_QUALIFICATION_DIR']=str(output)
        # unittest skip flags are evaluated at import time; the module above was inventory-only.
        import tests.test_blender_pipeline_live as live
        live.LiveTests.__unittest_skip__=False
        phases.append(('real-host',['tests.test_blender_pipeline_live']))
    if args.only:phases=[p for p in phases if p[0]==('real-host' if args.only=='host' else 'controlled')]
    if args.case:phases=[('real-host',['tests.test_blender_pipeline_live.LiveTests.'+args.case])]
    for name,modules in phases:
        print(f'{name}: starting; evidence {output}',flush=True)
        suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
        with (output/(name+'.log')).open('w') as stream:
            result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
        report['phases'].append(dict(name=name,tests=result.testsRun,failures=len(result.failures)+len(result.errors),
                                     skips=len(result.skipped),results=result.rows))
        failed=failed or not result.wasSuccessful() or bool(result.skipped)
        save();print(f'{name}: {result.testsRun} tests; {len(result.failures)+len(result.errors)} failures/errors; {len(result.skipped)} skipped',flush=True)
    report['finished']=datetime.now(timezone.utc).isoformat()
    report['outcome']='failed_or_incomplete' if failed else 'passed'
    save();print(str(output/'report.md'),flush=True)
    return int(failed)


if __name__=='__main__':raise SystemExit(main())
