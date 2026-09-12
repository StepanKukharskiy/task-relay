"""Observe an explicitly identified subsequent job; never infer opportunity from silence."""
import time
from datetime import datetime
from .analyzer import Analysis, require_text, model_event
from .proposals import trial_target
from .store import encoded, identifier, digest
from pathlib import Path

INSTRUCTION = '''Assess this subsequent job against the intervention's applicability and
targeted discrepancy. Use ordinary conversation feedback; do not request a correction log.
This is ONE job. Multiple repairs within it are one job, never independent recurrences.
Return {"eligible": true, "eligibility_reason": "reason", "evidence": ["event ID"],
"job_outcome": "accepted|incomplete|abandoned|unknown",
"target_status": "recurred|not_observed|unknown",
"correction_evidence": ["event ID"], "acceptance_evidence": ["event ID"],
"other_issues": [{"observation": "reported issue", "evidence": ["event ID"]}],
"recommendation": "keep|revise|remove|insufficient_evidence", "reason": "qualified assessment"}.
Not observed means the supplied evidence was relevant and inspected; it is not proof of
absence in an incomplete job. No eligible jobs must never be reported as zero recurrence.
Only explicit authored user acceptance supports accepted outcome. Do not infer human
attention from timestamps or claim causal/time-saving benefit from this one observation.'''


def evaluate(store, aid, dataset, job_id, workflow, mode, intervention_hash, human_minutes=None, **options):
    app = store.get('applications', aid)
    d = app['details']
    if d['state'] != 'applied' or intervention_hash != d['after_hash']:
        raise ValueError('Evaluation must identify the applied intervention hash actually used')
    if digest(trial_target(d).read_bytes()) != intervention_hash:
        raise ValueError('Trial guide changed; supply evidence for a separately versioned intervention')
    if human_minutes is not None and human_minutes < 0:
        raise ValueError('Human effort estimate cannot be negative')
    proposal = store.get('proposals', app['proposal_id'])
    for row in store.db.execute('SELECT details FROM evaluations WHERE application_id=?', (aid,)):
        import json
        if json.loads(row[0])['job_id'] == job_id:
            raise ValueError('This job was already evaluated for this application; do not count repair episodes as new jobs')
    run = Analysis(store, dataset, purpose='follow-up', **options)
    try:
        events = [e for e in store.evidence(dataset, workflow) if e['kind'] == 'conversation']
        discovery_sources = set(store.get('analysis_runs', store.get('findings', proposal['finding_id'])['run_id'])['details'].get('source_ids', []))
        if any(e['source_id'] in discovery_sources for e in events):
            raise ValueError('Discovery history cannot serve as subsequent job evidence')
        subsequent = []
        excluded = []
        for event in events:
            timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Follow-up timestamps require a timezone')
            if timestamp.timestamp() > app['created_at']:
                subsequent.append(event)
            else:
                excluded.append(event['id'])
        events = subsequent
        run.details['excluded_before_application'] = excluded
        result = None
        if not events or workflow != proposal['details']['scope']['workflow']:
            result = {'eligible': False, 'eligibility_reason': 'No selected conversations for the applicable workflow',
                      'evidence': [], 'job_outcome': 'unknown', 'target_status': 'unknown', 'correction_evidence': [],
                      'acceptance_evidence': [], 'other_issues': [], 'recommendation': 'insufficient_evidence',
                      'reason': 'No relevant jobs observed'}
        else:
            # No truncation: oversized follow-up remains incomplete and can be supplied as a job-specific export.
            result = run.call('follow-up', INSTRUCTION, {'job_id': job_id, 'workflow': workflow, 'mode': mode,
                               'intervention': proposal['details'], 'intervention_hash': intervention_hash,
                               'events': [model_event(e) for e in events]})
            require_text(result, ['eligibility_reason', 'job_outcome', 'target_status', 'recommendation', 'reason'])
            if type(result.get('eligible')) is not bool or result['job_outcome'] not in {'accepted', 'incomplete', 'abandoned', 'unknown'}:
                raise ValueError('Malformed job eligibility or outcome')
            if result['target_status'] not in {'recurred', 'not_observed', 'unknown'} or result['recommendation'] not in {'keep', 'revise', 'remove', 'insufficient_evidence'}:
                raise ValueError('Malformed evaluation status')
            allowed = {e['id'] for e in events}
            store.citations(result.get('evidence'), allowed)
            for field in ('correction_evidence', 'acceptance_evidence'):
                if not isinstance(result.get(field), list):
                    raise ValueError('Missing evaluation citation list')
                if result[field]:
                    store.citations(result[field], allowed)
                    if any(store.get('events', ref)['role'] != 'user' for ref in result[field]):
                        raise ValueError('Corrections and acceptance must cite authored user messages')
            if result['target_status'] == 'recurred' and not result['correction_evidence']:
                raise ValueError('Recurrence needs correction evidence')
            if result['job_outcome'] == 'accepted' and not result['acceptance_evidence']:
                raise ValueError('Acceptance needs explicit user evidence')
            if not isinstance(result.get('other_issues'), list):
                raise ValueError('Missing other issues list')
            for issue in result['other_issues']:
                require_text(issue, ['observation'])
                store.citations(issue.get('evidence'), allowed)
            run.details['coverage'] = [{'event_id': e['id'], 'start': 0, 'end': len(e['text'])} for e in events]
        eligible = result['eligible']
        if not eligible:
            result.update(target_status='unknown', recommendation='insufficient_evidence')
        definitive = eligible and result['job_outcome'] == 'accepted' and result['target_status'] == 'not_observed'
        if not definitive and result['target_status'] != 'recurred':
            result['recommendation'] = 'insufficient_evidence'
        report = {'schema_version': 1, 'job_id': job_id, 'workflow': workflow, 'mode': mode,
                  'intervention_hash': intervention_hash, 'eligible_jobs': int(eligible),
                  'recurrence_jobs': (1 if result['target_status'] == 'recurred' else 0 if definitive else None) if eligible else None,
                  'summary': 'no_relevant_jobs_observed' if not eligible else
                             ('recurred' if result['target_status'] == 'recurred' else
                              'no_recurrence_observed' if definitive else 'outcome_unknown'),
                  'assessment': result, 'human_minutes_estimate': human_minutes,
                  'causal_effect': 'not_established', 'visual_review': 'not_performed_by_observer',
                  'production_usage': 'not_supplied', 'intervention_use': 'operator_declared_hash; current_trial_verified',
                  'created_at': time.time()}
        eid = identifier('evaluation')
        with store.db:
            store.db.execute('INSERT INTO evaluations VALUES (?,?,?,?,?)', (eid, app['proposal_id'], aid, run.id, encoded(report)))
            store.db.execute("UPDATE proposals SET status='evaluated' WHERE id=? AND status IN ('applied-to-trial','evaluated')", (app['proposal_id'],))
        run.details['evaluation_id'] = eid
        run.details['report'] = report
        return run.finish('completed')
    except (Exception, KeyboardInterrupt) as exc:
        return run.finish('incomplete', exc)
