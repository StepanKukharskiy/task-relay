"""Local macOS bundle replacement primitives; caller must stop owned services first.

Keep the installed app root in place. Recovery archives live outside Applications.
The caller owns service/DB receipts and must never restore data after dispatch.
"""
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import tempfile


def run(args):
    subprocess.run([str(value) for value in args], check=True, capture_output=True)


def bundle_digest(app):
    app = Path(app)
    if app.is_symlink() or not app.is_dir():
        raise ValueError('Bundle must be a real directory.')
    digest = hashlib.sha256()
    for path in sorted(app.rglob('*')):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('Linked or non-regular bundle entry: ' + str(path))
        digest.update(str(path.relative_to(app)).encode() + b'\0' + str(mode).encode() + b'\0')
        if path.is_file():
            with path.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
    return digest.hexdigest()


def verify(app):
    info = plistlib.loads((Path(app) / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.taskrelay.desktop':
        raise ValueError('Expected Task Relay bundle identity.')
    run(['codesign', '--verify', '--deep', '--strict', app])


def archive_bundle(app, archive):
    app, archive = Path(app), Path(archive)
    expected = bundle_digest(app)
    verify(app)
    if archive.exists() or archive.is_symlink():
        raise ValueError('Recovery archives cannot be overwritten.')
    if archive.suffix != '.zip' or Path('/Applications') in archive.resolve().parents:
        raise ValueError('Store recovery ZIPs outside Applications.')
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Finder can recreate .DS_Store between cleanup's unlink and rmdir. A failed
    # cleanup must not invalidate an already verified immutable recovery archive.
    # Verification/archiving failures still propagate; leftover scratch is recorded.
    with tempfile.TemporaryDirectory(prefix='.archive-', dir=archive.parent, ignore_cleanup_errors=True) as directory:
        directory = Path(directory)
        temporary = directory / 'bundle.zip'
        run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, temporary])
        extracted = directory / 'verify'
        run(['ditto', '-x', '-k', temporary, extracted])
        restored = extracted / app.name
        verify(restored)
        if bundle_digest(restored) != expected or bundle_digest(app) != expected:
            raise ValueError('Archive verification failed or source changed; app preserved.')
        temporary.chmod(0o600)
        # Do not overwrite a concurrently created recovery record.
        os.link(temporary, archive)
    return {'source': str(app), 'archive': str(archive), 'bundle_sha256': expected,
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'temporary_cleanup_pending':str(directory) if directory.exists() else None}


def retire_archived_bundle(app, receipt):
    app = Path(app)
    archive = Path(receipt['archive'])
    if str(app) != receipt['source'] or bundle_digest(app) != receipt['bundle_sha256']:
        raise ValueError('Archived app identity changed; preserved.')
    if archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != receipt['archive_sha256']:
        raise ValueError('Recovery archive changed; app preserved.')
    shutil.rmtree(app)


def replace_contents(installed, candidate, holding):
    """Caller journals paths before calling; holding must be private and new.

    On failure restores the old Contents. On success retains it for caller's
    prelaunch rollback, until finish_contents is called after verified startup.
    """
    installed, candidate, holding = map(Path, (installed, candidate, holding))
    old = bundle_digest(installed)
    expected = bundle_digest(candidate)
    verify(candidate)
    if installed == candidate or holding.exists() or holding.is_symlink():
        raise ValueError('Choose a fresh holding directory and separate candidate.')
    if set(p.name for p in installed.iterdir()) != {'Contents'} or set(p.name for p in candidate.iterdir()) != {'Contents'}:
        raise ValueError('Unexpected app root entries; preserve for inspection.')
    inode = installed.stat().st_ino
    holding.mkdir(mode=0o700)
    staged, previous = holding / 'candidate-contents', holding / 'previous-contents'
    run(['ditto', candidate / 'Contents', staged])
    if bundle_digest(installed) != old:
        raise ValueError('Installed app changed before replacement.')
    try:
        (installed / 'Contents').rename(previous)
        staged.rename(installed / 'Contents')
        verify(installed)
        if bundle_digest(installed) != expected or installed.stat().st_ino != inode:
            raise ValueError('Installed bundle verification failed.')
    except BaseException:
        restore_contents(installed, holding)
        raise
    return {'installed_inode': inode, 'before_sha256': old, 'after_sha256': expected,
            'holding': str(holding)}


def restore_contents(installed, holding):
    """Only while services are stopped and before new dispatch; never restores DB."""
    installed, holding = Path(installed), Path(holding)
    previous = holding / 'previous-contents'
    if previous.is_dir() and not previous.is_symlink():
        current = installed / 'Contents'
        if current.exists():
            current.rename(holding / 'failed-contents')
        previous.rename(current)
        verify(installed)


def finish_contents(holding):
    shutil.rmtree(holding)
