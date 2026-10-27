#!/usr/bin/env python3
"""Fail-closed offline release gate for shared correction and delivery boundaries."""
import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import lifecycle_retention as retention

# This is an explicit maintained matrix, not discovery of an optional subset.
GROUPS={
    'gemini-transport-boundary':['tests.test_gemini_transport_boundary'],
    'canvas-node-admission':['tests.test_job_templates','tests.test_canvas_node_run','tests.test_node_result_actions','tests.test_node_usability','tests.test_codex_gate'],
    'reusable-node-bindings':['tests.test_reusable_nodes'],
    'operation-node-ports':['tests.test_operation_nodes'],
    'node-specification':['tests.test_node_specification'],
    'one-node-interface':['tests.test_node_interface'],
    'one-node-composed-correction':['tests.test_node_lifecycle.NodeLifecycle.test_node_failed_correction_render_review_partial'],
    'ordinary-owner-execution':['tests.test_ordinary_execution','tests.test_user_choice_images','tests.test_result_handoff'],
    'public-read-recovery':['tests.test_read_recovery','tests.test_public_browser_navigation',
        'tests.test_browser_source_boundary.Tests.test_late_unresolved_guard_error_cannot_be_promoted_to_capture',
        'tests.test_product_page_connectors.Tests.test_same_explicit_identity_retains_images_through_discovery_and_download',
        'tests.test_product_page_connectors.Tests.test_shared_name_or_page_without_identity_does_not_alias',
        'tests.test_product_page_connectors.Tests.test_shared_identifier_cannot_hide_variant_or_product_url_conflicts'],
    'inventory-acquisition-handoff':['tests.test_inventory_acquisition',
        'tests.test_inventory_acquisition_lifecycle.InventoryAcquisition.test_inventory_acquisition_failed_correction_full_path'],
    'inventory-acquisition-plants':[
        'tests.test_inventory_acquisition_lifecycle.Plants.test_inventory_acquisition_failed_correction_full_path'],
    'inventory-acquisition-components':[
        'tests.test_inventory_acquisition_lifecycle.Components.test_inventory_acquisition_failed_correction_full_path'],
    'image-acquisition-saved-render':['tests.test_acquisition_render_contract',
        'tests.test_artifact_roles.Tests.test_revision_preflight_keeps_render_zip_out_of_asset_port',
        'tests.test_artifact_roles.Tests.test_local_visual_references_are_bounded_reads_not_one_eager_image_pack',
        'tests.test_acquisition_render_lifecycle.AcquisitionRender.test_acquisition_failed_saved_section_restart_render_rereview_partial'],
    'image-acquisition-plants':[
        'tests.test_acquisition_render_lifecycle.Plants.test_acquisition_failed_saved_section_restart_render_rereview_partial'],
    'image-acquisition-components':[
        'tests.test_acquisition_render_lifecycle.Components.test_acquisition_failed_saved_section_restart_render_rereview_partial'],
    'discovery-workload-continuation':['tests.test_discovery_workload.Discovery',
        'tests.test_discovery_workload.Workload.test_declared_ceiling_survives_resolved_workload_and_no_empty_partitions',
        'tests.test_owner_compilation.Tests.test_registered_workload_uses_actual_subjects_and_expands_required_review',
        'tests.test_discovery_failed_lifecycle.DiscoveryFailed.test_discovery_deferred_inventory_failed_corrections_full_path'],
    'discovery-workload-plants':[
        'tests.test_discovery_failed_lifecycle.Plants.test_discovery_deferred_inventory_failed_corrections_full_path'],
    'discovery-workload-components':[
        'tests.test_discovery_failed_lifecycle.Components.test_discovery_deferred_inventory_failed_corrections_full_path'],
    'record-transport-efficiency':['tests.test_record_overhead','tests.test_review_input_interface.WorkerTests'],
    'correction-delivery':['tests.test_shared_lifecycle','tests.test_lifecycle_process'],
    'correction-export-handoff':['tests.test_correction_handoff_lifecycle'],
    'review-dependency-handoff':['tests.test_review_dependency_lifecycle','tests.test_navigation_inspection.Review'],
    'complete-correction-coverage':['tests.test_remaining_boundaries','tests.test_complete_correction_path'],
    'visual-selection-handoff':['tests.test_visual_selection_workflow.Selection','tests.test_visual_selection_workflow.Discovery',
        'tests.test_visual_selection_workflow.StandaloneInspection.test_rejected_standalone_inspection_then_two_fresh_reviews_without_replay',
        'tests.test_visual_selection_lifecycle.VisualPath.test_broad_pool_unknown_buying_three_visual_designs_restart_correct_review_partial'],
    'compiler-record-transfer':['tests.test_record_transfer_compiler',
        'tests.test_compiled_visual_lifecycle.Compiled.test_compiler_partition_to_visual_correction_review_partial',
        'tests.test_compiled_visual_lifecycle.Plants.test_compiler_partition_to_visual_correction_review_partial',
        'tests.test_compiled_visual_lifecycle.Components.test_compiler_partition_to_visual_correction_review_partial'],
    'failed-correction-continuation':['tests.test_failed_correction_checkpoint',
        'tests.test_failed_compiled_lifecycle.FailedCompiled.test_failed_corrections_full_compiler_to_rereview_partial',
        'tests.test_failed_compiled_lifecycle.Plants.test_failed_corrections_full_compiler_to_rereview_partial',
        'tests.test_failed_compiled_lifecycle.Components.test_failed_corrections_full_compiler_to_rereview_partial'],
    'photo-context':['tests.test_photo_context_lifecycle','tests.test_owner_context_retention.ContextTests'],
    'registered-baselines':['tests.test_content_baseline_construction',
        'tests.test_sourcing_recovery_composition','tests.test_coordination_boundary.CompiledRecovery'],
    'handoff-construction':['tests.test_handoff_construction','tests.test_compiler_owned_metadata'],
    'database-contention':['tests.test_database_lock_boundary','tests.test_shared_storage'],
    'exact-review':['tests.test_review_settlement','tests.test_visual_review_observation',
        'tests.test_shared_code_workers.Tests.test_large_render_preview_reaches_model_and_exact_review_without_extra_call'],
    'partial-export':['tests.test_partial_delivery'],
    'process-restart':['tests.test_runtime_cache_boundary',
        'tests.test_execution_boundary','tests.test_supervisor_cleanup',
        'tests.test_host_adapters.Tests.test_cancel_reaches_child_and_grandchild',
        'tests.test_native_hosts.ProcessTrees',
        'tests.test_worker_factory.Tests.test_startup_grace_survives_controller_restart_without_false_uncertainty_or_replay',
        'tests.test_worker_factory.Tests.test_final_receipt_arriving_during_process_probe_is_collected_without_uncertainty',
        'tests.test_worker_factory.Tests.test_missing_or_foreign_terminal_receipt_cannot_confirm_completion'],
    'installation-delivery-maintenance':['tests.test_desktop_local_install','tests.test_delivery_effects'],
    'gate-controls':['tests.test_lifecycle_release_gate','tests.test_lifecycle_retention'],
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(root=ROOT):
    files=[]
    for folder in ('orchestrator','task_relay','tests','scripts'):
        files.extend((root/folder).glob('*.py'))
    files.extend((root/'orchestrator').glob('*.rb'))
    files.extend((root/'orchestrator').glob('*.schema.json'))
    files.extend((root/'examples').glob('*.node.json'))
    files.extend((root/'examples').glob('*.workflow.json'))
    files.extend((root/'desktop/scripts').glob('*.py'))
    files.extend((root/'desktop/src-tauri/src').glob('*.rs'))
    files.extend((root/'desktop/src-tauri').glob('tauri.conf.json'))
    for folder in ('tests/fixtures','task_relay/assets'):
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    files.extend((root/'.github/workflows').glob('*.yml'))
    files.extend(root/n for n in ('AGENTS.md','pyproject.toml','source_inventory.json','docs/shared-lifecycle-qualification.md') if (root/n).exists())
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(files)}


class StrictResult(unittest.TextTestResult):
    """unittest considers skips and expected failures successful; release does not."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.executed=[];self.outcomes=[]
    def startTest(self,test):self.executed.append(test.id());super().startTest(test)
    def addSuccess(self,test):self.outcomes.append(dict(test=test.id(),status='passed'));super().addSuccess(test)
    def addSkip(self,test,reason):self.outcomes.append(dict(test=test.id(),status='skipped',reason=reason));super().addSkip(test,reason)
    def addExpectedFailure(self,test,err):self.outcomes.append(dict(test=test.id(),status='expected_failure'));super().addExpectedFailure(test,err)
    def addUnexpectedSuccess(self,test):self.outcomes.append(dict(test=test.id(),status='unexpected_success'));super().addUnexpectedSuccess(test)
    def addError(self,test,err):self.outcomes.append(dict(test=test.id(),status='error'));super().addError(test,err)
    def addFailure(self,test,err):self.outcomes.append(dict(test=test.id(),status='failed'));super().addFailure(test,err)
    def addSubTest(self,test,subtest,err):
        if err:self.outcomes.append(dict(test=subtest.id(),status='failed_subtest'))
        super().addSubTest(test,subtest,err)
    def gate_ok(self):
        return bool(self.testsRun) and self.wasSuccessful() and not self.skipped and not self.expectedFailures and len(self.executed)==len(set(self.executed))


def worker(group,out):
    from task_relay import runtime_process
    runtime_process.require_source_only()
    out.mkdir(parents=True,exist_ok=True)
    os.environ['TASK_RELAY_OFFLINE_EVIDENCE']=str(out/'journals')
    violations=[]
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
            violations.append(event)
            raise RuntimeError('Offline lifecycle qualification forbids network transport')
    sys.addaudithook(guard)
    suite=unittest.TestSuite();counts={}
    for name in GROUPS[group]:
        selected=unittest.defaultTestLoader.loadTestsFromName(name)
        counts[name]=selected.countTestCases();suite.addTest(selected)
    with (out/'tests.log').open('w') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=StrictResult).run(suite)
    report=dict(group=group,selectors=GROUPS[group],counts=counts,tests=result.testsRun,
        passed=result.gate_ok() and all(counts.values()) and not violations,
        outcomes=result.outcomes,network_attempts=violations,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),expected_failures=len(result.expectedFailures))
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1


def validate(report,current):
    if report.get('sources')!=current:raise ValueError('Lifecycle receipt is stale: source or gate changed')
    if report.get('matrix')!=GROUPS:raise ValueError('Lifecycle matrix differs')
    groups=report.get('groups',[])
    if [g.get('group') for g in groups]!=list(GROUPS):raise ValueError('Missing or reordered lifecycle groups')
    if not report.get('passed') or any(not g.get('passed') or not g.get('tests') or g.get('returncode')!=0 for g in groups):
        raise ValueError('Lifecycle gate failed or did not execute')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify',type=Path,help='Verify a retained receipt against current sources and evidence')
    parser.add_argument('--_worker',choices=GROUPS,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args._worker:
        if not args.output:parser.error('Worker output required')
        return worker(args._worker,args.output.resolve())
    if args.verify:
        if (args.verify.parent/retention.RETIRED).exists():
            raise ValueError('Lifecycle fixtures were retired; compact logs are not a full-evidence receipt')
        report=json.loads(args.verify.read_text());validate(report,sources())
        for name,digest in report['evidence'].items():
            if sha(args.verify.parent/name)!=digest:raise ValueError('Lifecycle evidence changed: '+name)
        print('Lifecycle receipt matches current sources and original evidence.');return 0
    if not args.output:parser.error('--output is required; use a fresh directory per run')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    with retention.lock(out/'.lifecycle.lock'):
        retention.register(out)
        code=qualify(out)
        retention.complete(out)
    try:
        cleanup=retention.prune(out.parent)
        retention.write(out/'cleanup.json',cleanup)
        if cleanup['skipped']:print('Lifecycle retention skipped protected directories; see cleanup.json',file=sys.stderr)
    except (OSError,ValueError,KeyError) as exc:
        # Cleanup cannot rewrite qualification results or hide a test failure.
        retention.write(out/'cleanup.json',dict(error=str(exc)))
        print('Lifecycle retention incomplete: '+str(exc),file=sys.stderr)
    return code


def qualify(out):
    before=sources();started=time.time();groups=[];error=None
    # Never inherit a user's provider/runtime installation selectors into fixtures.
    env={k:v for k,v in os.environ.items() if not k.startswith(('TASK_RELAY_','RELAY_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=os.path.abspath(os.devnull))
    try:
        dependencies={n:importlib.metadata.version(n) for n in ('python-pptx','Pillow')}
        for name in GROUPS:
            folder=out/name;folder.mkdir()
            command=[sys.executable,'-B','-X','pycache_prefix='+os.path.abspath(os.devnull),str(Path(__file__).resolve()),'--_worker',name,'--output',str(folder)]
            with (folder/'process.log').open('w') as log:
                try:run=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180);code=run.returncode
                except subprocess.TimeoutExpired:code=124
            path=folder/'result.json'
            item=json.loads(path.read_text()) if path.exists() else dict(group=name,passed=False,tests=0)
            item.update(returncode=code,command=command);groups.append(item)
            print(name+': '+('PASS' if item.get('passed') and code==0 else 'FAIL')+' ('+str(item['tests'])+' tests)',flush=True)
    except Exception as exc:
        dependencies={};error=type(exc).__name__+': '+str(exc)
    after=sources()
    evidence={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()
              and not (p.parent==out and (p.name in (retention.MARKER,'.lifecycle.lock') or p.name.startswith('.retention-')))}
    report=dict(version=1,scope='Controlled offline shared lifecycle; not live semantic or installed native qualification',
        sources=before,matrix=GROUPS,groups=groups,dependencies=dependencies,python=sys.version,
        source_unchanged=before==after,started=started,finished=time.time(),error=error,
        passed=not error and before==after and len(groups)==len(GROUPS) and all(g.get('passed') and g['returncode']==0 for g in groups),
        evidence=evidence,limits='Unchanged production ceilings in composed lifecycle; boundary probes may use smaller test deadlines.',
        limitations=['Scripted judgments do not qualify model or visual quality.','Composed graph crosses real controller restart with controlled worker observations; real supervisor/worker subprocesses qualified separately.','Network calls denied in test processes; subprocess fixtures are local scripts, not live provider runtimes.'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Shared lifecycle gate', '', 'PASS' if report['passed'] else 'FAIL', '',report['scope'],'']
    lines += ['- '+g['group']+': '+str(g['tests'])+' tests; '+('PASS' if g.get('passed') and g['returncode']==0 else 'FAIL') for g in groups]
    lines += ['','Original evidence (SHA-256):','']+[ '- `'+name+'` '+digest for name,digest in evidence.items()]
    (out/'AUDIT.md').write_text('\n'.join(lines)+'\n')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
