"""Install a source checkout into an owned environment, then run guided setup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def source_hash():
    paths = [ROOT / name for name in ('pyproject.toml', 'MANIFEST.in', 'README.md')]
    paths += list(ROOT.glob('*.py'))
    for package in ('task_relay', 'orchestrator'):
        paths += [p for p in (ROOT / package).rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def install(target):
    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11 or newer is required. Install it, then rerun install.sh.')
    if sys.platform not in ('darwin', 'linux'):
        raise ValueError('The installer supports macOS and Linux; Windows execution remains unsupported.')
    if target.is_symlink():
        raise ValueError('Choose an installation environment that is not a symlink.')
    target = target.absolute()
    marker = target / '.task-relay-install.json'
    identity = dict(source=str(ROOT), sha256=source_hash())
    if target.exists():
        if marker.is_symlink() or not marker.is_file():
            raise ValueError('This directory is not owned by the Task Relay installer. Select a new directory with --venv.')
        try:
            old = json.loads(marker.read_text())
        except (ValueError, OSError):
            raise ValueError('Installation receipt is unreadable. Preserve this directory and select a new --venv.') from None
        if any(old.get(k) != v for k, v in identity.items()):
            raise ValueError('Source changed since installation. Use the installed task-relay update command for published releases, or choose a new --venv. Existing code and data were preserved.')
    else:
        target.mkdir(parents=True, mode=0o700)
        marker.write_text(json.dumps({**identity, 'status': 'installing'}))
    # Serialize retries, including environment creation and pip, without touching a service.
    import fcntl
    with marker.open('r') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another installer is using this environment.') from None
        cli = target / 'bin/task-relay'
        ready = json.loads(marker.read_text()).get('status') == 'ready'
        if not ready:
            venv.EnvBuilder(with_pip=True).create(target)
            subprocess.run([str(target / 'bin/python'), '-m', 'pip', 'install', str(ROOT)], check=True)
            # Keep the locked inode stable; an interrupted write fails closed on retry.
            marker.write_text(json.dumps({**identity, 'status': 'ready'}))
        if not cli.is_file():
            raise ValueError('Installed CLI is missing. Preserve this environment and choose a new --venv.')
        subprocess.run([str(cli), '--version'], check=True)
    return cli


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', type=Path, default=ROOT / '.venv-relay', help='New dedicated environment directory')
    parser.add_argument('--no-setup', action='store_true', help='Install code only; no credentials, data or service configuration')
    args = parser.parse_args()
    try:
        cli = install(args.venv.expanduser())
        import shlex
        print('Installed CLI: ' + str(cli), flush=True)
        print('For this shell: export PATH=' + shlex.quote(str(cli.parent)) + ':"$PATH"', flush=True)
        print('Keep this environment in place while a service uses it.', flush=True)
        if not args.no_setup:
            raise SystemExit(subprocess.call([str(cli), 'setup']))
    except KeyboardInterrupt:
        print('Installation interrupted. Rerun the same command to continue.', file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('Installation stopped: ' + str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
