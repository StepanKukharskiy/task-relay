"""Source-backed connectors compile from their registered wire types."""
import base64,copy,json,unittest
from orchestrator import image_sources,contracts
from task_relay import production_planning as planning
from tests import test_mixed_planning as fixtures
from tests.test_mixed_execution import operation

class Tests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown
    request=fixtures.Tests.request;action=fixtures.Tests.action;queue=fixtures.Tests.queue
    row=fixtures.Tests.row;response=fixtures.Tests.response

    def test_product_photo_arguments_do_not_receive_unselected_archive_json(self):
        row=dict(self.queue(action=self.action(step_capabilities=['images.products'])))
        payload=json.loads(row['context']);inputs=[]
        for name in ('inventory.json','catalog.json','sources.json','unrelated.json'):
            p=self.rt.root/name;p.write_text('{"fixture":true}');aid=self.rt.register(p,'Small connector fixture')
            payload['sources'].append(planning.source_entry(self.rt,aid,name,'Exact fixture','Untrusted fixture'))
            payload['required_artifacts'].append(aid)
            if name!='unrelated.json':inputs.append(dict(artifact=aid,path=name,purpose='Exact fixture',authority='Fixture'))
        value=self.response();native=operation('photos','images.products',inputs)
        native['execution']['parameters']=dict(inventory_path='inventory.json',catalog_path='catalog.json',source_pack_path='sources.json',count_policy='target')
        native['outputs']=[dict(path='photos.zip',purpose='Catalog product photos',media_type='application/zip')]
        native.update(max_attempts=1,limits=dict(seconds=600,tool_calls=1,output_bytes=45000000))
        review=copy.deepcopy(value['plan']['tasks'][1]);review.update(id='review_photos',review_of='photos',dependencies=['photos'],criteria=['Inspect correspondence and disclosed gaps.'])
        review['inputs']=[dict(from_task='photos',output='photos.zip',path='candidate.zip',purpose='Exact photos',authority='Unaccepted photos')]
        value['plan']['tasks']=[native,review]
        row.update(context=contracts.encoded(payload),context_hash=contracts.digest(payload))
        _,plan=planning.validate_result(json.dumps(value),row)
        self.assertEqual([i['path'] for i in plan['tasks'][0]['inputs']],['inventory.json','catalog.json','sources.json'])
        self.assertEqual(self.factory.calls,[])

    def test_native_slide_assembly_accepts_exact_selected_json_png_and_zip(self):
        row=dict(self.queue(action=self.action(step_capabilities=['sourcing.slides'])))
        payload=json.loads(row['context']);inputs=[]
        data={'inventory.json':b'{"fixture":"inventory"}','catalog.json':b'{"fixture":"catalog"}',
              'sources.json':b'{"fixture":"sources"}',
              'room.png':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMv8AAAAASUVORK5CYII='),
              'photos.zip':image_sources.subject_base_bundle([dict(id='one',label='One',query='One')],'a'*64)}
        for name,raw in data.items():
            p=self.rt.root/name;p.write_bytes(raw);aid=self.rt.register(p,'Small connector fixture')
            source=planning.source_entry(self.rt,aid,name,'Exact fixture','Untrusted fixture bytes')
            payload['sources'].append(source);payload['required_artifacts'].append(aid)
            inputs.append(dict(artifact=aid,path=name,purpose='Exact fixture',authority='Fixture data'))
        value=self.response();native=operation('slides','sourcing.slides',inputs)
        native['execution']['parameters']=dict(inventory_path='inventory.json',catalog_path='catalog.json',source_pack_path='sources.json',image_path='room.png',photos_path='photos.zip',title='Small fixture',layout='standard')
        native['outputs']=[dict(path='slides.json',purpose='Native slide specification',media_type='application/json')]
        native.update(max_attempts=1,limits=dict(seconds=120,tool_calls=1,output_bytes=2000000))
        review=copy.deepcopy(value['plan']['tasks'][1]);review.update(id='review_slides',review_of='slides',dependencies=['slides'],criteria=copy.deepcopy(native['criteria']))
        review['inputs']=[dict(from_task='slides',output='slides.json',path='candidate.json',purpose='Exact candidate',authority='Unaccepted spec')]
        value['plan']['tasks']=[native,review]
        row.update(context=contracts.encoded(payload),context_hash=contracts.digest(payload))
        _,plan=planning.validate_result(json.dumps(value),row)
        task=next(t for t in plan['tasks'] if t['id']=='slides')
        self.assertEqual({i['path']:i['media_type'] for i in task['inputs']},{'inventory.json':'application/json','catalog.json':'application/json','sources.json':'application/json','room.png':'image/png','photos.zip':'application/zip'})
        self.assertEqual(self.factory.calls,[])
        # Compact references are compiled through the same native operation
        # validator; the model never needs to copy these workspace paths.
        from task_relay import planning_contract,planner_view
        compact_payload=copy.deepcopy(payload)
        compact_payload['handoff_binding_version']=compact_payload['options']['handoff_binding_version']=1
        selected=[next(s for s in payload['sources'] if s['artifact']==i['artifact']) for i in inputs]
        compact_payload['input_ports']=planner_view.ports(payload['sources'],[
            dict(kind='artifact',stage='any_stage',deliverable=str(n),media_type=task['inputs'][n]['media_type'],source=s)
            for n,s in enumerate(selected)])
        compact_payload['response_contract']=planning_contract.contract(compact_payload['options'],bindings=True)
        compact=copy.deepcopy(value)
        for t in compact['plan']['tasks']:
            t.pop('inputs');t.pop('dependencies');t['input_bindings']=[]
        native_compact=compact['plan']['tasks'][0]
        native_compact['input_bindings']=[dict(port='any_stage.'+str(n)) for n in range(5)]
        for n,name in enumerate(('inventory_path','catalog_path','source_pack_path','image_path','photos_path')):
            native_compact['execution']['parameters'][name]=dict(input_path=dict(port='any_stage.'+str(n)))
        compact_row={**row,'context':contracts.encoded(compact_payload),'options':contracts.encoded(compact_payload['options'])}
        _,compiled=planning.validate_result(json.dumps(compact),compact_row)
        bound=next(t for t in compiled['tasks'] if t['id']=='slides')
        self.assertEqual(bound['execution']['parameters'],native['execution']['parameters'])
        self.assertEqual(len(compiled['origin']['artifact_bindings']['tasks'][0]['parameter_bindings']),5)
        bad_ref=copy.deepcopy(compact);bad_ref['plan']['tasks'][0]['execution']['parameters']['inventory_path']={'input_path':{'port':'unbound.output'}}
        with self.assertRaisesRegex(ValueError,'Unknown captured handoff port'):
            planning.validate_result(json.dumps(bad_ref),compact_row)
        bad_type=copy.deepcopy(compact);bad_type['plan']['tasks'][0]['execution']['parameters']['image_path']={'input_path':{'port':'any_stage.0'}}
        with self.assertRaisesRegex(ValueError,'input type mismatch'):
            planning.validate_result(json.dumps(bad_type),compact_row)
        bad_parameter=copy.deepcopy(compact);bad_parameter['plan']['tasks'][0]['execution']['parameters']['title']={'input_path':{'port':'any_stage.0'}}
        with self.assertRaisesRegex(ValueError,'registered path parameter'):
            planning.validate_result(json.dumps(bad_parameter),compact_row)
        # A declared unsupported binary is still held; no arbitrary type coercion.
        bad=copy.deepcopy(payload);bad['sources'][-1]['path']='photos.avif';row['context']=contracts.encoded(bad)
        with self.assertRaisesRegex(ValueError,'binary source is incompatible'):
            planning.validate_result(json.dumps(value),row)
