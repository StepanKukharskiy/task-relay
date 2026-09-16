import copy
import json
import unittest
from task_relay.presentation_inputs import bind
from tests import test_production_planning as fixtures


class Tests(unittest.TestCase):
    def tasks(self):
        return [dict(id='capture',inputs=[],outputs=[],dependencies=[]),
            dict(id='author',inputs=[dict(artifact='photos',path='assets/photos.zip')],dependencies=['capture'],instruction='Edit the deck.'),
            dict(id='review',review_of='author',inputs=[],dependencies=['author'],instruction='Review the spec.'),
            dict(id='deck',execution={'capability':'pptx.create'},dependencies=['author','review','capture'],inputs=[
                dict(from_task='author',output='slides.json',path='spec.json',media_type='application/json'),
                dict(from_task='capture',output='map.png',path='images/map.png',media_type='image/png'),
                dict(artifact='photos',path='photos.zip',media_type='application/zip')])]

    def test_author_and_review_share_exact_creator_sources_without_alias_confusion(self):
        tasks=self.tasks();before=copy.deepcopy(tasks[-1]);bind(tasks)
        self.assertEqual(tasks[-1],before)
        for task in tasks[1:3]:
            text=task['instruction'];encoded=text.split('slide JSON): ',1)[1].split('\n',1)[0]
            bindings=json.loads(encoded)
            self.assertEqual([i['slide_path'] for i in bindings],['images/map.png','photos.zip'])
            self.assertIn('capture',task['dependencies'])
            png=next(i for i in task['inputs'] if i.get('from_task')=='capture')
            self.assertEqual(png['output'],'map.png')
        self.assertIn('"read_path":"assets/photos.zip"',tasks[1]['instruction'])
        self.assertEqual(len([i for i in tasks[1]['inputs'] if i.get('artifact')=='photos']),1)

    def test_downstream_image_cannot_create_preparation_cycle(self):
        tasks=self.tasks();tasks[0]['dependencies']=['author']
        with self.assertRaisesRegex(ValueError,'depends on its own'):bind(tasks)

    def test_conflicting_staged_path_is_rejected(self):
        tasks=self.tasks();tasks[1]['inputs'].append(dict(artifact='other',path='creator-inputs/deck/images/map.png'))
        with self.assertRaisesRegex(ValueError,'collision'):bind(tasks)


class RestoreTests(unittest.TestCase):
    setUp=fixtures.Tests.setUp;tearDown=fixtures.Tests.tearDown

    def test_restore_uses_recorded_selected_deck_images_and_rejects_changed_bytes(self):
        self.check_restoration({'slides':[{'elements':[{'type':'image','path':'images/old.png'}]}]})

    def test_restore_retains_exact_logo_from_template_brand(self):
        self.check_restoration(dict(version=2,title='Branded deck',brand=dict(logo=dict(path='images/old.png',x=11.5,y=6.95,w=1,h=.3)),
            slides=[dict(layout='title',content=dict(title='Title',subtitle='Subtitle'))]))

    def test_revision_restores_source_bundle_used_by_image_grid(self):
        self.check_restoration(dict(version=2,title='Reference images',slides=[dict(layout='image_grid',
            content=dict(title='Examples',items=[dict(image='photos.zip/images/subject.jpg',label='Subject')]))]),
            asset_path='photos.zip',media_type='application/zip')

    def check_restoration(self,document,asset_path='images/old.png',media_type='image/png'):
        from task_relay.presentation_inputs import restore_selected_images
        from task_relay.production_planning import source_entry
        from tests.test_orchestrator import pair
        from pathlib import Path
        self.rt.create(pair());self.rt.tick('demo')
        attempt=self.rt.task('demo','produce')['latest']
        def register(name,text,**kwargs):
            path=self.rt.root/name;path.write_text(text)
            return self.rt.register(path,'Fixture',path=name,**kwargs)
        image=register('old.png','Small image identity fixture')
        spec=register('slides.json',json.dumps(document))
        deck=register('original.pptx','Small deck identity fixture',run='demo',task='produce',attempt=attempt)
        frozen={'execution':{'capability':'pptx.create'},'inputs':[
            dict(artifact=spec,path='slides.json',media_type='application/json',sha256=self.rt.artifact(spec)['sha256']),
            dict(artifact=image,path=asset_path,media_type=media_type,sha256=self.rt.artifact(image)['sha256'],purpose='Old image',authority='Selected image')]}
        with self.state.db:self.state.db.execute('UPDATE production_attempts SET frozen=?,receipt=? WHERE id=?',
            (json.dumps(frozen),json.dumps({'status':'finished','operation':{'outcome':'completed'}}),attempt))
        payload={'sources':[source_entry(self.rt,aid,path,'Selected','User selection') for aid,path in ((deck,'selected.pptx'),(spec,'baseline.json'))]}
        tasks=[dict(id='creator',execution={'capability':'pptx.create'},inputs=[])]
        restore_selected_images(self.rt,payload,tasks)
        self.assertEqual(tasks[0]['inputs'][0]['artifact'],image)
        self.assertEqual(tasks[0]['inputs'][0]['path'],asset_path)
        blob=Path(self.rt.artifact(image)['blob']);blob.chmod(0o600);blob.write_text('changed')
        tasks[0]['inputs']=[]
        with self.assertRaisesRegex(ValueError,'changed'):restore_selected_images(self.rt,payload,tasks)
