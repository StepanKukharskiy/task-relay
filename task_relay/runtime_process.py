"""Shared Python process boundary: source imports, no derived bytecode reads/writes.

The host null device cannot contain a cache tree. Explicit flags also apply to
isolated (-I) interpreters, which ignore PYTHON* environment variables. The
environment carries the same policy into ordinary Python descendants.
"""
import os
import sys
from pathlib import Path
import hashlib


def verify_sources(frozen,root=None):
    """No new request/tool may use source changed since the assignment froze.

    This is a fail-closed execution barrier, not a snapshot or permission to
    reload. Original provider responses and saved work remain available.
    """
    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
    for name,expected in frozen.get('runtime_sources',{}).items():
        relative=Path(name) if '/' in name else Path('orchestrator')/name
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid frozen source path')
        path=root/relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen implementation changed; no new request or tool dispatched: '+name)


def command(python,*arguments,isolated=False):
    return [str(python),*(['-I'] if isolated else []),'-B','-X',
            'pycache_prefix='+os.path.abspath(os.devnull),*map(str,arguments)]


def environment(base=None):
    return {**(os.environ if base is None else base),'PYTHONDONTWRITEBYTECODE':'1',
            'PYTHONPYCACHEPREFIX':os.path.abspath(os.devnull)}


def require_source_only():
    if not sys.dont_write_bytecode or sys.pycache_prefix!=os.path.abspath(os.devnull):
        raise ValueError('Pinned controller requires the source-only Python launch policy')
