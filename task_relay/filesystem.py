"""Explicit read/edit grants enforced by the selected descriptor-based host adapter."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import uuid

from .host import HOST, UnsupportedHost


_DIR_FD_SUPPORTED = os.open in os.supports_dir_fd


class AccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class Grant:
    root: Path
    authority: str
    reads: frozenset | None = None
    writes: frozenset = frozenset()
    protected: tuple = ()

    def parts(self, path, write=False):
        if not isinstance(path,(str,Path)):raise AccessDenied('A relative file path is required')
        root=Path(self.root);target=Path(path)
        if not self.authority or not root.is_absolute() or '..' in root.parts:
            raise AccessDenied('A grant needs an absolute root and recorded authority')
        if not isinstance(path,(str,Path)) or '\x00' in str(path) or '..' in target.parts:
            raise AccessDenied('Parent traversal is outside the grant')
        if target.is_absolute():
            try:target=target.relative_to(root)
            except ValueError:raise AccessDenied('Path is outside the grant') from None
        name=target.as_posix()
        allowed=self.writes if write else self.reads
        if allowed is not None and name not in allowed:
            raise AccessDenied('Path is not granted for '+('editing' if write else 'reading'))
        absolute=root/target
        if any(absolute.is_relative_to(Path(p)) for p in self.protected):
            raise AccessDenied('Protected application data is outside the grant')
        return target.parts


class Filesystem:
    def __init__(self, host=HOST):self.host=host

    def require(self):
        self.host.require_posix('Filesystem read/edit grant enforcement')
        if not all(hasattr(os,n) for n in ('O_NOFOLLOW','O_DIRECTORY')) or not _DIR_FD_SUPPORTED:
            raise UnsupportedHost('Descriptor-relative no-follow filesystem enforcement unavailable')

    @contextmanager
    def root(self, grant):
        self.require();root=Path(grant.root)
        if not root.is_absolute() or '..' in root.parts or not grant.authority:
            raise AccessDenied('Invalid grant root/authority')
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=nxt
            yield fd
        finally:os.close(fd)

    @contextmanager
    def parent(self, grant, path, write=False):
        parts=grant.parts(path,write)
        if not parts:raise AccessDenied('A file path is required')
        with self.root(grant) as root:
            fd=os.dup(root)
            try:
                for part in parts[:-1]:
                    if write:
                        try:os.mkdir(part,mode=0o700,dir_fd=fd)
                        except FileExistsError:pass
                    nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    os.close(fd);fd=nxt
                yield fd,parts[-1]
            finally:os.close(fd)

    @contextmanager
    def open(self, grant, path, directory=False):
        parts=grant.parts(path)
        if not parts:
            with self.root(grant) as fd:yield fd
            return
        with self.parent(grant,path) as (parent,name):
            flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
            if directory:flags|=os.O_DIRECTORY
            fd=os.open(name,flags,dir_fd=parent)
            try:
                info=os.fstat(fd)
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise AccessDenied('Only regular files and directories are supported')
                if stat.S_ISREG(info.st_mode) and info.st_nlink!=1:
                    raise AccessDenied('Hard-linked files are outside the grant')
                yield fd
            finally:os.close(fd)

    def read(self,grant,path,limit):
        with self.open(grant,path) as fd:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise AccessDenied('A regular file is required')
            with os.fdopen(os.dup(fd),'rb') as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise AccessDenied('File exceeds the read limit')
        return raw

    def write(self,grant,path,raw,*,exclusive=False):
        with self.parent(grant,path,write=True) as (fd,dest):
            try:
                old=os.stat(dest,dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISREG(old.st_mode) or old.st_nlink!=1:raise AccessDenied('Existing output is linked or not a regular file')
            except FileNotFoundError:pass
            temp='.relay-write-'+uuid.uuid4().hex
            f=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            try:
                with os.fdopen(f,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
                if exclusive:os.link(temp,dest,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
                else:os.replace(temp,dest,src_dir_fd=fd,dst_dir_fd=fd)
            finally:
                try:os.unlink(temp,dir_fd=fd)
                except FileNotFoundError:pass


FILES=Filesystem()
