"""Offline MCP effect sentinel. Used only by the Codex gate qualifier."""
import json
import sys
from pathlib import Path

for line in sys.stdin:
    request=json.loads(line);method=request.get('method')
    with Path(sys.argv[1]).open('a') as stream:stream.write(json.dumps(dict(method=method))+'\n')
    if 'id' not in request:continue
    if method=='initialize':
        result=dict(protocolVersion='2024-11-05',capabilities=dict(tools={},resources={}),serverInfo=dict(name='relay-gate-fixture',version='1'))
    elif method=='tools/list':
        result=dict(tools=[dict(name='touch',description='Controlled sentinel effect',inputSchema=dict(type='object',properties={}))])
    elif method in ('resources/list','resources/templates/list','tools/call','resources/read'):
        Path(sys.argv[2]).write_text(method)
        result={'resources':[]} if method=='resources/list' else {'resourceTemplates':[]} if method=='resources/templates/list' else {'content':[dict(type='text',text='sentinel effect')]}
    else:result={}
    print(json.dumps(dict(jsonrpc='2.0',id=request['id'],result=result)),flush=True)
