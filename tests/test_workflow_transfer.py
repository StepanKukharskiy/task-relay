"""Small portable graph tests: no providers, schedulers or live jobs."""
import copy,json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from orchestrator import node_spec
from orchestrator.runtime import Runtime
from task_relay import workflow_transfer as transfer,desktop_node_drafts as drafts,desktop_node_files as files

class WorkflowTransfer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.paths=SimpleNamespace(data=self.root,state=self.root/'state.sqlite')
        self.paths.state.touch();Runtime(self.root/'orchestrator').close()
        def database(writable=False):
            db=sqlite3.connect(str(self.paths.state) if writable else self.paths.state.as_uri()+'?mode=ro',uri=not writable);db.row_factory=sqlite3.Row;return db
        self.database=database
        for p in (patch.object(transfer,'PATHS',self.paths),patch.object(drafts,'PATHS',self.paths),patch.object(files,'PATHS',self.paths),patch.object(transfer,'_database',database),patch.object(files,'_database',database)):
            p.start();self.addCleanup(p.stop)
        self.workflow=json.loads(Path('examples/reusable-summary.workflow.json').read_text())
        self.workflow['tasks'][1]['model']={'provider':'codex','id':'gpt-6.1-sol'}
    def save(self,workflow=None):
        return drafts.dispatch('node-draft-save',dict(id=None,revision=None,title='Reusable summary',workflow=workflow or self.workflow))
    def export(self,record,include=False,name='test.zip'):
        path=self.root/name
        transfer.export(dict(source=dict(kind='draft',id=record['id'],revision=record['revision']),path=str(path),include_files=include))
        return path
    def import_file(self,path,**kw):
        preview=transfer.preview({'path':str(path)})
        return transfer.import_workflow(dict(path=str(path),sha256=preview['sha256'],files=kw))
    def file_workflow(self):
        path=self.root/'article.json';path.write_text('{"text":"Tiny saved article"}')
        item=files.dispatch('node-file-import',{'paths':[str(path)]})['files'][0]
        w=copy.deepcopy(self.workflow);w['tasks'][1]['input_definitions']['reference']={'type':'artifact','label':'Reference','required':True,'media_type':'application/json'}
        w['tasks'][1]['inputs']['reference']={'artifact':item['artifact']}
        return path,item,self.save(w)
    def test_plain_roundtrip_retains_graph_and_models_no_history_or_execution(self):
        old=self.save();path=self.export(old);new=self.import_file(path)
        self.assertNotEqual(new['id'],old['id']);self.assertEqual(new['workflow'],old['workflow'])
        self.assertFalse(new['execution_authorized']);self.assertIn('workflow.article_url',new['missing_inputs'])
        checked=node_spec.resolve_workflow(new['workflow'],{'article_url':'https://example.com'})
        self.assertTrue(checked['ready']);self.assertEqual(checked['connections'][0]['source'],{'task':'article','output':'page'})
        with zipfile.ZipFile(path) as z:self.assertEqual(set(z.namelist()),{'manifest.json','workflow.json'})
        with self.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM production_runs').fetchone()[0],0)
        self.assertEqual(drafts.dispatch('node-draft',{'id':old['id']})['workflow'],old['workflow'])
    def test_included_files_receive_new_ids_and_exact_bytes(self):
        path,item,old=self.file_workflow();bundle=self.export(old,True);new=self.import_file(bundle)
        aid=new['workflow']['tasks'][1]['inputs']['reference']['artifact'];self.assertNotEqual(aid,item['artifact'])
        self.assertEqual(files.lookup(aid)['sha256'],item['sha256'])
        self.assertEqual(new['workflow']['tasks'][1]['inputs']['article'],{'task':'article','output':'page'})
        self.assertNotIn(item['artifact'],bundle.read_bytes().decode('latin1'))
    def test_omitted_files_require_exact_replacement_before_new_draft(self):
        path,item,old=self.file_workflow();bundle=self.export(old)
        self.assertEqual(len(transfer.preview({'path':str(bundle)})['missing_files']),1)
        before=list((self.root/'node-drafts').glob('*.json'))
        with self.assertRaisesRegex(ValueError,'all omitted'):self.import_file(bundle)
        self.assertEqual(list((self.root/'node-drafts').glob('*.json')),before)
        wrong=self.root/'wrong.json';wrong.write_text('wrong')
        with self.assertRaises(ValueError):self.import_file(bundle,**{'input-1':str(wrong)})
        self.assertTrue(self.import_file(bundle,**{'input-1':str(path)})['id'])
    def test_reject_changed_package_extra_entries_tampering_and_credential_fields(self):
        old=self.save();bundle=self.export(old)
        preview=transfer.preview({'path':str(bundle)})
        with zipfile.ZipFile(bundle,'a') as z:z.writestr('../private/.env','never extract')
        with self.assertRaises(ValueError):transfer.import_workflow(dict(path=str(bundle),sha256=preview['sha256'],files={}))
        w=copy.deepcopy(self.workflow);w['tasks'][1]['inputs']['length']={'value':'short'}
        w['tasks'][1]['input_definitions']['secret']={'type':'object','label':'Secret','required':False}
        w['tasks'][1]['inputs']['secret']={'value':{'api_key':'fixture-secret'}}
        # Secret-key detection is independent of the graph schema validation.
        with self.assertRaisesRegex(ValueError,'credential'):transfer.clean(w)
        good=self.export(old,name='good.zip');contents={}
        with zipfile.ZipFile(good) as z:contents={n:z.read(n) for n in z.namelist()}
        for mutation in ('checksum','operation','port','cycle'):
            w=copy.deepcopy(self.workflow)
            if mutation=='operation':w['tasks'][0]['operation']='unknown.operation'
            if mutation=='port':w['tasks'][1]['inputs']['article']['output']='unknown'
            if mutation=='cycle':w['tasks'][0]['dependencies']=['summary']
            raw=transfer.encoded(w);m=json.loads(contents['manifest.json'])
            if mutation!='checksum':m['workflow_sha256']=transfer.digest(raw)
            else:raw+=b' '
            broken=self.root/(mutation+'.zip')
            with zipfile.ZipFile(broken,'w') as z:z.writestr('manifest.json',transfer.encoded(m));z.writestr('workflow.json',raw)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):transfer.preview({'path':str(broken)})
    def test_failed_draft_write_rolls_back_new_input_records(self):
        _,_,old=self.file_workflow();bundle=self.export(old,True)
        with self.database() as db:before=db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0]
        with patch.object(transfer,'write',side_effect=ValueError('controlled write failure')):
            with self.assertRaisesRegex(ValueError,'controlled'):self.import_file(bundle)
        with self.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM production_artifacts').fetchone()[0],before)
        self.assertEqual(len(list((self.root/'node-drafts').glob('*.json'))),1)
    def test_mixed_wires_and_files_remap_only_declared_file_ports(self):
        path,item,old=self.file_workflow()
        w=copy.deepcopy(old['workflow'])
        w['tasks'][1]['input_definitions']['literal']={'type':'object','label':'Literal','required':False}
        w['tasks'][1]['inputs']['literal']={'value':{'artifact':item['artifact']}}
        old=self.save(w);new=self.import_file(self.export(old,True))
        self.assertEqual(new['workflow']['tasks'][1]['inputs']['literal'],w['tasks'][1]['inputs']['literal'])
        self.assertNotEqual(new['workflow']['tasks'][1]['inputs']['reference'],w['tasks'][1]['inputs']['reference'])
    def test_archive_symlinks_duplicate_entries_and_extra_history_rejected(self):
        old=self.save();good=self.export(old)
        with zipfile.ZipFile(good) as z:parts={n:z.read(n) for n in z.namelist()}
        for case in ('symlink','duplicate','history'):
            target=self.root/(case+'.zip')
            with zipfile.ZipFile(target,'w') as z:
                for name,data in parts.items():
                    info=zipfile.ZipInfo(name)
                    if case=='symlink' and name=='workflow.json':info.external_attr=(0o120777<<16)
                    z.writestr(info,data)
                if case=='duplicate':
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore');z.writestr('manifest.json',parts['manifest.json'])
                if case=='history':z.writestr('history.json','{}')
            with self.subTest(case=case),self.assertRaises(ValueError):transfer.preview({'path':str(target)})
    def test_stale_source_and_destination_overwrite_rejected(self):
        old=self.save();self.export(old)
        with self.assertRaisesRegex(ValueError,'new .zip'):self.export(old)
        bad=dict(old,revision='wrong')
        with self.assertRaisesRegex(ValueError,'changed'):self.export(bad,name='other.zip')

if __name__=='__main__':unittest.main()
