"""Complete missing internal preparation reviews within a frozen delivery grant."""
import copy


def bind_arguments(plan,scope):
    """Review receipts gate operations; they are not extra wire arguments."""
    if scope.get('connector_companions_version')!=1:return []
    tasks={t['id']:t for t in plan['tasks']};specs={s['id']:s for s in scope.get('graph_operations',[])}
    receipts=[]
    for operation in tasks.values():
        spec=specs.get(operation.get('execution',{}).get('capability'),{})
        if not spec:continue
        inputs=operation['inputs'];arguments=[];reviews=[]
        for item in inputs:
            author=tasks.get(item.get('from_task'),{})
            if (author.get('review_of') and any(i.get('from_task')==author['review_of'] for i in inputs)
                    and any(o['path']==item.get('output') for o in author['outputs'])):
                reviews.append(item)
            else:arguments.append(item)
        if not reviews:continue
        # Only repair a uniquely typed argument set against this frozen connector.
        if not spec.get('min_inputs',0)<=len(arguments)<=spec['max_inputs'] or any(i.get('media_type') not in spec['input_types'] for i in arguments):continue
        operation['inputs']=arguments
        operation['dependencies']=list(dict.fromkeys(operation['dependencies']+[i['from_task'] for i in reviews]))
        receipts.append(dict(operation=operation['id'],review_receipts=copy.deepcopy(reviews),
            source='frozen operation wire schema and exact independent input-review outputs',
            reason='retain reviews as completion dependencies rather than operation arguments'))
    return receipts


def bind(proposal, scope, options):
    if (scope.get('connector_companions_version')!=1
            or scope.get('delivery_completion_policy_version')!=1):return []
    tasks=proposal.get('plan',{}).get('tasks',[])
    specs={s['id']:s for s in scope.get('graph_operations',[])}
    delivered={v.get('task') for v in proposal.get('deliverable_map',{}).values() if isinstance(v,dict)}
    receipts=[]
    for producer in list(tasks):
        native=specs.get(producer.get('execution',{}).get('capability'),{})
        pure_json=(native.get('kind')=='procedure' and native.get('external_requests')==0
                   and native.get('output_type')=='application/json')
        if (producer.get('execution') and not pure_json or producer.get('review_of') or producer.get('user_gate')
                or producer['id'] in delivered):continue
        if any(t.get('review_of')==producer['id'] for t in tasks):continue
        consumers=[t for t in tasks if specs.get(t.get('execution',{}).get('capability'),{}).get('kind')=='procedure'
                   and any(i.get('from_task')==producer['id'] for i in t.get('inputs',[]))]
        if not consumers:continue
        ident=producer['id']+'_input_review'
        if len(ident)>80 or ident in {t['id'] for t in tasks}:
            raise ValueError('Preparation review ID conflicts with the proposed graph.')
        if len(tasks)>=options.get('max_tasks',6):
            raise ValueError('Required preparation review exceeds the frozen task ceiling.')
        reviewer=dict(id=ident,role='reviewer',review_of=producer['id'],
            objective='Independently verify the exact prepared connector inputs',
            instruction='Inspect every prepared output against its declared criteria and exact source evidence. Report unsupported references and gaps explicitly. Do not conduct new research or modify source files.',
            inputs=[dict(from_task=producer['id'],output=o['path'],path='candidate/'+o['path'],
                         purpose=o['purpose'],authority='Unaccepted prepared input',
                         **({'media_type':o['media_type']} if o.get('media_type') else {})) for o in producer['outputs']],
            outputs=[dict(path='input-review.md',purpose='Independent preparation findings',media_type='text/markdown')],
            dependencies=[producer['id']],criteria=copy.deepcopy(producer['criteria']),
            limits=dict(seconds=min(300,options['limits']['seconds']),tool_calls=min(10,options['limits']['tool_calls']),
                        output_bytes=min(100000,options['limits']['output_bytes'])),
            max_attempts=min(2,options.get('max_attempts',1)))
        if pure_json:reviewer['worker']={'requires':['files.text']}
        elif producer.get('worker'):reviewer['worker']=copy.deepcopy(producer['worker'])
        else:reviewer['tools']=copy.deepcopy(producer.get('tools',['files']))
        tasks.append(reviewer)
        for consumer in consumers:
            consumer['dependencies']=list(dict.fromkeys(consumer.get('dependencies',[])+[ident]))
        receipts.append(dict(producer=producer['id'],reviewer=ident,consumers=[t['id'] for t in consumers],
                             source='required independent producer review within frozen delivery grant'))
    return receipts
