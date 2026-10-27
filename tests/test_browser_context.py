import copy,json,tempfile,unittest
from pathlib import Path
from orchestrator.browser_context import Archive

class Tests(unittest.TestCase):
    def test_smaller_history_preserves_live_refs_signatures_and_exact_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root));contents=[]
            for n in range(8):
                contents.extend([{'role':'model','parts':[{'thoughtSignature':'signature-'+str(n),'functionCall':{'name':'browser_read','id':str(n),'args':{}}}]},
                    {'role':'user','parts':[{'functionResponse':{'name':'browser_read','id':str(n),'response':{'observation':str(n),'url':'https://example.test/'+str(n),'text':('Price $125; width 24 inches. '*1200),'controls':[{'ref':n}]}}}]}])
            original=copy.deepcopy(contents);view=a.view(contents)
            self.assertEqual(contents,original)
            self.assertLess(len(json.dumps(view)),len(json.dumps(contents))//4)
            self.assertEqual(view[-1],contents[-1])
            self.assertEqual(view[0],contents[0])
            self.assertEqual(view[1]['parts'][0]['functionResponse']['id'],'0')
            reference=view[1]['parts'][0]['functionResponse']['response'];offset=0;chunks=[]
            while True:
                part=a.read({'evidence':reference['evidence'],'offset':offset});chunks.append(part['text'])
                if part['next_offset'] is None:break
                offset=part['next_offset']
            self.assertEqual(json.loads(''.join(chunks)),original[1]['parts'][0]['functionResponse']['response'])
            self.assertEqual(a.view(contents),view)

    def test_unknown_path_and_tampered_archive_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root));a.save('browser-0',{'text':'Original price $125'})
            for args in ({'evidence':'../secret','offset':0},{'evidence':'browser-0','offset':-1},{'evidence':'browser-0','offset':True}):
                with self.assertRaises(ValueError):a.read(args)
            (Path(root)/'context-evidence/browser-0.json').write_text('{"text":"Fake price"}')
            with self.assertRaisesRegex(ValueError,'changed'):a.read({'evidence':'browser-0','offset':0})

    def test_error_and_latest_small_result_are_not_lost(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root));value={'error':'Retailer challenge','text':'x'*9000}
            history=[{'role':'user','parts':[{'functionResponse':{'name':'browser_read','response':value}}]},
                     {'role':'user','parts':[{'functionResponse':{'name':'browser_wait','response':{'observation':'current'}}}]}]
            view=a.view(history)
            self.assertEqual(view[0]['parts'][0]['functionResponse']['response']['error'],'Retailer challenge')
            self.assertEqual(view[-1],history[-1])

    def test_retrieved_excerpts_do_not_accumulate_but_latest_controls_remain(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root));contents=[]
            def turn(name,value):return {'role':'user','parts':[{'functionResponse':{'name':name,'response':value}}]}
            contents.append(turn('browser_read',{'observation':'live','controls':[{'ref':'specs'}],'text':'Page '*2000}))
            for n in range(6):contents.append(turn('evidence_read',{'evidence':'old-page','text':str(n)*8000,'offset':n*8000}))
            view=a.view(contents)
            self.assertEqual(view[0],contents[0]);self.assertEqual(view[-1],contents[-1])
            self.assertLess(len(json.dumps(view)),len(json.dumps(contents))//2)
            for item in view[1:-1]:
                ref=item['parts'][0]['functionResponse']['response']
                saved=a.read({'evidence':ref['evidence'],'offset':0})
                self.assertIn('text',saved['text'])
