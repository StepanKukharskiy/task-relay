"""Readable connector confirmations and request-bound Codex questions."""
import json
import re

from task_relay.telegram_text import Text

MCP = 'mcpServer/elicitation/request'
INPUT = 'item/tool/requestUserInput'
INPUT_METHOD = 'thread-follower-submit-user-input'
MAX_TEXT = 24000


def connector_supported(p):
    schema, meta = p.get('requestedSchema'), p.get('_meta', {})
    # Typed forms, authentication and special execution-bound connector plans
    # need their own UI/validation. Never turn them into a generic confirmation.
    return (p.get('mode') == 'form' and isinstance(schema, dict) and
            schema.get('type') == 'object' and schema.get('properties') == {} and
            set(schema) <= {'type', 'properties', 'required', 'additionalProperties'} and
            schema.get('required', []) == [] and isinstance(meta, dict) and
            meta.get('codex_approval_kind') == 'mcp_tool_call' and
            isinstance(meta.get('tool_params'), dict) and
            meta.get('connector_id') != 'connector_20205bf7d4e99a89d7154bb849718324' and
            not any(meta.get(k) for k in ('approveDisabled', 'executionBound', '_codex_apps')))


def questions(request):
    p = request.get('params', {})
    qs = p.get('questions')
    if request.get('method') != INPUT or not isinstance(qs, list) or not 1 <= len(qs) <= 3:
        return None
    ids = set()
    for q in qs:
        if (not isinstance(q, dict) or not isinstance(q.get('id'), str) or not q['id'] or
                q['id'] in ids or not isinstance(q.get('question'), str) or
                q.get('isSecret') or q.get('is_secret')):
            return None
        ids.add(q['id'])
        opts = q.get('options') or []
        if not isinstance(opts, list) or len(opts) > 10 or any(
                not isinstance(o, dict) or not isinstance(o.get('label'), str) or not o['label'] for o in opts):
            return None
    return qs


def literal(out, value):
    """Preserve nested argument structure and nulls, rendering strings literally."""
    if isinstance(value, str):
        out.styled(value, 'pre')
    else:
        out.styled(json.dumps(value, ensure_ascii=False, indent=2), 'pre')
    out.add('\n\n')


def render(title, request):
    p = request['params']
    qs = questions(request)
    if not qs and not (request['method'] == MCP and connector_supported(p)):
        return None
    out = Text()
    out.styled('Codex needs your input' if qs else 'Allow connector action?', 'bold')
    out.add('\n' + title[:160] + '\n\n')
    if qs:
        for i, q in enumerate(qs, 1):
            out.styled(f'{i}. {q.get("header") or "Question"}', 'bold')
            out.add('\n' + q['question'] + '\n')
            for n, opt in enumerate(q.get('options') or [], 1):
                out.add(f'{n}) {opt["label"]}')
                if opt.get('description'):
                    out.add(' — ' + str(opt['description']))
                out.add('\n')
            out.add('\n')
        out.add('Reply directly to this card with your answer. ')
        out.add('You can send an option number or your own text.' if len(qs) == 1 else
                'Answer each question on its own numbered line, for example:\n1: Your first answer\n2: Your second answer')
    else:
        out.add(str(p.get('message', '')) + '\n\n')
        out.add('Server: ' + str(p.get('serverName', '')) + '\n\n')
        meta = p['_meta']
        if meta.get('tool_description'):
            out.add(str(meta['tool_description']) + '\n\n')
        for key, value in meta['tool_params'].items():
            out.styled(str(key), 'bold'); out.add('\n'); literal(out, value)
        # Drop display metadata only when it is an exact redundant projection.
        display = meta.get('tool_params_display')
        redundant = isinstance(display, list) and all(isinstance(x, dict) and
            x.get('name') in meta['tool_params'] and x.get('value') == meta['tool_params'][x['name']]
            for x in display)
        extra = {k: v for k, v in meta.items() if k not in
                 ('tool_params', 'tool_description', 'codex_approval_kind', 'persist') and
                 not (k == 'tool_params_display' and redundant)}
        if extra:
            out.add('Additional request details\n'); literal(out, extra)
        unknown = {k: v for k, v in p.items() if k not in
                   ('threadId', 'turnId', 'itemId', 'startedAtMs', 'message', 'serverName', 'mode', 'requestedSchema', '_meta')}
        if unknown:
            literal(out, unknown)
        out.add('Allow this request once. No persistent permission will be saved.\nUse Allow/Deny below.')
    return out.result()


def supported(request):
    if len(json.dumps(request)) > 256000:
        return False
    value = render('', request)
    return value is not None and len(value[0]) <= MAX_TEXT - 200


def parse_answers(request, text):
    qs = questions(request)
    if not qs or not supported(request):
        raise ValueError('This question needs its desktop form.')
    if len(qs) == 1:
        values = [text.strip()]
    else:
        matches = list(re.finditer(r'(?m)^([1-3]):[ \t]*', text))
        if len(matches) != len(qs) or [int(m[1]) for m in matches] != list(range(1, len(qs) + 1)) or text[:matches[0].start()].strip():
            raise ValueError('Reply with one numbered line per question: 1: answer, then 2: answer on the next line.')
        values = [text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip() for i,m in enumerate(matches)]
    answers = {}
    for q, value in zip(qs, values):
        if not value or len(value) > 8000:
            raise ValueError('Each question needs a nonempty answer of at most 8,000 characters.')
        opts = q.get('options') or []
        if value.isascii() and value.isdigit() and opts:
            n = int(value)
            if not 1 <= n <= len(opts):
                raise ValueError('That option number is not listed. Choose a listed number or reply with your own text.')
            value = opts[n-1]['label']
        answers[q['id']] = {'answers': [value]}
    return {'answers': answers}
