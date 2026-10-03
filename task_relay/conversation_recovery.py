"""Export a saved direct reply without a provider call, state change or delivery."""
import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path


def recover(database,job_id,destination):
    from . import orchestrator_chat as chat, orchestrator_advice as advice
    database=Path(database).expanduser().resolve()
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM orchestrator_chats WHERE id=?',(job_id,)).fetchone()
        if not row or row['status'] not in ('failed','answered') or not row['response']:
            raise ValueError('Recover a saved terminal direct response; no provider retry is performed.')
        error=db.execute('SELECT * FROM orchestrator_chat_errors WHERE job_id=?',(job_id,)).fetchone()
    raw=row['response'];snapshot=json.loads(row['snapshot'] or '{}')
    value=chat.response_json(raw)
    if not isinstance(value,dict) or value.get('action') is not None:
        raise ValueError('Saved action proposals cannot be recovered as direct answers or executed here.')
    # Validate against the full captured catalog, not its truncated overview.
    tools=[{'id':i} for i in snapshot.get('option_tool_ids',[])]
    advice.validate(raw,row['prompt'],tools if 'next_options' in value else None)
    frozen=value.get('request_contract')
    if frozen is not None:
        from .request_contract import validate as validate_scope
        validate_scope(frozen)
    # Export unreviewed direct text even when it failed the production-routing
    # requirement. Extraction never fulfills that contract or executes a route.
    value=chat.interpret(json.dumps({k:v for k,v in value.items() if k!='request_contract'}),snapshot)
    answer=value['answer']
    content={'provider-response.json':raw.encode('utf-8'),'answer.md':answer.encode('utf-8')}
    matches=list(re.finditer(r'^## Article (\d+):[^\n]*',answer,re.M))
    articles=[]
    # Convenience splitting for legacy numbered drafts, never production acceptance.
    if matches and [int(m[1]) for m in matches]==list(range(1,len(matches)+1)):
        for i,match in enumerate(matches):
            name=f'article-{i+1:02}.md'
            content[name]=answer[match.start():matches[i+1].start() if i+1<len(matches) else len(answer)].encode('utf-8')
            articles.append(name)
    receipt={'version':1,'job_id':job_id,'request':row['prompt'],
             'provider':row['provider'],'model':row['model'],'original_status':row['status'],
             'original_error':dict(error) if error else None,
             'response_sha256':hashlib.sha256(raw.encode()).hexdigest(),
             'snapshot_sha256':hashlib.sha256((row['snapshot'] or '').encode()).hexdigest(),
             'article_files':articles,'review_status':'unreviewed saved provider text',
             'provider_calls':0,'dispatched_actions':0,
             'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in content.items()}}
    if frozen is not None:receipt.update(request_contract=frozen,request_fulfilled=False)
    content['recovery-receipt.json']=(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    destination=Path(destination).expanduser()
    if not destination.is_absolute():raise ValueError('Recovery destination must be an absolute path.')
    if destination.is_symlink():raise ValueError('Recovery destination cannot be a symlink.')
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Check every existing file before writing any new member. A partial export
    # resumes only when retained bytes still match; it never overwrites edits.
    for name,data in content.items():
        path=destination/name
        if path.is_symlink() or path.exists() and (not path.is_file() or path.read_bytes()!=data):
            raise ValueError('Recovery output already exists with different bytes: '+name)
    for name,data in content.items():
        path=destination/name
        if not path.exists():
            with path.open('xb') as stream:stream.write(data)
    return {**receipt,'directory':str(destination),'receipt':str(destination/'recovery-receipt.json')}


def main():
    from .relay_paths import PATHS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=PATHS.state)
    parser.add_argument('--job',type=int,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(recover(args.database,args.job,args.destination),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
