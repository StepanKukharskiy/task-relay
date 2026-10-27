"""Provider-neutral Python tool over a verified native host sandbox."""
import hashlib
import json
from pathlib import Path
import uuid
import os

from . import contracts as c
from .gemini_worker import Files
from .workers import atomic


def definitions():
    return [{'name':'python_run','description':'Run Python in the approved native sandbox. Read exact inputs below os.environ["RELAY_INPUTS"]. The working directory and RELAY_OUTPUTS retain scripts, intermediate files and outputs from the last successful call in this assignment; Python variables do not persist. Only declared outputs become deliverable artifacts. No network, subprocesses or native apps. All working files share the existing output byte limit.',
             'parameters':{'type':'object','properties':{'code':{'type':'string','description':'One compact incremental edit, at most 6000 UTF-8 bytes. Load and transform existing data instead of retyping it. Save progress in declared output paths.'},'seconds':{'type':'integer'}},'required':['code','seconds']}}]


def checkpoint_definition(python_tool):
    """Registered restricted phase of the same granted Python capability."""
    import copy
    value=copy.deepcopy(python_tool)
    value.update(name='python_checkpoint',description='Make a real incremental edit to a declared draft output. Read existing inputs or saved drafts and preserve their content. Save one or more changed outputs below RELAY_OUTPUTS; remaining outputs can follow in later calls. Do not write placeholders or empty documents. Printing or rewriting unchanged files is not progress. Use compact Python transformations rather than retyping source content. Same native sandbox and deadline as python_run.')
    return value


class CodeFiles(Files):
    def __init__(self,frozen,control):
        self.initialize_files(frozen,browser=False)
        self.control=Path(control)
        if 'runtime.log' in self.outputs:raise ValueError('runtime.log is reserved by the native runtime.')
        total=0
        for path,item in self.inputs.items():
            raw=self.read_bytes(path);total+=len(raw)
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Frozen code input changed.')
        if total>100000000:raise ValueError('Code input pack exceeds 100 MB.')

    def workspace(self):
        """Last committed successful call, never uncertain or failed writes."""
        saved=[]
        for path in self.control.glob('code-*/outcome.json'):
            receipt=json.loads(path.read_text())
            if receipt.get('returncode')==0 and 'workspace' in receipt:
                intent=json.loads(path.with_name('intent.json').read_text())
                if intent.get('assignment')!=self.frozen['assignment_id']:raise ValueError('Code workspace belongs to another assignment')
                saved.append((intent['sequence'],path.parent/'outputs',receipt['workspace']))
        return max(saved,key=lambda item:item[0])[1:] if saved else (None,{})

    def snapshot(self,folder,maximum):
        from task_relay.filesystem import FILES,Grant
        blobs={};total=0;root=Path(folder)
        grant=Grant(root,self.frozen['assignment_id'])
        for directory,dirs,names in os.walk(root,followlinks=False):
            for name in dirs:
                if (Path(directory)/name).is_symlink():raise ValueError('Code workspace contains a linked directory')
            for name in names:
                path=(Path(directory)/name).relative_to(root).as_posix()
                if path=='runtime.log':continue
                c.relative(path)
                if len(blobs)>=4096:raise ValueError('Code workspace file limit exceeded')
                raw=FILES.read(grant,path,maximum-total);total+=len(raw);blobs[path]=raw
        return blobs

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
        previous,manifest=self.workspace();code=args['code']
        if previous:
            # Private seed is copied by trusted wrapper code inside the existing
            # sandbox. Native host authority and runtime identity are unchanged.
            seed=inputs/('.relay-work-'+uuid.uuid4().hex);seed.mkdir()
            grant=Grant(previous,self.frozen['assignment_id'],frozenset(manifest))
            total=0
            for path,detail in manifest.items():
                raw=FILES.read(grant,path,self.frozen['limits']['output_bytes']-total);total+=len(raw)
                if len(raw)!=detail['bytes'] or hashlib.sha256(raw).hexdigest()!=detail['sha256']:raise ValueError('Saved code workspace changed')
                target=seed/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            code='import shutil as _relay_copy\n_relay_copy.copytree('+repr(str(seed))+', ".", dirs_exist_ok=True)\ndel _relay_copy\nexec(compile('+repr(code)+', "<relay-code>", "exec"), globals())'
        atomic(folder/'intent.json',{'runtime':runtime['id'],'assignment':self.frozen['assignment_id'],'sequence':len(pending)+1,
            'code_sha256':hashlib.sha256(args['code'].encode()).hexdigest(),'executed_code_sha256':hashlib.sha256(code.encode()).hexdigest(),'seconds':args['seconds']})
        result=native_code_host.run(runtime['runtime'],folder,code,args['seconds'],self.frozen['limits']['output_bytes'],lambda:(self.control/'cancel.json').exists())
        blobs={};maximum=self.frozen['limits']['output_bytes']
        workspace={}
        if result['returncode']==0:
            if Path(result['outputs'])!=folder/'outputs':raise ValueError('Code workspace escaped its owned directory')
            saved=self.snapshot(result['outputs'],maximum)
            workspace={p:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in saved.items()}
            blobs={p:raw for p,raw in saved.items() if p in self.outputs}
            if sum(map(len,blobs.values()))+sum(n for p,n in self.written.items() if p not in blobs)>maximum:raise ValueError('Code output byte budget exceeded.')
            for path,raw in blobs.items():FILES.write(self.grant(),path,raw);self.written[path]=len(raw)
        receipt={k:result[k] for k in ('returncode','log')}
        receipt['outputs']={p:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for p,raw in blobs.items()}
        if result['returncode']==0:receipt['workspace']=workspace
        atomic(folder/'outcome.json',receipt)
        return {k:v for k,v in receipt.items() if k!='workspace'}|dict(working_files=len(workspace),working_bytes=sum(d['bytes'] for d in workspace.values()))
