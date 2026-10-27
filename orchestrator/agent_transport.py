"""Provider wire adapters for the common agent session.

No task scheduling, artifact acceptance, permission changes or effect replay.
"""
import copy
import json
from dataclasses import dataclass
from . import contracts as c
from task_relay import api_providers as api

def gemini_declarations(tools):
    # Keep Gemini's constrained decoder away from the nested report union. The
    # complete frozen schema is still in the assignment and enforced locally.
    result=[]
    for tool in tools:
        # Explicit canonical JSON Schema is a lossless provider contract. Legacy
        # projections below remain frozen for previously admitted assignments.
        if 'parametersJsonSchema' in tool and tool['name']!='finish':
            result.append(copy.deepcopy(tool));continue
        value={k:v for k,v in tool.items() if not (k=='parameters' and v=={
            'type':'object','properties':{},'required':[]})}
        if tool['name'] in ('operation_submit','operation_amend','sourcing_source_read','source_read') or tool['name']=='job_delegate' and 'tasks' in tool.get('parameters',{}).get('properties',{}):
            # The shared contract exposes ordinary JSON Schema. Gemini's legacy
            # Schema field cannot carry additionalProperties; adapt only the wire.
            value['parametersJsonSchema']=value.pop('parameters')
        if tool['name'] in ('operation_submit','operation_amend'):
            # Deep fragment unions belong to the local contract validator, not
            # Gemini's constrained decoder. Keep the small control fields typed.
            schema=json.loads(json.dumps(value.pop('parametersJsonSchema')))
            field='records' if tool['name']=='operation_submit' else 'record'
            fragment=schema['properties'].pop(field);wire=field+'_json'
            schema['properties'][wire]={'type':'string','description':'JSON-encoded '+field+' conforming to this exact fragment schema: '+c.encoded(fragment)}
            schema['required']=[wire if key==field else key for key in schema['required']]
            schema.pop('additionalProperties',None)
            value['parameters']=schema
        if tool['name']=='finish':
            value.pop('parametersJsonSchema',None)
            value['parameters']={'type':'object','properties':{'report_json':{
                'type':'string','description':'JSON-encoded complete report object conforming to the frozen report_contract.schema (or legacy report schema). Include every required check. Relay validates its schema, evidence and decision before accepting it.'}},'required':['report_json']}
        from orchestrator.gemini_tool_schema import declaration
        result.append(declaration(value))
    return result


def gemini_record_arguments(name,args):
    field='records' if name=='operation_submit' else 'record'
    wire=field+'_json'
    if not isinstance(args,dict) or wire not in args:return args
    if field in args or not isinstance(args[wire],str):raise ValueError('Use one JSON-encoded fragment argument')
    parsed=json.loads(args[wire])
    if (field=='records' and not isinstance(parsed,list)) or (field=='record' and not isinstance(parsed,dict)):
        raise ValueError('Invalid fragment JSON container')
    return {**{k:v for k,v in args.items() if k!=wire},field:parsed}


def gemini_report_arguments(args):
    # Older recorded/direct report objects remain readable under the same strict
    # local validator. No additional fields may accompany a transport envelope.
    if isinstance(args,dict) and 'report_json' in args:
        if set(args)!={'report_json'} or not isinstance(args['report_json'],str):
            raise ValueError('finish accepts one report_json string containing the complete report.')
        value=json.loads(args['report_json'])
        if not isinstance(value,dict):raise ValueError('report_json must encode a report object.')
        return value
    return args


@dataclass(frozen=True)
class Transport:
    provider: str

    @property
    def key(self):
        return 'contents' if self.provider == 'gemini' else 'input' if self.provider == 'openai' else 'messages'

    @property
    def head(self):
        return 0 if self.provider in ('gemini', 'openai') else 1

    def payload(self, backend, system, tools, contents, history, tokens, runtime=''):
        if self.provider == 'gemini':
            return 'models/'+backend['model']+':generateContent', dict(
                systemInstruction=dict(parts=[dict(text=system)]), contents=contents,
                tools=[dict(functionDeclarations=gemini_declarations(tools))],
                toolConfig=dict(functionCallingConfig=dict(mode='AUTO')),
                generationConfig=dict(maxOutputTokens=tokens))
        specs=[dict(name=t['name'], description=t['description'],
                    parameters=t.get('parametersJsonSchema', t.get('parameters'))) for t in tools]
        common=dict(model=backend['model'], tool_choice='required')
        if self.provider == 'openai':
            return 'responses', dict(**common, instructions=system, input=history, store=False,
                include=['reasoning.encrypted_content'], max_output_tokens=tokens,
                tools=[dict(type='function', **t, strict=False) for t in specs])
        payload=dict(**common, messages=[dict(role='system', content=system), *history], stream=False,
                     max_tokens=tokens, tools=[dict(type='function', function=t) for t in specs])
        if self.provider == 'openrouter':payload['provider']=dict(allow_fallbacks=False)
        if self.provider == 'codex':payload['relay_runtime']=runtime
        return 'chat/completions', payload

    def request(self, client, endpoint, payload, timeout):
        if self.provider == 'gemini':
            return client.request(endpoint, payload, timeout=timeout, max_response_bytes=1000000)
        return client.request(endpoint, payload)

    def verify_response_authority(self, response):
        # Hosted execution is different from a proposed function call. Never
        # discard such an item and claim that local correction has no effects.
        from .runtime_outcomes import UncertainOperation
        if self.provider == 'openai':
            unexpected = [item.get('type') for item in response.get('output', [])
                          if item.get('type') not in ('function_call', 'message', 'reasoning')]
        elif self.provider == 'gemini':
            unexpected = [key for candidate in response.get('candidates', [])
                          for part in candidate.get('content', {}).get('parts', [])
                          for key in ('executableCode', 'codeExecutionResult') if key in part]
            if any(candidate.get('groundingMetadata') for candidate in response.get('candidates', [])):
                unexpected.append('groundingMetadata')
        else:
            unexpected = []  # Chat function calls are proposals, decoded below.
        if unexpected:
            raise UncertainOperation('Provider returned execution outside the declared function-only '
                                     'surface: '+str(unexpected)+'. Original response retained; no local calls executed or automatic replay.')

    def decode(self, response):
        if self.provider == 'gemini':
            candidate=(response.get('candidates') or [{}])[0]
            if candidate.get('finishReason') != 'STOP':
                raise ValueError('Provider response rejected: '+str(candidate.get('finishReason') or 'missing finish reason')[:80]+'. No tools from this response were executed.')
            content=candidate.get('content', {})
            return [p['functionCall'] for p in content.get('parts', []) if 'functionCall' in p], content, []
        calls=api.tool_calls(self.provider, response)
        return [dict(id=t['id'], name=t['name'], args=json.loads(t['arguments'])) for t in calls], None, calls

    def continue_request(self, payload, response, calls, results):
        # Appending a received result is not dispatch. Capacity is measured by
        # prepare() on the next actual transport message, before sending it.
        if self.provider == 'openai':
            payload['input'].extend(response['output'])
            payload['input'].extend(dict(type='function_call_output', call_id=c['id'], output=r)
                                    for c, r in zip(calls, results))
        else:
            payload['messages'].append(response['choices'][0]['message'])
            payload['messages'].extend(dict(role='tool', tool_call_id=c['id'], content=r)
                                       for c, r in zip(calls, results))

    def arguments(self, name, args, definition):
        if self.provider != 'gemini':return args
        from .gemini_tool_schema import decode
        if 'parametersJsonSchema' not in definition:
            args=decode(args, definition.get('parameters', {}))
        if name in ('operation_submit', 'operation_amend'):return gemini_record_arguments(name, args)
        if name == 'finish':return gemini_report_arguments(args)
        return args
