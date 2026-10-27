"""Proof for a changed local worker after a confirmed zero-dispatch failure."""
import json
from pathlib import Path
from . import contracts as c,executors
from .runtime import file_hash,safe_file
from .operation_session import outcome


def prove(rt,task,attempt):
    frozen=json.loads(attempt['frozen']);receipt=json.loads(attempt['receipt'] or '{}');spec=rt.spec(task)
    if (task['status']!='blocked' or attempt['state']!='blocked' or task['latest']!=attempt['id']
            or task['assignment']!=attempt['assignment'] or task['attempts']>=spec['max_attempts']
            or frozen.get('backend',{}).get('type') not in (*executors.FILE_TYPES,*executors.CODE_TYPES)
            or any(frozen.get(k) or spec.get(k) for k in ('execution','browser','computer','user_gate'))
            or receipt.get('status')!='finished' or not receipt.get('exit_code')
            or receipt.get('token')!=attempt['id'] or receipt.get('external_outcome')!='no_pending_response'
            or receipt.get('pending_requests')!=[] or receipt.get('api_requests')!=0
            or receipt.get('tool_calls')!=0 or receipt.get('cleanup_error')):return None
    # Frozen instructions, selected provider and all per-attempt authority stay exact.
    for key in ('instruction','criteria','tools','limits','inputs','outputs','job_owner','worker'):
        if key=='inputs':continue # frozen inputs additionally contain exact resolved hashes
        if spec.get(key)!=frozen.get(key):return None
    folder=rt.root/'workers'/attempt['id']
    if list(folder.glob('api-*.request.json')) or list(folder.glob('tool-*.json')) or list(folder.glob('code-*/intent.json')):return None
    from . import gemini_worker
    before=frozen.get('runtime_sources',{}).get('gemini_worker.py');after=file_hash(gemini_worker.__file__)
    if not before or before==after:return None
    journals={}
    for name in ('done.json','agent-result.json'):
        path=folder/name
        if not path.is_file() or path.is_symlink():return None
        journals[name]=file_hash(path)
    done=json.loads((folder/'done.json').read_text())
    if done.get('token')!=attempt['id'] or done.get('exit_code')!=receipt['exit_code'] or done.get('tool_calls')!=0:return None
    if json.loads((folder/'agent-result.json').read_text()).get('outcome')!='failed':return None
    workspace=Path(frozen['workspace'])
    if (workspace/'.relay/result.json').exists():return None
    if any((workspace/o['path']).exists() for o in frozen['outputs']):return None
    if rt.db.execute('SELECT 1 FROM production_artifacts WHERE attempt=?',(attempt['id'],)).fetchone():return None
    bound={i['path']:i for i in frozen['inputs']}
    for item in spec['inputs']:
        selected=rt.artifact(item['artifact']) if 'artifact' in item else rt.output(task['run'],item['from_task'],item['output'])
        if not selected or item['path'] not in bound or selected['id']!=bound[item['path']]['artifact']:return None
    inputs=[]
    for i in frozen['inputs']:
        a=rt.artifact(i['artifact'])
        if a['sha256']!=i['sha256'] or file_hash(a['blob'])!=i['sha256'] or file_hash(safe_file(workspace,i['path']))!=i['sha256']:return None
        inputs.append(dict(artifact=i['artifact'],path=i['path'],sha256=i['sha256']))
    for other in rt.db.execute('SELECT * FROM production_tasks WHERE run=?',(task['run'],)):
        if other['attempts'] and task['id'] in rt.spec(other)['dependencies']:return None
    proof=dict(frozen_sha256=c.digest(frozen),receipt_sha256=c.digest(receipt),journals=journals,
               inputs=inputs,implementation=dict(before=before,after=after))
    return proof,outcome('validate','yielded','confirmed_zero_dispatch_worker_change',effect='none')
