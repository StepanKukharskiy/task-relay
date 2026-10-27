"""Classify received provider candidates before any tool parsing or execution.

This is shared by planning and worker loops. Transport exceptions have no
received candidate and are never correction permission. Each owner retains its
own frozen request/time allowance and journals the decision before continuing.
"""
import json


def single(response,key):
    values=response.get(key)
    return values[0] if isinstance(values,list) and len(values)==1 and isinstance(values[0],dict) else {}


def output_limited(provider, response):
    if not isinstance(response, dict):return False
    if provider=='gemini':
        return single(response,'candidates').get('finishReason')=='MAX_TOKENS'
    if provider=='openai':
        return response.get('status')=='incomplete' and (response.get('incomplete_details') if isinstance(response.get('incomplete_details'),dict) else {}).get('reason')=='max_output_tokens'
    return provider in ('qwen','deepseek','openrouter') and single(response,'choices').get('finish_reason')=='length'


def generation_failure(provider, response):
    if not isinstance(response, dict):return None
    if output_limited(provider,response):return 'generation_output_limit'
    if provider=='gemini':
        if single(response,'candidates').get('finishReason')=='MALFORMED_FUNCTION_CALL':
            return 'malformed_function_call'
    elif provider in ('openai','qwen','deepseek','openrouter'):
        # Malformed arguments qualify only in an explicitly completed response.
        # Safety refusals, missing/ambiguous candidates and pending calls do not.
        complete=(response.get('status')=='completed' if provider=='openai' else
                  single(response,'choices').get('finish_reason') in ('stop','tool_calls'))
        if not complete:return None
        from task_relay import api_providers as api
        try:calls=api.tool_calls(provider,response)
        except (ValueError,TypeError,KeyError):return None
        try:
            for call in calls:json.loads(call['arguments'])
        except (json.JSONDecodeError,TypeError):return 'malformed_function_call'
    return None


def recovery_outcome(provider,response,phase):
    from .operation_session import outcome
    code=generation_failure(provider,response)
    return outcome(phase,'correction_needed',code,effect='none',
                   usage=response.get('usageMetadata',response.get('usage',{}))) if code else None
