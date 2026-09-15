"""Provider-neutral Python tool over a verified native host sandbox."""
import hashlib
import json
from pathlib import Path
import uuid

from . import contracts as c
from .gemini_worker import Files
from .workers import atomic


def definitions():
    return [{'name':'python_run','description':'Run Python in the approved native sandbox. Read exact inputs below os.environ["RELAY_INPUTS"], write declared outputs below os.environ["RELAY_OUTPUTS"]. No network, subprocesses or native apps. Each call is fresh; only declared written outputs persist.',
             'parameters':{'type':'object','properties':{'code':{'type':'string'},'seconds':{'type':'integer'}},'required':['code','seconds']}}]


class CodeFiles(Files):
    def __init__(self,frozen,control):
        self.frozen=frozen;self.root=Path(frozen['workspace']);self.control=Path(control)
        self.inputs={x['path']:x for x in frozen['inputs']};self.outputs={x['path'] for x in frozen['outputs']}
        self.written={};self.browser=False;self.captures=set();self.capture_outputs=set()
        if 'runtime.log' in self.outputs:raise ValueError('runtime.log is reserved by the native runtime.')
        total=0
        for path,item in self.inputs.items():
            raw=self.read_bytes(path);total+=len(raw)
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Frozen code input changed.')
        if total>100000000:raise ValueError('Code input pack exceeds 100 MB.')

    def read_bytes(self,path):
        from task_relay.filesystem import FILES
        return FILES.read(self.grant(),path,100000000)

    def call(self,name,args):
        if not isinstance(args,dict):raise ValueError('Tool arguments must be an object.')
        if name=='python_run':return self.run(args)
        if name=='file_read':
            if set(args)!={'path','offset','limit'} or type(args['offset']) is not int or args['offset']<0 or type(args['limit']) is not int or not 1<=args['limit']<=24000:raise ValueError('Invalid read page.')
            raw=self.read_bytes(args.get('path',''))
            from .worker_capabilities import has_binary
            item=next((i for i in self.frozen['inputs']+self.frozen['outputs'] if i['path']==args['path']),{'path':args['path']})
            binary=has_binary({'inputs':[item]})
            try:raw.decode('utf-8')
            except UnicodeError:binary=True
            if binary:return {'path':args['path'],'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'note':'Inspect this binary file locally with python_run; extracted text and code logs can go to the model.'}
        return super().call(name,args)

    def run(self,args):
        from task_relay import code_runtime,native_code_host
        from task_relay.filesystem import FILES,Grant
        if set(args)!={'code','seconds'} or not isinstance(args['code'],str) or not 1<=len(args['code'].encode())<=100000:
            raise ValueError('Provide Python code of at most 100 KB and a bounded deadline.')
        if type(args['seconds']) is not int or not 1<=args['seconds']<=min(120,self.frozen['limits']['seconds']):raise ValueError('Code call deadline must be 1–120 seconds within the task limit.')
        runtime=code_runtime.available(self.frozen['backend']['runtime'])
        pending=list(self.control.glob('code-*/intent.json'))
        if any(not p.with_name('outcome.json').exists() for p in pending):raise ValueError('A previous code execution has no outcome; no automatic replay.')
        ident=uuid.uuid4().hex;folder=self.control/('code-'+ident);folder.mkdir()
        inputs=folder/'inputs';inputs.mkdir()
        for path in sorted(set(self.inputs)|set(self.written)):
            c.relative(path);target=inputs/path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(self.read_bytes(path));target.chmod(0o444)
        atomic(folder/'intent.json',{'runtime':runtime['id'],'code_sha256':hashlib.sha256(args['code'].encode()).hexdigest(),'seconds':args['seconds']})
        result=native_code_host.run(runtime['runtime'],folder,args['code'],args['seconds'],self.frozen['limits']['output_bytes'],lambda:(self.control/'cancel.json').exists())
        blobs={};maximum=self.frozen['limits']['output_bytes']
        if result['returncode']==0:
            grant=Grant(Path(result['outputs']),self.frozen['assignment_id'],frozenset(self.outputs))
            for path in self.outputs:
                try:blobs[path]=FILES.read(grant,path,maximum)
                except FileNotFoundError:continue
            if sum(map(len,blobs.values()))+sum(n for p,n in self.written.items() if p not in blobs)>maximum:raise ValueError('Code output byte budget exceeded.')
            for path,raw in blobs.items():FILES.write(self.grant(),path,raw);self.written[path]=len(raw)
        receipt={k:result[k] for k in ('returncode','log')}
        receipt['outputs']={p:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for p,raw in blobs.items()}
        atomic(folder/'outcome.json',receipt);return receipt
