"""Request-bound Telegram buttons and reply routing for approval cards."""
import contextlib
import json
import time

from task_relay import backends
from task_relay import codex_approvals
from task_relay import codex_requests


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS approval_messages (
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, request_id TEXT NOT NULL,
        PRIMARY KEY(chat_id,message_id))''')


def controls(state, event_id):
    if event_id.startswith('codex-approval:'):
        token = event_id.removeprefix('codex-approval:')
        row = state.db.execute("SELECT * FROM codex_approvals WHERE id=? AND status='pending'", (token,)).fetchone()
        if not row:
            return None
        request = json.loads(row['request_json'])
        if request['method'] == codex_requests.INPUT and codex_requests.supported(request):
            qs = codex_requests.questions(request)
            options = qs[0].get('options') or [] if len(qs) == 1 else []
            if options:
                return token, {'inline_keyboard': [[{'text': str(i) + '. ' + o['label'][:70],
                        'callback_data': f'question:{token}:{i}'}] for i, o in enumerate(options, 1)]}
            return token, {'force_reply': True, 'input_field_placeholder': 'Reply to these questions'}
        if request['method'] not in codex_approvals.METHODS:
            return None
        allow = bool(row['can_allow'])
    elif event_id.startswith('permission:'):
        token = event_id.removeprefix('permission:')
        row = state.db.execute("SELECT 1 FROM tool_requests WHERE id=? AND status='pending' AND expires_at>?", (token, time.time())).fetchone()
        if not row:
            return None
        allow = True
    else:
        return None
    buttons = ([{'text': 'Allow', 'callback_data': 'approval:allow:' + token}] if allow else [])
    buttons.append({'text': 'Deny', 'callback_data': 'approval:deny:' + token})
    return token, {'inline_keyboard': [buttons]}


def remember(state, chat_id, message_id, token):
    state.db.execute('INSERT OR REPLACE INTO approval_messages VALUES (?,?,?)', (chat_id, message_id, token))


def command_token(state, message, arg):
    if arg.strip():
        return arg.strip()
    reply = message.get('reply_to_message', {}).get('message_id')
    row = state.db.execute('SELECT request_id FROM approval_messages WHERE chat_id=? AND message_id=?',
                           (message['chat']['id'], reply)).fetchone()
    if row:
        return row['request_id']
    raise ValueError('That command arrived without a request ID. Tap an Allow/Deny button, '
                     'reply directly to a new approval card with /allow or /deny, '
                     'or copy the full command including its ID. Tapping the /allow text alone omits the ID.')


def decide(bridge, token, allow):
    if token.startswith('cx-'):
        return codex_approvals.decide(bridge.state, token, allow, bridge.desktop_factory)
    tid = backends.decide(bridge.state, token, allow)
    return tid, 'Approved once.' if allow else 'Denied.'


def callback(bridge, update):
    """Return False only when this is another component's callback."""
    q = update['callback_query']
    data = q.get('data', '')
    is_question = data.startswith('question:')
    if not data.startswith('approval:') and not is_question:
        return False
    user, message = q.get('from', {}), q.get('message', {})
    chat = message.get('chat', {})
    state = bridge.state
    if (user.get('is_bot') or user.get('id') != state.get('user_id') or
            chat.get('type') != 'private' or chat.get('id') != state.get('chat_id')):
        return True
    # Acknowledge the UI spinner independently of the actual approval operation.
    from task_relay.bridge import BridgeError
    with contextlib.suppress(BridgeError):
        bridge.telegram.call('answerCallbackQuery', callback_query_id=q['id'])
    parts = data.split(':')
    row = state.db.execute('SELECT request_id FROM approval_messages WHERE chat_id=? AND message_id=?',
                           (chat['id'], message.get('message_id'))).fetchone()
    token = parts[1] if is_question and len(parts) == 3 else parts[2] if len(parts) == 3 else None
    if len(parts) != 3 or (not is_question and parts[1] not in ('allow', 'deny')) or not row or row['request_id'] != token:
        bridge.send('This button is not linked to that approval card. Use the original request.')
        return True
    try:
        if is_question:
            request_row = state.db.execute('SELECT request_json FROM codex_approvals WHERE id=?', (token,)).fetchone()
            request = json.loads(request_row['request_json']) if request_row else {}
            qs = codex_requests.questions(request)
            if not qs or len(qs) != 1 or not parts[2].isascii() or not parts[2].isdigit() or not 1 <= int(parts[2]) <= len(qs[0].get('options') or []):
                raise ValueError('This option is not available for that question.')
            tid, result = codex_approvals.decide(state, token, False, bridge.desktop_factory, answer=parts[2])
        else:
            tid, result = decide(bridge, token, parts[1] == 'allow')
    except (ValueError, BridgeError) as exc:
        if token and token.startswith('cx-'):
            spent = state.db.execute('SELECT status FROM codex_approvals WHERE id=?', (token,)).fetchone()
            if spent and spent['status'] != 'pending':
                with contextlib.suppress(BridgeError):
                    bridge.telegram.call('editMessageReplyMarkup', chat_id=chat['id'],
                                         message_id=message['message_id'], reply_markup={'inline_keyboard': []})
        bridge.send(str(exc))
        return True
    # The existing request handlers durably prevent duplicate grants, even if
    # clearing the old buttons or sending the acknowledgement fails.
    with contextlib.suppress(BridgeError):
        bridge.telegram.call('editMessageReplyMarkup', chat_id=chat['id'],
                             message_id=message['message_id'], reply_markup={'inline_keyboard': []})
    bridge.send(result, tid)
    return True


def reply_input(bridge, message, update_id):
    """Consume a direct question reply before ordinary task/command routing."""
    reply = message.get('reply_to_message', {}).get('message_id')
    row = bridge.state.db.execute('SELECT a.* FROM approval_messages m JOIN codex_approvals a '
        'ON a.id=m.request_id WHERE m.chat_id=? AND m.message_id=?',
        (message['chat']['id'], reply)).fetchone()
    if not row or json.loads(row['request_json'])['method'] != codex_requests.INPUT:
        return False
    from task_relay.bridge import BridgeError
    try:
        if not message.get('text'):
            raise ValueError('Reply to this question with text or tap one of its options.')
        tid, result = codex_approvals.decide(bridge.state, row['id'], False,
                                          bridge.desktop_factory, answer=message['text'])
    except (ValueError, BridgeError) as exc:
        bridge.send(str(exc), row['thread_id'])
        return True
    with bridge.state.db:
        bridge.state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'answered', tid))
    bridge.send(result, tid)
    return True
