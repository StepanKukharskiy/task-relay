"""Command entry point for the packaged relay; subcommands load on demand."""
import argparse
import runpy
import sys


COMMANDS = {
    'host': 'task_relay.host',
    'credentials': 'task_relay.credentials',
    'telegram': 'task_relay.bridge',
    'messages': 'task_relay.messages_service',
    'orchestrator': 'orchestrator',
    'paths': 'task_relay.relay_paths',
    'usage': 'task_relay.usage_tracker',
    'setup-gemini': 'task_relay.gemini_setup',
    'setup-claude': 'task_relay.claude_setup',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='task-relay 0.11.0')
    parser.add_argument('command', choices=tuple(COMMANDS))
    parser.add_argument('arguments', nargs=argparse.REMAINDER,
                        help='Arguments passed to the selected command; use COMMAND --help')
    args = parser.parse_args(argv)
    previous = sys.argv
    try:
        sys.argv = [parser.prog + ' ' + args.command, *args.arguments]
        runpy.run_module(COMMANDS[args.command], run_name='__main__')
    finally:
        sys.argv = previous
