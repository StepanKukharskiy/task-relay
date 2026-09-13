"""A read-only view over media and modeling receipts, never a second job queue."""
import json


def catalog(db):
    jobs = []
    for row in db.execute('''SELECT j.id,j.thread_id,j.status,r.capability,r.model,r.stage,r.operation_name
            FROM backend_jobs j JOIN gemini_runs r ON r.job_id=j.id
            WHERE r.capability IN ('image','video') ORDER BY j.created_at DESC LIMIT 10'''):
        job = dict(row)
        job.update(engine='gemini', receipt_type='gemini_runs', receipt_id=job['id'])
        job['artifacts'] = [dict(a) for a in db.execute('''SELECT id,filename,mime,sha256 FROM artifacts
            WHERE job_id=? AND role='output' ORDER BY created_at''', (job['id'],))]
        jobs.append(job)
    for row in db.execute('''SELECT id,run,task,state,frozen FROM production_attempts
            WHERE json_extract(frozen,'$.execution.capability') IN ('gemini.image','openai.image','openrouter.image','runway.image','runway.video','higgsfield.image','higgsfield.video','meshy.mesh')
               OR json_extract(frozen,'$.execution.capability') LIKE 'blender.%'
               OR json_extract(frozen,'$.execution.capability') LIKE 'rhino.%'
            ORDER BY rowid DESC LIMIT 10'''):
        frozen = json.loads(row['frozen'])
        operation = frozen['execution']
        cap = operation['capability']
        job = dict(id=row['id'], run=row['run'], task=row['task'], status=row['state'],
                   capability=cap.split('.')[1] if cap.split('.')[1] in ('image','video','mesh') else 'modeling', operation=cap,
                   engine=cap.split('.')[0], model=operation.get('parameters', {}).get('model'),
                   receipt_type='production_attempts', receipt_id=row['id'])
        job['artifacts'] = [dict(a) for a in db.execute('''SELECT id,path,sha256 FROM production_artifacts
            WHERE attempt=? ORDER BY rowid''', (row['id'],))]
        task = db.execute('SELECT status FROM production_tasks WHERE run=? AND id=?', (row['run'],row['task'])).fetchone()
        job['review_status'] = task['status'] if task else 'unknown'
        jobs.append(job)
    return {'jobs': jobs, 'limit_per_execution_path': 10,
            'scope': 'Recent recorded attempts; queued production steps are in production_runs. Completion is not user acceptance or delivery proof. Inspect the original receipt for recovery; never resubmit from this view.'}
