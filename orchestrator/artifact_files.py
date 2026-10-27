"""Declared evidence reads shared by record authors and operation workers.

Exact local bytes are not a code-execution grant or a semantic observation.
"""
import hashlib

DEFINITION=dict(name='artifact_inspect',description='Read exact artifact identity and byte count. This does not inspect visual appearance or infer semantic acceptance.',parameters=dict(type='object',properties=dict(path=dict(type='string')),required=['path'],additionalProperties=False))


def files(frozen,control):
    from .code_worker import CodeFiles
    class EvidenceFiles(CodeFiles):
        def read_bytes(self,path):
            raw=super().read_bytes(path)
            if path in self.inputs and hashlib.sha256(raw).hexdigest()!=self.inputs[path]['sha256']:raise ValueError('Frozen work input changed')
            return raw
        def call(self,name,args):
            if name=='artifact_inspect':
                if set(args)!={'path'}:raise ValueError('Inspect one exact declared artifact')
                path=args['path'];raw=self.read_bytes(path)
                return dict(path=path,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),visual_observation=False,semantic_acceptance=False)
            if name in ('python_run','python_checkpoint'):raise ValueError('Custom code is not granted by declared evidence tools')
            if name=='file_read' and args.get('path') in frozen.get('artifact_roles',{}).get('inputs',{}):
                from .artifact_roles import view
                route=view(self,args['path'])
                if route['tool'] in ('image_view','artifact_inspect'):
                    return dict(path=args['path'],inspection=route,note='Use the registered inspection tool on this assigned path to inspect the exact evidence through its registered representation. Metadata is not observation.')
            return super().call(name,args)
        def source_pack(self,max_bytes=None,paths=None):
            from .worker_capabilities import has_binary
            text=[p for p,i in self.inputs.items() if not has_binary(dict(inputs=[i]))]
            return super().source_pack(max_bytes,paths=text if paths is None else paths)
    return EvidenceFiles(frozen,control)

