"""Narrow public-photo continuation after a proved pre-submission setup stop."""
import copy
import hashlib
import json

SIGN_IN_STOP = 'ValueError: Complete sign-in in Chrome, then choose Done signing in in Task Relay Settings. No research was submitted.'


def confirmed(frozen, receipt):
    browser = frozen.get('browser', {})
    grants = browser.get('image_sources', [])
    outputs = frozen.get('outputs', [])
    return (
        frozen.get('backend', {}).get('type') == 'gemini-browser'
        and not frozen.get('execution') and not frozen.get('computer')
        and browser.get('profile') == 'managed' and browser.get('session_source') == 'settings'
        and browser.get('interaction_scope', '').lower().startswith('read only:')
        and 'no accounts' in browser.get('interaction_scope', '').lower()
        and not browser.get('uploads') and not browser.get('downloads')
        and len(grants) == 1 and len(outputs) == 1
        and outputs[0]['path'] == grants[0]['path']
        and outputs[0].get('media_type') == 'application/json'
        and receipt.get('status') == 'finished' and receipt.get('exit_code') == 1
        and receipt.get('reason') == SIGN_IN_STOP
        and receipt.get('external_outcome') == 'no_pending_response'
        and receipt.get('pending_requests') == []
        and receipt.get('api_requests') == 0 and receipt.get('tool_calls') == 0
        and receipt.get('browser', {}).get('actions') == []
        and receipt.get('browser', {}).get('uncertain_actions') == [])


def continuation(spec, attempt, policy):
    """Keep site/data/model authority; remove signed-in identity and bound time."""
    frozen = json.loads(attempt['frozen'])
    receipt = json.loads(attempt['receipt'])
    if not confirmed(frozen, receipt):
        raise ValueError('Public photo recovery requires exact pre-submission proof')
    from orchestrator.worker_capabilities import backend_for
    if spec.get('browser') != frozen['browser'] or backend_for(spec, frozen['backend']) != frozen['backend']:
        raise ValueError('Public photo recovery changed the original browser or model')
    from orchestrator.executors import request_limit
    if spec['limits']['tool_calls'] > policy['tool_calls'] or request_limit(spec) > policy['tool_calls']:
        raise ValueError('Public photo recovery exceeds the existing recovery grant')
    result = copy.deepcopy(spec)
    result['browser'].pop('session_source')
    result['browser']['profile'] = 'public-photo-' + hashlib.sha256(attempt['id'].encode()).hexdigest()[:16]
    result.pop('resource', None)  # Re-derived from the new isolated profile by assignment().
    result['limits']['seconds'] = min(result['limits']['seconds'], policy['seconds'])
    result['revision'] = dict(kind='public_photo_setup_recovery', source='existing_completion_recovery_grant', previous_attempt=attempt['id'],
                              instruction='Continue public read-only photo discovery in an isolated profile. The previous worker stopped before any provider request or browser action. Do not use accounts or modify browser settings.')
    return result


def validate_parent(rt, task, spec, backend, inputs):
    """Recheck the durable stop and granted continuation before dispatch."""
    from .completion_recovery import DELIVERY_POLICY
    parent=spec['revision']['previous_attempt']
    old=rt.db.execute('SELECT * FROM production_attempts WHERE id=?',(parent,)).fetchone()
    if (not old or old['run']!=task['run'] or old['task']!=task['id']
            or old['state']!='blocked' or task['latest']!=parent or task['attempts']!=1):
        raise ValueError('Public photo continuation lacks its exact stopped parent')
    grants=rt.db.execute('SELECT r.baseline,g.policy FROM completion_recoveries r JOIN completion_recovery_grants g ON g.pipeline=r.pipeline WHERE r.parent=?',(task['run'],)).fetchall()
    matching=[g for g in grants if any(item.get('attempt')==parent and item.get('kind')=='public_photo_setup' for item in json.loads(g['baseline'])['gaps'])]
    grant=matching[0] if len(matching)==1 else None
    if not grant or json.loads(grant['policy'])!=DELIVERY_POLICY or not any(
            g.get('attempt')==parent and g.get('kind')=='public_photo_setup'
            for g in json.loads(grant['baseline'])['gaps']):
        raise ValueError('Public photo continuation lacks its committed grant')
    prior=json.loads(rt.db.execute('SELECT spec FROM production_assignments WHERE id=?',(old['assignment'],)).fetchone()[0])
    from orchestrator import contracts
    expected=continuation(prior,old,DELIVERY_POLICY);expected['max_attempts']=2
    if contracts.assignment(expected)!=spec or backend!=json.loads(old['frozen'])['backend']:
        raise ValueError('Public photo continuation changed its frozen scope')
    identity=lambda values:sorted((i['path'],i['artifact'],i['sha256']) for i in values)
    if identity(inputs)!=identity(json.loads(old['frozen'])['inputs']):
        raise ValueError('Public photo continuation changed input versions')
