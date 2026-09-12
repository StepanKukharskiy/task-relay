"""One durable API/tool turn per process; ambiguous requests are never replayed."""
import json
import os
from pathlib import Path
import signal
import sys
import time
from task_relay import api_providers as api
from task_relay import gemini
from task_relay import file_tools
from task_relay.backends import finish, task


def run_job(state, jid, parent_pid=None, client=None):
    job = state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (jid,)).fetchone()
    run = state.db.execute('SELECT * FROM api_runs WHERE job_id=?', (jid,)).fetchone()
    if not job or job['status'] != 'running' or not run:
        return
    info = task(state, job['thread_id'])
    stopped = False
    submitted = run['stage'] != 'prepared'
    def stop(*_):
        nonlocal stopped
        stopped = True
    if parent_pid is not None:
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
    def cancelled():
        return stopped or state.db.execute('SELECT cancel FROM backend_jobs WHERE id=?', (jid,)).fetchone()[0] or (parent_pid is not None and os.getppid() != parent_pid)
    try:
        while True:
            run = state.db.execute('SELECT * FROM api_runs WHERE job_id=?', (jid,)).fetchone()
            path = Path(run['response_path'])
            submitted = run['stage'] != 'prepared'
            if cancelled():
                uncertain = submitted and not path.is_file()
                finish(state, jid, 'uncertain' if uncertain else 'stopped',
                       'Generation was stopped after submission; check its outcome.' if uncertain else 'Stopped. No further API or file calls were made.')
                return
            payload = json.loads(run['request_json'])
            if path.is_file():
                response = json.loads(path.read_text())
            else:
                if submitted:
                    finish(state, jid, 'uncertain', 'The previous API submission has no saved result. It was not replayed.')
                    return
                config = api.read_config(info['backend'])
                if not config:
                    raise ValueError('The provider is disabled or disconnected. Open /providers.')
                client = client or api.Client(info['backend'], config['api_key'], run['base_url'])
                api.encode_request(payload)
                with state.db:
                    claimed = state.db.execute("UPDATE api_runs SET stage='sending' WHERE job_id=? AND step=? AND stage='prepared' AND EXISTS (SELECT 1 FROM backend_jobs WHERE id=? AND status='running' AND cancel=0)", (jid, run['step'], jid)).rowcount
                if not claimed:
                    return
                submitted = True
                response = client.request('responses' if info['backend'] == 'openai' else 'chat/completions', payload)
                gemini.atomic_bytes(path, json.dumps(response).encode())
            with state.db:
                state.db.execute('INSERT OR IGNORE INTO api_steps VALUES (?,?,?)', (jid, run['step'], json.dumps(response.get('usage', {}))))
                usages = [json.loads(r[0]) for r in state.db.execute('SELECT usage_json FROM api_steps WHERE job_id=? ORDER BY step', (jid,))]
                state.db.execute('UPDATE api_runs SET usage_json=? WHERE job_id=?', (json.dumps({'steps': usages}), jid))
            if cancelled():
                finish(state, jid, 'stopped', 'Stopped after saving the provider response. No further file or API calls were made.')
                return
            calls = api.tool_calls(info['backend'], response)
            if not calls:
                text, complete = api.answer(info['backend'], response)
                with state.db:
                    state.db.execute("UPDATE api_runs SET stage='complete' WHERE job_id=?", (jid,))
                    if complete:
                        state.db.execute('INSERT OR IGNORE INTO api_history VALUES (?,?,?,?,?)', (jid, job['thread_id'], job['prompt'], text, time.time()))
                        finish(state, jid, 'completed', text)
                    else:
                        finish(state, jid, 'failed', text + '\n\nThe provider ended before a complete response. This partial result is preserved above.')
                return
            if not run['workspace'] or not payload.get('tools') or payload.get('tool_choice') == 'none' or run['step'] >= api.MAX_TOOL_ROUNDS:
                raise ValueError('File tools are unavailable or the tool budget is exhausted. No additional files were read.')
            used = state.db.execute('SELECT count(*) FROM api_tool_calls WHERE job_id=? AND step<?', (jid, run['step'])).fetchone()[0]
            if used + len(calls) > api.MAX_TOOL_CALLS:
                raise ValueError('The turn reached its file tool call limit. Please narrow the request.')
            results = []
            protected = (gemini.DATA, state.media_dir.parent)
            offered = {t.get('name') or t.get('function', {}).get('name') for t in payload['tools']}
            for call in calls:
                if cancelled():
                    finish(state, jid, 'stopped', 'Stopped during file inspection. No further API request was submitted.')
                    return
                saved = state.db.execute('SELECT result_json FROM api_tool_calls WHERE job_id=? AND step=? AND call_id=?', (jid, run['step'], call['id'])).fetchone()
                if saved:
                    result = saved[0]
                else:
                    value = (file_tools.execute(run['workspace'], call['name'], call['arguments'], protected)
                             if call['name'] in offered else {'ok': False, 'error': 'This tool is unavailable.'})
                    result = json.dumps(value, ensure_ascii=False)
                    with state.db:
                        state.db.execute('INSERT OR IGNORE INTO api_tool_calls VALUES (?,?,?,?,?,?)',
                                         (jid, run['step'], call['id'], call['name'], call['arguments'], result))
                results.append(result)
            exhausted = run['step'] + 1 >= api.MAX_TOOL_ROUNDS or used + len(calls) >= api.MAX_TOOL_CALLS
            encoded = api.continue_request(info['backend'], payload, response, calls, results, exhausted)
            next_path = path.parent / f"{jid}.{run['step'] + 1}.json"
            with state.db:
                advanced = state.db.execute("UPDATE api_runs SET step=step+1,stage='prepared',response_path=?,request_json=? WHERE job_id=? AND step=?",
                                            (str(next_path), encoded, jid, run['step'])).rowcount
            if not advanced:
                return
    except gemini.ProviderError as exc:
        hint = ' Select a model that supports function calling with /models.' if exc.status in (400, 422) else ''
        finish(state, jid, 'uncertain' if exc.uncertain else 'failed', f'{api.SPECS[info["backend"]]["name"]} request failed ({exc.status}). Open /providers to check the connection.{hint} No automatic generation retry was made.')
    except ValueError as exc:
        finish(state, jid, 'failed', str(exc))
    except Exception:
        finish(state, jid, 'uncertain' if submitted else 'failed', 'The API turn could not finish. A submitted request will not be replayed automatically.')


if __name__ == '__main__':
    os.umask(0o077)
    from task_relay.bridge import State
    state = State(Path(sys.argv[1]))
    try:
        run_job(state, sys.argv[2], int(sys.argv[3]))
    finally:
        state.db.close()
