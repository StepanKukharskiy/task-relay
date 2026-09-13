"""Shared channel controls, checked at intake and transport boundaries.

Changing policy never moves a reply, cancels work, or replays an uncertain send.
An operation admitted before a change can finish; subsequent sends read it afresh.
"""
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

from .relay_paths import PATHS

CHANNELS = ('telegram', 'messages')
VERSION = 1


class ChannelPaused(ValueError):
    """Dispatch was refused before contacting the messenger."""


def database_path(db):
    return Path(db.execute('PRAGMA database_list').fetchone()[2])


def defaults():
    return {'version': VERSION, 'revision': 0, 'paused': False,
            'proactive': 'telegram', 'enabled': {c: True for c in CHANNELS},
            'accept_after': {c: 0 for c in CHANNELS}}


def read(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='relay_channel_settings'").fetchone():
        return defaults()
    row = db.execute('SELECT value FROM relay_channel_settings WHERE id=1').fetchone()
    if not row:
        raise ValueError('Channel settings are incomplete. Messaging is held until repaired.')
    value = json.loads(row[0])
    if (not isinstance(value, dict) or value.get('version') != VERSION or type(value.get('revision')) is not int or value['revision'] < 0 or
            type(value.get('paused')) is not bool or value.get('proactive') not in (*CHANNELS, 'none') or
            not isinstance(value.get('enabled'), dict) or not isinstance(value.get('accept_after'), dict) or
            set(value.get('enabled', {})) != set(CHANNELS) or
            any(type(value['enabled'][c]) is not bool for c in CHANNELS) or
            set(value.get('accept_after', {})) != set(CHANNELS) or
            any(type(value['accept_after'][c]) not in (int, float) or
                not math.isfinite(value['accept_after'][c]) for c in CHANNELS)):
        raise ValueError('Channel settings need repair. Messaging is held.')
    return value


def load(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        return read(db)


def outgoing(db, channel):
    value = read(db)
    return channel in CHANNELS and value['enabled'][channel] and not value['paused']


def require_outgoing(path, channel):
    value = load(path)
    if channel not in CHANNELS or not value['enabled'][channel] or value['paused']:
        raise ChannelPaused('Messaging is paused. No message was submitted.')


def accepting(db, channel, created=None):
    value = read(db)
    return (channel in CHANNELS and value['enabled'][channel] and not value['paused'] and
            (created is None or (type(created) in (int, float) and math.isfinite(created) and
                                 created >= value['accept_after'][channel])))


def update(value, paths=PATHS, clock=time.time):
    if not isinstance(value, dict) or set(value) - {'revision', 'channel', 'enabled', 'paused', 'proactive'}:
        raise ValueError('Choose an exact channel setting.')
    if type(value.get('revision')) is not int:
        raise ValueError('Refresh channel settings before changing them.')
    if not paths.state.is_file():
        raise ValueError('Complete Relay setup before changing channels.')
    with closing(sqlite3.connect(paths.state.as_uri() + '?mode=rw', uri=True, timeout=5)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            current = read(db)
            if value['revision'] != current['revision']:
                raise ValueError('Channel settings changed. Refresh before trying again.')
            if 'channel' in value or 'enabled' in value:
                channel = value.get('channel')
                if channel not in CHANNELS or type(value.get('enabled')) is not bool:
                    raise ValueError('This channel is unavailable.')
                if value['enabled'] and not current['enabled'][channel]:
                    current['accept_after'][channel] = clock()
                current['enabled'][channel] = value['enabled']
            if 'paused' in value:
                if type(value['paused']) is not bool:
                    raise ValueError('Choose pause or resume.')
                if current['paused'] and not value['paused']:
                    current['accept_after'] = {c: clock() for c in CHANNELS}
                current['paused'] = value['paused']
            if 'proactive' in value:
                if value['proactive'] not in (*CHANNELS, 'none'):
                    raise ValueError('Choose an available notification destination.')
                current['proactive'] = value['proactive']
            current['revision'] += 1
            db.execute('CREATE TABLE IF NOT EXISTS relay_channel_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS relay_channel_changes(revision INTEGER PRIMARY KEY,created REAL NOT NULL,value TEXT NOT NULL)')
            raw = json.dumps(current, sort_keys=True)
            db.execute('INSERT OR REPLACE INTO relay_channel_settings VALUES (1,?)', (raw,))
            db.execute('INSERT INTO relay_channel_changes VALUES (?,?,?)', (current['revision'], clock(), raw))
    return {'policy': current, 'message': 'Saved. Existing work continues; held replies keep their original destination.'}


def heartbeat(state, channel, role):
    with state.db:
        state.put('health:channel-policy:' + channel + ':' + role,
                  {'version': VERSION, 'updated': time.time(), 'revision': read(state.db)['revision']})


def queue_proactive(state, ident, text):
    destination = read(state.db)['proactive']
    if destination == 'none':
        return False
    # Stable identity and destination commit together. A later preference change
    # never moves an existing notification to a different account/channel.
    with state.db:
        state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,NULL,?)', (ident, text))
        state.db.execute('INSERT OR IGNORE INTO relay_event_channels VALUES (?,?)', (ident, destination))
    return True


def snapshot(paths=PATHS):
    if not paths.state.is_file():
        return {'policy': defaults(), 'available': False, 'runtime': {}}
    with closing(sqlite3.connect(paths.state.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        policy = read(db)
        runtime = {}
        has_kv = db.execute("SELECT 1 FROM sqlite_master WHERE name='kv'").fetchone()
        for channel in CHANNELS:
            roles = []
            for role in ('intake', 'delivery'):
                row = db.execute('SELECT value FROM kv WHERE key=?',
                    ('health:channel-policy:' + channel + ':' + role,)).fetchone() if has_kv else None
                try:
                    health = json.loads(row[0]) if row else {}
                    roles.append(health.get('version') == VERSION and
                        health.get('revision') == policy['revision'] and
                        0 <= time.time() - health.get('updated', 0) < 30)
                except (ValueError, TypeError):
                    roles.append(False)
            runtime[channel] = all(roles)
        return {'policy': policy, 'available': True, 'runtime': runtime}
