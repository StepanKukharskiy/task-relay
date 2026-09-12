#!/usr/bin/env python3
"""Inspect only an exact pilot pairing message; save no other message content."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

from task_relay.relay_paths import PATHS


def rows(*arguments):
    result = subprocess.run(['/opt/homebrew/bin/imsg', *arguments, '--json'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError('Messages read failed. Check Terminal Full Disk Access.')
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def report_message(message, chat):
    guid = message.get('chat_guid', '')
    return {
        'message_keys': sorted(message),
        'is_from_me': message.get('is_from_me'),
        'is_group': message.get('is_group'),
        'chat_id_type': type(message.get('chat_id')).__name__,
        'chat_id_positive': isinstance(message.get('chat_id'), int) and message['chat_id'] > 0,
        'has_message_guid': bool(message.get('guid')),
        'chat_guid_prefix': ';'.join(guid.split(';')[:2]) if isinstance(guid, str) else None,
        'chat_service': chat.get('service'),
        'chat_is_group': chat.get('is_group'),
        'created_at': message.get('created_at'),
        'chat_guid_matches_directory': guid == chat.get('guid'),
    }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', required=True)
    args = parser.parse_args()
    report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'matches': []}
    try:
        # No raw chats, participant handles, names, or unrelated texts are retained.
        start = dt.datetime.fromtimestamp(time.time() - 7200, dt.timezone.utc).isoformat()
        for chat in rows('chats', '--limit', '10'):
            for message in rows('history', '--chat-id', str(chat['id']), '--limit', '100', '--start', start):
                if (message.get('text') or '').strip() == '/pair ' + args.code:
                    report['matches'].append(report_message(message, chat))
            if report['matches']:
                break
        report['status'] = 'found' if report['matches'] else 'pairing message not found in recent Messages history'
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        report['status'] = str(exc)
    path = PATHS.messages/'diagnostic.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(report, indent=2) + '\n')
    print('Diagnostic saved. Return to Codex; it can now read the result.')
    print('Status:', report['status'])


if __name__ == '__main__':
    main()
