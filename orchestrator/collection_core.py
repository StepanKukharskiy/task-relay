"""Subject-neutral collection capacity, coverage and exact partition composition."""
from dataclasses import dataclass
import copy


@dataclass(frozen=True)
class Capacity:
    submissions_per_unit: int = 1
    inspections_per_unit: int = 1
    reserved_calls: int = 3

    def ranges(self, count, ceiling):
        for value in (count,ceiling,self.submissions_per_unit,self.inspections_per_unit,self.reserved_calls):
            if type(value) is not int or value<0:raise ValueError('Capacity needs nonnegative integer costs')
        cost=self.submissions_per_unit+self.inspections_per_unit
        if cost<1:raise ValueError('Work units need a nonzero execution cost')
        capacity=(ceiling-self.reserved_calls)//cost
        if capacity<1 and count:raise ValueError('No capacity for a work unit and finalization within the frozen ceiling')
        return [[start,min(count,start+capacity)] for start in range(0,count,capacity)] if count else []


RECORD_CAPACITY=Capacity()


class PendingCollection(ValueError):
    uncertain=True


def collect(subjects,adapters,*,checkpoint=None,commit=None,batch_size=40,policy=None):
    """One loop for any subjects/source adapters; checkpoints never imply acceptance.

    Adapters return validated found/missing data. Exceptions leave an intent pending
    until the adapter supplies a confirmed outcome; the engine does not guess whether
    it is safe to replay. A durable caller commits each snapshot atomically.
    """
    from .operation_contracts import digest
    if type(batch_size) is not int or batch_size<1:raise ValueError('Invalid collection batch size')
    ids=[s['id'] for s in subjects]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate collection subject identity')
    adapter_ids=[a['id'] for a in adapters]
    if not adapters or len(set(adapter_ids))!=len(adapter_ids):raise ValueError('Use distinct registered source adapters')
    binding=digest(dict(subjects=subjects,adapters=[dict(id=a['id'],version=a['version']) for a in adapters],policy=policy))
    state=copy.deepcopy(checkpoint) if checkpoint is not None else dict(version=1,binding=binding,pending=None,units={})
    if not isinstance(state,dict) or set(state)!={'version','binding','pending','units'} or state['version']!=1 or state['binding']!=binding:
        raise ValueError('Collection checkpoint changed subjects, adapter versions or policy')
    if not isinstance(state['units'],dict) or set(state['units'])-set(ids):raise ValueError('Foreign checkpoint subject')
    # Validate the entire committed snapshot before any adapter can dispatch.
    for subject_id,results in state['units'].items():
        if not isinstance(results,dict) or set(results)-set(adapter_ids):raise ValueError('Foreign checkpoint source adapter')
        closed=False
        for index,name in enumerate(adapter_ids):
            if name not in results:
                if any(later in results for later in adapter_ids[index+1:]):raise ValueError('Checkpoint skips a source adapter')
                break
            outcome=results[name]
            if closed or not isinstance(outcome,dict) or outcome.get('id')!=subject_id or outcome.get('status') not in ('found','missing'):
                raise ValueError('Invalid committed collection outcome')
            closed=outcome['status']=='found'
    if state['pending'] is not None:
        pending=state['pending']
        if not isinstance(pending,dict) or set(pending)!={'subject','adapter','version'} or pending['subject'] not in ids or pending['adapter'] not in adapter_ids:
            raise ValueError('Invalid pending collection intent')
        adapter=adapters[adapter_ids.index(pending['adapter'])]
        if pending['version']!=adapter['version']:raise ValueError('Pending source version changed')
        raise PendingCollection('Collection has an unresolved source intent; reconcile its exact receipt before continuation')
    def save():
        if commit:commit(copy.deepcopy(state))
    entries=[]
    for start in range(0,len(subjects),batch_size):
        for subject in subjects[start:start+batch_size]:
            results=state['units'].setdefault(subject['id'],{})
            if set(results)-set(adapter_ids):raise ValueError('Foreign checkpoint source adapter')
            chosen=None
            for adapter in adapters:
                name=adapter['id']
                if name in results:
                    outcome=results[name]
                else:
                    state['pending']=dict(subject=subject['id'],adapter=name,version=adapter['version'])
                    save()  # Receipt intent precedes external dispatch.
                    outcome=adapter['collect'](subject)
                    if not isinstance(outcome,dict) or outcome.get('id')!=subject['id'] or outcome.get('status') not in ('found','missing'):
                        raise ValueError('Source adapter must return the exact subject with an explicit found/missing outcome')
                    results[name]=copy.deepcopy(outcome);state['pending']=None;save()
                if outcome.get('id')!=subject['id'] or outcome.get('status') not in ('found','missing'):
                    raise ValueError('Invalid committed collection outcome')
                chosen=copy.deepcopy(outcome)
                if outcome['status']=='found':break
            entries.append(chosen)
    return entries,state


def coverage(subjects,records,goal,qualifies=lambda option:True):
    """Count validated data, never snippets/pages; retain zero and excess results."""
    if type(goal) is not int or goal<0:raise ValueError('Invalid collection goal')
    by_id={r['id']:r for r in records}
    if len(by_id)!=len(records):raise ValueError('Duplicate collected subject identity')
    result=[]
    for subject in subjects:
        item=by_id.get(subject['id'],{'options':[]})
        count=sum(bool(qualifies(o)) for o in item['options'])
        result.append(dict(item=subject['id'],supported_options=count,goal=goal,shortfall=max(0,goal-count)))
    return result


def join(partitions,subject_ids,*,key,validate):
    """Content adapters verify versions/reviews; this engine owns exact coverage."""
    wanted=list(subject_ids)
    if len(set(wanted))!=len(wanted):raise ValueError('Duplicate expected subject identity')
    by_id={}
    for records in partitions:
        for record in records:
            validate(record)
            ident=key(record)
            if ident in by_id:raise ValueError('Duplicate inventory item across partitions')
            if ident not in wanted:raise ValueError('Foreign subject in collection partition')
            by_id[ident]=record
    if set(by_id)!=set(wanted):raise ValueError('Partition coverage differs from the exact full inventory')
    return [by_id[ident] for ident in wanted]


def chunks(values,size):
    if type(size) is not int or size<1:raise ValueError('Invalid collection chunk capacity')
    return [values[start:start+size] for start in range(0,len(values),size)]


def coverage_queries(subjects):
    """One authored query per subject per pass; preserve all exact strings."""
    result=[];seen=set()
    for n in range(max((len(s['queries']) for s in subjects),default=0)):
        for subject in subjects:
            if n<len(subject['queries']):
                q=subject['queries'][n]
                if q not in seen:seen.add(q);result.append(q)
    return result


def fallback_queries(subjects,states,existing,*,suffix,maximum=20,avoid=None):
    """Policy transforms authored queries; no invented subjects, URLs or facts."""
    pending={s['item'] for s in states if s['shortfall']}
    used={q.casefold() for q in existing};result=[]
    by_id={s['item']:s for s in states}
    # Zero coverage before deepening already represented subjects; stable ties.
    ordered=sorted(subjects,key=lambda s:by_id.get(s['id'],{}).get('supported_options',0))
    for subject in ordered:
        if subject['id'] not in pending:continue
        for original in subject['queries']:
            extra=''.join(' -site:'+host for host in (avoid or {}).get(subject['id'],[])[:3])
            # Never truncate authored country, price or subject constraints.
            tail=extra+suffix
            query=original+tail if len(original+tail)<=250 else original+extra if len(original+extra)<=250 else original+suffix if len(original+suffix)<=250 else original
            if query.casefold() in used:continue
            used.add(query.casefold())
            result.append(dict(id=subject['id'],queries=[query],required_options=subject['required_options']))
            break
        if len(result)>=maximum:break
    return result
