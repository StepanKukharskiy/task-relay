"""Lossless evidence paging, real registered graphs, scripted decisions/host only."""
import hashlib,json,unittest,copy
from itertools import chain
from pathlib import Path
from unittest.mock import patch
from orchestrator import execution_evidence as evidence,contracts as c,step_runner,worker_tools
from orchestrator.runtime import Runtime
from orchestrator.agent_loop import Files
from orchestrator.owner_compilation import label
from tests import test_execution_review as base,test_owner_intents as owner
from tests.test_native_source_browser import pack


class LazySteps:
    def __init__(self,steps):self.steps=steps
    def __add__(self,tail):return chain(self.steps,tail)


def restore(value,documents):
    if isinstance(value,dict) and value.get('representation')=='relay.exact-json-pages.v1':
        chunks=[];offset=0
        for p in value['pages']:
            raw=documents[p['path']]
            assert len(raw)==p['bytes'] and hashlib.sha256(raw).hexdigest()==p['sha256']
            assert p['byte_offset']==offset;offset+=len(raw);chunks.append(raw)
        raw=b''.join(chunks)
        assert len(raw)==value['bytes'] and hashlib.sha256(raw).hexdigest()==value['sha256']
        return json.loads(raw)
    if isinstance(value,dict):return {k:restore(v,documents) for k,v in value.items()}
    if isinstance(value,list):return [restore(v,documents) for v in value]
    return value


class RepresentationTests(unittest.TestCase):
    def test_lossless_unicode_nested_and_wide_values_inside_same_bounds(self):
        for value in [dict(receipts={'text':'é漢😀\\"\n'*40000},assignment='same'),
                      {str(n):'long value '*100 for n in range(600)}]:
            with self.subTest(keys=len(value)):
                docs={};index=evidence.bounded(value,docs)
                self.assertLessEqual(len(c.encoded(index).encode()),evidence.LIMIT)
                self.assertTrue(docs);self.assertTrue(all(len(raw)<=evidence.LIMIT for raw in docs.values()))
                self.assertEqual(restore(index,docs),value)
                path=next(iter(docs));bad=dict(docs);bad[path]=b'changed'
                with self.assertRaises(AssertionError):restore(index,bad)

    def test_small_historical_representation_unchanged(self):
        value=dict(version=1,receipts={'exact':'observed'},inputs=[]);docs={}
        self.assertEqual(c.encoded(evidence.bounded(value,docs)),c.encoded(value));self.assertEqual(docs,{})


class LifecycleTests(unittest.TestCase):
    setUp=base.Tests.setUp;tearDown=base.Tests.tearDown
    create=base.Tests.create;source=base.Tests.source;invoke=base.Tests.invoke
    session=base.Tests.session;run_worker=base.Tests.run_worker;execute_operation=base.Tests.execute_operation

    def flow(self,inline):
        source=self.source(c.encoded(pack()),'sources.json','application/json')
        self.create(inputs=[source]);self.rt.tick('job')
        native=owner.native('read','web.sources.rendered',[dict(artifact=source['artifact'])],dict(domains=[],max_pages=1))
        if inline:native=dict(id='read',objective='Read the observed source',work=dict(mode='execute',operation='web.sources.rendered',data=dict(artifact=source['artifact']),parameters=dict(domains=[],max_pages=1)))
        self.invoke([('job_delegate',dict(request_id='read',tasks=[native,owner.worker('report',[dict(task='read',output='source-pack')])]))])
        calls=[]
        def render(url,domains,folder):
            calls.append(url);folder=Path(folder)
            raw=('Original exact retained observation é漢😀\n'*10000).encode()
            (folder/'rendered-dom.html').write_bytes(raw)
            page=dict(url=url,text='Verified fixture: 42 units.',title='Fixture',sha256=hashlib.sha256(raw).hexdigest(),content_type='text/html',capture_method='isolated-rendered-dom',retrieval_status='captured')
            (folder/'render-intent.json').write_text(c.encoded(dict(url=url,domains=domains)))
            (folder/'render-outcome.json').write_text(c.encoded(dict(page=page,evidence={'rendered-dom.html':hashlib.sha256(raw).hexdigest()})))
            return page
        if inline:
            def stages(f):
                yield ('work_run',dict(step='build',request_key='one'))
                yield ('work_evidence',dict(step='build'))
                state=self.factory.sessions[f['assignment_id']]
                folder=Path(state['session']['control'])/'work-operations/0001'
                sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
                docs={};evidence.bounded(evidence.capsule(sub,folder),docs)
                yield ('work_evidence',dict(step='build',document='../ungranted'))
                yield ('work_evidence',dict(step='build',document=next(iter(docs)),offset=0))
            with patch('orchestrator.worker_tools.execute_local',side_effect=lambda f,p,*a,**kw:step_runner.execute(f,p)),patch('task_relay.source_browser.render',side_effect=render):
                self.run_worker('read',lambda f:LazySteps(stages(f)))
            state=self.factory.sessions[self.rt.task('job','read')['latest']];control=Path(state['session']['control']);folder=control/'work-operations/0001'
            sub=json.loads((folder/'workspace/.relay/ASSIGNMENT.json').read_text())
            docs={};index=evidence.bounded(evidence.capsule(sub,folder),docs)
            # Reopened operation session uses the same exact hashed documents.
            session=worker_tools.Session(Files(state['frozen']),control)
            for path,raw in docs.items():
                text='';offset=0
                while True:
                    page=evidence.work_read(session,dict(step='build',document=path,offset=offset));text+=page['text']
                    self.assertLessEqual(len(page['text']),24000)
                    if page['next_offset'] is None:break
                    offset=page['next_offset']
                self.assertEqual(text.encode(),raw)
            with self.assertRaisesRegex(ValueError,'exact evidence document'):evidence.work_read(session,dict(step='build',document='../operation.json'))
            with patch('orchestrator.executors.text_input_limit',return_value=100):
                with self.assertRaisesRegex(ValueError,'limit|allowance'):evidence.work_read(session,dict(step='build'))
        else:
            _,folder=self.execute_operation('read',render)
            sub=self.factory.sessions[self.rt.task('job','read')['latest']]['frozen']
        raw_capsule=evidence.capsule(sub,folder);self.assertGreater(len(c.encoded(raw_capsule).encode()),evidence.LIMIT)
        docs={};self.assertEqual(restore(evidence.bounded(raw_capsule,docs),docs),raw_capsule)
        if self.rt.task('job','read')['status']=='awaiting_review':
            self.run_worker(label('read','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']],decision='accept')
        self.rt.close();self.rt=Runtime(self.root,self.factory)
        f,_=self.run_worker('report',lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]+[('file_write',dict(path=f['outputs'][0]['path'],text='Observed 42 units; exact original provenance retained.'))])
        pages={i['path']:(Path(f['workspace'])/i['path']).read_bytes() for i in f['inputs'] if i['path'].startswith('execution-evidence/pages/')}
        indexes=[i for i in f['inputs'] if i['path'].startswith('execution-evidence/') and i['path'].endswith('.json')]
        self.assertTrue(pages)
        for i in indexes:
            index=json.loads((Path(f['workspace'])/i['path']).read_text());self.assertLessEqual(len((Path(f['workspace'])/i['path']).read_bytes()),evidence.LIMIT)
            full=restore(index,pages);self.assertEqual(full['operations'][0]['adapter_evidence'],raw_capsule['adapter_evidence'])
        # Inherited handoffs reuse exact identities, and a forged page fails closed.
        resolved=self.rt.checked_inputs('job',f,f['backend']);self.assertEqual(len(resolved),len(f['inputs']))
        selected=next(i for i in f['inputs'] if i['path'] in pages)
        bad=self.source('forged','forged.txt');bad['path']=selected['path'];spec=copy.deepcopy(f)
        spec['inputs']=[bad if i['path']==selected['path'] else i for i in spec['inputs']]
        with self.assertRaisesRegex(ValueError,'exact producer capsule'):self.rt.checked_inputs('job',spec,f['backend'])
        self.run_worker(label('report','review'),lambda f:[('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs']]+[('file_write',dict(path=f['outputs'][0]['path'],text='Exact candidate and bound provenance reviewed.'))],decision='accept')
        result=self.rt.output('job','report','outputs/result.txt');self.invoke([('job_complete',dict(deliverables_json=c.encoded(dict(report=result['id'])),summary='Reviewed fixture'))]);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['status'],'completed');self.assertEqual(len(calls),1)
        # Full originals are still verified after a successful downstream handoff.
        (folder/'render-1/rendered-dom.html').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'changed|materialization'):evidence.capsule(sub,folder)

    def test_standalone_lossless_handoff_review_restart_no_replay(self):self.flow(False)
    def test_inline_lossless_handoff_review_restart_no_replay(self):self.flow(True)
