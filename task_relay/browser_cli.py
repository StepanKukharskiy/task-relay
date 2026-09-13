"""Prepare general browser work, sign in locally and inspect recovery receipts."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing

from orchestrator import contracts as c,executors
from orchestrator.browser_contract import origin,validate
from orchestrator.runtime import Runtime
from .browser_journal import Journal
from .general_browser import browser,profile_lock
from .relay_paths import PATHS


def prepare(runtime,ident,request,backend,policy):
    """Register the exact request and return a plan; no model/browser dispatch."""
    validate(policy);c.label(ident);executors.validate(backend)
    if backend['type'] not in executors.BROWSER_TYPES:raise ValueError('Select the browser executor')
    if policy['uploads'] or policy['downloads']:raise ValueError('Use an authored graph with registered artifacts for file transfers')
    raw=Path(request).read_bytes()
    if len(raw)>24000:raise ValueError('Request exceeds 24000 bytes')
    c.nonempty(raw.decode('utf-8'),'exact user request')
    with runtime.transaction():artifact=runtime.register(request,'Exact browser request')
    inputs=[{'artifact':artifact,'path':'request.txt','purpose':'Exact user request','authority':'User instruction; retain its scope and decision boundaries'}]
    criteria=['Matches the exact request without expanding its authorization',
              'Cites observed URLs and distinguishes actions from verified remote results',
              'Reports incomplete or uncertain work without retrying it']
    producer=dict(id='produce',role='browser worker',objective='Complete the exact website request',
        instruction='Read request.txt. Complete only its authorized work. Write report.md with evidence, outcomes and remaining blockers.',
        inputs=inputs,outputs=[{'path':'report.md','purpose':'Observed browser work and evidence'}],dependencies=[],
        criteria=criteria,tools=['files','browser'],limits=executors.GEMINI_LIMITS.copy(),max_attempts=1,browser=policy)
    reviewer=dict(id='review',role='independent reviewer',review_of='produce',objective='Check the browser work against the request',
        instruction='Inspect the report and available pages without repeating website interactions. Unverifiable results stay unverified.',
        inputs=inputs+[{'from_task':'produce','output':'report.md','path':'candidate/report.md','purpose':'Candidate to inspect','authority':'Worker report, not user acceptance'}],
        outputs=[{'path':'review.md','purpose':'Independent findings'}],dependencies=['produce'],criteria=criteria,
        tools=['files','browser'],limits=executors.GEMINI_LIMITS.copy(),max_attempts=1,
        browser={**policy,'interaction_scope':'','uploads':[],'downloads':[]})
    return c.plan(dict(id=ident,brief='General browser work: '+ident,backend=backend,concurrency=1,tasks=[producer,reviewer]))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for name in ('login','inspect'):
        p=sub.add_parser(name);p.add_argument('--profile',required=True);p.add_argument('--url',required=True)
        p.add_argument('--origin',action='append',default=[],help='Additional exact origins, for example an explicitly selected sign-in provider')
    p=sub.add_parser('status');p.add_argument('--profile',required=True);p.add_argument('--job')
    p=sub.add_parser('resolve');p.add_argument('--profile',required=True);p.add_argument('--job',required=True)
    p.add_argument('--action-id',required=True);p.add_argument('--outcome',choices=['occurred','not_occurred'],required=True);p.add_argument('--note',required=True)
    p=sub.add_parser('prepare');p.add_argument('--profile',required=True);p.add_argument('--origin',action='append',required=True)
    p.add_argument('--interaction-scope',default='');p.add_argument('--request-file',type=Path,required=True)
    p.add_argument('--id',required=True);p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--provider',choices=['gemini','openai','qwen'],default='gemini')
    p.add_argument('--root',type=Path,default=PATHS.runtime)
    args=parser.parse_args(argv);os.umask(0o077)
    try:
        c.label(args.profile)
        if args.action=='prepare':
            if args.out.exists():raise ValueError('Plan output already exists; preserve the reviewed version')
            policy=dict(profile=args.profile,origins=args.origin,interaction_scope=args.interaction_scope,
                        max_tabs=3,max_actions=20,uploads=[],downloads=[])
            runtime=Runtime(args.root)
            try:plan=prepare(runtime,args.id,args.request_file,{'type':args.provider+'-browser','model':args.model},policy)
            finally:runtime.db.close()
            with args.out.open('x') as f:json.dump(plan,f,ensure_ascii=False,indent=2)
            result={'plan':str(args.out.resolve()),'status':'prepared; inspect before create/run','workers_started':False}
        elif args.action in ('login','inspect'):
            policy=dict(profile=args.profile,origins=list(dict.fromkeys([origin(args.url),*args.origin])),interaction_scope='Human sign-in only' if args.action=='login' else '',
                        max_tabs=1,max_actions=1,uploads=[],downloads=[])
            with browser(PATHS.data,policy) as driver:
                driver.open('manual',args.url)
                if args.action=='login':
                    input('Sign in yourself in this dedicated browser, then press Enter here to save the session. ')
                    result={'profile':args.profile,'status':'session saved; authentication not independently verified'}
                else:
                    result,_=driver.snapshot('manual')
                    result['limitation']='Fresh read-only observation; no prior action resolved or replayed'
        else:
            PATHS.data.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(PATHS.state,timeout=30)) as db:
                journal=Journal(db)
                if args.action=='resolve':
                    with profile_lock(PATHS.data,args.profile):journal.resolve(args.profile,args.job,args.action_id,args.outcome,args.note)
                actions=[dict(r) for r in db.execute('SELECT * FROM general_browser_actions WHERE profile=? ORDER BY created,job,id',(args.profile,))
                         if not args.job or r['job']==args.job]
                result={'profile':args.profile,'actions':actions,'unresolved':journal.pending(args.profile),
                        'tabs':journal.tabs(args.profile),'note':'Stored tab IDs are evidence; this command has no attached live tabs'}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except EOFError:parser.exit(2,'Sign-in was not confirmed; no task was submitted.\n')
    except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':main()
