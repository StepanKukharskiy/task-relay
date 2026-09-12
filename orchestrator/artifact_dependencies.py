"""Read-only provenance and replacement impact from immutable attempt inputs.

Every declared input is a potential dependency of every output from that attempt.
This establishes supplied context, not proof that the worker used every input.
No filenames, matching hashes or later assignment edits establish version identity.
"""
import json

from .storage import transaction


NOTE = ('Dependencies mean inputs supplied to a recorded attempt, including context and prior drafts; '
        'they do not prove semantic use. Impact is a preview, not a replacement decision, '
        'an outdated flag, or authorization to rerun work. Unregistered external files are not tracked.')
FIELDS = 'id,run,task,attempt,path,sha256,bytes,purpose'
EDGES = '''SELECT a.id AS output, json_extract(i.value,'$.artifact') AS input,
    p.id AS attempt, json_extract(i.value,'$.path') AS input_path,
    json_extract(i.value,'$.sha256') AS input_sha256,
    json_extract(i.value,'$.purpose') AS purpose,
    json_extract(i.value,'$.authority') AS authority
    FROM production_artifacts a JOIN production_attempts p ON p.id=a.attempt
    JOIN json_each(p.frozen,'$.inputs') i
    WHERE json_extract(i.value,'$.artifact') IS NOT NULL'''


def metadata(db, aid):
    row = db.execute('SELECT '+FIELDS+' FROM production_artifacts WHERE id=?', (aid,)).fetchone()
    if row is None:
        raise ValueError('Unknown artifact '+str(aid))
    value = dict(row)
    value['selections'] = [dict(d) for d in db.execute('''SELECT id,run,task,purpose,created
        FROM production_decisions WHERE artifact=? ORDER BY created,id''', (aid,))]
    return value


def trace(db, seeds, direction='upstream', limit=100):
    """Bounded transitive closure; UNION terminates even with corrupt cyclic history."""
    if direction not in ('upstream', 'downstream'):
        raise ValueError('Direction must be upstream or downstream')
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Dependency limit must be 1–200')
    seeds = list(dict.fromkeys(seeds))
    if not seeds or len(seeds) > limit:
        raise ValueError('Supply 1–limit exact artifact IDs')
    with transaction(db, write=False):
        for aid in seeds:
            metadata(db, aid)
        source, target = ('output', 'input') if direction == 'upstream' else ('input', 'output')
        marks = ','.join('?' for _ in seeds)
        rows = db.execute('''WITH RECURSIVE edges AS ('''+EDGES+'''), reached(id) AS (
            SELECT id FROM production_artifacts WHERE id IN ('''+marks+''')
            UNION SELECT e.'''+target+''' FROM edges e JOIN reached r ON e.'''+source+'''=r.id
            LIMIT ?)
            SELECT id FROM reached''', (*seeds, limit+1)).fetchall()
        ids = [r['id'] for r in rows[:limit]]
        truncated = len(rows) > limit
        marks = ','.join('?' for _ in ids)
        edges = [dict(r) for r in db.execute('SELECT * FROM ('+EDGES+') WHERE output IN ('+marks+
            ') AND input IN ('+marks+') ORDER BY output,input,input_path LIMIT 1001', (*ids, *ids))]
        edge_truncated = len(edges) > 1000
        nodes, gaps = [], []
        for aid in ids:
            try:
                node = metadata(db, aid)
            except ValueError:
                gaps.append({'artifact': aid, 'reason': 'Recorded input is missing from the registry'})
                continue
            if node['attempt']:
                attempt = db.execute('SELECT state,frozen FROM production_attempts WHERE id=?', (node['attempt'],)).fetchone()
                node['attempt_state'] = attempt['state'] if attempt else None
                if not attempt or not isinstance(json.loads(attempt['frozen']).get('inputs'), list):
                    gaps.append({'artifact': aid, 'reason': 'Frozen input evidence is unavailable'})
                elif any(not i.get('artifact') for i in json.loads(attempt['frozen'])['inputs']):
                    gaps.append({'artifact': aid, 'reason': 'A frozen input has no exact artifact identity'})
            nodes.append(node)
        hashes = {n['id']: n['sha256'] for n in nodes}
        for edge in edges[:1000]:
            if not edge['input_sha256'] or edge['input_sha256'] != hashes.get(edge['input']):
                gaps.append({'artifact': edge['input'], 'attempt': edge['attempt'],
                             'reason': 'Frozen input hash is missing or differs from the registered version'})
        return {'seeds': seeds, 'direction': direction, 'artifacts': nodes, 'dependencies': edges[:1000],
                'truncated': truncated or edge_truncated, 'gaps': gaps, 'note': NOTE}


def impact(db, artifact, replacement=None, limit=100):
    """Preview consumers of an exact version, including attempts without outputs."""
    with transaction(db, write=False):
        graph = trace(db, [artifact], 'downstream', limit)
        old = metadata(db, artifact)
        new = metadata(db, replacement) if replacement else None
        if replacement == artifact:
            raise ValueError('Choose a distinct replacement artifact version')
        ids = [n['id'] for n in graph['artifacts']]
        marks = ','.join('?' for _ in ids)
        consumers = [dict(r) for r in db.execute('''SELECT DISTINCT p.id AS attempt,p.run,p.task,p.state,
            json_extract(i.value,'$.artifact') AS input,
            json_extract(i.value,'$.sha256') AS input_sha256
            FROM production_attempts p JOIN json_each(p.frozen,'$.inputs') i
            WHERE json_extract(i.value,'$.artifact') IN ('''+marks+''')
            ORDER BY p.run,p.task,p.id,input LIMIT 201''', ids)]
        hashes = {n['id']: n['sha256'] for n in graph['artifacts']}
        for consumer in consumers[:200]:
            if not consumer['input_sha256'] or consumer['input_sha256'] != hashes.get(consumer['input']):
                graph['gaps'].append({'artifact': consumer['input'], 'attempt': consumer['attempt'],
                                     'reason': 'Consumer input hash is missing or differs from the registered version'})
        # These inputs have not been executed. Keep them separate from frozen evidence.
        planned = [dict(r) for r in db.execute('''SELECT DISTINCT t.run,t.id AS task,t.status,a.id AS assignment,
            json_extract(i.value,'$.artifact') AS input
            FROM production_tasks t JOIN production_assignments a ON a.id=t.assignment
            JOIN json_each(a.spec,'$.inputs') i WHERE t.status='queued'
            AND json_extract(i.value,'$.artifact') IN ('''+marks+''')
            ORDER BY t.run,t.id,input LIMIT 201''', ids)]
        return {'source': old, 'replacement': new,
                'same_content': new['sha256'] == old['sha256'] if new else None,
                'potentially_affected_outputs': [n for n in graph['artifacts'] if n['id'] != artifact],
                'recorded_consumers': consumers[:200], 'queued_explicit_inputs': planned[:200],
                'dependencies': graph['dependencies'], 'gaps': graph['gaps'],
                'truncated': graph['truncated'] or len(consumers) > 200 or len(planned) > 200,
                'note': NOTE+' Queued from_task references are unresolved until claim and are not frozen consumers.'}


def run_lineage(db, run, limit=100):
    """Current output provenance for the orchestrator and stage inspection card."""
    with transaction(db, write=False):
        rows = db.execute('''SELECT a.id FROM production_artifacts a JOIN production_tasks t
            ON t.run=a.run AND t.id=a.task AND t.latest=a.attempt WHERE a.run=?
            ORDER BY a.task,a.path LIMIT ?''', (run, limit+1)).fetchall()
        if not rows:
            return {'seeds': [], 'artifacts': [], 'dependencies': [], 'gaps': [], 'truncated': False, 'note': NOTE}
        result = trace(db, [r['id'] for r in rows[:limit]], limit=limit)
        result['truncated'] |= len(rows) > limit
        return result
