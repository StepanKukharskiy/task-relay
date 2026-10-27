"""Pure content-port validation shared by admission, claim and execution.

MIME compatibility cannot prove a typed record contract. These checks never
convert arbitrary JSON, accept source claims or perform external actions.
"""
from . import operation_contracts as contracts
from .research_quality import load_json


def validate(task, ports, read):
    declared={i['path']:i for i in task['inputs']}
    for parameter,roles in ports:
        paths=task['execution']['parameters'][parameter]
        if paths is None:continue # Parameter schema already enforces whether null is allowed.
        if not isinstance(paths,list):paths=[paths]
        for path in paths:
            if path not in declared or declared[path].get('media_type')!='application/json':
                raise ValueError('Content port '+parameter+' requires a declared JSON input')
            raw=read(path)
            if raw is None:continue  # Future bytes are checked at claim/execute.
            try:
                data=load_json(raw)
                contract=data.get('contract') if isinstance(data,dict) else None
                family=contracts.identity(contract)
                if family.get('record_role') not in roles:raise ValueError('incompatible record role')
                contracts.validate_document(raw,contract)
                if data.get('complete') is not True:raise ValueError('unsealed record document')
            except (ValueError,KeyError,TypeError) as exc:
                raise ValueError('Input '+path+' for '+parameter+' requires a sealed registered '+
                    '/'.join(roles)+' contract; '+str(exc)+'. Use its registered record producer; arbitrary JSON cannot substitute.') from exc


def resolved(task, inputs):
    """Validate exact runtime-resolved blobs without changing their identity."""
    from pathlib import Path
    from .runtime import file_hash
    from .execution import adapter
    by_path={i['path']:i for i in inputs}
    def read(path):
        item=by_path[path];blob=Path(item['blob'])
        if file_hash(blob)!=item['sha256']:raise ValueError('Content input bytes changed: '+path)
        return blob.read_bytes()
    adapter(task['execution']['capability']).validate_content(task,read)
