"""Small provider-neutral frozen-scope fixtures; no request keyword inference."""
import copy
import json

ANSWER={'mode':'answer','reason':'This fixture asks for an inline answer or a status check.','outcomes':[]}


def outcome(ident='outputs',count=1,format='.md',checks=None,validation=None):
    return {'id':ident,'description':'The exact requested outputs from the saved conversation.',
            'kind':'file','count':count,'format':format,'checks':checks or ['nonempty','utf8'],
            'validation':validation or ['Match the requested topic and disclose verification limitations.']}


def work(items):return {'mode':'new_work','reason':'The user explicitly requested these deliverables.','outcomes':items}


def response(provider,contract=None):
    data=copy.deepcopy(ANSWER if contract is None else contract)
    if provider=='gemini':return {'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'relay_intake','args':data}}]}}]}
    call={'type':'function_call','call_id':'intake','name':'relay_intake','arguments':json.dumps(data)}
    if provider=='openai':return {'status':'completed','output':[call]}
    return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
        'tool_calls':[{'id':'intake','type':'function','function':{'name':'relay_intake','arguments':call['arguments']}}]}}]}
