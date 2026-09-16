"""Native inspection arguments stay distinct from historical review evidence."""
import copy
import json
import unittest
from pathlib import Path
from task_relay import production_planning as planning
from tests import test_production_planning as fixture
from tests.test_blender_operations import operation


class Tests(unittest.TestCase):
    setUp=fixture.Tests.setUp
    tearDown=fixture.Tests.tearDown
    request=fixture.Tests.request
    action=fixture.Tests.action
    queue=fixture.Tests.queue
    row=fixture.Tests.row
    response=fixture.Tests.response

    def case(self,kind):
        suffix,media=('.3dm','application/vnd.rhino') if kind=='rhino' else ('.blend','application/x-blender')
        row=dict(self.queue())
        payload=json.loads(row['context']);options=json.loads(row['options'])
        options['step_capabilities']=[kind+'.inspect'];payload['options']=options
        sources=[]
        for name in ('old','selected'):
            path=self.state.media_dir.parent/(name+suffix);path.write_text(name+' native fixture')
            aid=self.rt.register(path,'Native version evidence',path=name+suffix)
            source=planning.source_entry(self.rt,aid,'history/'+name+suffix,'Previous native model','Historical evidence')
            payload['sources'].append(source);payload['required_artifacts'].append(aid);sources.append(source)
        row.update(context=json.dumps(payload),options=json.dumps(options))
        response=self.response();producer,review=response['plan']['tasks']
        out='delivery/model'+suffix
        producer['outputs']=[dict(path=out,purpose='New native model',media_type=media)]
        upstream=dict(from_task=producer['id'],output=out,path='candidate/model'+suffix,purpose='Inspect new exact model',authority='Unaccepted candidate',media_type=media)
        inspector=operation(kind+'.inspect',[upstream]);inspector['dependencies']=[producer['id']]
        inspector['limits']=dict(seconds=120,tool_calls=1,output_bytes=2000000)
        review['dependencies']=[producer['id'],'app'];review['inputs']=[copy.deepcopy(upstream)]
        review['inputs'] += [dict(from_task='app',output=o['path'],path='inspection/'+Path(o['path']).name,purpose='Inspect evidence',authority='Unaccepted candidate',media_type=o['media_type']) for o in inspector['outputs']]
        response['plan']['tasks']=[producer,inspector,review]
        return row,response,sources,media

    def assert_upstream_binding(self,kind):
        row,response,sources,media=self.case(kind)
        _,plan=planning.validate_result(json.dumps(response),row)
        inspector=plan['tasks'][1];review=plan['tasks'][2]
        native=[i for i in inspector['inputs'] if i.get('media_type')==media]
        self.assertEqual(len(native),1);self.assertEqual(native[0]['from_task'],'produce')
        self.assertFalse(any(i.get('artifact') in {s['artifact'] for s in sources} for i in inspector['inputs']))
        self.assertTrue({s['artifact'] for s in sources}<={i.get('artifact') for i in review['inputs']})

    def test_rhino_upstream_model_excludes_history_but_reviewer_keeps_it(self):
        self.assert_upstream_binding('rhino')

    def test_blender_upstream_model_excludes_history_but_reviewer_keeps_it(self):
        self.assert_upstream_binding('blender')

    def test_explicit_selection_keeps_exact_version(self):
        row,response,sources,media=self.case('rhino');source=sources[0]
        response['plan']['tasks'][1]['dependencies']=[]
        response['plan']['tasks'][1]['inputs']=[{k:source[k] for k in ('artifact','path','purpose','authority')}]
        _,plan=planning.validate_result(json.dumps(response),row)
        native=[i for i in plan['tasks'][1]['inputs'] if i.get('media_type')==media]
        self.assertEqual([i['artifact'] for i in native],[source['artifact']])

    def test_history_cannot_fill_missing_argument_or_hide_ambiguous_selection(self):
        row,response,sources,media=self.case('blender')
        for selected in ([],sources):
            with self.subTest(count=len(selected)):
                response['plan']['tasks'][1]['inputs']=[{k:s[k] for k in ('artifact','path','purpose','authority')} for s in selected]
                with self.assertRaisesRegex(ValueError,'Select exactly one Blender'):
                    planning.validate_result(json.dumps(response),row)
