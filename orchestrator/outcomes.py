"""Shared result policy: usable quality concerns need a user decision, not replay."""
CATEGORIES = ('quality', 'execution', 'integrity', 'authorization', 'uncertainty')
GATE = 'Review the noted quality concerns and accept these exact outputs as-is'
INSTRUCTIONS = '''Classify concrete findings in the findings array (use [] when none): each has category, code, message, evidence.
Use quality for usable outputs with design, visual, dimension, completeness or source-correspondence concerns.
Show actual evidence and preview paths; never claim visual inspection without pixels.
For usable outputs report delivered (producer) or accept/revise (reviewer), with quality findings.
Quality concerns require the user's feedback, not automatic acceptance or repair. The scheduler holds dependent work.
Use execution for failed code/tools, integrity for missing/corrupt files or invalid evidence,
authorization for missing permission, and uncertainty when the execution outcome is unknown.
These stop work; never relabel them quality to obtain delivery. Return blocked if no usable result or required evidence exists.
An empty findings list means no additional findings, not user acceptance. Preserve the frozen scope and artifact identities.
'''
SCHEMA = {'type':'array','maxItems':100,'items':{
    'type':'object','additionalProperties':False,
    'properties':{'category':{'type':'string','enum':list(CATEGORIES)},
        'code':{'type':'string'},'message':{'type':'string'},'evidence':{'type':'string'}},
    'required':['category','code','message','evidence']}}


def validate(findings):
    if not isinstance(findings,list) or len(findings)>100:raise ValueError('Invalid result findings.')
    for f in findings:
        if (not isinstance(f,dict) or set(f)!={'category','code','message','evidence'}
            or f['category'] not in CATEGORIES
            or any(not isinstance(f[k],str) or not f[k].strip() or len(f[k])>4000 for k in f)):
            raise ValueError('Findings require a known category, code, message and concrete evidence.')
    return findings


def disposition(findings):
    validate(findings)
    kinds={f['category'] for f in findings}
    if 'uncertainty' in kinds:return 'reconcile'
    if kinds-{'quality'}:return 'block'
    return 'user_review' if kinds else 'continue'


def quality(code,message,evidence):
    return dict(category='quality',code=code,message=message,evidence=evidence)
