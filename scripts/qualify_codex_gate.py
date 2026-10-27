#!/usr/bin/env python3
"""Run the real gated app-server against a local scripted provider and MCP peer.

No API keys, login changes or paid model calls. Provider-private instructions are
not collected: HTTP evidence retains tools and function results only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from orchestrator.codex_transport import Client, settings
from orchestrator.tool_authority import manifest, CONTRACT
from orchestrator.workers import atomic


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class Server(ThreadingHTTPServer):
    def __init__(self,folder):
        super().__init__(('127.0.0.1',0),Handler)
        self.folder=folder;self.steps=[];self.requests=[];self.auth=False;self.searches=[]


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        self.server.auth |= bool(self.headers.get('Authorization'))
        value=json.loads(raw)
        if self.path.endswith('/alpha/search'):
            self.server.searches.append(dict(path=self.path,commands=value.get('commands')))
            atomic(self.server.folder/'search-observations.json',self.server.searches)
            body=json.dumps(dict(output='Controlled public source result',results=[dict(url='https://example.org/fixture',title='Controlled source')])).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            return
        declared=value.get('tools') or [tool for item in value.get('input',[]) if item.get('type')=='additional_tools' for tool in item.get('tools',[])]
        receipt=dict(path=self.path,model=value.get('model'),tools=declared,
            function_results=[item for item in value.get('input',[]) if item.get('type')=='function_call_output'])
        self.server.requests.append(receipt)
        atomic(self.server.folder/'provider-observations.json',self.server.requests)
        number=len(self.server.requests);ident='offline-'+str(number)
        events=[dict(type='response.created',response=dict(id=ident))]
        step=self.server.steps.pop(0) if self.server.steps else None
        if step:
            name,args=step
            namespace,name = name if isinstance(name,tuple) else (None,name)
            item=dict(type='function_call',call_id=ident,name=name,arguments=json.dumps(args))
            if namespace:item['namespace']=namespace
            events.append(dict(type='response.output_item.done',item=item))
        else:
            events.append(dict(type='response.output_item.done',item=dict(type='message',id=ident,role='assistant',content=[dict(type='output_text',text='Controlled completion')],phase='final_answer')))
        events.append(dict(type='response.completed',response=dict(id=ident,usage=dict(input_tokens=1,output_tokens=1,total_tokens=2))))
        body=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


class Peer(Client):
    """Real binary, explicit unauthenticated local provider; no production bypass."""
    def __enter__(self):
        self.control.mkdir(parents=True,exist_ok=True)
        self.stderr=(self.control/'codex-stderr.txt').open('ab')
        env=dict(os.environ)
        for key in ('OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL'):env.pop(key,None)
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0,env=env,cwd=self.control)
        self.selector=selectors.DefaultSelector();self.selector.register(self.process.stdout,selectors.EVENT_READ)
        self.rpc('initialize',dict(clientInfo=dict(name='relay_gate_qualification',version='1'),capabilities=dict(experimentalApi=True)))
        self.write(dict(method='initialized'))
        return self


def config(peer,server,folder):
    value=settings();value.pop('forced_login_method',None)
    value.update(model_provider='relay_fixture',cli_auth_credentials_store='ephemeral')
    value['features']['shell_tool']=True  # Gate, not a hidden-tool flag, must deny it.
    value['model_providers']={'relay_fixture':dict(name='Unauthenticated local fixture',
        base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',wire_api='responses',
        requires_openai_auth=False,supports_websockets=False,supports_standalone_web_search=True,request_max_retries=0,stream_max_retries=0)}
    ambient=peer.rpc('config/read',dict(includeLayers=False),journal=False).get('config',{})
    value['mcp_servers']={key:dict(enabled=False) for key in ambient.get('mcp_servers',{})}
    value['mcp_servers']['relay_gate_fixture']=dict(command=sys.executable,args=[str(ROOT/'tests/codex_gate_mcp_fixture.py'),str(folder/'mcp-methods.jsonl'),str(folder/'native-effect')],enabled=True)
    return value


def run_case(binary,folder,names,steps,*,hosted=(),invalid=None,model_mode=None,lite=False):
    folder.mkdir(parents=True,exist_ok=True)
    server=Server(folder);server.steps=list(steps)
    listener=threading.Thread(target=server.serve_forever,daemon=True);listener.start()
    command=[str(binary),'-c','cli_auth_credentials_store="ephemeral"','-c','features.hooks=false',
             '-c','features.plugins=false','-c','features.apps=false']
    if model_mode:
        catalog=folder/'model-catalog.json'
        atomic(catalog,dict(models=[dict(slug='mock-model',display_name='Controlled model',
            base_instructions='Controlled fixture',supported_reasoning_levels=[],shell_type='disabled',
            visibility='list',supported_in_api=True,priority=0,support_verbosity=False,
            truncation_policy=dict(mode='tokens',limit=10000),experimental_supported_tools=[],tool_mode=model_mode,use_responses_lite=lite)]))
        command.extend(['-c','model_catalog_json='+json.dumps(str(catalog))])
    declarations=[dict(name=name,description='Controlled brokered fixture',parameters=dict(type='object',properties={})) for name in names]
    try:
        with Peer({},dict(model='mock-model'),folder,120,command=command) as peer:
            cfg=config(peer,server,folder);cfg['web_search']='live' if hosted or lite else 'disabled'
            if invalid!='missing':cfg['relay_tool_authority']=invalid if isinstance(invalid,dict) else manifest(declarations,hosted_tools=hosted)
            params=dict(model='mock-model',modelProvider='relay_fixture',approvalPolicy='never',sandbox='workspace-write',
                cwd=str(folder),ephemeral=True,config=cfg,baseInstructions='Controlled offline tool authority test.',
                developerInstructions='Use the declared tool only.',dynamicTools=[dict(type='function',name=t['name'],description=t['description'],inputSchema=t['parameters'],deferLoading=False) for t in declarations],
                environments=[],runtimeWorkspaceRoots=[],selectedCapabilityRoots=[],allowProviderModelFallback=False)
            atomic(folder/'thread-request.json',params)
            if invalid is not None:
                try:peer.rpc('thread/start',params)
                except ValueError:
                    assert not server.requests,'Invalid authority reached inference'
                    return dict(rejected=True,requests=[],auth=server.auth)
                raise AssertionError('Invalid authority accepted')
            reply=peer.rpc('thread/start',params);peer.thread=reply['thread']['id']
            turn=peer.rpc('turn/start',dict(threadId=peer.thread,input=[dict(type='text',text='Exercise the controlled tool sequence')],model='mock-model',approvalPolicy='never'))
            peer.turn=turn['turn']['id'];calls=[];search_items=[]
            while True:
                event=peer.events.pop(0) if peer.events else peer.receive()
                method=event.get('method');args=event.get('params',{})
                if 'id' in event and method:
                    assert method=='item/tool/call',event
                    assert args['tool'] in names and args.get('namespace') is None,event
                    calls.append(args['tool'])
                    peer.write(dict(id=event['id'],result=dict(success=True,contentItems=[dict(type='inputText',text='Controlled Relay result; no native effect')])) )
                if method=='item/completed' and args.get('item',{}).get('type')=='webSearch':search_items.append(args['item'])
                if method=='turn/completed' and args.get('turn',{}).get('id')==peer.turn:
                    assert args['turn']['status']=='completed',args
                    break
            assert not (folder/'native-effect').exists(),'MCP resource or native tool handler ran'
            assert not (folder/'shell-effect').exists(),'Native shell handler ran'
            return dict(calls=calls,requests=server.requests,auth=server.auth,searches=server.searches,search_items=search_items)
    finally:
        server.shutdown();server.server_close();listener.join(timeout=2)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();binary=args.binary.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    marker=json.loads(subprocess.check_output([str(binary),'--relay-tool-gate-info']))
    assert marker['enforcement']==CONTRACT
    checks={};results={}
    results['missing']=run_case(binary,out/'missing',[],[],invalid='missing');checks['missing_authority']=True
    results['mismatch']=run_case(binary,out/'mismatch',[],[],invalid=dict(version=1,dynamic_tools=['ungranted'],hosted_tools=[]));checks['mismatched_authority']=True
    for name in ('first','restart'):
        folder=out/name
        results[name]=run_case(binary,folder,['relay_probe'],[
            ('shell_command',dict(command='touch '+str(folder/'shell-effect'))),
            ('list_mcp_resources',dict(server='relay_gate_fixture')),
            ('future_undeclared_tool',{}),('relay_probe',{})])
        assert results[name]['calls']==['relay_probe']
        for request in results[name]['requests']:
            assert request['tools'] and all(t.get('type')=='function' and t.get('name')=='relay_probe' for t in request['tools']),request['tools']
        events=(folder/'codex-events.jsonl').read_text()
        assert events.count('RELAY_TOOL_AUTHORITY')>=3,'Missing pre-execution denial receipts'
    checks.update(closed_surface=True,denied_native_effects=True,dynamic_dispatch=True,restart=True)
    results['model_override']=run_case(binary,out/'model-override',['relay_probe'],
        [('exec',dict(code='throw new Error("native code must not run")')),('relay_probe',{})],model_mode='code_mode_only')
    assert results['model_override']['calls']==['relay_probe']
    assert all(request['tools'] and all(t.get('type')=='function' and t.get('name')=='relay_probe' for t in request['tools']) for request in results['model_override']['requests'])
    checks['model_override']=True
    results['collision']=run_case(binary,out/'collision',['list_mcp_resources'],[('list_mcp_resources',dict(server='relay_gate_fixture'))])
    assert results['collision']['calls']==['list_mcp_resources'];checks['name_collision']=True
    results['hosted']=run_case(binary,out/'hosted',[],[],hosted=['web_search'],model_mode='code_mode_only')
    assert results['hosted']['requests'] and all(request['tools'] and all(t.get('type')=='web_search' for t in request['tools']) for request in results['hosted']['requests'])
    checks['hosted_scope']=True
    search_call=(('web','run'),dict(search_query=[dict(q='controlled source')]))
    results['standalone_denied']=run_case(binary,out/'standalone-denied',['relay_probe'],[search_call,('relay_probe',{})],model_mode='code_mode_only',lite=True)
    assert results['standalone_denied']['calls']==['relay_probe']
    assert not results['standalone_denied']['searches'] and not results['standalone_denied']['search_items']
    results['standalone']=run_case(binary,out/'standalone',[],[search_call],hosted=['web_search'],model_mode='code_mode_only',lite=True)
    assert len(results['standalone']['searches'])==1
    assert len(results['standalone']['search_items'])==1
    assert results['standalone']['search_items'][0]['results'][0]['url']=='https://example.org/fixture'
    for request in results['standalone']['requests']:
        assert request['tools'] and all(t.get('type')=='namespace' and t.get('name')=='web' and [f['name'] for f in t['tools']]==['run'] for t in request['tools']),request['tools']
    checks['standalone_search']=True
    assert not any(result['auth'] for result in results.values());checks['no_credentials']=True
    patch=ROOT/'runtime-patches/codex-tool-authority-v1.patch'
    proof=dict(version=1,contract=CONTRACT,passed=True,checks=checks,executable_sha256=digest(binary),patch_sha256=digest(patch),
        scope='Actual custom app-server binary, local scripted HTTP and MCP peers. No live model or native application qualification.',paid_api_calls=False)
    atomic(out/'qualification.json',proof)
    from orchestrator.codex_gate import UPSTREAM_REVISION
    atomic(out/'qualified.json',dict(version=1,contract=CONTRACT,upstream_revision=UPSTREAM_REVISION,patch_sha256=proof['patch_sha256'],executable=str(binary),executable_sha256=proof['executable_sha256'],qualification=str(out/'qualification.json'),qualification_sha256=digest(out/'qualification.json')))
    print(json.dumps(proof,indent=2))


if __name__=='__main__':main()
