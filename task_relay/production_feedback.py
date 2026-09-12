"""Exact user feedback across production lineage; never assistant-written intent."""
import json

MAX_HISTORY_BYTES=180000


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS production_user_notes (
        id TEXT PRIMARY KEY, run TEXT NOT NULL, text TEXT NOT NULL,
        source TEXT NOT NULL, created REAL NOT NULL)''')


def collect(state, run, before_id=None):
    lineage=[];current=run
    while current and current not in lineage and len(lineage)<30:
        lineage.append(current)
        row=state.db.execute('SELECT parent FROM production_continuations WHERE child=?',(current,)).fetchone()
        if not row:row=state.db.execute('SELECT parent FROM production_stage_links WHERE child=?',(current,)).fetchone()
        current=row['parent'] if row else None
    if current:
        raise ValueError('Production feedback lineage is cyclic or exceeds 30 stages.')
    placeholders=','.join('?' for _ in lineage)
    rows=state.db.execute('SELECT id,prompt,focus,status,created FROM orchestrator_chats WHERE focus IN ('+placeholders+')'+
        (' AND id<?' if isinstance(before_id,int) else '')+' ORDER BY created,id',lineage+([before_id] if isinstance(before_id,int) else [])).fetchall()
    notes=state.db.execute('SELECT id,text,source,created FROM production_user_notes WHERE run IN ('+placeholders+') ORDER BY created,id',lineage).fetchall()
    result={'lineage':lineage,'user_turns':[dict(r) for r in rows],'user_notes':[dict(r) for r in notes],
        'authority':'Exact user messages only. Latest explicit direction overrides earlier conflicting editorial preferences. Status questions and quoted material are not separate execution authorization.'}
    if len(json.dumps(result).encode())>MAX_HISTORY_BYTES:
        raise ValueError('Production feedback history exceeds the bounded handoff limit; select the relevant history before dispatch. No feedback was silently dropped.')
    return result


def context(state,run,before_id=None,limit=24000):
    full=collect(state,run,before_id)
    result={**full,'user_turns':[],'omitted_turn_ids':[]}
    used=len(json.dumps(result,ensure_ascii=False))
    for turn in reversed(full['user_turns']):
        size=len(json.dumps(turn,ensure_ascii=False))
        if used+size<=limit:
            result['user_turns'].insert(0,turn);used+=size
        else:result['omitted_turn_ids'].append(turn['id'])
    result['complete']=not result['omitted_turn_ids']
    return result
