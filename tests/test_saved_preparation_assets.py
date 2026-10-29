"""Exact saved preparation → separate consumer; small offline files only."""
import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from orchestrator import producer_binding,prepared_schemas

class SavedAssets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE production_attempts(id,state,run,task,frozen)')
        self.artifacts={}
        self.rt=SimpleNamespace(db=self.db,artifact=lambda aid:self.artifacts[aid])
    def put(self,ident,data,**kw):
        p=self.root/ident;p.write_bytes(data)
        self.artifacts[ident]=dict(id=ident,blob=str(p),sha256=hashlib.sha256(data).hexdigest(),**kw)
    def fixture(self,target):
        self.put('image',b'synthetic pixels');self.put('audio',b'synthetic audio')
        assets=[dict(artifact='image',path='inputs/original/image.png',media_type='image/png'),dict(artifact='audio',path='inputs/original/audio.wav',media_type='audio/wav')]
        frozen=dict(inputs=[dict(i,sha256=self.artifacts[i['artifact']]['sha256']) for i in assets],
            operation_contract=dict(id='operation.preparation',version=1,output='outputs/project.json',parameters=dict(target=target)))
        if target=='hyperframes.preview':
            doc=dict(version=1,width=320,height=568,fps=30,duration=2,audio=True,samples=[1],files={'index.html':'<main data-composition-id="main" data-width="320" data-height="568" data-duration="2"></main>'},assets={'assets/image.png':assets[0]['path'],'assets/audio.wav':assets[1]['path']})
        else:
            doc=dict(version=1,width=320,height=568,fps=30,background='#ffffff',foreground='#000000',accent='#555555',audio=assets[1]['path'],scenes=[dict(duration=2,title='Fixture',body='',image=assets[0]['path'],entrance='fade',narration='')])
        self.put('project',json.dumps(doc).encode(),attempt='producer',run='run',task='author',path='outputs/project.json')
        self.db.execute('INSERT INTO production_attempts VALUES(?,?,?,?,?)',('producer','completed','run','author',json.dumps(frozen)))
        task=dict(id='preview',execution=dict(capability=target,parameters={}),inputs=[dict(artifact='project',path='inputs/saved/project.json',media_type='application/json')]+[dict(i,path='inputs/saved/'+i['artifact']+('.png' if i['artifact']=='image' else '.bin')) for i in assets],outputs=[dict(path='delivery/project.zip')])
        return dict(tasks=[task]),frozen,doc
    def test_two_registered_asset_graphs_keep_exact_bytes_and_paths(self):
        for target in ('hyperframes.preview','media.compose'):
            with self.subTest(target=target):
                self.db.execute('DELETE FROM production_attempts');plan,frozen,doc=self.fixture(target)
                original=copy.deepcopy(plan);before=self.db.execute('SELECT frozen FROM production_attempts').fetchone()[0]
                with self.assertRaises(ValueError):prepared_schemas.validate(target,doc,{i['path']:i['media_type'] for i in plan['tasks'][0]['inputs']})
                producer_binding.bind_saved_assets(plan,self.rt)
                prepared_schemas.validate(target,doc,{i['path']:i['media_type'] for i in plan['tasks'][0]['inputs']})
                self.assertEqual(self.db.execute('SELECT frozen FROM production_attempts').fetchone()[0],before)
                self.assertEqual(json.loads(Path(self.artifacts['project']['blob']).read_text()),doc)
                self.assertEqual([i['artifact'] for i in plan['tasks'][0]['inputs']],[i['artifact'] for i in original['tasks'][0]['inputs']])
                self.assertEqual(plan['tasks'][0]['execution'],original['tasks'][0]['execution'])
                producer_binding.bind_saved_assets(plan,self.rt) # stable repeated admission
    def test_uncertain_changed_ambiguous_and_conflicting_sources_reject(self):
        for case in ('uncertain','bytes','type','target','path','ambiguous','collision'):
            with self.subTest(case=case):
                self.db.execute('DELETE FROM production_attempts');plan,frozen,_=self.fixture('hyperframes.preview')
                if case=='uncertain':self.db.execute("UPDATE production_attempts SET state='uncertain'")
                if case=='bytes':Path(self.artifacts['image']['blob']).write_bytes(b'changed')
                if case=='type':plan['tasks'][0]['inputs'][1]['media_type']='image/jpeg'
                if case=='target':frozen['operation_contract']['parameters']['target']='media.compose'
                if case=='path':frozen['operation_contract']['output']='outputs/other.json'
                if case=='ambiguous':frozen['inputs'].append(copy.deepcopy(frozen['inputs'][0]))
                if case=='collision':frozen['inputs'][1]['path']=frozen['inputs'][0]['path']
                self.db.execute('UPDATE production_attempts SET frozen=?',(json.dumps(frozen),))
                before=copy.deepcopy(plan)
                with self.assertRaises(ValueError):producer_binding.bind_saved_assets(plan,self.rt)
                self.assertEqual(plan,before)

if __name__=='__main__':unittest.main()
