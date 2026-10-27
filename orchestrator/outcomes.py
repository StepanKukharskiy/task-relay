"""Shared result policy: distinguish advisory limitations from required user decisions."""
CATEGORIES = ('advisory', 'quality', 'requirements', 'execution', 'integrity', 'authorization', 'uncertainty')
GATE = 'Review the noted quality concerns and accept these exact outputs as-is'
INSTRUCTIONS = '''Classify concrete findings in the findings array (use [] when none): each has category, code, message, evidence.
Use advisory for disclosed limitations or optional refinements when the assigned criteria are met and no user decision is necessary.
Advisories preserve evidence and continue downstream work; they never establish user acceptance.
Use quality only when a genuine subjective choice requires the user to decide before the authorized work can proceed.
Do not request aesthetic approval for honestly disclosed sourcing alternatives or buyer checks.
Broken required deliverable links are integrity findings to repair, not optional aesthetic choices.
Judge the assigned task and its frozen criteria, not every later stage of the overall request.
For intermediate receipt reviews, record downstream product/coverage gaps in the report;
do not add blocking findings unless they violate the reviewed task criteria. Passing a
transport criterion does not approve downstream products or satisfy final coverage.
Use requirements when required item coverage, option counts, substantive deliverables
or product-specific evidence are missing. Generic sources are not a usable substitute
for requested product matches. Missing mandatory work stops downstream tasks;
accepting a file as-is does not establish its absent facts or satisfy later criteria.
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
    if kinds-{'quality','advisory'}:return 'block'
    return 'user_review' if 'quality' in kinds else 'continue'


def quality(code,message,evidence):
    return dict(category='quality',code=code,message=message,evidence=evidence)
