"""Read-only membership from explicit workflow requests, targets and recovery receipts.

Membership is a projection, not authorization to dispatch or delete. Destructive
consumers must still check exclusive ownership and unresolved effects.
"""
import json


def collect(db, pipeline, step=None):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    owner = db.execute('SELECT request_id FROM relay_pipelines WHERE id=?', (pipeline,)).fetchone()
    if not owner:
        return dict(requests=set(), plans=set(), runs=set())
    requests = {owner[0]} if step is None else set()
    plans, runs = set(), set()
    def rows(table):
        if table not in tables:
            return []
        sql = 'SELECT * FROM '+table+' WHERE pipeline=?'
        return db.execute(sql+(' AND step=?' if step is not None else ''),
                          (pipeline, step) if step is not None else (pipeline,)).fetchall()
    for row in rows('relay_pipeline_requests'):
        requests.add(row['request_id'])
    for table in ('completion_recoveries', 'local_review_invocations'):
        for row in rows(table):
            runs.add(row['parent'])
            if 'request_id' in row.keys():
                requests.add(row['request_id'])
    for row in rows('production_auto_repairs'):
        if row['plan_id']: plans.add(row['plan_id'])
        if row['preparation']: runs.add(row['preparation'])
    for row in db.execute('SELECT * FROM relay_pipeline_steps WHERE pipeline=?', (pipeline,)):
        if step is not None and row['id'] != step: continue
        if row['request_id'] is not None: requests.add(row['request_id'])
        if row['target']:
            if row['target_kind'] == 'production_run': runs.add(row['target'])
            elif row['target_kind'] in ('plan_production', 'production_plan'): plans.add(row['target'])
        # Older/native non-production stages store human-readable result text.
        # Only a structured result with an explicit run is a membership edge.
        try: result = json.loads(row['result'] or '{}')
        except (TypeError,ValueError): result = None
        if isinstance(result, dict) and result.get('run'): runs.add(result['run'])
    for row in rows('relay_pipeline_events'):
        if row['kind'] == 'registered_revision_queued':
            detail = json.loads(row['detail'])
            runs.update(detail[k] for k in ('parent', 'successor') if detail.get(k))
    saved_plans = list(db.execute('SELECT id,request_id,run,parent_id FROM production_plans'))
    links = [r for table in ('production_stage_links', 'production_continuations') if table in tables
             for r in db.execute('SELECT * FROM '+table)]
    while True:
        before = (len(requests), len(plans), len(runs))
        for row in saved_plans:
            if row['id'] in plans or row['request_id'] in requests or row['run'] in runs or row['parent_id'] in plans:
                plans.add(row['id']); requests.add(row['request_id'])
                if row['run']: runs.add(row['run'])
        for row in links:
            if row['parent'] in runs or ('plan_id' in row.keys() and row['plan_id'] in plans):
                if row['child']: runs.add(row['child'])
                if 'plan_id' in row.keys() and row['plan_id']: plans.add(row['plan_id'])
        if before == (len(requests), len(plans), len(runs)): break
    return dict(requests=requests, plans=plans, runs=runs)
