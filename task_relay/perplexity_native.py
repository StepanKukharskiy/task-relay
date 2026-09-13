"""Browser-owned native host for narrowly scoped Perplexity Search jobs."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import time

from . import browser_research
from .browser_jobs import Journal, conversation_url
from .host_perplexity import EXTENSION_ID, Port, prepare, register
from .perplexity_browser import HOME_URL, profile_lock
from .relay_paths import PATHS


class Driver:
    def __init__(self, port, heartbeat=lambda: None):
        self.port, self.heartbeat = port, heartbeat
        self.expected_open_url = None

    def call(self, action, **values):
        ident = secrets.token_hex(12)
        self.heartbeat()
        self.port.write({'id': ident, 'action': action, **values})
        reply = self.port.read()
        if reply.get('id') != ident:
            raise ValueError('Browser response identity changed. No action was retried.')
        if reply.get('error'):
            raise ValueError(str(reply['error'])[:1000])
        if 'value' not in reply:
            raise ValueError('Browser returned no result.')
        return reply['value']

    def open(self, url=None):
        self.expected_open_url = conversation_url(url) if url else HOME_URL
        self.call('open', url=self.expected_open_url)

    def snapshot(self):
        value = self.call('snapshot')
        if (not isinstance(value, dict) or not isinstance(value.get('text'), str)
                or len(value['text'].encode()) > 250000
                or any(type(value.get(k)) is not int or value[k] < 0 for k in ('queries', 'answers'))
                or type(value.get('ready')) is not bool):
            raise ValueError('Unrecognized Perplexity observation.')
        if value['url'] != HOME_URL:
            conversation_url(value['url'])
        if self.expected_open_url is not None:
            if value['url'] != self.expected_open_url:
                raise ValueError('The worker tab changed destination before observation. No submit was requested.')
            self.expected_open_url = None
        return value

    def check_ready(self, snapshot):
        if snapshot.get('blocked'):
            raise ValueError(snapshot['blocked'])
        if not snapshot['ready'] or snapshot['queries'] != snapshot['answers']:
            raise ValueError('Perplexity is busy or its Search controls are not recognized.')

    def submit(self, prompt, baseline):
        # The content script compares the actual DOM again before filling/clicking.
        self.call('submit', prompt=prompt, baseline=baseline)

    def pause(self):
        time.sleep(1)


def serve(port, state):
    browser_research.initialize(state.db)
    session = secrets.token_hex(16)
    with profile_lock(Path(state.db.execute('PRAGMA database_list').fetchone()[2]).parent):
        browser_research.recover(state)
        try:
            while True:
                message = port.read(timeout=30)
                if message != {'action': 'poll'}:
                    raise ValueError('Only the connected browser may poll the research queue.')
                browser_research.connection(state.db, session)
                driver = Driver(port, lambda: browser_research.connection(state.db, session))
                browser_research.run_next(state, driver)
                port.write({'action': 'idle'})
        finally:
            with state.db:
                state.db.execute('DELETE FROM browser_research_connection WHERE session=?', (session,))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('folder', type=Path)
    p = sub.add_parser('register'); p.add_argument('manifest', type=Path)
    p = sub.add_parser('serve'); p.add_argument('browser_arguments', nargs='*')
    p = sub.add_parser('send'); p.add_argument('--receipt', required=True); p.add_argument('--prompt-file', type=Path, required=True); p.add_argument('--url')
    p = sub.add_parser('status'); p.add_argument('receipt', nargs='?')
    p = sub.add_parser('reconcile'); p.add_argument('receipt'); p.add_argument('--url')
    p = sub.add_parser('retry'); p.add_argument('receipt')
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        print(json.dumps(prepare(args.folder, PATHS), indent=2)); return 0
    if args.action == 'register':
        print(register(args.manifest)); return 0
    if args.action == 'serve' and (not args.browser_arguments or args.browser_arguments[-1] != EXTENSION_ID):
        raise ValueError('The native host must be started by the Task Relay browser extension.')
    from .bridge import State
    state = State(PATHS.state)
    try:
        browser_research.initialize(state.db)
        if args.action == 'serve':
            try:serve(Port(sys.stdin.buffer, sys.stdout.buffer), state)
            except (EOFError, ValueError, OSError):return 2
        elif args.action == 'send':
            with args.prompt_file.open('rb') as stream: raw = stream.read(48001)
            if len(raw) > 48000: raise ValueError('Prompt file exceeds 48000 bytes.')
            receipt = browser_research.enqueue(state, args.receipt, '/perplexity ' + raw.decode('utf-8'), 'local', args.url)
            print(json.dumps(Journal(state.db).get(receipt), ensure_ascii=False, indent=2))
        elif args.action in ('reconcile', 'retry'):
            browser_research.requeue(state, args.receipt, inspect=args.action == 'reconcile', url=getattr(args, 'url', None))
            print('Observation queued; no resubmission.' if args.action == 'reconcile' else 'Blocked request queued for an explicit retry.')
        else:
            result = Journal(state.db).get(args.receipt) if args.receipt else {'connected': browser_research.connected(state.db)}
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        state.db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
