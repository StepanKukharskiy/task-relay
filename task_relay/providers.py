"""Bot-first provider settings with explicit in-chat credential handling."""
import json
from . import credentials
import os
from pathlib import Path
import secrets
import shlex
import subprocess
from .host import HOST, UnsupportedHost
import sys
import re
import time

from task_relay import gemini
from task_relay import api_providers as api

REGISTRY = {
    **{key: {'name': spec['name'], 'description': 'Project conversations with read-only file tools', 'capabilities': ('text',)} for key, spec in api.SPECS.items()},
    'gemini': {'name': 'Gemini', 'description': 'Project files and references · speech · images · video', 'capabilities': tuple(gemini.DEFAULT_MODELS)},
    'claude': {'name': 'Claude', 'description': 'Coding agent · Claude account login', 'capabilities': ('text',)},
    'codex': {'name': 'Codex', 'description': 'Existing tasks in the desktop app', 'capabilities': ()},
}
CANDIDATES = {'text': ['gemini-3.7-flash', 'gemini-3.8-flash', 'gemini-2.5-flash'],
              'speech': ['gemini-3.1-flash-tts-preview', 'gemini-2.5-flash-preview-tts'],
              'image': ['gemini-3.1-flash-image', 'gemini-3.1-flash-image-preview', 'gemini-2.5-flash-image'],
              'video': ['veo-3.1-fast-generate-preview', 'veo-3.1-generate-preview']}


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS provider_actions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,expires_at REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS provider_jobs(id TEXT PRIMARY KEY,provider TEXT NOT NULL,operation TEXT NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS provider_deletions(chat_id INTEGER,message_id INTEGER,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,PRIMARY KEY(chat_id,message_id));
      CREATE TABLE IF NOT EXISTS provider_key_sessions(id TEXT PRIMARY KEY,provider TEXT NOT NULL,prompt_id INTEGER,status TEXT NOT NULL,expires_at REAL NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS one_provider_setup ON provider_jobs(provider) WHERE status IN ('queued','running');
    ''')
    from .browser_setup import initialize as browser_initialize
    browser_initialize(db)


def stored(provider):
    if provider not in ('gemini', 'claude', *api.SPECS):
        return {}
    try:
        value = credentials.private_json(gemini.DATA / (provider + '.json'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def catalog(key):
    client = gemini.Client(key)
    names = set()
    path = 'models?pageSize=1000'
    for _ in range(10):
        response = client.request(path)
        for row in response.get('models', []):
            name = row.get('name', '').removeprefix('models/')
            try:
                names.add(gemini.model_name(name))
            except ValueError:
                pass
        token = response.get('nextPageToken')
        if not token:
            break
        from urllib.parse import quote
        path = 'models?pageSize=1000&pageToken=' + quote(token, safe='')
    if not names:
        raise ValueError('Google returned no available models. Settings were not changed.')
    return sorted(names)


def configure_gemini(key, names=None, preserve_reference=False):
    names = catalog(key) if names is None else names
    old = stored('gemini')
    models = dict(gemini.DEFAULT_MODELS)
    models.update(old.get('models', {}))
    for cap, choices in CANDIDATES.items():
        if cap not in old.get('models', {}):
            models[cap] = next((m for m in choices if m in names), models[cap])
    config = {**old, 'api_key': key, 'enabled': True, 'models': models, 'catalog': names, 'catalog_checked_at': time.time(),
              'voice': old.get('voice', 'Kore'), 'max_output_tokens': old.get('max_output_tokens', 4096),
              'duration_seconds': old.get('duration_seconds', 4), 'aspect_ratio': old.get('aspect_ratio', '16:9')}
    if preserve_reference and 'api_key_ref' in config:config.pop('api_key',None)
    else:config.pop('api_key_ref',None)
    credentials.save(gemini.DATA / 'gemini.json', config)
    return models


class Menu:
    def __init__(self, bridge):
        self.bridge, self.state = bridge, bridge.state

    def show(self, text, buttons, tid=None):
        keyboard = []
        with self.state.db:
            self.state.db.execute('DELETE FROM provider_actions WHERE expires_at<?', (time.time(),))
            for label, payload in buttons:
                token = secrets.token_hex(12)
                self.state.db.execute('INSERT INTO provider_actions VALUES (?,?,?,0)', (token, json.dumps(payload), time.time()+3600))
                keyboard.append([{'text': label, 'callback_data': 'p:' + token}])
        if tid:
            text = self.bridge.decorate(text, tid)
        response = self.bridge.telegram.call('sendMessage', chat_id=self.state.get('chat_id'), text=text,
                                             reply_markup={'inline_keyboard': keyboard}, link_preview_options={'is_disabled': True})
        if tid:
            with self.state.db:
                self.state.remember(self.state.get('chat_id'), response['message_id'], tid)

    def home(self):
        self.show('Providers\nConnect a provider, choose its models, or start a task here. Your Mac hosts the bot; no terminal commands are needed.',
                  [(p['name'], {'op': 'provider', 'provider': key}) for key, p in REGISTRY.items()]+[('Perplexity browser',{'op':'browser_home'})])

    def provider(self, provider):
        from task_relay import backends
        if provider not in REGISTRY:
            self.bridge.send('This provider needs a runtime adapter before it can be connected. Available providers: Gemini, Claude and Codex.')
            return
        entry = REGISTRY[provider]
        if provider == 'codex':
            self.show('Codex uses the existing desktop connection. Select an existing task with /tasks. API keys are not used by this adapter.', [('Providers', {'op': 'home'})])
            return
        config = stored(provider)
        ready = bool(api.read_config(provider)) if provider in api.SPECS else (bool(gemini.read_config()) if provider == 'gemini' else bool(backends.claude_config()))
        status = 'Disabled' if config.get('enabled') is False else ('Configured; access checked when used' if ready else 'Not connected')
        pending = self.state.db.execute("SELECT operation,status FROM provider_jobs WHERE provider=? AND status IN ('queued','running')", (provider,)).fetchone()
        text = f"{entry['name']}\n{entry['description']}\n{status}"
        if pending:
            text += f"\nSetup: {pending['operation']} · {pending['status']}"
        if provider == 'claude':
            text += '\nAn eligible Claude Code account is required. Website login alone is not sufficient.'
        buttons = [('Connect / update API key', {'op': 'connect_info', 'provider': provider})] if provider in ('gemini', *api.SPECS) else []
        if provider == 'qwen':
            text += '\nEndpoint: ' + config.get('base_url', api.SPECS['qwen']['base_url'])
            buttons += [('Region / endpoint', {'op': 'endpoints', 'provider': provider})]
        if provider == 'claude':
            text += '\nThis adapter uses native Claude account login, which is not yet available in the bot. API-key providers use the in-chat connection flow.'
        if config.get('enabled') is False and (config.get('api_key') or config.get('api_key_ref') or config.get('auth') == 'account'):
            buttons += [('Enable saved connection', {'op': 'enable', 'provider': provider})]
        if ready:
            buttons += [('New task', {'op': 'new', 'provider': provider}), ('Default models', {'op': 'caps', 'provider': provider})]
            if provider in ('gemini', *api.SPECS):
                buttons += [('Check connection / refresh models', {'op': 'refresh', 'provider': provider})]
            buttons += [('Disable provider', {'op': 'disable_confirm', 'provider': provider})]
        buttons += [('Providers', {'op': 'home'})]
        self.show(text, buttons)

    def caps(self, provider, tid=None):
        if provider not in REGISTRY or not REGISTRY[provider]['capabilities']:
            self.home()
            return
        text = 'Choose a model capability for this task.' if tid else 'Choose a default model. Text defaults apply to new tasks; media defaults apply to future runs without an override.'
        self.show(text, [(cap.capitalize(), {'op': 'models', 'provider': provider, 'cap': cap, 'tid': tid}) for cap in REGISTRY[provider]['capabilities']], tid)

    def models(self, provider, cap, tid=None, page=0):
        config = stored(provider)
        if provider == 'claude':
            choices = ['sonnet', 'opus', 'haiku']
        elif provider in api.SPECS:
            choices = list(dict.fromkeys([config.get('model', api.SPECS[provider]['model'])] + config.get('catalog', [])))
        else:
            available = set(config.get('catalog', []))
            choices = [m for m in CANDIDATES[cap] if not available or m in available]
            current = config.get('models', {}).get(cap, gemini.DEFAULT_MODELS[cap])
            choices = list(dict.fromkeys([current] + choices))
        text = f'{REGISTRY[provider]["name"]} · {cap}\nChoose a model for ' + ('this task.' if tid else 'the default.')
        text += '\nThese are supported adapter candidates; account access is verified when used. Exact IDs remain available through /model.'
        page = max(0, min(int(page), max(0, (len(choices) - 1) // 12)))
        buttons = [(m, {'op': 'setmodel', 'provider': provider, 'cap': cap, 'tid': tid, 'model': m}) for m in choices[page*12:(page+1)*12]]
        if page:
            buttons += [('Previous models', {'op': 'models', 'provider': provider, 'cap': cap, 'tid': tid, 'page': page-1})]
        if (page+1)*12 < len(choices):
            buttons += [('More models', {'op': 'models', 'provider': provider, 'cap': cap, 'tid': tid, 'page': page+1})]
        self.show(text, buttons + [('Back', {'op': 'caps', 'provider': provider, 'tid': tid})], tid)

    def queue(self, provider, operation, key=None):
        from task_relay import backends
        if operation == 'connect' and provider == 'claude' and not backends.CLAUDE_PYTHON.is_file():
            raise ValueError('Claude runtime is not installed on this Mac yet.')
        if self.state.db.execute("SELECT 1 FROM provider_jobs WHERE provider=? AND status IN ('queued','running')", (provider,)).fetchone():
            raise ValueError('Provider setup is already queued or running. Finish the window on your Mac, then reopen Providers.')
        if self.state.db.execute("SELECT 1 FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id WHERE t.backend=? AND j.status IN ('queued','running','waiting')", (provider,)).fetchone():
            raise ValueError('Wait for this provider’s active tasks to finish before changing its connection.')
        jid = secrets.token_hex(16)
        if operation == 'connect':
            if not key:
                raise ValueError('Use the provider connection button to enter a key.')
            credentials.save(gemini.DATA / 'setup-input' / (jid + '.json'), {'api_key':key})
        with self.state.db:
            self.state.db.execute('INSERT INTO provider_jobs VALUES (?,?,?,?,?)', (jid, provider, operation, 'queued', time.time()))
        self.bridge.send('Connection check queued. I’ll report the result here. This check does not generate content.')

    def set_endpoint(self, provider, url):
        if provider != 'qwen':
            raise ValueError('Only Qwen needs regional endpoint configuration.')
        url = api.endpoint(provider, url)
        if self.state.db.execute("SELECT 1 FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id WHERE t.backend=? AND j.status IN ('queued','running','waiting')", (provider,)).fetchone() or self.state.db.execute("SELECT 1 FROM provider_jobs WHERE provider=? AND status IN ('queued','running')", (provider,)).fetchone():
            raise ValueError('Wait for Qwen tasks and connection checks to finish before changing its endpoint.')
        config = stored(provider)
        config['base_url'] = url
        config.pop('catalog', None)
        credentials.save(gemini.DATA / 'qwen.json', config)
        self.bridge.send('Qwen endpoint saved. Open /providers → Qwen to connect or refresh the model list.')

    def act(self, action, update_id):
        from task_relay import backends
        op, provider = action['op'], action.get('provider')
        tid = action.get('tid')
        if op in ('browser_home','browser_connect','browser_status','browser_cancel'):
            from . import browser_setup
            if op in ('browser_connect','browser_cancel'):
                browser_setup.command(self.state,op.removeprefix('browser_'),'telegram-button:'+str(update_id))
            self.show(browser_setup.status(self.state),[
                ('Open Perplexity sign-in',{'op':'browser_connect'}),
                ('Check sign-in status',{'op':'browser_status'}),
                ('Cancel sign-in',{'op':'browser_cancel'})])
        elif op == 'home':
            self.home()
        elif op == 'provider':
            self.provider(provider)
        elif op == 'connect_info':
            name = REGISTRY[provider]['name']
            url = api.SPECS[provider]['keys'] if provider in api.SPECS else 'https://aistudio.google.com/apikey'
            self.show(f'Connect {name}\nGet an API key from {url}.\n\nTelegram bot chats are not end-to-end encrypted. If you enter a key here, Telegram receives that message. The bot requests deletion after receipt and stores it privately on your Mac; deletion cannot guarantee removal from Telegram backups. The key is never sent to a task or model prompt.\n\nContinue only if this method suits you.',
                      [('Enter key in this chat', {'op': 'key_prompt', 'provider': provider}), ('Back', {'op': 'provider', 'provider': provider})])
        elif op == 'key_prompt':
            if provider not in ('gemini', *api.SPECS):
                raise ValueError('This provider does not support API-key setup here yet.')
            sid = secrets.token_hex(16)
            with self.state.db:
                self.state.db.execute("UPDATE provider_key_sessions SET status='cancelled' WHERE status='waiting'")
                self.state.db.execute('INSERT INTO provider_key_sessions VALUES (?,?,NULL,?,?)', (sid, provider, 'waiting', time.time()+300))
            result = self.bridge.telegram.call('sendMessage', chat_id=self.state.get('chat_id'),
                text=f'Send your {REGISTRY[provider]["name"]} API key as your next text message. I will use it only for connection setup and request deletion of the message. Expires in 5 minutes. /cancelsetup cancels.',
                reply_markup={'force_reply': True, 'input_field_placeholder': REGISTRY[provider]['name'] + ' API key'})
            with self.state.db:
                self.state.db.execute('UPDATE provider_key_sessions SET prompt_id=? WHERE id=?', (result['message_id'], sid))
        elif op in ('refresh', 'enable'):
            if op == 'enable' and provider == 'claude':
                config = stored(provider)
                if config.get('auth') != 'account':
                    raise ValueError('A saved Claude account connection is required.')
                config['enabled'] = True
                credentials.save(gemini.DATA / 'claude.json', config)
                self.provider(provider)
            else:
                self.queue(provider, op)
        elif op == 'caps':
            self.caps(provider, tid)
        elif op == 'models':
            self.models(provider, action['cap'], tid, action.get('page', 0))
        elif op == 'endpoints':
            self.show('Choose the region where your Qwen API key was created. For a workspace endpoint, send /endpoint qwen followed by the full HTTPS base URL from Model Studio.',
                      [(name, {'op': 'setendpoint', 'provider': 'qwen', 'url': url}) for name, url in api.QWEN_ENDPOINTS.items()])
        elif op == 'setendpoint':
            self.set_endpoint(provider, action['url'])
        elif op == 'setmodel':
            cap, model = action['cap'], (api.model_name(action['model']) if provider in api.SPECS else gemini.model_name(action['model']))
            if tid:
                info = backends.task(self.state, tid)
                row = self.state.db.execute('SELECT status FROM watched WHERE id=?', (tid,)).fetchone()
                if not info or info['backend'] != provider or not row or row[0] != 'idle':
                    raise ValueError('This task is busy or no longer available. Reopen /models after it is idle.')
                with self.state.db:
                    if provider == 'gemini':
                        self.state.db.execute('INSERT OR REPLACE INTO gemini_models VALUES (?,?,?)', (tid, cap, model))
                    if cap == 'text':
                        self.state.db.execute('UPDATE backend_tasks SET model=? WHERE id=?', (model, tid))
            else:
                if self.state.db.execute("SELECT 1 FROM provider_jobs WHERE provider=? AND status IN ('queued','running')", (provider,)).fetchone():
                    raise ValueError('Finish provider setup before changing defaults.')
                config = stored(provider)
                if not config:
                    raise ValueError('Connect this provider first.')
                if provider == 'gemini':
                    config.setdefault('models', {})[cap] = model
                else:
                    config['model'] = model
                credentials.save(gemini.DATA / (provider + '.json'), config)
            self.bridge.send(f'{provider.capitalize()} {cap} model set to {model}.', tid)
        elif op == 'new':
            folder = gemini.WORKSPACES
            folder.mkdir(parents=True,exist_ok=True)
            new_id, title, _ = backends.create_task(self.state, f'{provider} {shlex.quote(str(folder))} {REGISTRY[provider]["name"]} task', update_id)
            note = (f' Read-only file tools can inspect {folder}. Requested file contents are sent to this provider. '
                    f'For another folder, use /new {provider} "/absolute/project/path" Title.') if provider in ('gemini', *api.SPECS) else ''
            self.bridge.send(f'Created {title}. Send your first instruction. /models chooses this task’s model.{note}', new_id)
        elif op == 'disable_confirm':
            self.show(f'Disable {provider.capitalize()}? This blocks new runs and keeps your saved credentials and tasks. Reconnect to enable it again.',
                      [('Disable', {'op': 'disable', 'provider': provider}), ('Keep connected', {'op': 'provider', 'provider': provider})])
        elif op == 'disable':
            if self.state.db.execute("SELECT 1 FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id WHERE t.backend=? AND j.status IN ('queued','running','waiting')", (provider,)).fetchone() or self.state.db.execute("SELECT 1 FROM provider_jobs WHERE provider=? AND status IN ('queued','running')", (provider,)).fetchone():
                raise ValueError('Finish active tasks or setup before disabling this provider.')
            config = stored(provider)
            config['enabled'] = False
            credentials.save(gemini.DATA / (provider + '.json'), config)
            self.provider(provider)

    def credential_message(self, update):
        # Called only after the bridge has authenticated the paired private user.
        message = update['message']
        text = message.get('text', '').strip()
        reply = message.get('reply_to_message', {}).get('message_id')
        session = self.state.db.execute('SELECT * FROM provider_key_sessions WHERE prompt_id=? ORDER BY expires_at DESC LIMIT 1', (reply,)).fetchone() if reply is not None else None
        if session is None:
            session = self.state.db.execute("SELECT * FROM provider_key_sessions WHERE status='waiting' ORDER BY expires_at DESC LIMIT 1").fetchone()
        if text == '/cancelsetup':
            with self.state.db:
                self.state.db.execute("UPDATE provider_key_sessions SET status='cancelled' WHERE status='waiting'")
            self.bridge.send('Provider connection entry cancelled.')
            return True
        looks_like_key = bool(re.fullmatch(r'(?:AIza|sk-)[A-Za-z0-9_-]{20,}', text))
        if not session and not looks_like_key:
            return False
        if text.startswith('/'):
            return False
        if not text:
            if session and session['status'] == 'waiting' and session['expires_at'] > time.time():
                self.bridge.send('Provider setup is waiting for a text API key. /cancelsetup returns to tasks. Files are not accepted as credentials.')
                return True
            return False
        with self.state.db:
            self.state.db.execute('INSERT OR IGNORE INTO incoming VALUES (?,?,?)', (update['update_id'], 'credential', ''))
            if message.get('message_id') is not None:
                self.state.db.execute('INSERT OR IGNORE INTO provider_deletions(chat_id,message_id) VALUES (?,?)', (self.state.get('chat_id'), message['message_id']))
            if session:
                self.state.db.execute("UPDATE provider_key_sessions SET status='consumed' WHERE id=?", (session['id'],))
        valid_session = session and session['status'] == 'waiting' and session['expires_at'] > time.time()
        try:
            if not valid_session:
                self.bridge.send('This key was not used or sent to a task. Open /providers and start a new connection step.')
            elif not re.fullmatch(r'[A-Za-z0-9_-]{20,512}', text):
                self.bridge.send('That entry was not a valid API-key format. It was not sent to a task. Open /providers to try again.')
            else:
                self.queue(session['provider'], 'connect', key=text)
        except ValueError as exc:
            self.bridge.send(str(exc))
        finally:
            try:
                delete_pending(self.state, self.bridge.telegram)
            except Exception:
                self.bridge.send('Telegram did not confirm deletion of your key message. Please delete that message yourself. It was not sent to a model prompt.')
        return True

    def callback(self, update):
        q = update['callback_query']
        user, chat = q.get('from', {}), q.get('message', {}).get('chat', {})
        if user.get('is_bot') or user.get('id') != self.state.get('user_id') or chat.get('type') != 'private' or chat.get('id') != self.state.get('chat_id'):
            return
        data = q.get('data', '')
        row = self.state.db.execute('SELECT * FROM provider_actions WHERE id=? AND expires_at>?', (data[2:] if data.startswith('p:') else '', time.time())).fetchone()
        self.bridge.telegram.call('answerCallbackQuery', callback_query_id=q['id'])
        if not row or row['used']:
            self.bridge.send('This button expired or was already used. Open /providers or /models again.')
            return
        action = json.loads(row['payload'])
        if action['op'] in ('browser_connect','browser_cancel'):
            from . import browser_setup
            from orchestrator.storage import transaction
            with transaction(self.state.db):
                if not self.state.db.execute('UPDATE provider_actions SET used=1 WHERE id=? AND used=0',(row['id'],)).rowcount:return
                browser_setup.command(self.state,action['op'].removeprefix('browser_'),'telegram-button:'+row['id'])
            self.act({'op':'browser_home'},update['update_id'])
            return
        mutation = action['op'] in ('key_prompt', 'refresh', 'enable', 'new', 'setmodel', 'setendpoint', 'disable','browser_connect','browser_cancel')
        if mutation:
            with self.state.db:
                if not self.state.db.execute('UPDATE provider_actions SET used=1 WHERE id=? AND used=0', (row['id'],)).rowcount:
                    return
        try:
            self.act(action, update['update_id'])
        except ValueError as exc:
            self.bridge.send(str(exc))


def delete_pending(state, telegram):
    row = state.db.execute("SELECT * FROM provider_deletions WHERE status='pending' AND next_attempt<=? ORDER BY message_id LIMIT 1", (time.time(),)).fetchone()
    if not row:
        return
    with state.db:
        claimed = state.db.execute("UPDATE provider_deletions SET status='deleting' WHERE chat_id=? AND message_id=? AND status='pending'", (row['chat_id'], row['message_id'])).rowcount
    if not claimed:
        return
    try:
        telegram.call('deleteMessage', chat_id=row['chat_id'], message_id=row['message_id'])
    except Exception as exc:
        attempts = row['attempts'] + 1
        failed = attempts >= 3 or getattr(exc, 'status', 0) in (400, 403)
        with state.db:
            state.db.execute('UPDATE provider_deletions SET status=?,attempts=?,next_attempt=? WHERE chat_id=? AND message_id=?',
                              ('failed' if failed else 'pending', attempts, time.time()+15*attempts, row['chat_id'], row['message_id']))
            if failed:
                state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                  ('key-delete:'+str(row['message_id']), '', 'Telegram did not confirm deletion of your key message. Please delete it yourself. It was not sent to a model prompt.'))
    else:
        with state.db:
            state.db.execute("UPDATE provider_deletions SET status='deleted' WHERE chat_id=? AND message_id=?", (row['chat_id'], row['message_id']))


def finish_setup(state, jid, ok, text):
    row=state.db.execute('SELECT provider FROM provider_jobs WHERE id=?',(jid,)).fetchone()
    if row and row['provider']=='perplexity':
        from .browser_setup import finish
        finish(state,jid,ok,text.replace('Check Providers and reconnect if needed.','Use /browser connect to try again.'))
        return
    (gemini.DATA / 'setup-input' / (jid + '.json')).unlink(missing_ok=True)
    with state.db:
        state.db.execute('UPDATE provider_jobs SET status=? WHERE id=?', ('completed' if ok else 'failed', jid))
        state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)', ('provider:' + jid, '', text + '\nOpen /providers for connection settings.'))


class Worker:
    def __init__(self, state, popen=subprocess.Popen, telegram=None):
        self.state, self.popen, self.active, self.telegram = state, popen, None, telegram
        with state.db:
            state.db.execute("UPDATE provider_deletions SET status='pending' WHERE status='deleting'")
        for row in state.db.execute("SELECT id FROM provider_jobs WHERE status='running'").fetchall():
            finish_setup(state, row['id'], False, 'Provider setup was interrupted. Check Providers and reconnect if needed.')

    def tick(self):
        if self.telegram:
            delete_pending(self.state, self.telegram)
        if self.active:
            jid, process, started = self.active
            if process.poll() is not None:
                if self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?', (jid,)).fetchone()[0] == 'running':
                    finish_setup(self.state, jid, False, 'Provider setup ended without a confirmed result.')
                self.active = None
            elif self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?',(jid,)).fetchone()[0]=='cancelled' or time.monotonic()-started > 660:
                self.close()
            return
        row = self.state.db.execute("SELECT * FROM provider_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return
        with self.state.db:
            if not self.state.db.execute("UPDATE provider_jobs SET status='running' WHERE id=? AND status='queued'", (row['id'],)).rowcount:return
        try:
            dbpath = self.state.db.execute('PRAGMA database_list').fetchone()[2]
            command=([HOST.browser_python(gemini.ROOT,Path(dbpath).parent),'-m','task_relay.browser_setup',dbpath,row['id']]
                     if row['provider']=='perplexity' else [sys.executable,str(gemini.ROOT/'provider_runner.py'),dbpath,row['id']])
            process = HOST.spawn(command,
                                 popen=self.popen, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, UnsupportedHost):
            finish_setup(self.state, row['id'], False, 'Provider setup could not start on this host.')
            return
        self.active = (row['id'], process, time.monotonic())

    def close(self):
        if not self.active:
            return
        jid, process, _ = self.active
        if process.poll() is None:
            import signal
            try:
                HOST.signal_tree(process)
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                HOST.signal_tree(process, force=True)
                process.wait(timeout=2)
            except ProcessLookupError:
                pass
        if self.state.db.execute('SELECT status FROM provider_jobs WHERE id=?', (jid,)).fetchone()[0] == 'running':
            finish_setup(self.state, jid, False, 'Provider setup was interrupted. Reconnect when ready.')
        self.active = None
