"""Public release metadata and durable, at-most-once Telegram notices."""
import json
from pathlib import Path
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.request

from . import credentials
from .relay_paths import PATHS

VERSION = '0.12.1'
PROTOCOL = 2
REPOSITORY = 'StepanKukharskiy/task-relay'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases/'
WEB = 'https://github.com/' + REPOSITORY + '/releases/'
INTERVAL = 86400


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('A stable version such as 0.12.0 is required.')
    return tuple(map(int, value.split('.')))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Unexpected release metadata redirect.')


def https_opener(redirects):
    context = ssl.create_default_context()
    bundle = Path('/etc/ssl/cert.pem')
    if bundle.is_file():
        context.load_verify_locations(bundle)
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), redirects())


def fetch(selected=None):
    if selected is not None:
        version(selected)
    req = urllib.request.Request(API + ('tags/v' + selected if selected else 'latest'), headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'Task-Relay-release-check',
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with https_opener(NoRedirect).open(req, timeout=15) as res:
            raw = res.read(1_000_001)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise ValueError('GitHub release check is unavailable; retry later.') from None
    if len(raw) > 1_000_000:
        raise ValueError('Release metadata exceeds its limit.')
    data = json.loads(raw)
    tag = data.get('tag_name', '')
    number = tag.removeprefix('v')
    version(number)
    if tag != 'v' + number or data.get('draft') or data.get('prerelease') or (selected and number != selected):
        raise ValueError('Release is not the requested stable version.')
    filename = f'task_relay-{number}-py3-none-any.whl'
    assets = [a for a in data.get('assets', []) if a.get('name') == filename and a.get('state') == 'uploaded']
    if len(assets) != 1:
        raise ValueError('Release has no unique installable wheel.')
    asset = assets[0]
    url = WEB + f'download/{tag}/{filename}'
    digest = asset.get('digest', '')
    if asset.get('browser_download_url') != url or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Release wheel URL or SHA-256 digest is missing or invalid.')
    if type(asset.get('size')) is not int or not 0 < asset['size'] <= 100_000_000:
        raise ValueError('Release wheel exceeds its size limit.')
    return dict(version=number, url=WEB + 'tag/' + tag, wheel_url=url,
                filename=filename, sha256=digest[7:], size=asset['size'])


class Store:
    def __init__(self, data=PATHS.data):
        path = data / 'updates.sqlite'
        if not path.exists():
            # Atomic owner-only creation; SQLite then owns this regular file.
            data.mkdir(parents=True, exist_ok=True, mode=0o700)
            import os
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        from .filesystem import FILES, Grant
        with FILES.open(Grant(data, 'release state', frozenset({path.name})), path.name):
            pass
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute('CREATE TABLE IF NOT EXISTS cache(id INTEGER PRIMARY KEY CHECK(id=1),checked REAL NOT NULL,release TEXT,error TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS notices(version TEXT PRIMARY KEY,status TEXT NOT NULL,message_id INTEGER)')
        self.db.commit()

    def close(self):
        self.db.close()

    def check(self, force=False, fetcher=fetch, now=None):
        now = time.time() if now is None else now
        # Claim the daily attempt before network I/O; failures and crashes are throttled too.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT checked,release,error FROM cache WHERE id=1').fetchone()
            if not force and row and now - row[0] < INTERVAL:
                return json.loads(row[1]) if row[1] else None
            self.db.execute('INSERT OR REPLACE INTO cache VALUES (1,?,?,?)',
                            (now, row[1] if row else None, 'Check in progress or interrupted'))
        try:
            release = fetcher()
        except Exception:
            with self.db:
                self.db.execute("UPDATE cache SET error='Release check failed; cached information may be stale' WHERE id=1")
            return json.loads(row[1]) if row and row[1] else None
        with self.db:
            self.db.execute('UPDATE cache SET release=?,error=NULL WHERE id=1', (json.dumps(release) if release else None,))
        return release

    def notify(self, release, telegram, chat_id, current=VERSION):
        if not release or version(release['version']) <= version(current) or chat_id is None:
            return
        with self.db:
            claimed = self.db.execute("INSERT OR IGNORE INTO notices VALUES (?,'submitting',NULL)", (release['version'],)).rowcount
        if not claimed:
            return
        text = (f"Task Relay {release['version']} is available.\nRelease notes: {release['url']}\n"
                f"On your host: task-relay update apply --version {release['version']}\n"
                "Disable notices: task-relay update notifications off")
        try:
            result = telegram.call('sendMessage', chat_id=chat_id, text=text,
                                   link_preview_options={'is_disabled': True})
        except Exception as exc:
            from .channel_policy import ChannelPaused
            with self.db:
                if isinstance(exc, ChannelPaused):
                    self.db.execute("DELETE FROM notices WHERE version=? AND status='submitting'", (release['version'],))
                else:
                    self.db.execute("UPDATE notices SET status='uncertain' WHERE version=?", (release['version'],))
            return  # Never replay a possibly delivered notice.
        with self.db:
            self.db.execute("UPDATE notices SET status='sent',message_id=? WHERE version=?", (result['message_id'], release['version']))


def preferences(data=PATHS.data):
    path = data / 'update-preferences.json'
    value = credentials.private_json(path) if path.exists() else {'notifications': True}
    if type(value.get('notifications')) is not bool:
        raise ValueError('Invalid update notification preference.')
    return value


def cached(data=PATHS.data):
    path = data / 'updates.sqlite'
    if not path.exists():
        return {'checked': None, 'release': None, 'error': None}
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        row = db.execute('SELECT checked,release,error FROM cache WHERE id=1').fetchone()
        return dict(checked=row[0], release=json.loads(row[1]) if row[1] else None, error=row[2]) if row else dict(checked=None, release=None, error=None)
    finally:
        db.close()


def tick(state, telegram):
    from .channel_policy import queue_proactive
    data = state.media_dir.parent.resolve()
    if not preferences(data)['notifications']:
        return
    store = Store(data)
    try:
        release = store.check(fetcher=fetch)
        if not release or version(release['version']) <= version(VERSION):
            return
        if store.db.execute('SELECT 1 FROM notices WHERE version=?', (release['version'],)).fetchone():
            return  # Preserve legacy sent, submitting and uncertain identities.
        text = (f"Task Relay {release['version']} is available.\nRelease notes: {release['url']}\n"
                f"On your host: task-relay update apply --version {release['version']}\n"
                "Manage proactive updates in Task Relay Channels.")
        if queue_proactive(state, 'proactive:release:' + release['version'], text):
            with store.db:
                store.db.execute("INSERT OR IGNORE INTO notices VALUES (?,'queued',NULL)", (release['version'],))
    finally:
        store.close()
