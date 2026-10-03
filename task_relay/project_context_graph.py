"""Deterministic, evidence-linked graph projection of a saved Relay context run."""
import json
from pathlib import Path

from . import project_context as pc
from .filesystem import FILES, Grant


def build(db, run_id):
    row = pc.get(db, run_id)
    if row['status'] not in ('proposed', 'proposed_with_gaps'):
        raise ValueError('Graph requires a validated topic organization')
    capture = pc.model_evidence(json.loads(row['capture_json']))
    proposal = json.loads(row['proposal_json'])
    report = json.loads(db.execute('SELECT report_json FROM project_context_validation WHERE run_id=?', (run_id,)).fetchone()[0])
    sources = {s['id']: s for s in capture['sources']}
    files = {f['path']: f for f in capture['files']}
    nodes, edges, known = [], [], set()

    def node(nid, kind, label, **data):
        if nid not in known:
            nodes.append(dict(id=nid, kind=kind, label=label, **data)); known.add(nid)
        return nid

    def edge(a, b, relation, basis, **data):
        edges.append(dict(source=a, target=b, relation=relation, basis=basis, **data))

    root = node('project', 'project', Path(capture['project']).name, path=capture['project'])
    for thread in capture['threads']:
        tid = node('chat:' + thread['id'], 'chat', thread.get('name') or thread.get('title') or thread['id'],
                   thread_id=thread['id'], url='codex://threads/' + thread['id'])
        edge(root, tid, 'contains_chat', 'captured_history')
    # Inventory nodes prove only presence at capture. They do not establish
    # that a source was used to produce a file or that an artifact was accepted.
    for path, info in sorted(files.items()):
        fid = node('file:' + path, 'file', Path(path).name, path=path,
                   url=str(Path(capture['project']) / path), bytes=info['bytes'],
                   modified_ns=info.get('modified_ns'), artifact=False)
        edge(root, fid, 'inventory_contains', 'captured_metadata')
    for sid, source in sources.items():
        nid = node('source:' + sid, source['kind'], source.get('title') or source.get('path'),
                   source_id=sid, data=source)
        if source['kind'] == 'message':
            edge('chat:' + source['thread_id'], nid, 'contains_message', 'captured_history')
        else:
            edge('file:' + source['path'], nid, 'has_text_snapshot', 'captured_content')
    artifacts = set()
    for topic in proposal['topics']:
        topic_id = node('topic:' + topic['id'], 'topic', topic['title'], topic_id=topic['id'],
                        summary=topic['summary'], open_questions=topic['open_questions'], next_steps=topic['next_steps'])
        edge(root, topic_id, 'organizes_as', 'model_proposal')
        chat_sources = {}
        for sid in topic['source_ids']:
            edge(topic_id, 'source:' + sid, 'groups_source', 'model_proposal')
            source = sources[sid]
            if source['kind'] == 'message':
                chat_sources.setdefault(source['thread_id'], []).append(sid)
        for tid, ids in sorted(chat_sources.items()):
            edge('chat:' + tid, topic_id, 'discusses_topic', 'model_proposal', source_ids=ids, message_count=len(ids))
        for path in topic['artifact_paths']:
            artifacts.add('file:' + path)
            edge(topic_id, 'file:' + path, 'associates_artifact', 'model_proposal')
        claims = [(c, 'quotation_checked', None) for c in topic['claims']]
        claims += [(r['claim'], 'held_for_review', r['reason']) for r in report['rejected_claims'] if r['topic_id'] == topic['id']]
        for index, (claim, status, reason) in enumerate(claims):
            cid = node('claim:' + topic['id'] + ':' + str(index), 'claim',
                       claim.get('statement', 'Malformed claim') if isinstance(claim, dict) else 'Malformed claim',
                       status=status, validation_reason=reason, claim=claim)
            edge(topic_id, cid, 'proposes_claim', 'model_proposal')
            if not isinstance(claim, dict) or not isinstance(claim.get('evidence'), list):
                continue
            for ref in claim['evidence']:
                if isinstance(ref, dict) and ref.get('source_id') in sources:
                    edge(cid, 'source:' + ref['source_id'], 'cites' if status == 'quotation_checked' else 'unverified_citation',
                         'exact_quote_and_role' if status == 'quotation_checked' else 'rejected_model_citation', quote=ref.get('quote'))
    for n in nodes:
        if n['id'] in artifacts:
            n['artifact'] = True
    if any(e['source'] not in known or e['target'] not in known for e in edges):
        raise ValueError('Graph contains an unresolved endpoint')
    return dict(schema_version=1, run_id=run_id, capture_sha256=row['capture_sha256'],
                proposal_sha256=pc.digest(row['proposal_json'].encode()), origin='relay_runtime_projection',
                nodes=nodes, edges=edges,
                counts={k: sum(n['kind'] == k for n in nodes) for k in ('chat', 'topic', 'message', 'document', 'file', 'claim')},
                artifact_count=len(artifacts), limitations=capture['limitations'] +
                ['Topic and artifact associations are model proposals, not proven production dependencies',
                 'No inferred supersession, acceptance or causal edges; unverified citations remain labeled'])


def export(db, run_id, destination, request):
    if not isinstance(request, str) or not request.strip():
        raise ValueError('Exact graph request required')
    graph = build(db, run_id)
    raw = pc.encoded(graph).encode()
    outputs = {str(Path(destination).absolute()): raw}
    receipt = dict(run_id=run_id, exact_request=request, graph_schema_version=1,
                   capture_sha256=graph['capture_sha256'], proposal_sha256=graph['proposal_sha256'],
                   model_calls=0, files={p: pc.digest(v) for p, v in outputs.items()})
    db.execute('''CREATE TABLE IF NOT EXISTS project_context_graph_exports (
      run_id TEXT NOT NULL, destination TEXT NOT NULL, receipt_json TEXT NOT NULL,
      status TEXT NOT NULL, PRIMARY KEY(run_id,destination));''')
    with db:
        prior = db.execute('SELECT receipt_json FROM project_context_graph_exports WHERE run_id=? AND destination=?', (run_id, str(Path(destination).absolute()))).fetchone()
        if prior and json.loads(prior[0]) != receipt:
            raise ValueError('Graph export intent differs from the recorded version')
        db.execute('INSERT OR IGNORE INTO project_context_graph_exports VALUES (?,?,?,?)',
                   (run_id, str(Path(destination).absolute()), pc.encoded(receipt), 'exporting'))
    for location, content in outputs.items():
        path = Path(location); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        grant = Grant(path.parent, 'Relay graph projection export', reads=frozenset({path.name}), writes=frozenset({path.name}))
        if path.exists() or path.is_symlink():
            if FILES.read(grant, path.name, 10000000) != content:
                raise ValueError('Graph destination was edited; refusing overwrite')
        else:
            FILES.write(grant, path.name, content, exclusive=True)
        if FILES.read(grant, path.name, 10000000) != content:
            raise ValueError('Graph export read-back failed')
    with db:
        db.execute("UPDATE project_context_graph_exports SET status='completed' WHERE run_id=? AND destination=?",
                   (run_id, str(Path(destination).absolute())))
    return receipt
