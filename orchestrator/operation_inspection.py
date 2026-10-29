"""Registered receipt observations. Hooks do not dispatch, queue or accept work."""
import json

def search(control, result, details):
    operation=control/'operation.json'
    pending=[];confirmed=[]
    for path in control.glob('query-*/search-*.json'):
        try:
            record=json.loads(path.read_text())
            if record.get('status') in ('submitted','uncertain'):
                receipt=None
                if record.get('backend',{}).get('type')=='codex-agent':
                    from .codex_rejection import proof
                    receipt=proof(path.parent/'codex')
                    if receipt and receipt['model']!=record['backend'].get('model'):receipt=None
                if receipt:confirmed.append(dict(search=str(path.relative_to(control)),proof=receipt))
                else:pending.append(str(path.relative_to(control)))
        except (OSError,ValueError):pending.append(str(path.relative_to(control)))
    if confirmed and not pending:
        original=dict(details)
        details.update(outcome='rejected',reason=confirmed[-1]['proof']['detail']['message'],usage=None)
        result.update(external_outcome='rejected',rejection_reconciliation=dict(original=original,confirmed=confirmed,replayed=False))
    if pending:result.update(status='uncertain',external_outcome='unknown',pending_requests=pending,
        reason='Public search has no confirmed response; its saved intent is held without replay.')


def rendered(control, result, details):
    operation=control/'operation.json'
    pending=sorted({str(p.parent.name) for pattern,outcome in (('render-*/render-intent.json','render-outcome.json'),('render-*/http-intent.json','http-outcome.json'),('render-*/fallback-read-intent.json','fallback-read-outcome.json')) for p in control.glob(pattern) if not p.with_name(outcome).exists()})
    if pending:result.update(status='uncertain',external_outcome='unknown',pending_requests=pending,
        reason='Rendered source read has no confirmed outcome; preserve its intent without replay.')


def local_render(control, result, details):
    operation=control/'operation.json'
    if not ((control/'media-intent.json').exists() or (control/'hyperframes-intent.json').exists()) or operation.exists():return
    result.update(external_outcome='unknown',local_terminal=True)
    if not (control/'cancel.json').exists():
        result.update(status='uncertain',reason='Local render has no conclusive receipt; reconcile owned processes and partial files before explicit recovery. No automatic replay.')


def library_script(control, result, details):
    operation=control/'operation.json'
    uncertain=details.get('outcome')=='uncertain' or ((control/'rhino3dm-script-intent.json').exists() and not operation.exists())
    if uncertain:
        result.update(external_outcome='unknown',local_terminal=True)
        if not (control/'cancel.json').exists():
            result.update(status='uncertain',reason='Standalone library script has no conclusive receipt; no automatic replay.')


def sketchup(control, result, details):
    operation=control/'operation.json'
    uncertain=details.get('outcome')=='uncertain' or ((control/'sketchup-intent.json').exists() and not operation.exists())
    if uncertain:
        result.update(external_outcome='unknown',local_terminal=True)
        if not (control/'cancel.json').exists():
            result.update(status='uncertain',reason='SketchUp execution has no conclusive receipt; no automatic replay.')


def api(control, result, details):
    operation=control/'operation.json'
    sent=(control/'request.json').exists();received=(control/'response.json').exists()
    if received:
        response=json.loads((control/'response.json').read_text())
        details.update(upstream_id=details.get('upstream_id') or response.get('responseId') or response.get('id') or response.get('request_id'),usage=response.get('usageMetadata',response.get('usage',{})))
    if (control/'remote.json').exists(): details['remote']=json.loads((control/'remote.json').read_text())
    uncertain=details.get('outcome')=='uncertain' or (sent and not received and details.get('outcome')!='rejected')
    if uncertain:
        result['external_outcome']='unknown'
        if not (control/'cancel.json').exists():
            result.update(status='uncertain',reason='API submission outcome is unknown; no automatic retry. Local process has stopped.',local_terminal=True)
    elif received:result['external_outcome']='response_received'
    else:
        local_rejection=(details.get('outcome')=='rejected' and details.get('effect')=='none'
            and details.get('submission')=='not_started' and details.get('failure_kind')=='local_validation')
        result['external_outcome']='not_submitted' if local_rejection or not sent else 'rejected'


def native_effect(control,result,details):
    """A generic wrapper error cannot stand in for a host's terminal receipt."""
    intents=[p.name for p in control.glob('*-intent.json')]
    if not intents:return
    confirmed=(details.get('execution')==result.get('execution') and details.get('outcome') in ('completed','failed','rejected'))
    if not confirmed:
        from .local_media_receipts import historical_failure
        proof=historical_failure(control,result,details)
        if proof:
            confirmed=True
            result['local_failure_binding']=proof
    if confirmed:
        result['operation_terminal_confirmed']=True
        return
    result.update(external_outcome='unknown',local_terminal=True,pending_requests=intents)
    if not (control/'cancel.json').exists():
        result.update(status='uncertain',reason='Host intent has no matching terminal adapter receipt; reconcile the original effect without replay.')
