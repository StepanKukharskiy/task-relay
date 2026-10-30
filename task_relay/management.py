"""Local management protocol. No job execution, messaging or database repair."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .host import HOST, UnsupportedHost

PROTOCOL = 1
SKILL = Path(__file__).parent / 'assets/skills/relay-manage'


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def paths():
    # Unlike interactive startup, management must report a broken saved binding,
    # rather than diagnosing or updating a different, apparently empty database.
    from . import desktop_binding
    from .relay_paths import resolve
    env = dict(os.environ)
    if 'TASK_RELAY_DATA_DIR' not in env:
        if desktop_binding.FILE.is_symlink():
            raise ValueError('Linked desktop binding requires inspection; no default data folder was selected.')
        if desktop_binding.FILE.exists():
            env = {**desktop_binding._paths(json.loads(desktop_binding.FILE.read_text())), **env}
    return resolve(env)


def install_skill(destination, *, source=SKILL):
    target = Path(destination).expanduser().absolute()
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('Choose a skill destination without symbolic links.')
    source = (source / 'SKILL.md').read_bytes()
    if target.exists():
        if (target.is_dir() and {p.name for p in target.iterdir()} == {'SKILL.md'}
                and (target / 'SKILL.md').is_file() and not (target / 'SKILL.md').is_symlink()
                and (target / 'SKILL.md').read_bytes() == source):
            return dict(path=str(target), installed=True, changed=False)
        raise ValueError('Skill destination already exists or was edited. Choose a new folder; nothing was overwritten.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o700)  # Exclusive; a concurrent installer cannot overwrite it.
    with (target / 'SKILL.md').open('xb') as stream:
        stream.write(source)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=str(target), installed=True, changed=True)


def execute(args):
    if args.action == 'skill-install':
        return install_skill(args.destination)
    if args.action == 'skill':
        return dict(name='relay-manage', path=str(SKILL), auto_installed=False)
    selected = paths()
    if args.action == 'discover':
        applications = []
        if HOST.platform == 'darwin':
            from .management_macos import discover
            applications = discover(args.app)
        return dict(version=__version__, platform=HOST.platform, paths=selected.describe(),
                    applications=applications, skill=str(SKILL),
                    scope='Local inspection; no network, service changes or execution.')
    if args.action == 'diagnose' and not args.app:
        from .management_macos import current_app
        if HOST.platform != 'darwin' or current_app() is None:
            from .diagnostics import inspect
            return dict(configuration=inspect(selected), app_updates_supported=False)
    if HOST.platform != 'darwin':
        raise UnsupportedHost('Packaged app updates require the macOS app. Source/package installations use task-relay update.')
    from .management_macos import Manager
    manager = Manager(selected, args.app)
    if args.action == 'diagnose':
        return manager.diagnose()
    if args.action == 'update-receipts':
        return manager.receipts(args.attempt)
    if args.action == 'update-status':
        return manager.updater.status()
    if args.action == 'update-recover':
        return manager.updater.recover(args.attempt)
    manager.require_installed_runtime()
    if args.action == 'update-check':
        return manager.updater.check(args.beta)
    if args.action == 'update-download':
        return manager.updater.download(args.candidate)
    if args.action == 'update-install':
        return manager.updater.install(args.attempt)
    raise ValueError('Unknown management action.')


def main(argv=None):
    action = None
    try:
        parser = Arguments(description=__doc__)
        parser.add_argument('--app', help='Exact app path when using its retained recovery helper')
        commands = parser.add_subparsers(dest='action', required=True, parser_class=Arguments)
        for name in ('discover', 'diagnose', 'skill', 'update-status'):
            commands.add_parser(name)
        commands.add_parser('skill-install').add_argument('--destination', required=True)
        commands.add_parser('update-check').add_argument('--beta', action='store_true')
        commands.add_parser('update-download').add_argument('--candidate', required=True)
        for name in ('update-install', 'update-recover'):
            commands.add_parser(name).add_argument('--attempt', required=True)
        commands.add_parser('update-receipts').add_argument('--attempt')
        args = parser.parse_args(argv)
        action = args.action
        result = execute(args)
        print(json.dumps(dict(protocol=PROTOCOL, ok=True, action=action, result=result)))
        return 0
    except Exception as exc:
        # OS error text can contain private paths; diagnostics explicitly expose
        # bindings, but failures do not dump tracebacks, arbitrary files or secrets.
        message = str(exc) if isinstance(exc, (ValueError, UnsupportedHost)) else 'Local management could not finish; preserve the existing installation and receipts.'
        print(json.dumps(dict(protocol=PROTOCOL, ok=False, action=action,
                             error=dict(code=type(exc).__name__, message=message))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
