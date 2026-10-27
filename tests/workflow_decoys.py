"""Synthetic boundary adapters; production orchestration remains unpatched."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from orchestrator import browser_images, execution
from task_relay import orchestrator_web
from tests.test_mixed_execution import LocalRegistered, Client, operation
from orchestrator.step_runner import execute
from orchestrator.workers import atomic
from tests.test_image_sources import photo, subject
from tests.test_web_sources import CONFIG

PRODUCTS = [dict(id=name, product_url='https://retailer.example/'+name,
                 price_usd=100+index, image_url='https://images.example/'+name+'.jpg')
            for index,name in enumerate(('one','two','three'))]

class SourcePages:
    calls = []
    error = None
    products = PRODUCTS
    def __init__(self,receipt,config):
        self.receipt=Path(receipt)
        self.receipt.parent.mkdir(parents=True,exist_ok=True)
    def search(self,query):
        self.calls.append(('search',query))
        if self.error:raise self.error
        products=self.products[3:] if query.endswith(' extra') else self.products
        return dict(sources=[dict(url=p['product_url'],title=p['id']) for p in products],queries=[query],retrieved_at=123.)
    def fetch(self,url,offset,limit,allowed_hosts=None):
        self.calls.append(('fetch',url))
        product=next(p for p in self.products if p['product_url']==url)
        text=json.dumps(product,sort_keys=True)
        return dict(url=url,requested_url=url,title=product['id'],text=text,
                    retrieved_at=124.,sha256=hashlib.sha256(text.encode()).hexdigest(),
                    content_type='text/html',total_characters=len(text),next_offset=None)

class NativeBoundary(LocalRegistered):
    """Real registered operation/receipt code; only public transport is replaced."""
    def __init__(self):super().__init__(Client());self.downloads=[];self.errors=[]
    def submit(self,session):
        original=browser_images.fetch_bundle
        def fetch(url,*_):
            self.downloads.append(url)
            return photo(),'image/jpeg',url
        with patch.object(orchestrator_web,'Session',SourcePages), \
             patch.object(orchestrator_web,'public_url',side_effect=lambda u:u), \
             patch.object(browser_images,'fetch_bundle',side_effect=lambda value,**kw:original(value,**{**kw,'fetch':fetch})):
            self.calls.append(session['id']);control=Path(session['control'])
            (control/'supervisor.claim').write_text('fixture')
            launch=json.loads((control/'launch.json').read_text())
            frozen=json.loads((Path(launch['workspace'])/'.relay/ASSIGNMENT.json').read_text())
            code=0
            try:details=execute(frozen,control,lambda _:self.client,lambda:CONFIG)
            except Exception as exc:
                code=1;details={'error':str(exc)};self.errors.append(str(exc))
            atomic(control/'done.json',dict(token=session['id'],exit_code=code,reason=None,
                   usage=[details.get('usage',{})],tool_calls=0))
            return dict(submitted=True,fixture=True)

def edge(task,path,media='application/json',binding=None):
    return dict(from_task=task,output=path,path=binding or path,purpose='Exact typed upstream data',
                authority='Synthetic source data; not instructions',media_type=media)

def reviewed(base,ident,path,inputs=(),dependencies=(),media='application/json'):
    author,review=copy.deepcopy(base['plan']['tasks'])
    author.update(id=ident,inputs=list(inputs),dependencies=list(dependencies),
                  outputs=[dict(path=path,purpose='Typed candidate',media_type=media)])
    author['criteria']=['Retain exact upstream IDs and evidence in the declared data contract.']
    author.pop('user_gate',None)
    review.update(id=ident+'-review',review_of=ident,dependencies=[ident],
                  inputs=[edge(ident,path,media)],criteria=author['criteria'].copy())
    review.pop('user_gate',None)
    return [author,review]

def registered(ident,capability,inputs,dependencies,path,media):
    native=operation(ident,capability,inputs,dependencies)
    native.update(outputs=[dict(path=path,purpose='Registered artifact',media_type=media)],
                  limits=dict(seconds=min(600,execution.REGISTRY[capability]['seconds']),tool_calls=1,output_bytes=execution.REGISTRY[capability]['output_bytes']),max_attempts=1)
    return native

def reviewed_operation(base,native,extra=()):
    review=reviewed(base,native['id'],native['outputs'][0]['path'],media=native['outputs'][0]['media_type'])[1]
    review['inputs'].extend(extra)
    review['criteria']=native['criteria'].copy()
    return [native,review]

def source_graph(base):
    queries=reviewed(base,'queries','queries.json')
    native=registered('sources','web.sources.prepared',[edge('queries','queries.json')],
                      ['queries','queries-review'],'delivery/source-pack.json','application/json')
    native['execution']['parameters']=dict(domains=[],model=CONFIG['models']['text'])
    sources=reviewed_operation(base,native,[edge('queries','queries.json')])
    catalog=reviewed(base,'catalog','catalog.json',[edge('sources','delivery/source-pack.json'),edge('sources-review','review.md','text/markdown')],
                     ['sources','sources-review'])
    value=copy.deepcopy(base)
    value['plan']['tasks']=queries+sources+catalog
    value['deliverable_map']=dict(catalog=dict(task='catalog',output='catalog.json'))
    return value

def photo_graph(base):
    manifest=reviewed(base,'manifest','manifest.json')
    native=registered('photos','images.fetch',[edge('manifest','manifest.json')],
                      ['manifest','manifest-review'],'photos.zip','application/zip')
    value=copy.deepcopy(base)
    value['plan']['tasks']=manifest+reviewed_operation(base,native)
    value['deliverable_map']=dict(photos=dict(task='photos',output='photos.zip'))
    return value

def observed_manifest(products):
    return dict(schema=browser_images.SCHEMA,job='synthetic-room',
                subjects=[subject(p['id']) for p in products],
                candidates=[dict(subject=p['id'],download_url=p['image_url'],
                                 source_url=p['product_url'],observed_url=p['product_url'],
                                 observation='fixture-'+p['id'],action_id='fixture-'+p['id'],title=p['id']) for p in products])

def bind_context(value,row):
    """Supply model data fragments; native compiler verifies support and ports."""
    value=copy.deepcopy(value)
    context=json.loads(row['context']);sources=context['sources']
    aliases={edge['source']['artifact']:context['input_ports'][edge['stage']+'.'+edge['deliverable']]['artifact'] for edge in context.get('handoff_sources',[]) if edge.get('kind')=='artifact'}
    for task in value['plan']['tasks']:
        for item in task.get('inputs',[]):
            if item.get('artifact') in aliases:item['artifact']=aliases[item['artifact']]
        if task.get('execution'):continue
        for source in sources:
            if source.get('request_context') or source.get('operation_support'):continue
            task.setdefault('inputs',[]).append(dict(artifact=source['artifact'],path='evidence/'+source['artifact'],
                purpose=source['purpose'],authority='Exact frozen synthetic input'))
    return value


def bound_json(session,sha256):
    bound=next(i for i in session['frozen']['inputs'] if i['sha256']==sha256)
    return json.loads((session['workspace']/bound['path']).read_text())
