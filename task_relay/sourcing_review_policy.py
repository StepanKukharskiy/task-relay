"""Apply explicit target policies to prospective criteria, never old verdicts."""
import re

def bind(plan,scope):
    policy=scope.get('sourcing_count_policy')
    if scope.get('connector_companions_version')!=1 or policy!='target':return []
    receipts=[];reviewed={t['review_of'] for t in plan['tasks'] if t.get('review_of')};tasks={t['id']:t for t in plan['tasks']}
    for task in plan['tasks']:
        from .record_planning import collection_policy
        if not task.get('review_of') and not collection_policy(task) and task['id'] not in reviewed:continue
        before=list(task['criteria']);after=[]
        native=bool(task.get('execution') or tasks.get(task.get('review_of'),{}).get('execution'))
        for criterion in before:
            if not native and re.search(r'\b(?:alternatives?|options?|photos?|images?|coverage)\b',criterion,re.I):
                criterion=('Under the explicit target policy, evaluate the included records and disclosed gaps: '+criterion+
                    ' Requested option counts and unavailable photos are targets; an accurate explicit shortfall is advisory. '
                    'Incorrect subject identity, captured field or captured price, variant, source support, link or supplied photo is a correction requirement.')
            after.append(criterion)
        task['criteria']=list(dict.fromkeys(after))
        task['instruction']+='\nThe saved count_policy is target. After bounded coverage discovery, deliver all supported options and explicit per-item shortfalls. Review the truth of each supplied claim and photo. Missing options or unavailable photos alone do not require a user gate. Do not call a partial collection complete coverage or waive incorrect evidence.'
        if before!=task['criteria']:receipts.append(dict(task=task['id'],before=before,criteria=task['criteria'],source='explicit saved target policy',old_verdicts_changed=False))
    return receipts
