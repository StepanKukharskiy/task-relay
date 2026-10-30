"""Structured local job authoring. Use `author commands` to discover its contract."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
from . import __version__
from .management import Arguments, install_skill, paths

LIMIT=600000
SKILL=Path(__file__).parent/'assets/skills/relay-author'


def decode(raw):
    if len(raw)>LIMIT:raise ValueError('Authoring request exceeds 600000 bytes')
    def invalid(value):raise ValueError('JSON numbers must be finite')
    value=json.loads(raw,parse_constant=invalid) if raw else {}
    if not isinstance(value,dict):raise ValueError('Authoring input must be an object')
    return value


def worker(action):
    """Fresh process binds every shared service to the explicitly resolved paths."""
    from .authoring import dispatch
    try:
        value=decode(sys.stdin.buffer.read(LIMIT+1))
        with contextlib.redirect_stdout(sys.stderr):result=dispatch(action,value)
        reply=dict(protocol=1,version=__version__,ok=True,action=action,result=result)
    except (ValueError,KeyError,TypeError) as exc:
        reply=dict(protocol=1,version=__version__,ok=False,action=action,error=dict(code=type(exc).__name__,message=str(exc)[:800]))
    except Exception:
        reply=dict(protocol=1,version=__version__,ok=False,action=action,error=dict(code='AuthoringError',message='Authoring could not finish. Preserve the request ID and inspect the job before retrying.'))
    print(json.dumps(reply,ensure_ascii=False));return 0 if reply['ok'] else 2


def main(argv=None):
    action=None
    try:
        parser=Arguments(description=__doc__)
        parser.add_argument('action',help='commands, jobs, open, operations, operation, schema, edit-preview, edit-save, files, file-import, setup, run-preview, run-start, run-status, templates, template, skill, skill-install')
        parser.add_argument('--input',help='JSON file, or - for stdin; omitted means {}')
        parser.add_argument('--destination',help='Destination folder for skill-install only')
        args=parser.parse_args(argv);action=args.action
        if args.destination and action!='skill-install':raise ValueError('--destination belongs to skill-install')
        if action in ('skill','skill-install'):
            if args.input:raise ValueError('Skill commands do not take JSON input')
            if action=='skill-install':
                if not args.destination:raise ValueError('Supply --destination for skill-install')
                result=install_skill(args.destination,source=SKILL)
            else:result=dict(name='relay-author',path=str(SKILL),auto_installed=False)
            print(json.dumps(dict(protocol=1,version=__version__,ok=True,action=action,result=result)));return 0
        if args.input=='-':raw=sys.stdin.buffer.read(LIMIT+1)
        elif args.input:
            with Path(args.input).expanduser().open('rb') as stream:raw=stream.read(LIMIT+1)
        else:raw=b'{}'
        value=decode(raw)
        env={**os.environ,**paths().environment()}
        code='import sys;sys.path.insert(0,sys.argv.pop(1));from task_relay.author_cli import worker;raise SystemExit(worker(sys.argv[1]))'
        # No timeout retries: a lost response may follow a committed mutation.
        child=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parent.parent),action],
            input=json.dumps(value).encode(),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        reply=json.loads(child.stdout)
        if reply.get('protocol')!=1 or reply.get('action')!=action:raise ValueError('Unexpected authoring response; inspect the saved job before retrying')
        print(json.dumps(reply,ensure_ascii=False));return 0 if reply['ok'] else 2
    except Exception as exc:
        message=str(exc)[:800] if isinstance(exc,ValueError) else 'Could not read the request or invoke Relay. Preserve request IDs; inspect before retrying.'
        print(json.dumps(dict(protocol=1,version=__version__,ok=False,action=action,error=dict(code=type(exc).__name__,message=message))));return 2


if __name__=='__main__':raise SystemExit(main())
