"""Test-only subprocess transport substitutes. Never imported by product code."""
import json
import os
from pathlib import Path
import time

MODEL='fixture-browser-model'
CONFIG={'api_key':'fixture-no-network-key','models':{'text':MODEL}}


def install():
    if os.environ.get('RELAY_BROWSER_PIPELINE_FIXTURE')!='1':raise RuntimeError('Explicit fixture environment required')
    from task_relay import gemini
    gemini.read_config=lambda:CONFIG
    gemini.Client.request=request
    from playwright.sync_api import BrowserType
    original=BrowserType.launch_persistent_context
    def launch(self,*args,**kwargs):
        kwargs['headless']=True
        context=original(self,*args,**kwargs)
        def route(route):
            from urllib.parse import urlsplit
            host=urlsplit(route.request.url).hostname
            if host in ('127.0.0.1','localhost'):route.continue_()
            elif host=='www.perplexity.ai':route.fulfill(status=200,content_type='text/html',body=PERPLEXITY)
            else:route.abort()
        context.route('**/*',route)
        return context
    BrowserType.launch_persistent_context=launch


def request(self,path,payload=None,**kwargs):
    if payload is None:return {'name':'models/'+MODEL,'supportedGenerationMethods':['generateContent']}
    frozen=json.loads(payload['contents'][0]['parts'][0]['text'])
    mode=os.environ.get('RELAY_BROWSER_PIPELINE_MODE','normal')
    if mode=='hold':time.sleep(30)
    if mode=='provider-lost':
        from task_relay.gemini import ProviderError
        raise ProviderError('fixture disconnected after submission',uncertain=True)
    history=[p['functionResponse'] for item in payload['contents'] for p in item.get('parts',[]) if 'functionResponse' in p]
    for item in history:
        if 'error' in item['response']:raise AssertionError('Unexpected real worker tool error: '+json.dumps(item))
    n=len(history);review=bool(frozen.get('review_of'))
    if n==0:
        name,args='file_read',dict(path=frozen['inputs'][0]['path'],offset=0,limit=24000)
    elif n==1:
        name,args='browser_open',{'url':os.environ['RELAY_BROWSER_PIPELINE_URL']+('/result' if review else '/form')}
    elif n==2 and not review:
        page=history[-1]['response'];target=next(x for x in page['controls'] if x['tag']=='INPUT')
        name,args='browser_fill',dict(tab=page['tab'],observation=page['observation'],ref=target['ref'],text='pipeline request',purpose='Submit the fixture request once')
    elif n==3 and not review:
        page=history[-1]['response'];target=next(x for x in page['controls'] if x['tag']=='BUTTON')
        name,args='browser_click',dict(tab=page['tab'],observation=page['observation'],ref=target['ref'],purpose='Submit the fixture request once')
    elif n==(2 if review else 4):
        page=history[-1]['response']
        if 'Submitted once' not in page['text']:raise AssertionError('Remote fixture result missing')
        name,args='file_write',dict(path=frozen['outputs'][0]['path'],text='Observed Submitted once at '+page['url']+'; no user acceptance inferred.')
    else:
        name,args='finish',dict(assignment_id=frozen['assignment_id'],summary='Inspected fixture evidence',
                decision='accept' if review else 'delivered',instruction='',
                checks=[dict(criterion=i,passed=True,evidence='Observed the fixture result and exact request') for i in range(1,len(frozen['criteria'])+1)])
    return {'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':5},'candidates':[{'finishReason':'STOP',
            'content':{'role':'model','parts':[{'functionCall':{'name':name,'args':args,'id':'fixture-'+str(n)}}]}}]}


PERPLEXITY='''<!doctype html><button aria-label="Profile avatar">Account</button><main>
<button aria-pressed="true">Search</button><section id="history"></section>
<div role="textbox" contenteditable="true"></div><button>Submit</button></main>
<script>
const box=document.querySelector('[role=textbox]');
const historyNode=document.querySelector('#history');
const turns=JSON.parse(localStorage.getItem(location.pathname)||'[]');
function show(){historyNode.replaceChildren(); for(const t of turns){
 const p=document.createElement('p');p.textContent=t;historyNode.append(p);
 for(const text of ['Edit query','Copy']){const b=document.createElement('button');b.textContent=text;historyNode.append(b);}}}
show();box.addEventListener('keydown',e=>{if(e.key!=='Enter')return;e.preventDefault();
 turns.push(box.innerText);box.innerText='';
 if(location.pathname==='/')history.replaceState({},'', '/search/11111111-1111-1111-1111-111111111111');
 localStorage.setItem(location.pathname,JSON.stringify(turns));show();});
</script>'''
