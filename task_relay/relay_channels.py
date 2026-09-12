"""Delivery ownership for the shared orchestrator's Telegram and Messages fronts."""


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS relay_request_channels (
        request_id INTEGER PRIMARY KEY, channel TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS relay_event_channels (
        event_id TEXT PRIMARY KEY, channel TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS relay_channel_bindings (
        kind TEXT NOT NULL, entity TEXT NOT NULL, after_row INTEGER NOT NULL,
        channel TEXT NOT NULL, PRIMARY KEY(kind,entity,after_row));
    ''')


def request_channel(state, request_id):
    row = state.db.execute('SELECT channel FROM relay_request_channels WHERE request_id=?', (request_id,)).fetchone()
    return row[0] if row else 'telegram'


def bind(state, kind, entity, channel):
    if not entity:
        return
    after = state.db.execute('SELECT COALESCE(max(rowid),0) FROM outbox').fetchone()[0]
    state.db.execute('INSERT OR REPLACE INTO relay_channel_bindings VALUES (?,?,?,?)',
                     (kind, entity, after, channel))


def binding(state, kind, entity, rowid):
    row = state.db.execute('SELECT channel FROM relay_channel_bindings WHERE kind=? AND entity=? '
                           'AND after_row<? ORDER BY after_row DESC LIMIT 1', (kind, entity, rowid)).fetchone()
    return row[0] if row else None


def event_channel(state, event_id, thread_id=None, rowid=None):
    explicit = state.db.execute('SELECT channel FROM relay_event_channels WHERE event_id=?', (event_id,)).fetchone()
    if explicit:
        return explicit[0]
    if rowid is None:
        row = state.db.execute('SELECT rowid,thread_id FROM outbox WHERE id=?', (event_id,)).fetchone()
        if not row:
            return 'telegram'
        rowid, thread_id = row['rowid'], row['thread_id']
    parts = event_id.split(':')
    if len(parts) > 1 and parts[0] in ('orchestrator', 'image-request', 'capability-request', 'routed', 'uncertain'):
        # Mode/status notices have nonnumeric keys and retain their default route.
        if parts[1].isdigit():
            return request_channel(state, int(parts[1]))
    if len(parts) > 1 and parts[0] == 'references':
        row = state.db.execute('SELECT job_id FROM reference_packs WHERE id=?', (parts[1],)).fetchone()
        if row:
            return request_channel(state, row[0])
    if len(parts) > 1 and parts[0] in ('workflow', 'production'):
        return binding(state, parts[0], parts[1], rowid) or 'telegram'
    if thread_id:
        return binding(state, 'task', thread_id, rowid) or 'telegram'
    return 'telegram'


def pending(state, channel, limit=20):
    result = []
    for row in state.db.execute('SELECT rowid,* FROM outbox WHERE sent=0 ORDER BY rowid'):
        if event_channel(state, row['id'], row['thread_id'], row['rowid']) == channel:
            result.append(row)
            if len(result) >= limit:
                break
    return result


class ScopedState:
    """Conversation preferences are separate; projects, jobs and workers are shared."""
    def __init__(self, state, channel):
        self.base, self.channel, self.db = state, channel, state.db

    def __getattr__(self, name):
        return getattr(self.base, name)

    def get(self, key, default=None):
        if self.channel == 'messages' and key in ('orchestrator_mode', 'orchestrator_production_focus', 'selected'):
            return self.base.get('messages:' + key, default)
        if self.channel == 'messages' and key in ('user_id', 'chat_id'):
            return -1  # Internal callback adapter; the Messages pilot authenticates the real sender.
        return self.base.get(key, default)

    def put(self, key, value):
        if self.channel == 'messages' and key in ('orchestrator_mode', 'orchestrator_production_focus', 'selected'):
            key = 'messages:' + key
        self.base.put(key, value)
