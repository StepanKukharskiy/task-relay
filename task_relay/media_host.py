"""Fixed local media commands, independent of model providers. macOS adapter v1.

Trusted adapters run generated templates or authored front-end projects, never arbitrary agent commands.
An isolated guardian owns every CLI invocation and watches its owner's pipe.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

VERSION='0.8.46'
KEYS=('node','hyperframes','browser','ffmpeg','ffprobe','font')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def config_path():
    from .relay_paths import PATHS
    return PATHS.data/'media-runtime.json'


def identity(paths):
    from .host import HOST
    if HOST.platform!='darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise ValueError('Local HyperFrames execution currently requires the macOS rendering adapter.')
    if set(paths)!=set(KEYS):raise ValueError('Configure exact local media runtime paths: '+', '.join(KEYS))
    paths={k:str(Path(v).expanduser().resolve(strict=True)) for k,v in paths.items()}
    for k,p in paths.items():
        if not Path(p).is_file():raise ValueError('Media runtime file missing: '+k)
    package=Path(paths['hyperframes']).parent.parent
    if json.loads((package/'package.json').read_text()).get('version')!=VERSION:
        raise ValueError('This media adapter requires qualified HyperFrames '+VERSION)
    files={k:digest(p) for k,p in paths.items()}
    # The CLI is bundled; pin its project runtime and render workers as well.
    files['hyperframes_bundle']=hashlib.sha256(json.dumps([(str(p.relative_to(package)),digest(p))
        for p in sorted((package/'dist').rglob('*')) if p.is_file()],separators=(',',':')).encode()).hexdigest()
    return dict(adapter='macos-hyperframes-v1',version=VERSION,paths=paths,sha256=files)


def available(feature='template'):
    try:
        saved=json.loads(config_path().read_text())
        current=identity(saved['runtime']['paths'])
        if saved.get('qualified') is not True or current!=saved['runtime'] or saved.get('implementation')!=implementation():
            raise ValueError('Media runtime changed or is not qualified; run the local media qualification again.')
        if feature=='project' and saved.get('project_qualified') is not True:
            raise ValueError('Full HyperFrames project execution needs its separate preview/render qualification.')
        return current
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('Local reel renderer is not configured and qualified; see docs/reels.md.') from exc


def implementation():
    from orchestrator import reel_document,reel_contract,hyperframes_project,hyperframes_contract
    return {Path(m.__file__).name:digest(m.__file__) for m in (sys.modules[__name__],reel_document,reel_contract,hyperframes_project,hyperframes_contract)}


def environment(runtime,folder):
    folder=Path(folder);home=folder/'home';home.mkdir(exist_ok=True)
    tmp=folder/'tmp';tmp.mkdir(exist_ok=True)
    return {'PATH':':'.join(dict.fromkeys([str(Path(runtime['paths'][k]).parent) for k in ('node','ffmpeg','ffprobe')]+['/usr/bin','/bin'])),
        'HOME':str(home),'CFFIXED_USER_HOME':str(home),'TMPDIR':str(tmp),'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
        'HYPERFRAMES_BROWSER_PATH':runtime['paths']['browser'],'PRODUCER_HEADLESS_SHELL_PATH':runtime['paths']['browser'],
        'HYPERFRAMES_NO_TELEMETRY':'1','DO_NOT_TRACK':'1','CI':'1','NO_COLOR':'1',
        'PRODUCER_LOW_MEMORY_MODE':'1','PRODUCER_EXPERIMENTAL_FAST_CAPTURE':'false'}


def run(runtime,folder,command,cwd,seconds,maximum,cancelled=lambda:False,output_root=None,isolated=False):
    """Only trusted adapter callers construct command; no shell or inherited secrets."""
    folder=Path(folder);folder.mkdir()
    policy=folder/'network.sb'
    policy.write_text('(version 1)\n(allow default)\n(deny network*)\n'
        '(allow network* (local ip "localhost:*") (remote ip "localhost:*"))\n'
        '(allow network* (local unix-socket) (remote unix-socket))\n')
    spec=folder/'guard.json'
    spec.write_text(json.dumps(dict(command=['/usr/bin/sandbox-exec','-f',str(policy),*command],
        cwd=str(cwd),output_root=str(output_root) if output_root else None,runtime=runtime,isolated=isolated,
        env=environment(runtime,folder),seconds=max(.1,seconds),maximum=maximum)))
    process=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),str(spec)],
        stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        env=environment(runtime,folder),start_new_session=True,close_fds=True)
    try:
        while process.poll() is None:
            if cancelled():raise ValueError('Media operation cancelled.')
            time.sleep(.05)
    finally:
        process.stdin.close()
        process.wait(timeout=15)
    result=json.loads((folder/'outcome.json').read_text())
    if result.get('error'):raise ValueError(result['error'])
    if result['returncode']!=0:
        tail=(folder/'command.log').read_bytes()[-6000:].decode('utf-8','replace')
        raise ValueError('Local media command failed ('+str(result['returncode'])+'): '+tail)
    return (folder/'command.log').read_text(errors='replace')


def descendants(root):
    """Capture detached Chromium descendants as well as the CLI process group."""
    rows=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,lstart='],text=True,timeout=2)
    entries=[line.split(maxsplit=2) for line in rows.splitlines()]
    parents={int(p):int(parent) for p,parent,_ in entries};birth={int(p):started for p,_,started in entries}
    owned={root}
    while True:
        new={p for p,parent in parents.items() if parent in owned}
        if new<=owned:return {p:birth[p] for p in owned if p in birth}
        owned|=new


def guard(spec):
    import select
    import tempfile
    value=json.loads(spec.read_text());folder=spec.parent;process=None;result={};owned={}
    # Chromium singleton sockets cannot use arbitrarily long workspace paths.
    temporary_runtime=tempfile.TemporaryDirectory(prefix='relay-media-',dir='/private/tmp')
    value['env']['TMPDIR']=temporary_runtime.name
    if value.get('isolated'):
        policy=folder/'network.sb'
        policy.write_text(policy.read_text()+file_policy(value['runtime'],value['cwd'],value.get('output_root'),temporary_runtime.name))
    try:
        with (folder/'command.log').open('xb') as log:
            process=subprocess.Popen(value['command'],cwd=value['cwd'],env=value['env'],stdin=subprocess.DEVNULL,
                stdout=log,stderr=log,close_fds=True,start_new_session=True)
            start=time.monotonic()
            while process.poll() is None:
                owned.update(descendants(process.pid))
                ready,_,_=select.select([sys.stdin.buffer],[],[],.15)
                if ready and not os.read(sys.stdin.fileno(),1):raise ValueError('Media owner exited or cancelled; partial output is unapproved.')
                if time.monotonic()-start>value['seconds']:raise ValueError('Media command exceeded the remaining task deadline.')
                if (folder/'command.log').stat().st_size>2000000:raise ValueError('Media command log limit exceeded.')
                size=0
                for base in filter(None,(value['cwd'],value.get('output_root'),temporary_runtime.name)):
                    for root,dirs,files in os.walk(base,followlinks=False):
                        for name in files:
                            try:size+=(Path(root)/name).lstat().st_size
                            except FileNotFoundError:pass  # Chrome removes temporary files concurrently.
                        if size>value['maximum']:raise ValueError('Media working-file limit exceeded.')
            result={'returncode':process.returncode}
    except Exception as exc:result={'error':str(exc)}
    finally:
        if process is not None:
            # Stop descendants first, including Chrome's separate process group.
            current=descendants(1)
            for pid,started in owned.items():
                if pid==process.pid or current.get(pid)!=started:continue
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
        target=folder/'outcome.json';temporary=folder/'outcome.tmp'
        temporary.write_text(json.dumps(result));temporary.replace(target)
        temporary_runtime.cleanup()


def file_policy(runtime,work,output,tmp):
    """Front-end projects may read staged data and installed runtimes, not the home directory."""
    paths=runtime['paths'];browser=Path(paths['browser'])
    browser_root=next((p for p in browser.parents if p.suffix=='.app'),browser.parent)
    reads=['/System','/usr','/bin','/sbin','/Library/Apple','/Library/Preferences','/opt/homebrew/Cellar','/opt/homebrew/lib',
        '/private/var/db/dyld','/private/preboot','/private/etc/hosts','/private/etc/localtime','/private/etc/resolv.conf','/dev',
        str(Path(paths['node']).parent.parent),str(Path(paths['hyperframes']).parent.parent.parent),str(browser_root)]
    writes=list(dict.fromkeys(str(Path(p).resolve()) for p in (work,output,tmp) if p))
    def roots(values):return ' '.join('(subpath '+json.dumps(str(p))+')' for p in values)
    # macOS Chromium places its singleton socket in the OS temp directory even
    # with an explicit userDataDir/TMPDIR. Grant only that application's namespace.
    os_tmp=str(Path(subprocess.check_output(['/usr/bin/getconf','DARWIN_USER_TEMP_DIR'],text=True).strip()).resolve())
    import re
    socket_scope='(regex #'+json.dumps('^'+re.escape(os_tmp)+'/com[.]google[.](Chrome|chrome[.]for[.]testing)[.][^/]+(/.*)?$')+')'
    return ('\n(deny file-read-data (require-not (require-any (literal "/") '+socket_scope+' '+roots(reads+writes)+')))\n'
        '(deny file-write* (require-not (require-any (literal "/dev/null") '+socket_scope+' '+roots(writes)+')))\n')


if __name__=='__main__':guard(Path(sys.argv[1]))
