"""Full public compiler path after two failed corrections; synthetic media only."""
import copy,json
from pathlib import Path
from orchestrator import operation_contracts as c
from orchestrator.operation_records import Store
from orchestrator.runtime import Runtime
from tests.test_compiled_visual_lifecycle import Compiled
from tests.test_visual_selection_lifecycle import VisualPath

class FailedCompiled(Compiled):
    def content(self,ident,source,baseline=None):
        task=super().content(ident,source,baseline)
        if baseline:task['content'].pop('parameters')
        return task

    def repair(self,ident,base,fragment,source,blocked=False):
        if ident=='repair_again':
            # The later scripted correction consumes the actual current export,
            # rather than reconstructing a record from an earlier fixture.
            retained=json.loads(Path(base['blob']).read_text())['records'][0]
            retained['options'][0]['comparison']=fragment['options'][0]['comparison']
            fragment=retained
        return super().repair(ident,base,fragment,source,blocked)
    def artifact(self,task,path='outputs/result.json'):
        if task=='repair' and getattr(self,'recovered',False):task='recovered_merge'
        return super().artifact(task,path)

    def review(self,ident):
        if ident=='repair' and getattr(self,'recovered',False):ident='recovered_merge'
        return super().review(ident)

    def run_worker(self,ident,steps,decision='delivered'):
        if ident!='repair':return super().run_worker(ident,steps,decision)
        chunks=[self.rt.spec(t) for t in self.rt.status('job')['tasks'] if t['id'].startswith('repair_batch_') and not self.rt.spec(t).get('review_of')]
        self.assertEqual(len(chunks),2);first,other=sorted(chunks,key=lambda t:t['operation_contract']['parameters']['record_range'])
        def actions(f):
            calls=steps(f)
            return calls
        VisualPath.run_worker(self,first['id'],actions,'blocked')
        self.assertEqual(self.rt.task('job',first['id'])['status'],'blocked')
        VisualPath.run_worker(self,other['id'],lambda f:[])
        self.review(other['id'])
        failed=self.artifact(first['id']);pack=self.artifact(first['id'],'delivery/retained-sources.json')
        original=Path(failed['blob']).read_bytes();saved=json.loads(original)['records']
        # Two fresh failed workers retain different corrections. Neither failure
        # becomes a baseline acceptance or an implicit scheduling prerequisite.
        for name,blocked in (('checkpoint_second',True),('checkpoint_final',False)):
            self.submit(name,[self.content(name,pack,failed)])
            frozen=self.factory.sessions[self.rt.task('job',name)['latest']]['frozen']
            self.assertEqual(frozen['operation_contract']['parameters']['record_range'],[0,10])
            progress=Store(frozen,self.rt.db).progress()
            self.assertEqual(progress['committed'],10);self.assertEqual(progress['remaining'],0)
            self.assertEqual(progress['scope']['items'],[i['id'] for i in self.h.inventory['items'][:10]])
            self.assertEqual(progress['record_versions'],{r['item']:c.digest(r) for r in saved})
            revised=copy.deepcopy(saved[0])
            field=next(k for k in self.h.config['fields'] if k!=self.h.config['identity'])
            option=0 if blocked else 1
            revised['options'][option]['fields'][field]=dict(status='unknown',reason='Saved capture does not establish the selected variant; '+name+' qualification.')
            def amend(f):
                calls=[('operation_amend',dict(request_key=name,revision=0,expected_record_sha256=c.digest(saved[0]),record=revised))]
                # Three actual fixture image observations are prepended. Inspect
                # the export at request 23 and finish at 24, never larger grants.
                calls += [('file_read',dict(path=f['inputs'][0]['path'],offset=0,limit=100))]*18
                calls += [('file_read',dict(path=f['operation_contract']['output'],offset=0,limit=24000))]
                return calls
            f,script=VisualPath.run_worker(self,name,amend,'blocked' if blocked else 'delivered')
            self.assertEqual(len(script.requests),24)
            failed=self.artifact(name);pack=self.artifact(name,'delivery/retained-sources.json')
            saved=json.loads(Path(failed['blob']).read_text())['records']
            self.assertEqual(saved[0],revised)
            self.assertEqual([o['selection'] for o in saved[0]['options']],[o['selection'] for o in json.loads(original)['records'][0]['options']])
            self.assertIn('checkpoint_second qualification',json.dumps(saved[0]['options'][0]))
            if blocked:
                self.rt.close();self.rt=Runtime(self.root,self.factory,connection=self.state.db)
            else:self.review(name)
        self.assertEqual(Path(self.artifact(first['id'])['blob']).read_bytes(),original)
        reviews=[]
        for producer in ('checkpoint_final',other['id']):
            rid=next(t['id'] for t in self.rt.status('job')['tasks'] if self.rt.spec(t).get('review_of')==producer)
            path=self.rt.spec(self.rt.task('job',rid))['operation_contract']['output']
            reviews.append({'artifact':self.artifact(rid,path)['id']})
        p=self.rt.spec(self.rt.task('job','repair'))['execution']['parameters']
        params={k:copy.deepcopy(v) for k,v in p.items() if k not in ('inventory_path','source_pack_path','catalog_paths','review_paths')}
        params.update(inventory_path={'artifact':self.inv['artifact']},source_pack_path={'artifact':pack['id']},
            catalog_paths=[{'artifact':failed['id']},{'artifact':self.artifact(other['id'])['id']}],review_paths=reviews)
        self.submit('recovered_merge',[dict(id='recovered_merge',objective='Merge exact independently reviewed corrected partitions',operation='records.merge',parameters=params)])
        self.native('recovered_merge');self.recovered=True

    def test_failed_corrections_full_compiler_to_rereview_partial(self):
        self.test_compiler_partition_to_visual_correction_review_partial()
        self.assertEqual(self.rt.task('job','repair_batch_1')['status'],'blocked')
        self.assertEqual(self.rt.task('job','checkpoint_second')['status'],'blocked')
        final=json.loads(Path(self.artifact('final_repair')['blob']).read_text())['records'][0]
        self.assertIn('checkpoint_second qualification',json.dumps(final['options'][0]))
        self.assertIn('checkpoint_final qualification',json.dumps(final['options'][1]))

class Plants(FailedCompiled):schema='plants'
class Components(FailedCompiled):schema='components'
