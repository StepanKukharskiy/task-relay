"""Bundled starting points, not installed integrations or execution authority."""
import argparse
import copy
import hashlib
import json


def stage(ident, title, tools, inputs, outputs, review, instructions):
    return dict(id=ident,title=title,tools=tools,inputs=inputs,outputs=outputs,
                review=review,instructions=instructions)


WORKFLOWS = [
    dict(id='research-report',version=1,title='Research → evidence → report',stages=[
        stage('research','Collect and check sources',['browser/research'],
            ['Research question','Date range and source scope'],['Source ledger','Evidence brief'],
            'Check citations, dates, uncertainty and missing evidence.',
            'Research the stated question and independently check the claims. Record source URLs and retrieval dates. Stop at the evidence brief.'),
        stage('report','Write the report',['codex/files-shell'],['Selected evidence brief','Report requirements'],
            ['Editable report','Source links'],'Review factual support and document readability.',
            'Use the selected evidence to create the requested report. Preserve uncertainty and inspect the exported document.')]),
    dict(id='architecture-presentation',version=2,title='Architecture research → model → presentation',stages=[
        stage('research','Research constraints and precedents',['browser/research'],['Brief','Site evidence','Applicable requirements'],
            ['Constraint register','Cited precedent brief'],'Review sources and proposed design criteria.',
            'Prepare a cited architectural research brief and constraints. Perplexity is an optional source only when configured and explicitly requested; no design or modeling yet.'),
        stage('concept','Develop and review a concept',['codex/files-shell'],['Selected research','Design requirements'],
            ['Concept description','Model specification'],'Select a concept before modeling.',
            'Produce a scoped concept and a concrete model specification. Preserve mandatory constraints and identify unresolved design choices.'),
        stage('model','Build or revise the selected model',['blender/registered-host','rhino/registered-host'],['Selected concept','Exact native sources where editing'],
            ['Native model','Preview','Reopen checks'],'Inspect model and previews; select an exact version.',
            'Choose the requested application. First prepare missing exact manifests/scripts and review them. Host execution needs a separate approved stage once exact files exist.'),
        stage('presentation','Build a presentation',['codex/files-shell','pptx.create'],['Selected model previews','Selected concept','Audience and format'],
            ['PPTX','Preview images'],'Inspect slides and editable file.',
            'Select pptx.create after checking availability. Prepare and independently review slides.json from selected sources, then create and review the editable PPTX. Preview images require a separate verified renderer of that actual file. Native Keynote and Google Slides adapters are not qualified; do not claim those integrations or publish automatically.')]),
    dict(id='model-revision',version=1,title='Native model → scoped revision → checked candidate',stages=[
        stage('inspect','Inspect the exact source model',['blender/registered-host','rhino/registered-host'],['Exact .blend or .3dm','Requested change'],
            ['Scene inventory','Scoped edit plan'],'Confirm source identity and edit scope.',
            'Use the matching registered inspect operation on the exact artifact. Report object identities and dependencies; do not modify the source.'),
        stage('prepare','Prepare the exact edit',['codex/files-shell'],['Scene inventory','Requested change'],
            ['Edit script','Checks manifest'],'Independently review exact code and checks.',
            'Prepare and review the requested edit against the registered Blender or Rhino contract. Stop before host execution.'),
        stage('apply','Apply and inspect a candidate',['blender/registered-host','rhino/registered-host'],['Exact scene','Reviewed script','Checks'],
            ['Native candidate','Matching preview','Reopen checks'],'Select the candidate; checks do not imply acceptance.',
            'Propose the matching registered run_python operation on exact artifacts. Preserve the original and inspect candidate geometry and appearance.')]),
    dict(id='carousel-reel',version=1,title='Approved carousel → reel → review',stages=[
        stage('adaptation','Prepare the adaptation',['codex/files-shell'],['Approved cards','Exact assets','Applicable guides','Current request and established preferences'],
            ['Adaptation brief','Card and asset correspondence'],
            'Review titles, order, imagery, adaptation mode and duration/readability conflicts.',
            'Resolve exact adaptation versus authorized summary from the current request and applicable established preferences. Ask only if unresolved. Preserve approved card content in exact mode. Stop at the adaptation brief; no media production.'),
        stage('production','Produce and inspect the reel',['codex/media-tools'],['Selected adaptation brief','Approved cards and assets','Qualified media tools'],
            ['Editable composition','First render','Correspondence report'],
            'Inspect framing, readability, imagery, audio and ending; user acceptance is separate from technical checks.',
            'Use exact selected inputs and the requested production tools. Preserve the first output before corrections. Media tooling must be verified in the chosen execution environment before proposing this stage.')]),
    dict(id='data-presentation',version=2,title='Data → analysis → charts → presentation',stages=[
        stage('analysis','Validate and analyze data',['codex/files-shell'],['Exact CSV/XLSX','Question','Definitions and units'],
            ['Analysis report','Reproducible calculations','Chart data'],'Check formulas, missing values, units and evidence for conclusions.',
            'Validate the selected dataset and produce reproducible calculations and chart data. Distinguish observations from interpretations. Stop before presentation production.'),
        stage('presentation','Build and inspect the presentation',['codex/files-shell','pptx.create'],['Selected analysis','Audience','Design requirements'],
            ['Editable PPTX','Charts','Source workbook where applicable'],
            'Inspect chart labels, scales, slide layout and consistency with source data.',
            'Select pptx.create after checking availability. Prepare and independently review slides.json with native chart data, then create and review the actual editable deck. Preserve source data and formulas in the source workbook; do not publish or send to another app without explicit authorization.')]),
]

INSTRUCTIONS = '''snapshot.starter_workflows is the bundled workflow catalog.
These are versioned starting points, not permission to execute an entire pipeline.
For a user's request to use one, plan_production may include starter_workflow (exact
catalog id) and starter_stage (exact stage id). Use template="custom". Plan just
the requested stage, or its first stage if starting the workflow. Honor requested
apps/providers, inputs and review gates. Required tools listed in a template are
requirements, not proof of installation or compatibility. Check the current
capability/executor catalog; unsupported native app operations remain handoffs.
Do not automatically run later stages, infer acceptance, install tools, or hide
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
        return ('Bundled workflows (v1):\n'+ '\n'.join(w['id']+' — '+w['title'] for w in WORKFLOWS)+
            '\n\nUse /templates ID for stages, or ask Relay to prepare a workflow for your project. '
            'Each selected stage gets a concrete plan. Tools and connections must be available; nothing starts from listing this catalog.')
    w=definition(ident.strip())
    lines=[w['title']+' · v'+str(w['version'])]
    for s in w['stages']:
        lines += ['\n'+s['id']+': '+s['title'], 'Tools: '+', '.join(s['tools']),
            'Inputs: '+', '.join(s['inputs']), 'Outputs: '+', '.join(s['outputs']), 'Review: '+s['review']]
    return '\n'.join(lines)+'\n\nTemplates do not install or authorize tools. Ask to prepare a specific stage for a project; later stages require separate requests and selected inputs.'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id',nargs='?',default='')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    try:
        print(json.dumps(definition(args.id) if args.id else catalog(),indent=2) if args.json else describe(args.id))
    except ValueError as exc:
        parser.error(str(exc))
