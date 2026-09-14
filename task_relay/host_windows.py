"""Windows 10+ process ownership. Native calls are loaded only on Windows.

CreateProcess receives the Job Object in its startup attributes: user code never
runs outside the owned job. A scheduler-launched supervisor has a separate
lifetime and owns the job for its executable and all descendants.
"""
import ctypes as C
from contextlib import ExitStack
import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

DWORD=C.c_uint32
WORD=C.c_uint16
HANDLE=C.c_void_p
SIZE_T=C.c_size_t
BOOL=C.c_int32
ULONG_PTR=C.c_size_t
INFINITE=0xffffffff
WAIT_TIMEOUT=258
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000
PROC_THREAD_ATTRIBUTE_JOB_LIST=0x2000d
PROC_THREAD_ATTRIBUTE_HANDLE_LIST=0x20002


class IO_COUNTERS(C.Structure):
    _fields_=[(name,C.c_uint64) for name in ('reads','writes','other','read_bytes','write_bytes','other_bytes')]


class BASIC_LIMITS(C.Structure):
    _fields_=[('process_time',C.c_int64),('job_time',C.c_int64),('flags',DWORD),
              ('min_working_set',SIZE_T),('max_working_set',SIZE_T),('active_limit',DWORD),
              ('affinity',ULONG_PTR),('priority',DWORD),('scheduling',DWORD)]


class EXTENDED_LIMITS(C.Structure):
    _fields_=[('basic',BASIC_LIMITS),('io',IO_COUNTERS),('process_memory',SIZE_T),
              ('job_memory',SIZE_T),('peak_process_memory',SIZE_T),('peak_job_memory',SIZE_T)]


class STARTUPINFO(C.Structure):
    _fields_=[('cb',DWORD),('reserved',C.c_wchar_p),('desktop',C.c_wchar_p),('title',C.c_wchar_p),
              *[(name,DWORD) for name in ('x','y','xsize','ysize','xchars','ychars','fill','flags')],
              ('show',WORD),('reserved_size',WORD),('reserved_bytes',C.c_void_p),
              ('stdin',HANDLE),('stdout',HANDLE),('stderr',HANDLE)]


class STARTUPINFOEX(C.Structure):
    _fields_=[('startup',STARTUPINFO),('attributes',C.c_void_p)]


class PROCESS_INFORMATION(C.Structure):
    _fields_=[('process',HANDLE),('thread',HANDLE),('pid',DWORD),('tid',DWORD)]


class FILETIME(C.Structure):
    _fields_=[('low',DWORD),('high',DWORD)]


class OVERLAPPED(C.Structure):
    _fields_=[('internal',ULONG_PTR),('internal_high',ULONG_PTR),('offset',DWORD),
              ('offset_high',DWORD),('event',HANDLE)]


def require_native():
    if sys.platform!='win32' or sys.getwindowsversion().major<10:
        raise OSError('Native Windows 10 or newer is required')


def kernel():
    require_native()
    lib=C.WinDLL('kernel32',use_last_error=True)
    definitions={
        'CreateJobObjectW':([C.c_void_p,C.c_wchar_p],HANDLE),
        'SetInformationJobObject':([HANDLE,C.c_int,C.c_void_p,DWORD],BOOL),
        'TerminateJobObject':([HANDLE,C.c_uint],BOOL),
        'CloseHandle':([HANDLE],BOOL),
        'GetCurrentProcess':([],HANDLE),
        'GetStdHandle':([DWORD],HANDLE),
        'DuplicateHandle':([HANDLE,HANDLE,HANDLE,C.POINTER(HANDLE),DWORD,BOOL,DWORD],BOOL),
        'InitializeProcThreadAttributeList':([C.c_void_p,DWORD,DWORD,C.POINTER(SIZE_T)],BOOL),
        'UpdateProcThreadAttribute':([C.c_void_p,DWORD,SIZE_T,C.c_void_p,SIZE_T,C.c_void_p,C.c_void_p],BOOL),
        'DeleteProcThreadAttributeList':([C.c_void_p],None),
        'CreateProcessW':([C.c_wchar_p,C.c_wchar_p,C.c_void_p,C.c_void_p,BOOL,DWORD,C.c_void_p,
                           C.c_wchar_p,C.POINTER(STARTUPINFOEX),C.POINTER(PROCESS_INFORMATION)],BOOL),
        'WaitForSingleObject':([HANDLE,DWORD],DWORD),
        'GetExitCodeProcess':([HANDLE,C.POINTER(DWORD)],BOOL),
        'OpenProcess':([DWORD,BOOL,DWORD],HANDLE),
        'GetProcessTimes':([HANDLE,*[C.POINTER(FILETIME)]*4],BOOL),
        'QueryFullProcessImageNameW':([HANDLE,DWORD,C.c_wchar_p,C.POINTER(DWORD)],BOOL),
        'LockFileEx':([HANDLE,DWORD,DWORD,DWORD,DWORD,C.POINTER(OVERLAPPED)],BOOL),
    }
    for name,(arguments,result) in definitions.items():
        function=getattr(lib,name);function.argtypes=arguments;function.restype=result
    return lib


def checked(value):
    if not value:raise C.WinError(C.get_last_error())
    return value


def command_line(command):
    if not isinstance(command,(list,tuple)) or not command:
        raise ValueError('Windows workers require an argument list, not a shell command')
    args=[os.fspath(arg) for arg in command]
    if any(not isinstance(arg,str) or '\x00' in arg for arg in args):
        raise ValueError('Worker arguments must be Unicode strings without NUL')
    executable=shutil.which(args[0])
    if not executable or Path(executable).suffix.lower() not in ('.exe','.com'):
        raise ValueError('Configure a native Windows executable; shell and batch launchers are not supported')
    return args,str(Path(executable).resolve()),subprocess.list2cmdline(args)


def environment_block(env):
    if env is None:return None
    values={}
    for name,value in env.items():
        if (not isinstance(name,str) or not name or '=' in name or '\x00' in name
                or not isinstance(value,str) or '\x00' in value or name.upper() in values):
            raise ValueError('Invalid or duplicate Windows environment entry')
        values[name.upper()]=(name,value)
    return C.create_unicode_buffer('\x00'.join(k+'='+v for k,v in sorted(values.values(),key=lambda item:item[0].upper()))+'\x00\x00')


class Process:
    """The process/pipe operations used by Relay; closing its job stops descendants."""
    def __init__(self,lib,info,job,args,streams):
        self._lib=lib;self._handle=info.process;self._job=job
        self.pid=info.pid;self.args=args;self.returncode=None
        self.stdin,self.stdout,self.stderr=streams

    def poll(self):
        if self.returncode is not None:return self.returncode
        result=self._lib.WaitForSingleObject(self._handle,0)
        if result==WAIT_TIMEOUT:return None
        if result!=0:raise C.WinError(C.get_last_error())
        code=DWORD();checked(self._lib.GetExitCodeProcess(self._handle,C.byref(code)))
        self.returncode=code.value
        return self.returncode

    def wait(self,timeout=None):
        if self.returncode is not None:return self.returncode
        if timeout is not None and (not math.isfinite(timeout) or timeout<0):
            raise ValueError('Invalid process timeout')
        milliseconds=INFINITE if timeout is None else min(math.ceil(timeout*1000),INFINITE-1)
        result=self._lib.WaitForSingleObject(self._handle,milliseconds)
        if result==WAIT_TIMEOUT:raise subprocess.TimeoutExpired(self.args,timeout)
        if result!=0:raise C.WinError(C.get_last_error())
        return self.poll()

    def terminate(self):
        if self._job:checked(self._lib.TerminateJobObject(self._job,1))

    kill=terminate

    def close(self):
        # Closing every resource must still happen if a pipe flush fails.
        with ExitStack() as cleanup:
            if self._handle:
                handle=self._handle;self._handle=None
                cleanup.callback(lambda:checked(self._lib.CloseHandle(handle)))
            if self._job:
                job=self._job;self._job=None
                cleanup.callback(lambda:checked(self._lib.CloseHandle(job)))
            for stream in (self.stdin,self.stdout,self.stderr):
                if stream is not None:cleanup.callback(stream.close)

    def __del__(self):
        try:self.close()
        except (OSError,ValueError):pass


def spawn(command,*,stdin=None,stdout=None,stderr=None,cwd=None,env=None,
          text=False,encoding=None,errors=None,bufsize=-1,**kwargs):
    require_native()
    if kwargs:raise ValueError('Unsupported Windows process options: '+', '.join(sorted(kwargs)))
    args,executable,line=command_line(command)
    block=environment_block(env)
    import msvcrt
    lib=kernel();job=checked(lib.CreateJobObjectW(None,None))
    info=PROCESS_INFORMATION();parent_streams=[None,None,None]
    try:
        limits=EXTENDED_LIMITS();limits.basic.flags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        checked(lib.SetInformationJobObject(job,9,C.byref(limits),C.sizeof(limits)))
        with ExitStack() as resources:
            handles=[]
            for index,value in enumerate((stdin,stdout,stderr)):
                if value==subprocess.STDOUT:
                    if index!=2:raise ValueError('STDOUT redirection is valid only for stderr')
                    handles.append(handles[1]);continue
                if value==subprocess.PIPE:
                    read_fd,write_fd=os.pipe()
                    child_fd,parent_fd=(read_fd,write_fd) if index==0 else (write_fd,read_fd)
                    resources.callback(os.close,child_fd)
                    try:
                        stream=os.fdopen(parent_fd,'wb' if index==0 else 'rb',buffering=bufsize)
                    except BaseException:
                        os.close(parent_fd);raise
                    parent_streams[index]=stream
                    if text or encoding or errors:
                        parent_streams[index]=io.TextIOWrapper(stream,encoding=encoding or 'utf-8',errors=errors or 'strict')
                    handle=msvcrt.get_osfhandle(child_fd)
                elif value==subprocess.DEVNULL or value is None:
                    handle=lib.GetStdHandle(DWORD((-10,-11,-12)[index]).value) if value is None else None
                    if not handle or handle==C.c_void_p(-1).value:
                        fd=os.open(os.devnull,(os.O_RDONLY if index==0 else os.O_WRONLY)|os.O_BINARY)
                        resources.callback(os.close,fd);handle=msvcrt.get_osfhandle(fd)
                else:
                    handle=msvcrt.get_osfhandle(value if isinstance(value,int) else value.fileno())
                duplicate=HANDLE()
                checked(lib.DuplicateHandle(lib.GetCurrentProcess(),handle,lib.GetCurrentProcess(),C.byref(duplicate),0,True,2))
                resources.callback(lib.CloseHandle,duplicate.value);handles.append(duplicate.value)
            size=SIZE_T()
            lib.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
            attributes=C.create_string_buffer(size.value)
            checked(lib.InitializeProcThreadAttributeList(attributes,2,0,C.byref(size)))
            resources.callback(lib.DeleteProcThreadAttributeList,attributes)
            jobs=(HANDLE*1)(job);inherited=(HANDLE*len(set(handles)))(*set(handles))
            checked(lib.UpdateProcThreadAttribute(attributes,0,PROC_THREAD_ATTRIBUTE_JOB_LIST,jobs,C.sizeof(jobs),None,None))
            checked(lib.UpdateProcThreadAttribute(attributes,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,inherited,C.sizeof(inherited),None,None))
            startup=STARTUPINFOEX();startup.startup.cb=C.sizeof(startup)
            startup.startup.flags=0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin,startup.startup.stdout,startup.startup.stderr=handles
            startup.attributes=C.cast(attributes,C.c_void_p)
            # Job membership is atomic with creation; there is no suspended orphan window.
            checked(lib.CreateProcessW(executable,C.create_unicode_buffer(line),None,None,True,
                0x00080000|0x00000400|0x08000000,block,os.fspath(cwd) if cwd is not None else None,
                C.byref(startup),C.byref(info)))
            checked(lib.CloseHandle(info.thread));info.thread=None
        return Process(lib,info,job,args,parent_streams)
    except BaseException:
        lib.CloseHandle(job)  # Kills a child if creation succeeded before later setup failed.
        if info.thread:lib.CloseHandle(info.thread)
        if info.process:lib.CloseHandle(info.process)
        for stream in parent_streams:
            if stream is not None:stream.close()
        raise


def identity(pid):
    if type(pid) is not int or pid<2:return None
    lib=kernel();handle=lib.OpenProcess(0x1000|0x00100000,False,pid)
    if not handle:
        error=C.get_last_error()
        if error==87:return None  # The process no longer exists.
        raise C.WinError(error)
    try:
        state=lib.WaitForSingleObject(handle,0)
        if state==0:return None
        if state!=WAIT_TIMEOUT:raise C.WinError(C.get_last_error())
        times=[FILETIME() for _ in range(4)]
        checked(lib.GetProcessTimes(handle,*[C.byref(t) for t in times]))
        size=DWORD(32768);name=C.create_unicode_buffer(size.value)
        checked(lib.QueryFullProcessImageNameW(handle,0,name,C.byref(size)))
        return {'pid':pid,'created':(times[0].high<<32)|times[0].low,'executable':name.value.casefold()}
    finally:lib.CloseHandle(handle)


def matches(pid,expected):
    if not isinstance(expected,dict) or set(expected)!={'pid','created','executable'} or expected['pid']!=pid:
        return False
    return identity(pid)==expected


def lock(stream):
    import msvcrt
    lib=kernel();overlapped=OVERLAPPED()
    if not lib.LockFileEx(msvcrt.get_osfhandle(stream.fileno()),3,0,1,0,C.byref(overlapped)):
        error=C.get_last_error()
        if error==33:raise BlockingIOError('Another process owns this Relay lock')
        raise C.WinError(error)
