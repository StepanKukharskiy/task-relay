"""Silent, durable Gemini analysis jobs using the existing provider and usage adapter.

Internal jobs have UUIDs, no Telegram update/task/outbox rows, and no tools.
The local consumer explicitly drains its queue. An ambiguous submission is never
retried. A crash leaves a sending job inspectable as uncertain via recover().
"""
import json
import time
import uuid
from pathlib import Path
from task_relay import api_providers
from task_relay import gemini
from task_relay.gemini_runner import content


def initialize(db):
    api_providers.initialize(db)
    db.executescript('''
      CREATE TABLE IF NOT EXISTS internal_jobs (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, backend TEXT NOT NULL,
        model TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
        finished_at REAL, cancel INTEGER NOT NULL DEFAULT 0,
        request_json TEXT NOT NULL, response_json TEXT, answer TEXT,
        error TEXT, usage_json TEXT);
    ''')


def enqueue(db, owner, model, system, evidence, max_output_tokens=4096):
    model = gemini.model_name(model)
    if not 256 <= max_output_tokens <= 32768:
        raise ValueError('Output budget must be between 256 and 32768 tokens')
    payload = {'systemInstruction': {'parts': [{'text': system}]},
               'contents': [{'role': 'user', 'parts': [{'text': evidence}]}],
               'generationConfig': {'maxOutputTokens': max_output_tokens,
                                    'responseMimeType': 'application/json'}}
    encoded = api_providers.encode_request(payload)
    jid = 'internal:' + uuid.uuid4().hex
    with db:
        db.execute('INSERT INTO internal_jobs(id,owner_id,backend,model,status,created_at,request_json) '
                   'VALUES (?,?,?,?,?,?,?)', (jid, owner, 'gemini', model, 'queued', time.time(), encoded))
    return jid


def cancel(db, owner):
    with db:
        db.execute("UPDATE internal_jobs SET cancel=1 WHERE owner_id=? AND status IN ('queued','sending')", (owner,))
        db.execute("UPDATE analysis_runs SET status='incomplete' WHERE id=? AND status='running'", (owner,))


def recover(db, jid):
    # Explicit recovery only, never automatic replay of a billable request.
    with db:
        db.execute("UPDATE internal_jobs SET status='uncertain',error='Submission interrupted; not replayed' "
                   "WHERE id=? AND status='sending'", (jid,))


def run(db, jid, client=None):
    row = db.execute('SELECT * FROM internal_jobs WHERE id=?', (jid,)).fetchone()
    if not row:
        raise ValueError('Unknown internal job')
    if row['status'] != 'queued':
        raise ValueError('Only queued internal jobs can run; submissions are never replayed')
    if row['cancel']:
        with db:
            db.execute("UPDATE internal_jobs SET status='stopped',finished_at=? WHERE id=?", (time.time(), jid))
        raise ValueError('Analysis cancelled')
    config = gemini.read_config()
    if client is None:
        if not config:
            raise ValueError('Connect Gemini through the existing provider setup before analysis')
        client = gemini.Client(config['api_key'])
    with db:
        claimed = db.execute("UPDATE internal_jobs SET status='sending' WHERE id=? AND status='queued' AND cancel=0", (jid,)).rowcount
    if not claimed:
        raise ValueError('Internal job cancelled or already claimed')
    try:
        response = client.request('models/' + row['model'] + ':generateContent', json.loads(row['request_json']))
        usage = json.dumps(response.get('usageMetadata', {}))
        with db:
            db.execute('UPDATE internal_jobs SET response_json=?,usage_json=? WHERE id=?',
                       (json.dumps(response), usage, jid))
            db.execute('INSERT OR IGNORE INTO api_steps VALUES (?,?,?)', (jid, 0, usage))
        native = content(response)
        if any('functionCall' in part for part in native['parts']):
            raise ValueError('Analysis jobs have no tools')
        answer = '\n'.join(p['text'] for p in native['parts'] if 'text' in p and not p.get('thought'))
        if not answer.strip():
            raise ValueError('Empty analysis response')
        cancelled = db.execute('SELECT cancel FROM internal_jobs WHERE id=?', (jid,)).fetchone()[0]
        with db:
            db.execute('UPDATE internal_jobs SET status=?,answer=?,finished_at=? WHERE id=?',
                       ('stopped' if cancelled else 'completed', answer, time.time(), jid))
        if cancelled:
            raise ValueError('Analysis cancelled after response was saved')
        return answer
    except BaseException as exc:
        status = 'uncertain' if isinstance(exc, (KeyboardInterrupt, SystemExit)) or getattr(exc, 'uncertain', False) else 'failed'
        with db:
            db.execute("UPDATE internal_jobs SET status=?,error=?,finished_at=? WHERE id=? AND status='sending'",
                       (status, type(exc).__name__ + ': ' + str(exc), time.time(), jid))
        raise
