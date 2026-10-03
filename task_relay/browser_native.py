"""Narrow Chrome native-messaging interface; never exposes desktop dispatch."""
import argparse
import contextlib
import json
import struct
import sys
from pathlib import Path

MAX_MESSAGE = 900000
HOST_NAME = 'ai.task_relay.capture'


def read_message(stream):
    def exact(length):
        chunks = bytearray()
        while len(chunks) < length:
            part = stream.read(length - len(chunks))
            if not part: raise EOFError('Native channel closed')
            chunks.extend(part)
        return bytes(chunks)
    length = struct.unpack('=I', exact(4))[0]
    if not 0 < length <= MAX_MESSAGE: raise ValueError('Native message exceeds capture budget')
    value = json.loads(exact(length))
    if not isinstance(value, dict): raise ValueError('Expected native message object')
    return value


def write_message(stream, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > MAX_MESSAGE: raise ValueError('Reply exceeds native message budget')
    stream.write(struct.pack('=I', len(raw)) + raw); stream.flush()


def dispatch(db, folder, message):
    from . import browser_capture as bc, portable_work as portable, gemini
    action = message.get('action')
    if action == 'status':
        configured = bool(gemini.read_config())
        return {'connected': True, 'analysis_available': configured,
                'analysis_label': 'Relay Gemini (provider charges may apply)' if configured else 'Use your AI chat to propose reusable work'}
    if action == 'library': return bc.library(db)
    if action == 'work': return bc.bounded_work(db, message['work_id'])
    if action == 'source':
        row = db.execute('SELECT source_json FROM browser_sources WHERE id=?', (message['source_id'],)).fetchone()
        if not row: raise ValueError('Unknown Source')
        return json.loads(row[0])
    if action == 'skill':
        row = db.execute('SELECT document FROM browser_skill_versions WHERE name=? ORDER BY created DESC LIMIT 1', (message['name'],)).fetchone()
        if not row: raise ValueError('Unknown Skill')
        return json.loads(row[0])
    if action == 'relay_analyze_capture':
        if message.get('run_analysis') is not True:
            source = bc.capture(message['capture'])
            revision = bc.ws.project(db, source['work_id'])['revision'] if source['work_id'] else None
            return {'source_record': source, 'analysis_prompt': bc.prompt(db, source), 'base_revision': revision,
                    'skill_candidates': [], 'work_changes': [], 'limitations': source['metadata']['limitations']}
        return bc.relay_analyze_capture(db, message['capture'], request_key=message['request_key'])
    if action == 'review_candidates':
        source = bc.capture(message['capture'])
        if source['work_id'] and bc.ws.project(db, source['work_id'])['revision'] != message.get('base_revision'):
            raise ValueError('Work changed while the AI prepared proposals. Refresh and prepare a new request')
        return bc.relay_analyze_capture(db, message['capture'], answer=message['answer'])
    if action == 'save':
        receipt = bc.save(db, message['capture'], message['kind'], message.get('candidate'), message['request'],
                          message['request_key'], confirmed=message.get('confirmed'), base_revision=message.get('base_revision'))
        if receipt['kind'] == 'skill':
            try: receipt = bc.project_skill(db, receipt, folder)
            except (OSError, ValueError):
                receipt = {**receipt, 'projection': 'pending', 'limitation': 'Skill is in SQLite. Retry the same Save to recover its files.'}
        return receipt
    if action == 'continue': return bc.continue_work(db, message['work_id'], message['request'], message.get('skill_name'))
    if action == 'export_skill':
        if message.get('confirmed') is not True: raise ValueError('Explicit export required')
        return portable.review_export(dispatch(db, folder, {'action': 'skill', 'name': message['name']}), True)
    raise ValueError('Unsupported capture action')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin'); parser.add_argument('--extension-id', required=True)
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args(argv)
    if args.origin != 'chrome-extension://' + args.extension_id + '/':
        parser.error('Caller is not the explicitly registered extension')
    folder = Path(args.data_dir)
    if not folder.is_absolute(): parser.error('Select an absolute Relay data folder')
    # Resolve bindings before importing the shared runtime/provider modules.
    import os
    os.environ['TASK_RELAY_DATA_DIR'] = str(folder)
    from . import browser_capture as bc, work_state as ws
    db = ws.connect(folder / 'state.sqlite'); bc.initialize(db)
    try:
        while True:
            try: message = read_message(sys.stdin.buffer)
            except EOFError: break
            try:
                with contextlib.redirect_stdout(sys.stderr): result = dispatch(db, folder, message)
                reply = {'ok': True, 'result': result}
            except (ValueError, KeyError, TypeError, OSError) as exc:
                reply = {'ok': False, 'error': str(exc)[:1000]}
            write_message(sys.stdout.buffer, reply)
    finally: db.close()


if __name__ == '__main__': main()
