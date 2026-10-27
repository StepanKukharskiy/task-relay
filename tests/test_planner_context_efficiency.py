import copy,json,unittest
from unittest.mock import Mock,patch
from task_relay.production_planning import generate

class Tests(unittest.TestCase):
    def test_instructions_are_sent_once_without_changing_authority_or_correction(self):
        payload={'planner_instructions':'Follow the exact frozen scope. '*100,
                 'original_request':'Source three alternatives for every piece.',
                 'sources':[{'sha256':'abc','path':'photo.jpg'}],
                 'structural_correction':{'previous_response':'retained','error':'missing binding'},
                 'response_contract':{'schema':{'type':'object'}}}
        original=copy.deepcopy(payload);client=Mock()
        client.request.return_value={'candidates':[{'content':{'parts':[{'text':'{}'}]}}],'usageMetadata':{'promptTokenCount':123}}
        with patch('task_relay.production_planning.gemini.read_config',return_value={'api_key':'fixture'}),patch('task_relay.production_planning.gemini.Client',return_value=client):
            answer,usage=generate({'provider':'gemini','model':'gemini-3.7-flash'},payload)
        sent=client.request.call_args.args[1]
        self.assertEqual(sent['systemInstruction']['parts'][0]['text'],payload['planner_instructions'])
        self.assertEqual(json.loads(sent['contents'][0]['parts'][0]['text']),{k:v for k,v in payload.items() if k!='planner_instructions'})
        self.assertEqual(payload,original);self.assertEqual(usage,{'promptTokenCount':123})
