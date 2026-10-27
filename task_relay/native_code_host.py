"""Native code isolation. Unsupported hosts never fall back to unrestricted Python."""
import hashlib
import json
import os
from pathlib import Path
import sys
import sysconfig
import time
import subprocess
import stat


def identity():
    from .host import HOST
    if HOST.platform!='darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise ValueError('Native code isolation is currently available on macOS. Windows code isolation and file-grant qualification are pending.')
    python=Path(sys.executable).resolve()
    # python.org framework's bin/python is a posix_spawn launcher. Run its real
    # interpreter directly so the sandbox can prohibit all child processes.
    framework=Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python'
    if framework.is_file():python=framework.resolve()
    roots={str(Path(sysconfig.get_path(k)).resolve()) for k in ('stdlib','platstdlib','purelib','platlib')}
    # Framework binaries and shared runtime libraries, not the whole user profile.
    roots.add(str(Path(sys.base_prefix).resolve()))
    from importlib.metadata import distributions
    # Standalone workers may prepend the same package root already on sys.path.
    # Repeated discovery of identical metadata is not a runtime change; distinct
    # installed versions still produce distinct entries in the identity.
    libraries=[list(v) for v in sorted({(d.metadata.get('Name',''),d.version) for d in distributions()})]
    return {'adapter':'macos-seatbelt-v1','python':str(python),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),
            'read_roots':sorted(roots),'version':sys.version.split()[0],
            'libraries':libraries,
            'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def pin(destination):
    """Retain the complete relocatable Python tree before prospective admission."""
    from . import runtime_snapshot,runtime_process
    current=identity();base=Path(sys.base_prefix).resolve()
    if any(not Path(p).is_relative_to(base) for p in [current['python'],*current['read_roots']]):
        raise ValueError('Native runtime is not self-contained; cannot pin it')
    receipt=runtime_snapshot.capture(base,destination)
    python=Path(receipt['root'])/Path(current['python']).relative_to(base)
    package=str(Path(__file__).resolve().parents[1])
    code='import sys,json;sys.path.insert(0,'+repr(package)+');from task_relay.native_code_host import identity;print(json.dumps(identity()))'
    result=subprocess.run(runtime_process.command(python,'-c',code,isolated=True),env=runtime_process.environment(),capture_output=True,text=True,timeout=30,check=True)
    runtime=json.loads(result.stdout)
    if runtime['libraries']!=current['libraries'] or runtime['python_sha256']!=current['python_sha256']:
        raise ValueError('Relocated runtime differs from source')
    if any(not Path(p).is_relative_to(Path(receipt['root'])) for p in [runtime['python'],*runtime['read_roots']]):
        raise ValueError('Relocated runtime still reads outside its snapshot')
    runtime['snapshot']=receipt
    runtime['process_policy_sha256']=runtime_snapshot.sha(runtime_process.__file__)
    verify(runtime);return runtime


def verify(runtime):
    if 'snapshot' not in runtime:
        if runtime!=identity():raise ValueError('Native Python runtime changed; check tools again before execution.')
        return
    from . import runtime_snapshot,runtime_process
    root=runtime_snapshot.verify(runtime['snapshot'])
    if runtime['snapshot'].get('version')==2 and runtime.get('process_policy_sha256')!=runtime_snapshot.sha(runtime_process.__file__):
        raise ValueError('Pinned runtime process policy changed')
    if (runtime.get('adapter')!='macos-seatbelt-v1'
        or runtime['adapter_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or any(not Path(p).resolve().is_relative_to(root) for p in [runtime['python'],*runtime['read_roots']])
        or runtime['python_sha256']!=runtime_snapshot.sha(runtime['python'])):
        raise ValueError('Pinned native runtime identity changed')


def profile(runtime,inputs,outputs,program,bootstrap):
    def literal(path):return json.dumps(str(Path(path).resolve()),ensure_ascii=False)
    reads=[*runtime['read_roots'],'/System/Library','/usr/lib','/usr/share/zoneinfo',str(inputs)]
    return ('(version 1)\n(deny default)\n(allow file-read-metadata)\n(allow sysctl-read)\n'
            '(allow process-exec (literal '+literal(runtime['python'])+'))\n'
            '(allow file-read* '+''.join('(subpath '+literal(p)+')' for p in reads)+
            '(literal '+literal(program)+')(literal '+literal(bootstrap)+')(literal '+literal(runtime['python'])+')'
            '(literal "/")(literal "/dev/null")(literal "/dev/urandom")(literal "/dev/random"))\n'
            '(allow file-read* file-write* (subpath '+literal(outputs)+'))\n'
            '(allow file-write* (literal "/dev/null"))\n')


def run(runtime,folder,code,seconds,maximum,cancelled=lambda:False):
    from . import runtime_process
    verify(runtime)
    folder=Path(folder).resolve();inputs=folder/'inputs';outputs=folder/'outputs';outputs.mkdir()
    program=folder/'program.py'
    program.write_text(code,encoding='utf-8')
    bootstrap=folder/'bootstrap.py'
    bootstrap.write_text('import resource\nresource.setrlimit(resource.RLIMIT_CPU,('+str(seconds)+','+str(seconds)+'))\n'
        'resource.setrlimit(resource.RLIMIT_FSIZE,('+str(maximum)+','+str(maximum)+'))\n'
        # Document libraries need standard MIME defaults, not the host's Apache
        # configuration files (which remain outside their read grant).
        'import mimetypes\nmimetypes.knownfiles=[]\nmimetypes.init(files=[])\n'
        'import runpy\nrunpy.run_path('+repr(str(program))+',run_name="__main__")\n',encoding='utf-8')
    policy=folder/'sandbox.sb';policy.write_text(profile(runtime,inputs,outputs,program,bootstrap),encoding='utf-8')
    env={'PATH':'/usr/bin:/bin','HOME':str(outputs),'TMPDIR':str(outputs),'PYTHONDONTWRITEBYTECODE':'1',
         'RELAY_INPUTS':str(inputs),'RELAY_OUTPUTS':str(outputs),'LANG':'en_US.UTF-8'}
    env=runtime_process.environment(env)
    command=['/usr/bin/sandbox-exec','-f',str(policy),*runtime_process.command(runtime['python'],bootstrap,isolated=True)]
    log=outputs/'runtime.log'
    spec=folder/'guard.json'
    spec.write_text(json.dumps(dict(command=command,outputs=str(outputs),env=env,seconds=seconds,maximum=maximum)))
    # This trusted guardian owns the sandboxed child directly. Its stdin is a
    # lifetime pipe: even SIGKILL of the API worker closes it and kills the child.
    # It is outside the API supervisor's process group, carries no credentials,
    # and never passes the lifetime pipe into generated code.
    process=subprocess.Popen(runtime_process.command(runtime['python'],Path(__file__).resolve(),spec,isolated=True),
        env=env,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=True,close_fds=True)
    try:
        while process.poll() is None:
            if cancelled():raise ValueError('Code task cancelled.')
            time.sleep(.05)
    finally:
        process.stdin.close()
        process.wait(timeout=10)
    outcome=json.loads((folder/'guard-outcome.json').read_text())
    if outcome.get('error'):raise ValueError(outcome['error'])
    # Generated code can replace its own output files. Never follow a substituted
    # log symlink/FIFO/hard link into the host when returning diagnostics.
    fd=os.open(log,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Code log is not an owned regular file.')
        text=stream.read(12000).decode('utf-8','replace')
    return {'returncode':outcome['returncode'],'log':text,'outputs':str(outputs)}


def guard(spec):
    """Trusted standalone supervisor; no project imports or generated-code eval."""
    import select
    value=json.loads(spec.read_text());outputs=Path(value['outputs']);log=outputs/'runtime.log'
    result={};process=None
    try:
        with log.open('wb') as stream:
            process=subprocess.Popen(value['command'],cwd=outputs,env=value['env'],stdin=subprocess.DEVNULL,
                                     stdout=stream,stderr=stream,close_fds=True)
            start=time.monotonic()
            while process.poll() is None:
                readable,_,_=select.select([sys.stdin.buffer],[],[],.05)
                if readable and not os.read(sys.stdin.fileno(),1):raise ValueError('Code owner exited or cancelled.')
                if time.monotonic()-start>value['seconds']+2:raise ValueError('Code task time limit reached.')
                if log.stat().st_size>min(value['maximum'],1000000):raise ValueError('Code log byte limit reached.')
                total=0
                for root,dirs,files in os.walk(outputs,followlinks=False):
                    for name in files:total+=(Path(root)/name).lstat().st_size
                    if total>value['maximum']:raise ValueError('Code output byte budget exceeded.')
            result={'returncode':process.returncode}
    except Exception as exc:result={'error':str(exc)}
    finally:
        # No fork/spawn is permitted inside Seatbelt. Kill the owned child by
        # handle even if generated code changes its process group/session.
        if process is not None:
            if process.poll() is None:process.kill()
            process.wait()
        temporary=spec.with_name('guard-outcome.tmp');temporary.write_text(json.dumps(result))
        temporary.replace(spec.with_name('guard-outcome.json'))


if __name__=='__main__':guard(Path(sys.argv[1]))
