"""One Claude SDK turn. Prompts and results stay in private state, not argv/logs."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid
from task_relay import capabilities

from task_relay.bridge import State
from task_relay.backends import ACTIVE, claude_config, finish, task


async def run_job(state, job_id, parent_pid):
    from claude_agent_sdk import (ClaudeSDKClient, ClaudeAgentOptions, ResultMessage,
                                  SystemMessage, PermissionResultAllow, PermissionResultDeny)
    job = state.db.execute('SELECT * FROM backend_jobs WHERE id=?', (job_id,)).fetchone()
    if not job or job['status'] != 'running':
        return
    info = task(state, job['thread_id'])
    config = claude_config()
    if not config:
        finish(state, job_id, 'failed', 'Claude account setup is missing. Open Setup Claude.command. Your instruction was not sent.')
        return
    from task_relay.host_apps import claude_cli
    try: cli_path=claude_cli()
    except ValueError as exc:
        finish(state,job_id,'failed',str(exc));return
    # Account mode must not accidentally use an inherited, separately billed key.
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN',
                'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        os.environ.pop(key, None)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stopped.set)
    loop.add_signal_handler(signal.SIGINT, stopped.set)

    async def permission(tool_name, tool_input, context):
        # SDK default rules decide what is already allowed. This callback handles
        # only actions requiring a decision, not an alternate all-tools allowlist.
        if tool_name == 'AskUserQuestion':
            return PermissionResultDeny(message='Ask the user in your final response, then wait for their next Telegram reply.')
        body = json.dumps(tool_input, ensure_ascii=False, indent=2)
        if len(body.encode('utf-16-le')) > 4200:
            return PermissionResultDeny(message='This permission request is too large to review in Telegram. Split the action into smaller, reviewable steps.')
        request_id = uuid.uuid4().hex[:16]
        text = (f'Claude needs permission: {tool_name}\n\n{body}\n\n'
                'Use the Allow/Deny buttons below, or type the full command:\n'
                f'/allow {request_id}\n/deny {request_id}\nExpires in 15 minutes. Approval applies once.')
        with state.db:
            state.db.execute('INSERT INTO tool_requests VALUES (?,?,?,?,?,?,?)',
                             (request_id, job_id, job['thread_id'], tool_name, body, 'pending', time.time() + 900))
            state.db.execute("UPDATE backend_jobs SET status='waiting' WHERE id=?", (job_id,))
            state.db.execute("UPDATE watched SET status='waiting' WHERE id=?", (job['thread_id'],))
            state.db.execute('INSERT INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                             ('permission:' + request_id, job['thread_id'], text))
        try:
            while not stopped.is_set():
                row = state.db.execute('SELECT * FROM tool_requests WHERE id=?', (request_id,)).fetchone()
                if row['status'] == 'allowed':
                    with state.db:
                        state.db.execute("UPDATE tool_requests SET status='used' WHERE id=?", (request_id,))
                    return PermissionResultAllow(updated_input=tool_input)
                if row['status'] != 'pending' or time.time() >= row['expires_at']:
                    break
                await asyncio.sleep(.4)
            return PermissionResultDeny(message='The user declined, the request expired, or the task was stopped.')
        finally:
            with state.db:
                state.db.execute("UPDATE tool_requests SET status='expired' WHERE id=? AND status='pending'", (request_id,))
                state.db.execute("UPDATE backend_jobs SET status='running' WHERE id=? AND status='waiting'", (job_id,))
                state.db.execute("UPDATE watched SET status='running' WHERE id=? AND status='waiting'", (job['thread_id'],))

    options = ClaudeAgentOptions(
        cli_path=cli_path,
        cwd=info['cwd'], model=info['model'],
        resume=info['session_id'] if info['initialized'] else None,
        session_id=None if info['initialized'] else info['session_id'],
        permission_mode='default', can_use_tool=permission,
        setting_sources=[], strict_mcp_config=True,
        tools=capabilities.CLAUDE_TOOLS,
        max_turns=100, max_budget_usd=float(config.get('max_budget_usd', 5)),
        system_prompt={'type': 'preset', 'preset': 'claude_code', 'append':
            'The user is working through a private Telegram task relay. Complete their task in the chosen working folder. '
            'Include explicit Markdown links to generated files in the final response so the relay can attach them. '
            'Report what changed and meaningful verification. If you need clarification, end your turn with a concise question. '
            'Do not start detached background work; the task runner closes after your result. '
            'Only the user can approve a requested tool action through Telegram.'},
        stderr=lambda _: None,
    )
    result = None
    async with ClaudeSDKClient(options=options) as client:
        async def watchdog():
            started = time.monotonic()
            while not stopped.is_set():
                row = state.db.execute('SELECT status,cancel FROM backend_jobs WHERE id=?', (job_id,)).fetchone()
                if os.getppid() != parent_pid or not row or row['cancel'] or row['status'] not in ACTIVE or time.monotonic() - started > 3600:
                    stopped.set()
                    break
                await asyncio.sleep(.5)
            await client.interrupt()
        watcher = asyncio.create_task(watchdog())
        try:
            await client.query(job['prompt'])
            async for message in client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == 'init':
                    actual = message.data.get('session_id')
                    if actual != info['session_id']:
                        raise RuntimeError('Claude returned a different session')
                    with state.db:
                        state.db.execute('UPDATE backend_tasks SET initialized=1 WHERE id=?', (job['thread_id'],))
                        state.db.execute("UPDATE incoming SET status='submitted' WHERE id=?", (job['update_id'],))
                if isinstance(message, ResultMessage):
                    if message.session_id != info['session_id']:
                        raise RuntimeError('Claude result session mismatch')
                    result = message
                    from task_relay import usage_tracker
                    with state.db:
                        usage_tracker.record_claude(state.db,job,info,message)
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
    if stopped.is_set():
        finish(state, job_id, 'stopped', 'Claude was interrupted. Some work may already have completed; review the project before continuing.')
    elif result is None:
        finish(state, job_id, 'uncertain', 'Claude returned no confirmed result. Check the session before continuing.')
    else:
        # SDK errors may contain raw request data; expose a stable classification,
        # not arbitrary transport diagnostics or provider credentials.
        if result.is_error:
            code = result.subtype if result.subtype in ('error_max_turns', 'error_max_budget_usd', 'error_during_execution') else 'execution_error'
            summary = f'Claude could not finish ({code}). Check account login, model availability, and the local session. Some work may have completed.'
        else:
            summary = result.result or 'Claude finished without a text response.'
        finish(state, job_id, 'failed' if result.is_error else 'completed', summary, result.total_cost_usd)


def main():
    os.umask(0o077)
    state = State(Path(sys.argv[1]))
    job_id = sys.argv[2]
    try:
        asyncio.run(run_job(state, job_id, int(sys.argv[3])))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            label = 'Claude was interrupted before a result was confirmed.'
        else:
            label = f'Claude connection ended without a confirmed result ({type(exc).__name__}). Check account login and the local session before continuing.'
        finish(state, job_id, 'uncertain', label)
    finally:
        state.db.close()


if __name__ == '__main__':
    main()
