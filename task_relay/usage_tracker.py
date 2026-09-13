"""Local, metadata-only usage ledger. No provider requests or billing estimates.

Run: python3 usage_tracker.py --refresh --days 7 [--json]
Imports recorded Relay usage and bounded chunks of local session logs. Repeat
--refresh to finish a large initial backfill. Unknown usage remains unknown.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from task_relay.relay_paths import PATHS

FIELDS=('input_tokens','cached_input_tokens','cache_write_tokens','output_tokens','reasoning_tokens','total_tokens')


def initialize(db):
    for statement in '''CREATE TABLE IF NOT EXISTS usage_events (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, provider TEXT NOT NULL, model TEXT,
      project TEXT, session_id TEXT, occurred REAL, counts TEXT NOT NULL,
      cost_usd REAL, cost_kind TEXT, observed REAL NOT NULL);
      CREATE INDEX IF NOT EXISTS usage_time ON usage_events(occurred);
      CREATE TABLE IF NOT EXISTS usage_cursors (
      path TEXT PRIMARY KEY, identity TEXT NOT NULL, offset INTEGER NOT NULL,
      metadata TEXT NOT NULL, size INTEGER NOT NULL, modified REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS usage_health (source TEXT PRIMARY KEY, checked REAL, details TEXT NOT NULL)
      '''.split(';'):
        if statement.strip():db.execute(statement)


def unpack(raw,default=None):
    try:return json.loads(raw) if isinstance(raw,str) else raw if raw is not None else default
    except (ValueError,TypeError):return default


def number(value):return value if type(value) is int and value>=0 else None


def normalize(provider,usage):
    u=usage if isinstance(usage,dict) else {}
    def get(*keys):
        for key in keys:
            value=u
            for part in key.split('.'):value=value.get(part) if isinstance(value,dict) else None
            if number(value) is not None:return value
        return None
    i=get('input_tokens','prompt_tokens','promptTokenCount','inputTokens')
    cached=get('cached_input_tokens','cache_read_input_tokens','prompt_cache_hit_tokens','cachedContentTokenCount','input_tokens_details.cached_tokens','prompt_tokens_details.cached_tokens','cacheReadInputTokens')
    write=get('cache_write_input_tokens','cache_creation_input_tokens','cacheCreationInputTokens')
    output=get('output_tokens','completion_tokens','candidatesTokenCount','outputTokens')
    reasoning=get('reasoning_output_tokens','thoughtsTokenCount','output_tokens_details.reasoning_tokens','completion_tokens_details.reasoning_tokens')
    if provider=='claude' and i is not None:i+= (cached or 0)+(write or 0)
    if 'candidatesTokenCount' in u and output is not None:output+=reasoning or 0
    total=get('total_tokens','totalTokenCount')
    if total is None and i is not None and output is not None:total=i+output
    return dict(zip(FIELDS,(i,cached,write,output,reasoning,total)))


def record(db,ident,source,provider,model,project,session_id,occurred,usage,cost=None,cost_kind=None):
    counts=normalize(provider,usage)
    if not isinstance(cost,(float,int)) or isinstance(cost,bool) or not math.isfinite(cost) or cost<0:cost=None
    db.execute('''INSERT INTO usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
       counts=excluded.counts,cost_usd=excluded.cost_usd,cost_kind=excluded.cost_kind,
       model=excluded.model,project=excluded.project,session_id=excluded.session_id,
       occurred=COALESCE(excluded.occurred,usage_events.occurred),observed=excluded.observed''',
       (ident,source,provider,model or 'unknown',project,session_id,occurred,json.dumps(counts),cost,cost_kind,time.time()))


def health(db,source,details):
    db.execute('INSERT OR REPLACE INTO usage_health VALUES (?,?,?)',(source,time.time(),json.dumps(details)))


def record_claude(db,job,info,result):
    prefix='claude-job:'+job['id']
    models=getattr(result,'model_usage',None)
    if isinstance(models,dict) and models:
        # Replace the derived historical placeholder, never the provider receipt.
        db.execute('DELETE FROM usage_events WHERE id=?',(prefix,))
        for model,u in models.items():
            record(db,prefix+':model:'+model,'relay_api','claude',model,info['cwd'],info['session_id'],
                   job['started_at'] or job['created_at'],u,u.get('costUSD'),'sdk_usage_value')
    else:
        record(db,prefix,'relay_api','claude',info['model'],info['cwd'],info['session_id'],
               job['started_at'] or job['created_at'],getattr(result,'usage',None),result.total_cost_usd,'sdk_usage_value')


def collect_relay(db,source_path):
    """Use per-call receipts in preference to aggregate copies of those receipts."""
    source_path=Path(source_path)
    if not source_path.is_file():return
    src=sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True);src.row_factory=sqlite3.Row
    prefix='relay:'+hashlib.sha256(str(source_path).encode()).hexdigest()[:16]+':'
    tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def rows(query,required):return src.execute(query).fetchall() if set(required)<=tables else []
    try:
        with db:
            for job in rows('SELECT j.*,t.backend,t.model,t.cwd,t.session_id FROM backend_jobs j JOIN backend_tasks t ON t.id=j.thread_id',('backend_jobs','backend_tasks')):
                usages=[];model='unknown'
                if job['backend']=='claude':
                    # New Claude SDK receipts are recorded directly, with this
                    # same identity; historical cost-only jobs stay unmeasured.
                    ident='claude-job:'+job['id']
                    if db.execute('SELECT 1 FROM usage_events WHERE id=? OR substr(id,1,?)=?',(ident,len(ident+':model:'),ident+':model:')).fetchone():continue
                    usages=[(ident,{})]
                else:
                    table='gemini_runs' if job['backend']=='gemini' else 'api_runs'
                    run=src.execute('SELECT model,usage_json FROM '+table+' WHERE job_id=?',(job['id'],)).fetchone() if table in tables else None
                    if run:model=run['model']
                    steps=src.execute('SELECT step,usage_json FROM api_steps WHERE job_id=?',(job['id'],)).fetchall() if 'api_steps' in tables else []
                    if steps:usages=[(prefix+'api:'+job['id']+':'+str(s['step']),unpack(s['usage_json'],{})) for s in steps]
                    else:
                        u=unpack(run['usage_json'],{}) if run else {}
                        if not isinstance(u,dict):u={}
                        usages=[(prefix+'api:'+job['id']+':'+str(n),v) for n,v in enumerate(u.get('steps') or [u])]
                for ident,u in usages:
                    if not isinstance(u,dict):u={}
                    record(db,ident,'relay_api',job['backend'],model,job['cwd'],job['session_id'],
                           job['started_at'] or job['created_at'],u,job['cost_usd'] if job['backend']=='claude' else u.get('cost') if job['backend']=='openrouter' else None,
                           'sdk_usage_value' if job['backend']=='claude' else 'provider_reported')
            for row in rows('SELECT c.*,p.provider,p.model,p.options FROM production_plan_calls c JOIN production_plans p ON p.id=c.plan_id',('production_plan_calls','production_plans')):
                record(db,prefix+'planner:'+row['plan_id']+':'+str(row['number']),'relay_planner',row['provider'],row['model'],unpack(row['options'],{}).get('project'),None,row['created'],unpack(row['usage'],{}))
            for row in rows('SELECT * FROM production_attempts',('production_attempts',)):
                frozen=unpack(row['frozen'],{});receipt=unpack(row['receipt'],{})
                backend=frozen.get('backend',{});execution=frozen.get('execution',{})
                if execution.get('kind')=='procedure' or execution.get('capability')=='text.bundle':continue
                provider='gemini' if backend.get('type') in ('gemini-agent','gemini-browser') or execution.get('capability')=='gemini.text' else 'codex'
                usage=receipt.get('usage') or [{}]
                if isinstance(usage,dict):usage=[usage]
                for n,u in enumerate(usage):
                    record(db,prefix+'worker:'+row['id']+':'+str(n),'relay_worker',provider,execution.get('parameters',{}).get('model') or backend.get('model'),
                           frozen.get('run'),receipt.get('thread_id'),receipt.get('started') or receipt.get('finished'),u)
            for job in rows('SELECT id,provider,model,created,focus FROM orchestrator_chats',('orchestrator_chats',)):
                path=source_path.parent/'orchestrator-reads'/(hashlib.sha256(str(job['id']).encode()).hexdigest()+'.json')
                journal=[]
                if path.is_file() and not path.is_symlink() and path.stat().st_size<=16000000:journal=unpack(path.read_text(),[])
                if not isinstance(journal,list):journal=[]
                for step in journal or [{'step':0}]:
                    response=step.get('response',{})
                    record(db,prefix+'chat:'+str(job['id'])+':'+str(step['step']),'relay_chat',job['provider'],job['model'],job['focus'],None,
                           step.get('submitted_at',job['created']),response.get('usageMetadata',response.get('usage',{})))
                for path in path.with_suffix('').glob('search-*.json'):
                    if path.is_symlink() or path.stat().st_size>16000000:continue
                    search=unpack(path.read_text(),{});response=search.get('response',{})
                    record(db,prefix+'search:'+str(job['id'])+':'+path.stem,'relay_search','gemini',search.get('model'),job['focus'],None,search.get('submitted_at'),response.get('usageMetadata',{}))
            health(db,str(source_path),{'status':'read','scope':'recorded Relay calls; missing receipts remain unknown'})
    finally:src.close()


def report(db,days=7,group='provider',now=None):
    if group not in ('provider','model','project','day'):raise ValueError('Group by provider, model, project or day.')
    if not 1<=days<=3660:raise ValueError('Days must be between 1 and 3660.')
    end=now or time.time();start=(datetime.fromtimestamp(end,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=days-1)).timestamp()
    # Native worker history may overlap its Relay receipt. Prefer the latter
    # for sessions with recorded usage, including when viewing a narrower date range.
    owned={(r[0],r[1]) for r in db.execute("SELECT DISTINCT provider,session_id FROM usage_events WHERE source IN ('relay_worker','relay_api') AND session_id IS NOT NULL AND json_extract(counts,'$.total_tokens') IS NOT NULL")}
    groups={};unknown=0;excluded=0;events=0
    for row in db.execute('SELECT * FROM usage_events WHERE occurred>=? AND occurred<=?',(start,end)):
        if row['source'] in ('local_codex','local_claude') and (row['provider'],row['session_id']) in owned:excluded+=1;continue
        counts=json.loads(row['counts']);events+=1
        if counts['total_tokens'] is None:unknown+=1
        key=(row[group] or 'unattributed') if group!='day' else datetime.fromtimestamp(row['occurred'],timezone.utc).date().isoformat()
        bucket=groups.setdefault(key,{'name':key,'records':0,'unmeasured':0,**{k:None for k in FIELDS},'reported_cost_usd':None,'sdk_usage_value_usd':None})
        bucket['records']+=1;bucket['unmeasured']+=counts['total_tokens'] is None
        for k,v in counts.items():
            if v is not None:bucket[k]=(bucket[k] or 0)+v
        if row['cost_usd'] is not None:
            k='sdk_usage_value_usd' if row['cost_kind']=='sdk_usage_value' else 'reported_cost_usd'
            bucket[k]=(bucket[k] or 0)+row['cost_usd']
    return {'start_utc':datetime.fromtimestamp(start,timezone.utc).isoformat(),'end_utc':datetime.fromtimestamp(end,timezone.utc).isoformat(),
        'group':group,'groups':sorted(groups.values(),key=lambda g:g['total_tokens'] or 0,reverse=True),'records':events,'unmeasured_records':unknown,
        'deduplicated_local_records':excluded,'undated_records':db.execute('SELECT count(*) FROM usage_events WHERE occurred IS NULL').fetchone()[0],
        'sources':[{'source':r['source'],'checked':r['checked'],**json.loads(r['details'])} for r in db.execute('SELECT * FROM usage_health')],
        'limits':['Local recorded activity, not an account-wide bill or remaining subscription quota.','Cache and reasoning breakdowns are subsets of the normalized totals; do not add them again.',
                  'External API calls, cloud-only sessions, tool charges and missing logs require additional sources.',
                  'Relay receipts take precedence for overlapping managed sessions; other activity in those sessions may be omitted.',
                  'Fork baselines and reset counters are skipped where fresh usage cannot be established; affected totals are lower bounds.',
                  'Calendar dates use UTC. Missing fields and incomplete backfills are not zero usage.']}


def render(value):
    def count(x):return f'{x:,}' if x is not None else 'unknown'
    lines=['Token usage · '+value['start_utc'][:10]+' to '+value['end_utc'][:10]+' UTC']
    for row in value['groups'][:20]:
        lines += [f"\n{row['name']}: {count(row['total_tokens'])} total",f"Input {count(row['input_tokens'])} · cached {count(row['cached_input_tokens'])} · output {count(row['output_tokens'])}"]
        if row['reported_cost_usd'] is not None:lines.append(f"Provider-reported cost: ${row['reported_cost_usd']:.4f}")
        if row['sdk_usage_value_usd'] is not None:lines.append(f"SDK usage value: ${row['sdk_usage_value_usd']:.4f} (not a subscription charge)")
    if len(value['groups'])>20:lines.append(f"Showing 20 of {len(value['groups'])} groups; full report is available through the local CLI.")
    if not value['groups']:lines.append('No indexed usage in this period.')
    lines += [f"\nUnmeasured records: {value['unmeasured_records']}. Undated records: {value['undated_records']}.",
              'Recorded usage only; this is not your bill or subscription quota. Cached input is already included in input.']
    for s in value['sources']:
        if s.get('status')!='read':lines.append(f"{Path(s['source']).name}: {s.get('status')}"+(f" · {s['pending_bytes']:,} bytes awaiting indexing" if s.get('pending_bytes') else ''))
        if s.get('warnings'):lines.append('Coverage caveats: '+', '.join(s['warnings'])+'; totals may be incomplete.')
    if value['deduplicated_local_records']:lines.append('Overlapping managed sessions use Relay receipts; additional local activity in those sessions may be omitted.')
    if value['sources']:
        checked=min(s['checked'] for s in value['sources'])
        lines.append('Oldest source refresh: '+datetime.fromtimestamp(checked,timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
    return '\n'.join(lines)


def refresh(db,data=PATHS.data,local=True,max_bytes=32000000,roots=None):
    from task_relay.usage_sources import collect_local, default_roots
    collect_relay(db,Path(data)/'state.sqlite')
    if local:collect_local(db,roots if roots is not None else default_roots(),max_bytes=max_bytes)


class Worker:
    def __init__(self,state):self.state=state
    def tick(self):
        if self.state.get('usage_tracking_enabled',False):refresh(self.state.db,self.state.media_dir.parent)


def command(state,arg):
    parts=arg.split();days=7;group='provider'
    if parts:
        if not parts[0].isdigit():raise ValueError('Use /usage [DAYS] [provider|model|project|day].')
        days=int(parts[0])
    if len(parts)>1:group=parts[1]
    if len(parts)>2:raise ValueError('Use /usage [DAYS] [provider|model|project|day].')
    value=report(state.db,days,group)
    return render(value)+'\nBackground indexing: '+('enabled' if state.get('usage_tracking_enabled',False) else 'disabled')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--refresh',action='store_true');p.add_argument('--relay-only',action='store_true',help='Skip local-log refresh; reports still include previously indexed local usage.')
    tracking=p.add_mutually_exclusive_group()
    tracking.add_argument('--enable',action='store_true',help='Enable local background indexing in the Relay service.')
    tracking.add_argument('--disable',action='store_true',help='Pause background indexing, retaining recorded usage.')
    p.add_argument('--days',type=int,default=7);p.add_argument('--group',choices=['provider','model','project','day'],default='provider');p.add_argument('--json',action='store_true')
    p.add_argument('--max-bytes',type=int,default=32000000);args=p.parse_args()
    PATHS.data.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(PATHS.state,timeout=30);db.row_factory=sqlite3.Row;initialize(db)
    if args.enable or args.disable:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',('usage_tracking_enabled',json.dumps(args.enable)))
    if args.refresh:refresh(db,local=not args.relay_only,max_bytes=args.max_bytes)
    value=report(db,args.days,args.group);print(json.dumps(value,indent=2) if args.json else render(value));db.close()


if __name__=='__main__':main()
