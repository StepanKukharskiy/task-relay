"""Read-only, versioned job state and bounded stage context from saved workflow evidence."""

from collections import defaultdict
from . import impact_handoff


SCHEMA = 'task-relay.job-state'
VERSION = 12  # Adds bounded research campaign policy, progress and receipt records.


def project(report):
    """Project a committed workflow snapshot; never treat this view as authority."""
    artifacts = [{key: artifact.get(key) for key in
                  ('id', 'run', 'task', 'attempt', 'path', 'copy_path', 'sha256',
                   'bytes', 'purpose', 'source', 'selected', 'copy_status')}
                 for artifact in report['artifacts']]
    for artifact in artifacts:
        if artifact['copy_status'] not in ('copied', 'present'):
            artifact['copy_path'] = None  # A planned export path is not a verified file.
    by_attempt = defaultdict(list)
    for artifact in artifacts:
        if artifact['attempt']:
            by_attempt[artifact['attempt']].append(artifact['id'])
    dependencies = []
    attempts = []
    decisions = []
    for production in report['productions']:
        decisions.extend(production['decisions'])
        for attempt in production['attempts']:
            frozen = attempt['frozen']
            attempts.append({'id': attempt['id'], 'run': production['run'],
                             'task': attempt['task'], 'state': attempt['state'],
                             'error': attempt['error'],
                             'receipt_status': (attempt['receipt'] or {}).get('status'),
                             'executor': frozen.get('backend', {}).get('type'),
                             'operation': frozen.get('execution', {}).get('capability')})
            for output in by_attempt[attempt['id']]:
                for source in frozen.get('inputs', []):
                    if source.get('artifact'):
                        dependencies.append({'output': output, 'input': source['artifact'],
                                             'input_sha256': source.get('sha256'),
                                             'attempt': attempt['id'], 'path': source.get('path'),
                                             'purpose': source.get('purpose'),
                                             'authority': source.get('authority'),
                                             'basis': 'declared_input_potential_dependency'})
    stages = [{key: stage.get(key) for key in
               ('id', 'position', 'status', 'error', 'target_kind', 'target',
                'folder', 'sources', 'choices', 'runs', 'plans')}
              for stage in report['stages']]
    process = report.get('process') or {
        'schema': 'task-relay.job-process', 'version': 3, 'records': [], 'coverage': [],
        'gaps': [{'category': None, 'kind': 'process_not_collected',
                  'source_table': 'state.sqlite', 'source_id': report['id'],
                  'reason': 'The committed process record was not collected.'}],
        'complete': False}
    return {'schema': SCHEMA, 'version': VERSION,
            'authority': 'Read-only view of committed Relay records; editing this file does not change the job.',
            'job': {'id': report['id'], 'title': report['title'],
                    'objective': report['request'], 'status': report['status']},
            'snapshot': report['snapshot'], 'stages': stages, 'artifacts': artifacts,
            **({'research_campaign':report['research_campaign']} if report.get('research_campaign') else {}),
            'dependencies': dependencies, 'decisions': decisions, 'attempts': attempts,
            'replacements': report.get('replacements', []),
            'facts': report.get('facts', {'bindings': [], 'coverage': [], 'revisions': [],
                                           'candidate_reviews': [], 'selections': []}),
            'translations': report.get('translations', {'links': [], 'revisions': [],
                                                        'reviews': [], 'selections': []}),
            'presentations': report.get('presentations', {'links': [], 'coverage': [],
                'revisions': [], 'reviews': [], 'selections': []}),
            'native_links': report.get('native_links', {'links': [], 'coverage': []}),
            'reviewed_links': report.get('reviewed_links'),
            'reviewed_impacts': report.get('reviewed_impacts', []),
            'impact_handoffs': impact_handoff.view_records(report.get('impact_handoffs', [])),
            'agent_candidates': report.get('agent_candidates', {
                'candidates': [], 'inputs': [], 'reviews': [], 'selections': []}),
            'revision_bundles': report.get('revision_bundles', {
                'plans': [], 'bundles': [], 'files': [], 'reviews': [], 'selections': []}),
            'bundle_continuations': report.get('bundle_continuations', {
                'plans': [], 'candidates': [], 'reviews': [], 'selections': []}),
            'process': process,
            'missing_artifacts': report['missing_artifacts'],
            'coverage': {'dependencies': 'Declared frozen inputs are potential dependencies, not proof of semantic use.',
                         'facts_entities': 'Only explicit reviewed XLSX, bounded PPTX text and typed native-subject links are represented; this is not general extraction.',
                         'unregistered_files': 'Files outside registered inputs and outputs are not indexed.',
                         'checks': 'Recorded check events and review rows are indexed in process; missing expected checks are marked explicitly.'}}


def stage_context(job_state, stage_id):
    """Select exact recorded context for one stage without summarizing its request."""
    stage = next((s for s in job_state['stages'] if s['id'] == stage_id), None)
    if stage is None:
        raise ValueError('Unknown job stage.')
    inputs = {source['artifact'] for source in stage['sources'] if source.get('artifact')}
    edges = job_state['dependencies']
    if len(edges) > 10000:
        raise ValueError('Stage context exceeds the bounded working set; inspect exact sources.')
    parents = defaultdict(set)
    for edge in edges:
        parents[edge['output']].add(edge['input'])
    relevant = set(inputs)
    todo = list(inputs)
    while todo:
        for ancestor in parents[todo.pop()]:
            if ancestor not in relevant:
                relevant.add(ancestor)
                todo.append(ancestor)
        if len(relevant) > 100:
            raise ValueError('Stage context exceeds the bounded working set; inspect exact sources.')
    artifacts = [a for a in job_state['artifacts'] if a['id'] in relevant]
    known = {a['id'] for a in artifacts}
    missing = sorted(relevant - known)
    outdated = [item for replacement in job_state['replacements']
                for item in replacement['outdated_outputs'] if item['artifact'] in relevant]
    return {'schema': 'task-relay.stage-context', 'version': 1,
            'job': job_state['job'], 'snapshot': job_state['snapshot'],
            'stage': stage, 'artifacts': artifacts,
            'dependencies': [e for e in edges if e['output'] in relevant and e['input'] in relevant],
            'decisions': [d for d in job_state['decisions'] if d['artifact'] in relevant],
            'exceptions': [a for a in job_state['attempts']
                           if a['error'] and (a['run'] in stage['runs'] or a['task'] == stage_id)],
            'outdated_inputs': outdated,
            'missing_artifacts': missing,
            'complete': job_state['process']['complete'] and not missing and not job_state['missing_artifacts']
                        and not any(r['truncated'] for r in job_state['replacements']),
            'coverage': job_state['coverage']}
