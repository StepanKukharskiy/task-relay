"""Gemini configuration, bounded REST transport, and reference-file intake."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from task_relay.relay_paths import PATHS
ROOT = PATHS.install
DATA = PATHS.data
WORKSPACES = PATHS.workspaces
GENERATED = PATHS.generated
BASE = 'https://generativelanguage.googleapis.com/v1beta/'
DEFAULT_MODELS = {'text': 'gemini-3.7-flash', 'speech': 'gemini-3.1-flash-tts-preview',
                  'image': 'gemini-3.1-flash-image', 'video': 'veo-3.1-fast-generate-preview'}
MAX_INPUT = 10_000_000
MAX_CONTEXT = 16_000_000
INPUT_MIMES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
               '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.txt': 'text/plain',
               '.md': 'text/plain', '.csv': 'text/plain'}


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS gemini_runs (
        job_id TEXT PRIMARY KEY, capability TEXT NOT NULL, model TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'prepared', operation_name TEXT,
        response_path TEXT NOT NULL, options_json TEXT NOT NULL,
        usage_json TEXT, attempts INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS gemini_models (
        thread_id TEXT, capability TEXT, model TEXT, PRIMARY KEY(thread_id,capability));
      CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, job_id TEXT,
        role TEXT NOT NULL, path TEXT NOT NULL, filename TEXT NOT NULL,
        mime TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
        created_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS gemini_history (
        job_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, capability TEXT NOT NULL,
        input_path TEXT NOT NULL, response_path TEXT NOT NULL, created_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS incoming_files (
        update_id INTEGER PRIMARY KEY, thread_id TEXT NOT NULL, file_id TEXT NOT NULL,
        filename TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER DEFAULT 0,
        next_attempt REAL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS gemini_tool_runs (
        job_id TEXT PRIMARY KEY,step INTEGER NOT NULL DEFAULT 0,
        stage TEXT NOT NULL DEFAULT 'prepared',request_json TEXT NOT NULL,response_path TEXT NOT NULL);
    ''')


def read_config():
    from .credentials import configuration, CredentialError
    from .capability_defaults import overlay
    try:return overlay('gemini', configuration(DATA/'gemini.json'), DATA/'state.sqlite')
    except CredentialError:return None


def status():
    return 'configured (access checked when used)' if read_config() else 'setup required; open Setup Gemini.command'


def model_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', value):
        raise ValueError('Use an exact model ID without spaces or a URL.')
    return value


def speech_text(value):
    """Remove common copied Markdown formatting without fetching linked content."""
    value = html.unescape(value)
    value = re.sub(r'\\([\\`*_{}\[\]()#+.!>|-])', r'\1', value)
    value = re.sub(r'!?\[([^\]\n]*)\]\(\s*(?:<[^>\n]+>|(?:[^()\n]|\([^()\n]*\))+)\s*\)', r'\1', value)
    value = re.sub(r'(?m)^\s*```[^\n]*$', '', value)
    value = re.sub(r'(?m)^\s*(?:>\s*)+', '', value)
    value = re.sub(r'(?m)^\s*#{1,6}\s+', '', value)
    value = re.sub(r'(\*\*|__)(.+?)\1', r'\2', value, flags=re.S)
    value = re.sub(r'`([^`\n]+)`', r'\1', value)
    value = re.sub(r'(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$', '', value)
    return value.strip()


def operation_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:models/[A-Za-z0-9._-]+/)?operations/[A-Za-z0-9._-]+', value):
        raise ValueError('Unexpected provider operation identifier')
    return value


class ProviderError(Exception):
    def __init__(self, status, uncertain=False, detail=None):
        self.status, self.uncertain = status, uncertain
        self.detail = detail or {}
        suffix = ': '+self.detail['message'] if self.detail.get('message') else ''
        super().__init__(f'Gemini request failed ({status})'+suffix)


def error_detail(response, key):
    """Retain a bounded structured diagnostic, never HTTP headers or raw bodies."""
    try:
        raw=response.read(8193)
        if len(raw)>8192:return {}
        value=json.loads(raw)
        error=value.get('error') if isinstance(value,dict) else None
        if not isinstance(error,dict) or not isinstance(error.get('message'),str):return {}
        message=error['message']
        # Redact before truncating, including the URL-encoded configured key.
        for secret in sorted({key,urllib.parse.quote(key,safe=''),urllib.parse.quote_plus(key)},key=len,reverse=True):
            if secret:message=message.replace(secret,'[redacted]')
        message=re.sub(r'https?://[^\s<>"\']+','[redacted URL]',message,flags=re.I)
        message=re.sub(r'(?i)(?:authorization\s*:\s*bearer|bearer|x-goog-api-key|api[_-]?key|access[_-]?token)\s*[:=]?\s*[^\s,;]+','[redacted credential]',message)
        message=' '.join(message.split())[:1500]
        result={'message':message}
        status=error.get('status')
        if isinstance(status,str) and re.fullmatch(r'[A-Z_]{1,64}',status):result['status']=status
        return result
    except (OSError,ValueError,TypeError):return {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, key):
        self.key = key
        context = ssl.create_default_context()
        if Path('/etc/ssl/cert.pem').is_file():
            context.load_verify_locations('/etc/ssl/cert.pem')
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())

    def request(self, path, payload=None, *, timeout=None, max_response_bytes=72000000):
        if timeout is None:timeout=120 if payload is not None else 30
        if type(timeout) is not int or not 1<=timeout<=120 or type(max_response_bytes) is not int or not 1<=max_response_bytes<=72000000:
            raise ValueError('Invalid bounded Gemini transport limits')
        if not re.fullmatch(r'[A-Za-z0-9/_.:?=&%-]+', path) or '..' in path or path.startswith('/'):
            raise ValueError('Invalid Gemini API path')
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(BASE + path, data=data,
                                      headers={'x-goog-api-key': self.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=timeout) as res:
                raw = res.read(max_response_bytes+1)
                if len(raw) > max_response_bytes:
                    raise ProviderError('response-too-large', uncertain=data is not None)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:detail=error_detail(exc,self.key)
            finally:exc.close()
            raise ProviderError(code, uncertain=data is not None and code >= 500,detail=detail) from None
        except (OSError, ValueError):
            raise ProviderError('connection-or-response', uncertain=data is not None) from None

    def download(self, url, destination):
        # Keep the API key on Google's API origin, never on redirected media URLs.
        for _ in range(5):
            parsed = urllib.parse.urlsplit(url)
            host = parsed.hostname or ''
            allowed = host in ('generativelanguage.googleapis.com', 'storage.googleapis.com') or host.endswith('.googleusercontent.com')
            if parsed.scheme != 'https' or not allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
                raise ProviderError('untrusted-media-url')
            headers = {'x-goog-api-key': self.key} if host == 'generativelanguage.googleapis.com' else {}
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=60) as res:
                    data = res.read(50_000_001)
                if not data or len(data) > 50_000_000:
                    raise ProviderError('media-too-large-or-empty')
                atomic_bytes(destination, data)
                return
            except urllib.error.HTTPError as exc:
                code, location = exc.code, exc.headers.get('Location')
                exc.close()
                if code in (301, 302, 303, 307, 308) and location:
                    url = urllib.parse.urljoin(url, location)
                    continue
                raise ProviderError(code) from None
            except OSError:
                raise ProviderError('download-connection') from None
        raise ProviderError('too-many-redirects')


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def artifact(state, tid, jid, role, path, filename, mime):
    path = Path(path)
    data = path.read_bytes()
    aid = hashlib.sha256((str(tid) + ':' + str(jid) + ':' + str(path)).encode()).hexdigest()[:20]
    state.db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,1)',
                     (aid, tid, jid, role, str(path), filename, mime, hashlib.sha256(data).hexdigest(), len(data), time.time()))
    return aid


def validate_input(path, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in INPUT_MIMES:
        raise ValueError('Supported references: PDF, PNG, JPG, WEBP, TXT, MD, CSV.')
    data = Path(path).read_bytes()
    if not data or len(data) > MAX_INPUT:
        raise ValueError('Reference files must be nonempty and at most 10 MB.')
    if suffix == '.pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('The file is not a valid PDF.')
    if suffix in ('.png', '.jpg', '.jpeg', '.webp'):
        from task_relay.media import valid_image
        if not valid_image(data, suffix):
            raise ValueError('The image content does not match its file type.')
    if INPUT_MIMES[suffix] == 'text/plain':
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError('Text references must use UTF-8 encoding.') from None
    return INPUT_MIMES[suffix]


def receive_file(state, message, tid, update_id):
    entry = message.get('document') or (message.get('photo') or [None])[-1]
    if not entry:
        return False
    count = state.db.execute("SELECT count(*) FROM artifacts WHERE thread_id=? AND role='input' AND active=1", (tid,)).fetchone()[0]
    pending = state.db.execute("SELECT count(*) FROM incoming_files WHERE thread_id=? AND status='pending'", (tid,)).fetchone()[0]
    if count + pending >= 6:
        raise ValueError('This task already has six references. Use /references and /forget ID before adding more.')
    filename = Path(entry.get('file_name') or 'telegram-photo.jpg').name.replace('\n', '_').replace('\r', '_')[:180]
    if Path(filename).suffix.lower() not in INPUT_MIMES or entry.get('file_size', 0) > MAX_INPUT:
        raise ValueError('Send PDF, PNG, JPG, WEBP, TXT, MD, or CSV references up to 10 MB.')
    with state.db:
        state.db.execute('INSERT INTO incoming VALUES (?,?,?)', (update_id, 'reference', tid))
        state.db.execute('INSERT INTO incoming_files(update_id,thread_id,file_id,filename,status) VALUES (?,?,?,?,?)',
                         (update_id, tid, entry['file_id'], filename, 'pending'))
    return True


class InputWorker:
    def __init__(self, state, telegram):
        self.state, self.telegram = state, telegram

    def tick(self):
        row = self.state.db.execute("SELECT * FROM incoming_files WHERE status='pending' AND next_attempt<=? ORDER BY update_id LIMIT 1", (time.time(),)).fetchone()
        if not row:
            return
        path = self.state.media_dir.parent / 'references' / (str(row['update_id']) + Path(row['filename']).suffix.lower())
        try:
            self.telegram.download_file(row['file_id'], path, MAX_INPUT)
            mime = validate_input(path, row['filename'])
        except Exception as exc:
            permanent = isinstance(exc, ValueError) or getattr(exc, 'status', 0) in (400, 403, 404)
            attempts = row['attempts'] + 1
            with self.state.db:
                self.state.db.execute('UPDATE incoming_files SET status=?,attempts=?,next_attempt=? WHERE update_id=?',
                                      ('failed' if permanent or attempts >= 3 else 'pending', attempts, time.time() + 15 * attempts, row['update_id']))
                if permanent or attempts >= 3:
                    path.unlink(missing_ok=True)
                    self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                          ('input:' + str(row['update_id']), row['thread_id'], 'The reference could not be downloaded or validated. Send it again as PDF, PNG, JPG, WEBP, or UTF-8 text, up to 10 MB.'))
            return
        with self.state.db:
            aid = artifact(self.state, row['thread_id'], None, 'input', path, row['filename'], mime)
            self.state.db.execute("UPDATE incoming_files SET status='attached' WHERE update_id=?", (row['update_id'],))
            self.state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                                  ('input:' + str(row['update_id']), row['thread_id'],
                                   f"Reference attached: {row['filename']}\nID: {aid}\nSend your instruction now. Caption text does not start generation.\n/references lists references; /forget {aid} removes it from future prompts."))


def prepare_run(state, jid, tid, capability):
    config = read_config()
    if not config:
        raise ValueError('Connect Gemini first: open Setup Gemini.command on your Mac.')
    if capability not in DEFAULT_MODELS:
        raise ValueError('Unknown Gemini capability')
    if state.db.execute("SELECT 1 FROM incoming_files WHERE thread_id=? AND status='pending'", (tid,)).fetchone():
        raise ValueError('A reference is still downloading. Wait for “Reference attached” before sending the instruction.')
    refs = state.db.execute("SELECT * FROM artifacts WHERE thread_id=? AND role='input' AND active=1 ORDER BY created_at", (tid,)).fetchall()
    if sum(r['size'] for r in refs) > 11_000_000:
        raise ValueError('Combined references exceed 11 MB. Remove some with /forget ID.')
    configured = state.db.execute('SELECT model FROM gemini_models WHERE thread_id=? AND capability=?', (tid, capability)).fetchone()
    if capability == 'text':
        model = state.db.execute('SELECT model FROM backend_tasks WHERE id=?', (tid,)).fetchone()[0]
    else:
        model = configured[0] if configured else config.get('models', {}).get(capability, DEFAULT_MODELS[capability])
    options = {'references': [dict(r) for r in refs] if capability in ('text', 'image') else [],
               'voice': config.get('voice', 'Kore'), 'max_output_tokens': config.get('max_output_tokens', 4096),
               'aspect_ratio': config.get('aspect_ratio', '16:9'), 'duration_seconds': config.get('duration_seconds', 4)}
    if capability == 'text':
        options['workspace'] = state.db.execute('SELECT cwd FROM backend_tasks WHERE id=?', (tid,)).fetchone()[0]
    response = state.media_dir.parent / 'gemini-runs' / (jid + '.json')
    return (jid, capability, model_name(model), str(response), json.dumps(options))


def resume_job(state, jid, manual=False):
    row = state.db.execute('SELECT r.*,j.status,j.cancel,j.thread_id FROM gemini_runs r JOIN backend_jobs j ON j.id=r.job_id WHERE job_id=?', (jid,)).fetchone()
    if not row or (row['status'] not in ('running', 'waiting') and not (manual and row['status'] in ('uncertain', 'stopped'))):
        return False
    if row['cancel'] and not manual:
        return False
    safe = (not manual and row['stage'] == 'prepared') or row['operation_name'] or Path(row['response_path']).is_file()
    tool_run = state.db.execute('SELECT * FROM gemini_tool_runs WHERE job_id=?', (jid,)).fetchone()
    if tool_run:
        safe = ((tool_run['stage'] == 'prepared' and row['stage'] == 'prepared') or Path(tool_run['response_path']).is_file()
                or Path(row['response_path']).is_file())
    if not safe:
        return False
    with state.db:
        state.db.execute("UPDATE backend_jobs SET status='queued',cancel=0,finished_at=NULL WHERE id=?", (jid,))
        state.db.execute("UPDATE watched SET status='queued' WHERE id=?", (row['thread_id'],))
        if manual:
            state.db.execute('DELETE FROM outbox WHERE id=?', ('backend:' + jid + ':result',))
    return True
