"""Command entry point for the packaged relay; subcommands load on demand."""
import argparse
import importlib
import sys


COMMANDS = {
    'launcher': 'task_relay.launcher',
    'update': 'task_relay.updates',
    'cleanup': 'task_relay.cleanup',
    'storage': 'task_relay.messages_storage',
    'browser': 'task_relay.perplexity_browser',
    'setup': 'task_relay.onboarding',
    'doctor': 'task_relay.diagnostics',
    'host': 'task_relay.host',
    'credentials': 'task_relay.credentials',
    'telegram': 'task_relay.bridge',
    'messages': 'task_relay.messages_service',
    'orchestrator': 'orchestrator.__main__',
    'paths': 'task_relay.relay_paths',
    'usage': 'task_relay.usage_tracker',
    'setup-gemini': 'task_relay.gemini_setup',
    'setup-claude': 'task_relay.claude_setup',
}


def main(argv=None):
    from .desktop_binding import apply_binding
    apply_binding()
    from .updates import redirect
    from .releases import VERSION
    redirect(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='task-relay ' + VERSION)
    parser.add_argument('command', choices=tuple(COMMANDS))
    parser.add_argument('arguments', nargs=argparse.REMAINDER,
                        help='Arguments passed to the selected command; use COMMAND --help')
    args = parser.parse_args(argv)
    previous = sys.argv
    try:
        sys.argv = [parser.prog + ' ' + args.command, *args.arguments]
        result=importlib.import_module(COMMANDS[args.command]).main()
        if type(result) is int and result:raise SystemExit(result)
    except KeyboardInterrupt:
        print('\nStopped.')
        raise SystemExit(130) from None
    finally:
        sys.argv = previous
