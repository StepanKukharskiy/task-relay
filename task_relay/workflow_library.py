"""Bundled starting points, not installed integrations or execution authority."""
import argparse
import copy
import hashlib
import json


def stage(ident, title, tools, inputs, outputs, review, instructions):
    return dict(id=ident,title=title,tools=tools,inputs=inputs,outputs=outputs,
                review=review,instructions=instructions)


WORKFLOWS = [
    dict(id='research-report',version=2,title='Research → evidence → report',stages=[
        stage('research','Collect and check sources',['browser.research'],
            ['Research question','Date range and source scope'],['Source ledger','Evidence brief'],
            'Check citations, dates, uncertainty and missing evidence.',
            'Research the stated question and independently check the claims. Record source URLs and retrieval dates. Stop at the evidence brief.'),
        stage('report','Write the report',['files.text','code.execute'],['Selected evidence brief','Report requirements'],
            ['Editable report','Source links'],'Review factual support and document readability.',
            'Use the selected evidence to create the requested report. Preserve uncertainty and inspect the exported document.')]),
    dict(id='architecture-presentation',version=4,title='Architecture research → model → visualization → presentation',stages=[
        stage('research','Research constraints and precedents',['browser.research'],['Brief','Site evidence','Applicable requirements'],
            ['Constraint register','Cited precedent brief'],'Review sources and proposed design criteria.',
            'Prepare a cited architectural research brief and constraints. Perplexity is an optional source only when configured and explicitly requested; no design or modeling yet.'),
        stage('concept','Develop and review a concept',['files.text'],['Selected research','Design requirements'],
            ['Concept description','Model specification'],'Select a concept before modeling.',
            'Produce a scoped concept and a concrete model specification. Preserve mandatory constraints and identify unresolved design choices.'),
        stage('model','Build or revise the selected model',['native.model'],['Selected concept','Exact native sources where editing'],
            ['Native model','Preview','Reopen checks'],'Inspect model and previews; select an exact version.',
            'Choose the requested application. First prepare missing exact manifests/scripts and review them. Host execution needs a separate approved stage once exact files exist.'),
        stage('visualization','Visualize the selected model',['image.edit'],['Exact selected model preview','Material and lighting brief'],
            ['Generated visualization','Reference correspondence notes'],'Review visual correspondence with the selected model.',
            'When visualization is requested, use the exact selected viewport image as the reference for the connected image provider. Preserve massing and camera intent. Review correspondence; an AI image is not a geometry-verified renderer. Do not substitute an unrelated image or send the raw native model to an image-only operation.'),
        stage('presentation','Build a presentation',['files.text','code.execute','pptx.create'],['Selected model previews','Selected visualization when requested','Selected concept','Audience and format'],
            ['PPTX','Preview images'],'Inspect slides and editable file.',
            'Select pptx.create after checking availability. Prepare and independently review slides.json from selected sources, then create and review the editable PPTX. Preview images require a separate verified renderer of that actual file. Native Keynote and Google Slides adapters are not qualified; do not claim those integrations or publish automatically.')]),
    dict(id='model-revision',version=2,title='Native model → scoped revision → checked candidate',stages=[
        stage('inspect','Inspect the exact source model',['native.inspect'],['Exact .blend or .3dm','Requested change'],
            ['Scene inventory','Scoped edit plan'],'Confirm source identity and edit scope.',
            'Use the matching registered inspect operation on the exact artifact. Report object identities and dependencies; do not modify the source.'),
        stage('prepare','Prepare the exact edit',['files.text','code.execute'],['Scene inventory','Requested change'],
            ['Edit script','Checks manifest'],'Independently review exact code and checks.',
            'Prepare and review the requested edit against the registered Blender or Rhino contract. Stop before host execution.'),
        stage('apply','Apply and inspect a candidate',['native.model'],['Exact scene','Reviewed script','Checks'],
            ['Native candidate','Matching preview','Reopen checks'],'Select the candidate; checks do not imply acceptance.',
            'Propose the matching registered run_python operation on exact artifacts. Preserve the original and inspect candidate geometry and appearance.')]),
    dict(id='carousel-reel',version=2,title='Approved carousel → reel → review',stages=[
        stage('adaptation','Prepare the adaptation',['files.text','code.execute'],['Approved cards','Exact assets','Applicable guides','Current request and established preferences'],
            ['Adaptation brief','Card and asset correspondence'],
            'Review titles, order, imagery, adaptation mode and duration/readability conflicts.',
            'Resolve exact adaptation versus authorized summary from the current request and applicable established preferences. Ask only if unresolved. Preserve approved card content in exact mode. Stop at the adaptation brief; no media production.'),
        stage('production','Produce and inspect the reel',['code.execute','media.compose'],['Selected adaptation brief','Approved cards and assets','Qualified media tools'],
            ['Editable composition','First render','Correspondence report'],
            'Inspect framing, readability, imagery, audio and ending; user acceptance is separate from technical checks.',
            'Use exact selected inputs and the requested production tools. Preserve the first output before corrections. Media tooling must be verified in the chosen execution environment before proposing this stage.')]),
    dict(id='data-presentation',version=3,title='Data → analysis → charts → presentation',stages=[
        stage('analysis','Validate and analyze data',['files.text','code.execute'],['Exact CSV/XLSX','Question','Definitions and units'],
            ['Analysis report','Reproducible calculations','Chart data'],'Check formulas, missing values, units and evidence for conclusions.',
            'Validate the selected dataset and produce reproducible calculations and chart data. Distinguish observations from interpretations. Stop before presentation production.'),
        stage('presentation','Build and inspect the presentation',['files.text','code.execute','pptx.create'],['Selected analysis','Audience','Design requirements'],
            ['Editable PPTX','Charts','Source workbook where applicable'],
            'Inspect chart labels, scales, slide layout and consistency with source data.',
            'Select pptx.create after checking availability. Prepare and independently review slides.json with native chart data, then create and review the actual editable deck. Preserve source data and formulas in the source workbook; do not publish or send to another app without explicit authorization.')]),
]

INSTRUCTIONS = '''snapshot.starter_workflows is the bundled workflow catalog.
These are versioned starting points, not permission to execute an entire pipeline.
For a user's request to use one, plan_production may include starter_workflow (exact
catalog id) and starter_stage (exact stage id). Use template="custom" for a single
requested stage. For a full workflow request, use plan_pipeline to derive all
requested stages from these starting points and the user's brief. Its scheduler
continues after completed work and explicit selections; do not require a new request
for every stage. Omit optional outcomes the user did not request. Honor requested
apps/providers, inputs and review gates. Required tools listed in a template are
requirements, not proof of installation or compatibility. Check the current
capability/executor catalog; unsupported native app operations remain handoffs.
Create task-specific worker roles from the brief; no starter requires its own
hardcoded domain agent. files.text, files.binary, code.execute and browser.use are
worker requirements resolved against the captured executor catalog. browser.research
maps to the research route; image.edit maps to a configured reference-image route.
native.model/native.inspect mean the matching requested Rhino OR Blender registered
operation, never both by default. pptx.create is a registered operation. media.compose
is an environment requirement, not a worker capability: verify a composition/render
runtime separately. Do not invent its availability from shell access or a video model.
Do not run outside the agreed pipeline, infer acceptance, install tools, or hide
missing integrations. A catalog/status question has action=null. Present the list
without launching analysis. The exact selected definition is frozen in each plan.
'''


def definition(ident):
    value = next((w for w in WORKFLOWS if w['id']==ident),None)
    if value is None:
        raise ValueError('Unknown starter workflow. Use /templates to list the bundled workflows.')
    return copy.deepcopy(value)


def freeze(ident, stage_id=None):
    value = definition(ident)
    selected = stage_id or value['stages'][0]['id']
    if not any(s['id']==selected for s in value['stages']):
        raise ValueError('Choose a stage from the selected starter workflow.')
    digest = hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(definition=value,sha256=digest,stage=selected)


def catalog():
    return copy.deepcopy(WORKFLOWS)


def describe(ident=''):
    if not ident:
        return ('Bundled workflows:\n'+ '\n'.join(w['id']+' — '+w['title'] for w in WORKFLOWS)+
            '\n\nUse /templates ID for stages, or ask Relay to prepare a workflow for your project. '
            'A full workflow request gets a saved plan that continues through its agreed stages and decisions. Tools and connections must be available; nothing starts from listing this catalog.')
    w=definition(ident.strip())
    lines=[w['title']+' · v'+str(w['version'])]
    for s in w['stages']:
        lines += ['\n'+s['id']+': '+s['title'], 'Tools: '+', '.join(s['tools']),
            'Inputs: '+', '.join(s['inputs']), 'Outputs: '+', '.join(s['outputs']), 'Review: '+s['review']]
    return '\n'.join(lines)+'\n\nTemplates do not install or authorize tools. Request a specific stage or a full workflow. A saved workflow continues after completed stages and your selections; native code still needs its exact Start approval.'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id',nargs='?',default='')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    try:
        print(json.dumps(definition(args.id) if args.id else catalog(),indent=2) if args.json else describe(args.id))
    except ValueError as exc:
        parser.error(str(exc))
