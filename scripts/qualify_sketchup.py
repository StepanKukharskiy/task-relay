#!/usr/bin/env python3
"""Explicit local SketchUp qualification with tiny fixtures, no providers/messages.

Uses controlled orchestration and the real registered native executor. It never
attaches to an existing SketchUp process or modifies an existing project model.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',action='store_true',required=True)
    parser.add_argument('--case',choices=['startup','roundtrip'],default='startup')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--executable',help='Exact installed SketchUp executable; no fallback')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    if args.executable:os.environ['TASK_RELAY_SKETCHUP']=args.executable
    os.environ['TASK_RELAY_DATA_DIR']=str(output/'data')
    os.environ['TASK_RELAY_WORKSPACE_DIR']=str(output/'workspaces')
    os.environ['TASK_RELAY_GENERATED_DIR']=str(output/'generated')
    from orchestrator.runtime import Runtime, file_hash
    from orchestrator import host_code
    from orchestrator.step_runner import execute
    from tests.test_orchestrator import FakeFactory, plan
    from tests.test_blender_operations import operation
    from tests.test_sketchup_operations import inputs, checks, MEDIA
    from task_relay.host_apps import sketchup
    report=dict(command=sys.argv,app=sketchup(),started=time.time(),cases=[],
                limitations=['Controlled orchestration with real native execution; no installed-service/provider/channel qualification.',
                             'Only tiny untextured geometry fixtures, not arbitrary models, plugins or production loads.'])
    report_path=output/'report.json'
    def save():report_path.write_text(json.dumps(report,indent=2))
    save()

    def run_case(name,make):
        folder=output/name;folder.mkdir();factory=FakeFactory();rt=Runtime(folder/'runtime',factory)
        try:
            op=make(rt,folder);rt.create(plan([op]))
            if host_code.required(op):
                with rt.transaction():host_code.authorize(rt,'demo','app',dict(source='explicit_cli_qualification_fixture',command=sys.argv))
            rt.tick('demo');task=rt.task('demo','app')
            if not task['latest']:raise ValueError('Fixture did not dispatch: '+json.dumps(task))
            entry=factory.sessions[task['latest']];frozen=entry['frozen'];control=Path(entry['session']['control']);control.mkdir(parents=True)
            result=execute(frozen,control);delivery=Path(frozen['workspace'])/'delivery'
            receipt=json.loads((delivery/'execution.json').read_text())
            report['cases'].append(dict(name=name,result=result,passed=receipt['passed'],delivery=str(delivery),
                hashes={p.name:file_hash(p) for p in delivery.iterdir() if p.is_file()}));save()
            print(name+': '+result['summary'],flush=True)
            if not receipt['passed']:raise ValueError('Native '+name+' failed; receipt retained')
            return delivery
        finally:rt.close()

    def startup(rt,folder):
        path=folder/'request.txt';path.write_text('Check SketchUp startup with a fixed owned Ruby worker.')
        aid=rt.register(path,'Explicit startup fixture',path='request.txt')
        return operation('sketchup.startup',[dict(artifact=aid,path='request.txt',media_type='text/plain',purpose='Diagnostic',authority='Explicit qualification')])

    try:
        run_case('startup',startup)
        if args.case=='roundtrip':
            created=run_case('create',lambda rt,folder:inputs(rt,folder))
            def inspect(rt,folder):
                aid=rt.register(created/'candidate.skp','Created fixture',path='source.skp')
                return operation('sketchup.inspect',[dict(artifact=aid,path='source.skp',media_type=MEDIA,purpose='Inspect fixture',authority='Exact created candidate')])
            inspected=run_case('inspect',inspect)
            inventory=json.loads((inspected/'inspection.json').read_text())
            ident=next(i for i,e in inventory['entities'].items() if e.get('name')=='Box')
            contract=checks();contract.update(mode='edit',changed_entities=[ident],allow_additions=False,
                                               expected_dimensions_mm={'Box':[100,200,450]})
            script="box = model.entities.find { |e| e.respond_to?(:name) && e.name == 'Box' }\nbox.transform!(Geom::Transformation.scaling(1,1,1.5))\n"
            run_case('edit',lambda rt,folder:inputs(rt,folder,source=(created/'candidate.skp').read_bytes(),script=script,contract=contract))
        report['passed']=True
    except Exception as exc:
        report['passed']=False;report['error']=str(exc);raise
    finally:
        report['finished']=time.time();save()


if __name__=='__main__':main()
