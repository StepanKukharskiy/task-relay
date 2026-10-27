"""Offline source→correction→compose→executed independent review→partial copy.

Real local PPTX, retained image bytes and production handoffs. Renderer responses
are explicit synthetic fixtures; no native opening, pixel quality or live claims.
"""
import copy,hashlib,io,json,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from orchestrator import contracts as c,job_owner,web_sources
from tests import test_correction_handoff_lifecycle as chain
from tests import test_review_dependency_lifecycle as binary
from tests import test_owner_intents as owner
from tests import lifecycle_fixture as life

class Complete(chain.Fixtures,unittest.TestCase):
    schema='furniture'
    run_steps=binary.ReviewDependency.run_steps
    def setUp(self):
        # Frozen host identity is a local executable; invocation itself is scripted.
        tool=dict(path=sys.executable,sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest())
        binding=dict(platform=sys.platform,tools=dict(soffice=tool,pdftoppm=tool),alternatives=[],basis='offline synthetic renderer fixture')
        for p in (patch('task_relay.presentation_host.discover',return_value=binding),patch('task_relay.code_runtime.available',return_value={'tools':{}})):
            p.start();self.addCleanup(p.stop)
        super().setUp()

    def capture(self,text,name):
        pack=json.loads(text)
        for entry in pack['entries']:
            for page in entry['pages']:
                page['text']=page['text'].replace('USD $123.45','EUR €394,95')
                page['sha256']=hashlib.sha256(page['text'].encode()).hexdigest()
        if name=='original':self.h.pack=copy.deepcopy(pack)
        return super().capture(json.dumps(pack,indent=2),name)

    def initial_catalog(self):
        # Same registered prepared-query contract used before the controlled fetch.
        targets=[dict(id=k,queries=[k+' exact US',k+' alternative US'],required_options=3) for k in ('S0','S1')]
        self.assertEqual(web_sources.validate_prepared(dict(version=1,targets=targets)),['S0 exact US','S1 exact US','S0 alternative US','S1 alternative US'])
        base,fragment=super().initial_catalog()
        self.assertIn('394.95',Path(base['blob']).read_text());self.assertIn('EUR',Path(base['blob']).read_text())
        return base,fragment

    def run_worker(self,ident,steps,decision='delivered'):
        if ident not in ('repair','repair_again'):return chain.Fixtures.run_worker(self,ident,steps,decision)
        def late_read(f):
            actions=steps(f)
            # Exercise the real 23rd request under the unchanged 24-request cap.
            # Reads are local fixture observations; no failures/reads are forced live.
            actions += [('file_read',dict(path=f['inputs'][0]['path'],offset=0,limit=1000))]*(22-len(actions))
            actions += [('file_read',dict(path=f['operation_contract']['output'],offset=0,limit=24000))]
            return actions
        f,script=chain.Fixtures.run_worker(self,ident,late_read,decision)
        self.assertEqual(len(script.requests),24)
        control=Path(self.factory.sessions[f['assignment_id']]['session']['control'])
        validation=control/'api-23.validation.json'
        self.assertFalse(validation.exists(),validation.read_text() if validation.exists() else '')
        last=script.requests[-1]['contents'][-1]['parts'][0]['functionResponse']
        self.assertEqual(last['name'],'file_read');self.assertNotIn('tool_authority_denied',json.dumps(last))
        return f,script

    def fake_renderer(self,command,timeout,*,cwd):
        folder=Path(cwd);out=folder/'preview'
        with zipfile.ZipFile(folder/'candidate.pptx') as z:
            count=len([p for p in z.namelist() if p.startswith('ppt/slides/slide') and p.endswith('.xml') and '/' not in p[len('ppt/slides/'):]])
        if '--convert-to' in command:
            from pypdf import PdfWriter
            writer=PdfWriter()
            for _ in range(count):writer.add_blank_page(width=100,height=100)
            with (out/'candidate.pdf').open('wb') as target:writer.write(target)
        else:
            for n in range(1,count+1):Image.new('RGB',(4,4),(n,0,0)).save(out/f'slide-{n:03d}.png')
        return dict(command=command,exit_code=0,stdout='Offline synthetic renderer',stderr='')

    def finish_delivery(self,deck):
        inspection=next(t for t in self.rt.status('job')['tasks'] if t.get('latest') and self.factory.sessions[t['latest']]['frozen'].get('execution',{}).get('capability')=='pptx.render')
        with patch('task_relay.presentation_host.invoke',side_effect=self.fake_renderer):self.native(inspection['id'])
        pdf=self.artifact(inspection['id'],'delivery/preview.pdf')
        preview=self.artifact(inspection['id'],'delivery/slide-previews.zip')
        def observations(f):
            self.assertEqual(f['review_target'],deck['attempt'])
            self.assertIn(deck['id'],[i.get('artifact') for i in f['inputs']])
            z=next(i for i in f['inputs'] if i.get('artifact')==preview['id'])
            with zipfile.ZipFile(Path(f['workspace'])/z['path']) as archive:members=archive.namelist()
            self.assertGreater(len(members),0)
            # Every synthetic page is supplied in bounded batches.
            required={p for b in f.get('final_quality',{}).get('checks',{}).values() for p in b['inspection_inputs']}
            return [('file_read',dict(path=i['path'],offset=0,limit=24000)) for i in f['inputs'] if i.get('media_type')=='application/json' and i['path'] in required]+[
                ('image_view',dict(path=z['path'],members=members[n:n+4])) for n in range(0,len(members),4)]
        self.run_steps('deck_review',observations,'revise')
        original=deck;original_bytes=Path(original['blob']).read_bytes()
        base=self.artifact('repair_again');source=self.artifact('repair_again','delivery/retained-sources.json')
        fragment=json.loads(Path(base['blob']).read_text())['records'][0]
        fragment['options'][0]['comparison']='Corrected after final independent presentation review; provisional, not a purchasing recommendation.'
        final,retained=self.repair('final_repair',base,fragment,source)
        photos=self.artifact('photos','outputs/result.zip')
        self.submit('final_slides',[dict(id='final_slides',objective='Apply independent presentation findings',operation='collection.slides',parameters=dict(inventory_path={'artifact':self.inv['artifact']},catalog_path={'artifact':final['id']},source_pack_path={'artifact':retained['id']},photos_path={'artifact':photos['id']},image_path=None,title='Corrected partial evidence',layout='readable'))])
        self.native('final_slides')
        self.submit('final_compose',[dict(id='final_compose',objective='Compose corrected evidence',operation='document.compose',parameters=dict(document_paths=[{'artifact':self.artifact('final_slides')['id']}],image_paths=[],image_titles=[],title='Corrected partial evidence'),inputs=[{'artifact':photos['id']}])]);self.native('final_compose')
        self.submit('final_deck',[dict(id='final_deck',objective='Build corrected deck',operation='pptx.create',data={'artifact':self.artifact('final_compose')['id']},inputs=[{'artifact':photos['id']}]),dict(id='final_review',objective='Independently re-review correction against prior exact evidence',review_of='final_deck',inputs=[{'artifact':original['id']}])]);self.native('final_deck')
        deck=self.artifact('final_deck','outputs/result.pptx')
        inspection=None
        with patch('task_relay.presentation_host.invoke',side_effect=self.fake_renderer):
            for _ in range(3):
                # Poll newly launched inspections even when the prior candidate's
                # collected evidence is reused and needs no extra native step.
                self.rt.tick('job')
                inspections=[t for t in self.rt.status('job')['tasks'] if t.get('latest') and t['status']=='running' and self.factory.sessions[t['latest']]['frozen'].get('execution',{}).get('capability')=='pptx.render']
                for task in inspections:
                    if self.factory.sessions[task['latest']]['frozen']['inputs'][0]['artifact']==deck['id']:inspection=task
                    self.native(task['id'])
                if self.rt.task('job','final_review')['latest']:break
        self.assertIsNotNone(inspection)
        pdf=self.artifact(inspection['id'],'delivery/preview.pdf');preview=self.artifact(inspection['id'],'delivery/slide-previews.zip')
        reviewed=self.run_steps('final_review',observations,'accept')
        self.assertNotIn('deck',reviewed['dependencies'])
        self.assertEqual(self.rt.task('job','final_deck')['status'],'completed')
        self.assertEqual(Path(original['blob']).read_bytes(),original_bytes)
        # Only the deck target was accepted by the scripted reviewer. PDF retains
        # its actual derived label; no inferred four-file/user approval.
        self.submit('peers',[owner.worker('unknown'),owner.worker('slow')])
        unknown=self.rt.task('job','unknown')['latest'];self.factory.sessions[unknown]['status']=dict(status='uncertain',reason='Controlled missing external receipt')
        self.rt.tick('job');calls=list(self.factory.calls)
        self.run_worker('slow',lambda f:[('file_write',dict(path=f['outputs'][0]['path'],text='Honest partial peer'))])
        status=self.rt.status('job');self.assertEqual(status['status'],'uncertain')
        delivery=status['delivery'];labels={x['artifact']:x['review_status'] for x in delivery['candidates']}
        self.assertEqual(labels[deck['id']],'reviewed');self.assertFalse(delivery['user_acceptance']);self.assertFalse(delivery['complete'])
        self.assertEqual(labels[original['id']],'requires_attention')
        self.assertIn(pdf['id'],labels)
        from task_relay import result_handoff
        folder=result_handoff.sync(self.state,'job');marker=json.loads((folder/'.relay-workflow.json').read_text())
        for a in (deck,pdf):self.assertEqual((folder/marker['paths'][a['id']]).read_bytes(),Path(a['blob']).read_bytes())
        from orchestrator.runtime import Runtime
        self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db);self.rt.tick('job')
        self.assertEqual(self.rt.status('job')['delivery'],delivery);self.assertEqual(self.factory.calls,calls)
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['task_limits'],life.LIMITS)
        self.assertEqual(self.rt.db.execute('SELECT count(*) FROM production_decisions').fetchone()[0],0)
        (self.root/'partial-projection.json').write_text(json.dumps(delivery,indent=2))

    def test_two_fresh_corrections_export_at_request23_restart_compose_review_and_partial(self):self.complete_path(False)

class LateExport(chain.Fixtures,unittest.TestCase):
    schema='plants'
    run_worker=Complete.run_worker
    def test_export_read_remains_available_at_request23_without_new_authority(self):
        base,fragment=self.initial_catalog();fragment['options'][0]['comparison']='Corrected source-qualified comparison.'
        result,_=self.repair('repair',base,fragment,self.pack)
        self.assertEqual(self.rt.task('job','repair')['status'],'completed')
        self.assertEqual(job_owner.original(self.rt,'job')['job_owner']['task_limits'],life.LIMITS)
