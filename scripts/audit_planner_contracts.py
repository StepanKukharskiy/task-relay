"""Read-only planning-error inventory; does not infer cause or recover any job.

Prints aggregate JSON by default. --details includes exact saved error messages
and plan IDs: store that output only in ignored private/development storage.
Classification uses known validator message signatures, not model interpretation.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


RULES = (
    ('provider_error', ('Gemini request failed', 'Provider request failed', 'Planning provider is disconnected')),
    ('capability_unavailable', ('No eligible worker', 'The requested executor is unavailable')),
    ('worker_configuration', ('Worker specifies requires', 'Worker tools conflict', 'Planner exceeds frozen worker limits',
                              'Planner exceeds the frozen attempt allowance', 'Requested worker executor')),
    ('operation_contract', ('Use the registered operation criteria', 'Execution needs an exact',
                            'Invalid registered-operation parameters', 'Unknown capability or unsupported execution version')),
    ('artifact_binding', ('Unknown input artifact', 'Unknown upstream output', 'Host inputs must stay outside',
                          'Blender inputs must stay outside', 'Declared input type differs',
                          'Selected binary source is incompatible', 'Registered input media types',
                          'Select exactly one Rhino model', 'Concrete output type differs',
                          'Upstream output type does not match', 'Proposed host code/input hash differs')),
    ('graph_contract', ('Only exact-input host operations can be deferred', 'Host deferral requires',
                        'The plan omitted selected operations', 'Image sourcing needs independent review',
                        'A deferral requires a gated preparation', 'Host script preparation requires selection_outputs',
                        'Every member of a selection set', 'An independent reviewer is required')),
    ('response_shape', ('Unsupported assignment field', 'Missing or oversized task',
                        'Invalid planning response envelope', 'Duplicate JSON key', '$.')),
    ('json_syntax', ('Expecting ', 'Unterminated string', 'Invalid control character', 'Extra data')),
)


def classify(error):
    for category,prefixes in RULES:
        if error.startswith(prefixes):return category
    return 'unclassified'


def audit(database, since=None, details=False):
    """A consistent read snapshot; SQLite mode=ro cannot create or update state."""
    path=Path(database).expanduser().resolve()
    if not path.is_file():raise ValueError('Choose an existing Relay SQLite database; no database was created.')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        columns={r['name'] for r in db.execute('PRAGMA table_info(production_plan_calls)')}
        if not {'plan_id','number','created','error'}<=columns:
            raise ValueError('Database lacks the supported planning-call receipt table; no migration was attempted.')
        plan_columns={r['name'] for r in db.execute('PRAGMA table_info(production_plans)')}
        if not {'id','status'}<=plan_columns:
            raise ValueError('Database lacks planning statuses; no migration was attempted.')
        where=' WHERE c.created>=?' if since is not None else ''
        args=(since,) if since is not None else ()
        total=db.execute('SELECT count(*) FROM production_plan_calls c'+where,args).fetchone()[0]
        rows=db.execute('SELECT c.plan_id,c.number,c.created,c.error,p.status '
                        'FROM production_plan_calls c LEFT JOIN production_plans p ON p.id=c.plan_id'+
                        where+(' AND ' if where else ' WHERE ')+'c.error IS NOT NULL '
                        'ORDER BY c.created,c.plan_id,c.number',args).fetchall()
    grouped=defaultdict(list)
    for row in rows:grouped[classify(row['error'])].append(row)
    groups=[]
    for category,items in sorted(grouped.items()):
        plans={r['plan_id']:r['status'] or 'missing' for r in items}
        group={'category':category,'failed_calls':len(items),'affected_plans':len(plans),
               'current_plan_statuses':dict(sorted(Counter(plans.values()).items())),
               'first_seen_utc':utc(min(r['created'] for r in items)),
               'last_seen_utc':utc(max(r['created'] for r in items)),
               'distinct_error_signatures':len({r['error'] for r in items})}
        if details:
            group['receipts']=[{'plan_id':r['plan_id'],'call':r['number'],'error':r['error']} for r in items]
        if category=='unclassified':
            group['signature_sha256s']=sorted({hashlib.sha256(r['error'].encode()).hexdigest() for r in items})
        groups.append(group)
    return {'schema_version':1,'scope':'production_plan_calls only',
            'classification':'Known error-message signatures; not a determination of LLM causation.',
            'since_utc':utc(since) if since is not None else None,
            'planning_calls':total,'failed_calls':len(rows),
            'plans_with_failed_calls':len({r['plan_id'] for r in rows}),
            'groups':groups,
            'limitations':['Historical errors remain counted after a plan is corrected.',
                          'One plan may occur in several categories; category plan counts are not additive.',
                          'Provider and capability failures are separate from contract failures.',
                          'No prompts, responses or artifact contents are read; routing/worker receipts are not included.',
                          'A date filter is not a deployed-version or schema-version filter.']}


def utc(timestamp):
    return datetime.fromtimestamp(timestamp,timezone.utc).isoformat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True,help='Existing database; opened read-only')
    parser.add_argument('--since',help='Inclusive UTC date, YYYY-MM-DD')
    parser.add_argument('--details',action='store_true',help='Include private plan IDs and exact error messages')
    args=parser.parse_args()
    try:
        since=datetime.strptime(args.since,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() if args.since else None
        result=audit(args.db,since,args.details)
    except (ValueError,sqlite3.Error) as exc:parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
