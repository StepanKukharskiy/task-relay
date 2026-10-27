"""Offline app-server peer. Scripted model decisions, actual JSON-line pipes."""
import json
import sys
from pathlib import Path


def main():
    steps=json.loads(Path(sys.argv[1]).read_text());cursor=0;model=None;turn='turn';turn_number=0;declared=set()
    def send(value):print(json.dumps(value),flush=True)
    def next_call():
        nonlocal cursor
        if cursor>=len(steps):raise SystemExit(0)
        step=steps[cursor];cursor+=1
        if isinstance(step,dict):
            if step.get('disconnect'):raise SystemExit(0)
            for event in step.get('events',[]):send(event)
            return
        name,args=step
        if len(sys.argv)>3 and sys.argv[3]=='strict':assert name in declared, 'Tool omitted from frozen lifecycle ceiling: '+name
        send(dict(method='thread/tokenUsage/updated',params=dict(threadId='thread',turnId=turn,tokenUsage=dict(total=dict(inputTokens=cursor*10,outputTokens=cursor*2,totalTokens=cursor*12)))))
        send(dict(id=100+cursor,method='item/tool/call',params=dict(threadId='thread',turnId=turn,callId='call-'+str(cursor),namespace=None,tool=name,arguments=args)))
    for line in sys.stdin:
        request=json.loads(line);method=request.get('method')
        if method=='initialize':send(dict(id=request['id'],result={}))
        elif method=='account/read':
            account_type=sys.argv[2] if len(sys.argv)>2 else 'chatgpt'
            send(dict(id=request['id'],result=dict(account=dict(type=account_type,email='fixture-private-account'))))
        elif method=='config/read':
            send({'id':request['id'],'result':{'config':{'mcp_servers':{'unrelated':{'enabled':True,'env':{'SECRET':'fixture-secret-must-not-be-logged'}}}}}})
        elif method=='thread/start':
            params=request['params'];model=params['model']
            assert params['config']['mcp_servers']['unrelated']['enabled'] is False
            assert params['environments']==[] and params['sandbox']=='read-only'
            assert all(tool['type']=='function' for tool in params['dynamicTools'])
            declared={tool['name'] for tool in params['dynamicTools']}
            authority=params['config']['relay_tool_authority']
            assert authority['dynamic_tools']==sorted(tool['name'] for tool in params['dynamicTools'])
            assert authority['hosted_tools']==(['web_search'] if params['config']['web_search']=='live' else [])
            send(dict(id=request['id'],result=dict(model=model,thread=dict(id='thread'))))
        elif method=='turn/start':
            turn_number+=1;turn='turn' if turn_number==1 else 'turn-'+str(turn_number)
            # Real app-server emits transcript items before its first model
            # decision. They are observations, not requests to execute tools.
            for kind in ('userMessage','contextCompaction'):
                item=dict(id='transcript-'+kind,type=kind)
                if kind=='userMessage':item['content']=request['params']['input']
                for event in ('item/started','item/completed'):
                    send(dict(method=event,params=dict(threadId='thread',turnId=turn,item=item)))
            next_call() # Exercise notifications/server requests preceding RPC reply.
            send(dict(id=request['id'],result=dict(turn=dict(id=turn))))
        elif 'result' in request:next_call()
        elif 'error' in request:raise SystemExit(0)


if __name__=='__main__':main()
