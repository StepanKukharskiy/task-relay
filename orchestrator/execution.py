"""Versioned graph capabilities. Plans choose registered operations, never commands."""
import copy
import importlib.util
import re
from .media_adapters import PROVIDERS as IMAGE_PROVIDERS
from .cloud_media import SPECS as CLOUD_MEDIA
from .native_apps import profile as native_profile

TEXT_TYPES = ('text/plain','text/markdown')
REGISTRY = {
    'text.bundle': {'version':1,'kind':'procedure','input_types':[*TEXT_TYPES,'application/json'],'output_type':'text/plain',
        'max_inputs':20,'input_bytes':2000000,'seconds':30,'output_bytes':2100000,
        'criteria':['Inputs are preserved verbatim in a UTF-8 bundle with artifact identities and hashes.'],
        'parameters':{},'external_requests':0,'cancellation':'Local process termination; no external effects.'},
    'gemini.text': {'version':1,'kind':'api','input_types':list(TEXT_TYPES),'output_type':'text/plain',
        'max_inputs':20,'input_bytes':120000,'seconds':180,'output_bytes':200000,
        'criteria':['The API returned complete nonempty text within the declared bounds; its content is not independently verified.'],
        'parameters':{'model':'Exact configured or explicitly chosen model ID','max_output_tokens':'Integer 1–4096'},
        'external_requests':1,'cancellation':'Stop local waiting; an accepted remote request cannot be undone and usage may remain unknown.'},
    'blender.startup': {'version':1,'kind':'host','input_types':list(TEXT_TYPES),'output_type':'application/json',
        'max_inputs':20,'input_bytes':2000000,'seconds':120,'output_bytes':200000,
        'outputs':{'delivery/execution.json':'application/json'},
        'criteria':['The fixed Blender startup probe has a recorded exit status, output and startup-marker result.'],
        'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; no automatic retry.',
        'permissions':'Host Blender process with normal OS permissions; fixed Relay probe only; no agent shell escalation.'},
    'blender.scene': {'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json'],'output_type':None,
        'max_inputs':20,'input_bytes':2000000,'seconds':600,'output_bytes':100000000,
        'outputs':{'delivery/scene.blend':'application/x-blender','delivery/preview.png':'image/png',
                   'delivery/scene-script.py':'text/plain','delivery/execution.json':'application/json'},
        'criteria':['The validated primitive scene is saved, reopened in a separate Blender process, checked and rendered to PNG.'],
        'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; partial files may remain; no retry.',
        'permissions':'Host Blender process with normal OS permissions; fixed Relay code and bounded primitive JSON only; no arbitrary scripts or existing blend inputs.'},
}

REGISTRY['images.crop'] = {
    'version':1,'kind':'procedure','input_types':['image/png','image/jpeg'],
    'min_inputs':1,'max_inputs':1,'input_bytes':10000000,'output_type':'image/png',
    'seconds':30,'output_bytes':10000000,'external_requests':0,
    'parameters':{'region':'[x,y,width,height] integer pixels after EXIF orientation'},
    'runtime_modules':['image_crop.py','browser_contract.py'],
    'criteria':['Exact source bytes and bounded region produced a PNG crop with recorded source/output hashes; no inferred pixels, object identity or acceptance.'],
    'permissions':'Local image decoding and cropping only; no network. An explicit downstream browser upload grant is required for visual search.',
    'cancellation':'Local process termination; original source remains immutable.'}

# File construction is explicit graph work, never a delivery-side effect.
for _name,_media in (
    ('images.pptx','application/vnd.openxmlformats-officedocument.presentationml.presentation'),
    ('images.gallery','text/html')):
    REGISTRY[_name] = {
        'version':1,'kind':'procedure','user_review':True,
        'description':'Export every acquired image and the advisory report as '+('an editable PowerPoint.' if _name=='images.pptx' else 'a self-contained HTML gallery.'),
        'input_types':['application/zip',*TEXT_TYPES],'output_type':_media,
        'min_inputs':2,'max_inputs':2,'input_bytes':50000000,
        'seconds':120,'output_bytes':50000000,'external_requests':0,
        'parameters':{'photos':'Exact acquired image bundle','recommendations':'Literal advisory report'},
        'criteria':['All acquired candidates and the literal advisory report are included; source image hashes and unavailable outcomes are preserved. Recommendations do not filter membership or imply user acceptance.'],
        'permissions':'Local format conversion only; no network, model, selection or arbitrary code.',
        'cancellation':'Stop local conversion; preserve original inputs and operation receipts.',
        'support_modules':['task_relay.image_gallery','orchestrator.image_sources',
                           'orchestrator.image_representation']+(['orchestrator.pptx_document','orchestrator.table_layout'] if _name=='images.pptx' else [])}

REGISTRY['web.sources'] = {
    'version': 1, 'kind': 'api', 'input_types': [], 'min_inputs': 0,
    'output_type': 'application/json', 'outputs': {'delivery/source-pack.json': 'application/json'},
    'max_inputs': 0, 'input_bytes': 0, 'seconds': 1800, 'output_bytes': 2000000,
    'criteria': ['The exact literal queries, grounded search candidates, fetched public page versions and failures are recorded; no source candidate is asserted as a verified fact.'],
    'parameters': {'queries': '1–20 distinct literal public search queries',
                   'domains': '0–8 exact allowed public domains; empty permits any public domain',
                   'model': 'Exact configured Gemini text model'},
    'external_requests': 60,
    'cancellation': 'Stop after the current request; an uncertain search submission is never replayed.',
    'permissions': 'Public Google-grounded search and bounded HTTPS page reads; no login, JavaScript or private network.'}

# Prepared research consumes exact reviewed query data instead of inventing
# item-specific queries before the upstream observations exist. Legacy stays fixed.
REGISTRY['web.sources.prepared'] = {
    **copy.deepcopy(REGISTRY['web.sources']),
    'input_types':['application/json'], 'min_inputs':1, 'max_inputs':1,
    'input_bytes':120000, 'external_requests':80,
    'parameters':{'domains':'0–8 exact public domains; [] permits any public domain',
                  'model':'Exact configured Gemini text model'},
    'criteria':['The exact query specification, target mappings, literal queries, grounded candidates, fetched public page versions and failures are recorded; candidates are not verified facts.']}

REGISTRY['web.sources.rendered']={
    'version':1,'kind':'procedure','input_types':['application/json'],'min_inputs':1,'max_inputs':1,
    'input_bytes':2000000,'output_type':'application/json','outputs':{'delivery/source-pack.json':'application/json'},
    'output_bytes':3000000,'seconds':900,'external_requests':12,
    'parameters':{'domains':'0–8 exact public domains; [] permits observed public domains','max_pages':'1–12 total direct HTTP or rendered read attempts; a fallback consumes another slot'},
    'criteria':['Original source entries are preserved; only observed public candidate URLs are read through the public HTTP reader or isolated unsigned-in browser, sharing the original total read allowance. Captures, hashes, method-specific failures and missing outcomes remain distinct from acceptance.'],
    'permissions':'Public HTTPS GET/HEAD/OPTIONS through the direct reader or isolated rendered browser; no accounts, forms, uploads, file downloads or invented URLs.',
    'cancellation':'Stop owned browser processes and retain outcomes; missing read outcomes are never automatically replayed.',
    'saved_evidence':{'capability':'web.sources','kind':'pages'}}
for _cap in ('web.sources','web.sources.prepared'):
    REGISTRY[_cap]['companions']={'web.sources.rendered':'observed-public-page-rendering-fallback'}

# Different authority, same observed-source interface and collection lifecycle.
# It is deliberately not injected into an existing isolated-browser grant.
REGISTRY['web.sources.native']={
    **copy.deepcopy(REGISTRY['web.sources.rendered']),
    'parameters':{'domains':'0–8 exact public domains','max_pages':'1–3 observed candidate URLs',
                  'browser':'safari-visual: explicit native computer-use transport',
                  'max_observations':'2–8 observations per page, including initial load and bounded scrolling'},
    'criteria':['Original source entries and failed reads remain intact; exact observed URLs are read through the explicitly granted native browser. Each bounded visible-text observation, action receipt and failure is retained as unverified evidence.'],
    'permissions':'Native Safari session and ordinary page-generated networking. Foreground dedicated window, exact-URL navigation, observation and scrolling only. No clicks, forms, login, uploads or downloads; not a request-method firewall.',
    'cancellation':'Existing native ownership controls stop further actions; uncertain actions are preserved and never replayed.',
    'browser_transport':'native', 'source_mode':'web.sources.rendered',
    'resources':['computer-safari'], 'external_requests':3}

from .reel_contract import OUTPUTS as REEL_OUTPUTS
from .hyperframes_contract import PREVIEW_OUTPUTS,RENDER_OUTPUTS,ASSET_TYPES
REGISTRY['hyperframes.preview']={
    'version':1,'kind':'procedure','review_correction':'application/json',
    'input_types':list(dict.fromkeys([*TEXT_TYPES,'application/json',*ASSET_TYPES])),
    'output_type':None,'outputs':PREVIEW_OUTPUTS,'max_inputs':100,'input_bytes':50000000,
    'seconds':600,'output_bytes':50000000,'parameters':{},'external_requests':0,
    'criteria':['The exact authored HyperFrames project passed local check, produced the declared full-size preview samples and a hash-bound editable bundle; source inputs are unchanged. Technical checks do not establish visual/editorial quality or user acceptance.'],
    'permissions':'Author-supplied front-end HTML/CSS/JavaScript runs in local Chromium. Fixed installed HyperFrames commands, scoped filesystem reads/writes, clean environment, external network denied; local sockets/loopback remain available. No Node programs, shell commands, downloads or package installation.',
    'cancellation':'Stop owned processes and retain evidence; confirmed failures may use an explicitly planned bounded source-correction loop. Never replay uncertain execution.'}
REGISTRY['hyperframes.render']={
    'version':1,'kind':'procedure','input_types':[*TEXT_TYPES,'application/json','application/zip'],
    'output_type':None,'outputs':RENDER_OUTPUTS,'max_inputs':20,'input_bytes':50000000,
    'seconds':1200,'output_bytes':50000000,'requires_registered_inputs':True,
    'parameters':{'project_sha256':'Exact selected preview project.zip SHA-256','preview_sha256':'Exact passed preview verification.json SHA-256'},
    'external_requests':0,
    'criteria':['The exact selected preview project was rechecked and rendered to H.264 with matching dimensions, FPS, frame count, duration and audio presence; source bundle and inputs are unchanged. Rendered samples require independent review and human visual selection.'],
    'permissions':'Same scoped local front-end execution as hyperframes.preview; exact registered project/preview hashes, no source regeneration.',
    'cancellation':'Stop owned processes; preserve partial files and receipts; no automatic replay.'}

REGISTRY['media.compose'] = {
    'version':1,'kind':'procedure','input_types':[*TEXT_TYPES,'application/json','image/png','image/jpeg','audio/mpeg','audio/wav'],
    'output_type':None,'outputs':REEL_OUTPUTS,'max_inputs':50,'input_bytes':50000000,
    'seconds':1200,'output_bytes':100000000,'parameters':{},'external_requests':0,
    'criteria':['The bounded scene specification produced an H.264 reel with matching dimensions, FPS, frame count, duration and audio presence, scene samples and an editable project; source inputs are unchanged. Technical checks do not establish visual/editorial quality or user acceptance.'],
    'permissions':'Fixed local HyperFrames/Chromium/FFmpeg commands with a clean environment and external network denied; loopback is permitted. Normal host file permissions; no arbitrary agent shell, HTML, JavaScript, downloads or generated audio.',
    'cancellation':'Stop owned rendering processes; preserve partial files and receipts; no automatic replay.'}

REGISTRY['pptx.create'] = {
    'review_correction':'application/json',
    'version':1, 'kind':'procedure',
    'input_types':[*TEXT_TYPES,'application/json','image/png','image/jpeg','application/zip'],
    'output_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'max_inputs':50, 'input_bytes':50000000, 'seconds':120, 'output_bytes':50000000,
    'criteria':['The bounded slide specification produced a PPTX that reopened with matching editable text, tables, chart data and embedded images; visual layout and Keynote import require separate review.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the local process; preserve partial results and never automatically replay.'}

from .pptx_render import MIME as PPTX_MIME, OUTPUTS as PPTX_PREVIEW_OUTPUTS
REGISTRY['pptx.render'] = {
    'version':1,'kind':'procedure','input_types':[PPTX_MIME],'output_type':None,'outputs':PPTX_PREVIEW_OUTPUTS,
    'min_inputs':1,'max_inputs':1,'input_bytes':50000000,'seconds':180,'output_bytes':50000000,
    'parameters':{},'external_requests':0,'review_evidence':True,
    'criteria':['The exact candidate PPTX opened in the verified compatible presentation renderer and every slide produced a hash-bound preview; source bytes are unchanged. Visual quality requires independent review; no PowerPoint or Keynote compatibility is inferred.'],
    'permissions':'Fixed owned headless compatible renderer and PDF rasterizer with an isolated temporary profile; no arbitrary scripts, source edits, software installation or interactive app attachment.',
    'cancellation':'Stop only owned renderer processes; preserve candidate and receipts.'}
REGISTRY['pptx.create']['companions']={'pptx.render':'independent-review-evidence'}

from .sourcing_slides import PARAMETERS as SOURCING_SLIDE_PARAMETERS
from .sourcing_merge import PARAMETERS as SOURCING_MERGE_PARAMETERS,OUTPUTS as SOURCING_MERGE_OUTPUTS
REGISTRY['sourcing.merge'] = {
    'version':1,'kind':'procedure','input_types':['application/json'],'output_type':'application/json',
    'outputs':SOURCING_MERGE_OUTPUTS,'min_inputs':4,'max_inputs':32,'input_bytes':12000000,
    'seconds':120,'output_bytes':6000000,'parameters':SOURCING_MERGE_PARAMETERS,'external_requests':0,
    'criteria':['Exact sealed sourcing partitions and version-bound independent supported reviews cover the full inventory without duplicates; original option goals, source versions and explicit gaps are preserved. This is not user acceptance.'],
    'cancellation':'Stop local composition; preserve inputs and receipts. No model or network.'}
for _cap in ('web.sources','web.sources.prepared'):
    REGISTRY[_cap].setdefault('companions',{})['sourcing.merge']='bounded-typed-record-partitions'
REGISTRY['web.sources.coverage'] = {
    'version':1,'kind':'procedure','input_types':['application/json'],'output_type':'application/json',
    'min_inputs':2,'max_inputs':2,'input_bytes':6000000,'seconds':900,'output_bytes':3000000,
    'parameters':{'catalog_path':'Exact independently reviewed typed catalog','source_pack_path':'Exact matching source pack',
                  'domains':'Same allowed public domains','model':'Exact configured Gemini text model'},
    'external_requests':80,'saved_evidence':{'capability':'web.sources','kind':'pages'},
    'criteria':['Exact reviewed product shortfalls selected bounded mapped subject queries; public candidates and failures are recorded. Search results are not verified products; new catalog records require independent semantic review.'],
    'permissions':'One bounded coverage round using public search and public page GETs within the original declared domain scope. No accounts, purchases or invented product URLs.',
    'cancellation':'Stop collection; retain request intents, responses and partial evidence; uncertain calls are not replayed.'}
for _cap in ('web.sources','web.sources.prepared'):
    REGISTRY[_cap].setdefault('companions',{})['web.sources.coverage']='reviewed-product-coverage-recovery'
for _cap in ('web.sources','web.sources.prepared','web.sources.coverage'):
    REGISTRY[_cap]['usage_source']='public-search-journals'
REGISTRY['sourcing.slides'] = {
    'version':1,'kind':'procedure','input_types':['application/json','image/png','application/zip'],
    'output_type':'application/json','min_inputs':4,'max_inputs':5,'input_bytes':50000000,
    'seconds':120,'output_bytes':2000000,'parameters':SOURCING_SLIDE_PARAMETERS,'external_requests':0,
    'criteria':['The exact typed inventory and source-bound catalog produced a schema-valid slide specification with editable image-map markers, captured prices, retailer links and explicit coverage/photo gaps. Semantic and visual quality require independent review.'],
    'cancellation':'Stop local assembly; retain inputs and receipt. No model or network request.'}

REGISTRY['pptx.edit'] = {
    'review_correction':'application/json', 'version':1, 'kind':'procedure',
    'input_types':['application/json','application/vnd.openxmlformats-officedocument.presentationml.presentation','image/png','image/jpeg'],
    'output_type':'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'min_inputs':2, 'max_inputs':20, 'input_bytes':51000000, 'seconds':120, 'output_bytes':50000000,
    'criteria':['The exact baseline PPTX and guarded manifest produced a new editable PPTX; every untargeted package part retained its bytes and edited text or pictures reopened correctly. Visual fit requires separate review.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Terminate the local process; preserve the baseline and partial evidence; never automatically replay.'}
REGISTRY['pptx.edit']['companions']={'pptx.render':'independent-review-evidence'}

REGISTRY['images.collect'] = {
    'conversation_execution':True,
    'version':1,'kind':'procedure','input_types':list(TEXT_TYPES),'output_type':'application/zip',
    'min_inputs':0,'max_inputs':20,'input_bytes':120000,'seconds':600,'output_bytes':45000000,
    'criteria':['At least one usable photo is collected. Each requested subject has a found or missing receipt; downloaded JPEG/PNG candidates retain source, author, licence and byte hashes. Metadata matches are not visual identification.'],
    'parameters':{'subjects':'1–40 {id,label,query} objects; literal public subject names; optional identity and exclude_titles'},
    'external_requests':320,
    'permissions':'Public read-only Wikimedia Commons search and image downloads; no credentials, paid model, generation or arbitrary URLs.',
    'cancellation':'Stop local downloads; retain receipts; no automatic replay.'}

# Viewing acquired pictures does not require another model to author advice.
# Existing reports remain exact optional inputs; every candidate is retained.
REGISTRY['images.gallery'].update(conversation_execution=True,min_inputs=1,
    optional_parameters=['recommendations'],input_defaults={'recommendations':None},
    description='Display every acquired image, source and explicit gap in a self-contained HTML gallery. An advisory report is optional; it never filters candidates.')

REGISTRY['images.fetch'] = {
    'version':1,'kind':'procedure','input_types':['application/json'],'output_type':'application/zip',
    'min_inputs':1,'max_inputs':1,'input_bytes':512000,'seconds':600,'output_bytes':45000000,
    'criteria':['At least one observed source image was downloaded and validated. Exact source URLs, image bytes, hashes and gaps are retained. Subject identity and reuse rights require independent review.'],
    'parameters':{},'external_requests':320,
    'permissions':'Public HTTPS GETs to observed image/publisher hosts, no credentials or cookies. Unknown author/licence remain explicitly unknown. No image generation.',
    'cancellation':'Stop downloads; retain evidence; no automatic replay.'}

REGISTRY['images.merge'] = {
    'version':1,'kind':'procedure','input_types':['application/zip'],'output_type':'application/zip',
    'min_inputs':2,'max_inputs':20,'input_bytes':45000000,'seconds':120,'output_bytes':45000000,
    'criteria':['Exact base photo subjects and found bytes are preserved; recovery bundles fill only missing subjects with hash-validated images and retained provenance. Full subject identity and suitability require independent review.'],
    'parameters':{},'external_requests':0,
    'permissions':'Local validation and byte-preserving ZIP composition only; no network, generation or arbitrary code.',
    'cancellation':'Stop local composition and retain receipts.'}

from .product_photos import PARAMETERS as PRODUCT_PHOTO_PARAMETERS
REGISTRY['images.products'] = {
    'user_review':True,
    'version':1,'kind':'procedure','input_types':['application/json'],'output_type':'application/zip',
    'min_inputs':2,'max_inputs':3,'input_bytes':12000000,'seconds':600,'output_bytes':45000000,
    'criteria':['Product images recorded on the exact source-bound catalog pages were downloaded and hash-validated; all found/missing receipts and original WebP/AVIF bytes are retained. Explicit target policy permits partial or empty coverage. Acquisition does not establish visual correspondence or rights; apply the workflow assessment policy.'],
    'parameters':PRODUCT_PHOTO_PARAMETERS,'external_requests':320,
    'permissions':'Public HTTPS GETs only to image references already captured in declared product-page evidence; no new search, cookies, credentials or invented URLs.',
    'cancellation':'Stop owned downloads; preserve evidence and never replay unknown requests.'}

# Receipt reuse is connector metadata. New read connectors must declare this
# boundary rather than accidentally fall through a capability-name list.
for _cap in ('web.sources','web.sources.prepared','images.fetch','images.products'):
    REGISTRY[_cap]['saved_evidence']={'capability':'web.sources' if _cap.startswith('web.sources') else _cap,
                                    'kind':'pages' if _cap.startswith('web.sources') else 'photos'}
for _cap in ('images.fetch','images.products'):
    REGISTRY[_cap]['completion_companions']={'images.merge':'partial-photo-composition'}

# Legacy operation names retain their definitions. New generic ports use the
# same native adapters and execution loop, with configurable content schemas.
REGISTRY['records.merge']={**copy.deepcopy(REGISTRY['sourcing.merge']),
    'parameters':{**SOURCING_MERGE_PARAMETERS,'field_definitions':'Registered field extraction rules','identity_field':'Observed identity field'},
    'criteria':['Exact sealed record partitions and version-bound independent supported reviews cover the declared subjects without duplicates; source versions, quantity policy and gaps are preserved. This is not user acceptance.']}
REGISTRY['collection.slides']={**copy.deepcopy(REGISTRY['sourcing.slides']),'min_inputs':3,
    'criteria':['Exact source-bound collected records produced an editable slide specification with captured fields, source links and explicit gaps. Semantic and visual quality require independent review.']}
REGISTRY['images.catalog']=copy.deepcopy(REGISTRY['images.products'])
REGISTRY['images.catalog']['parameters'].update(source_adapters='Ordered observed-pages and/or commons adapters',image_identity='page or subject; Commons requires subject')
for _cap in ('images.products','images.catalog'):
    REGISTRY[_cap]['evidence_revision']={
        'media_type':'application/zip',
        'admit':'orchestrator.image_sources:revision_contract',
        'validate':'orchestrator.image_sources:validate_revision',
        'project':'orchestrator.image_sources:revise_bundle',
        'repair':'orchestrator.image_sources:repair_revision',
        'instruction':'Create a new ZIP projection of the exact base. Quarantine only photographs rejected by the supplied independent review. Retain all original image and source-original bytes inside the delivered ZIP, referenced by rejected_evidence; quarantined entries stay missing and are never usable slide images. Never fetch replacements, generate pixels, relabel subjects or alter retained evidence. Use the supplied revision helper with a JSON object mapping exact manifest subject IDs to review-backed rejection reasons. Missing coverage is allowed by the frozen target policy. Retain other qualifications in the review report.'}
from .image_sources import MAX_BUNDLE_SUBJECTS,MAX_SUBJECT_REQUESTS
REGISTRY['images.catalog']['external_requests']=MAX_BUNDLE_SUBJECTS*MAX_SUBJECT_REQUESTS*2
for _cap in ('sourcing.merge','records.merge'):
    REGISTRY[_cap].setdefault('support_modules',[]).extend(['orchestrator.record_transfers','orchestrator.operation_contracts'])
for _cap in ('records.merge','collection.slides','images.catalog'):
    REGISTRY[_cap]['scope_versions']={'record_interfaces_version':1}
for _cap,_adapter in [('sourcing.merge','reviewed-record-merge'),('records.merge','reviewed-record-merge'),
                      ('sourcing.slides','record-slides'),('collection.slides','record-slides'),
                      ('images.products','catalog-images'),('images.catalog','catalog-images')]:
    REGISTRY[_cap]['native_adapter']=_adapter
    REGISTRY[_cap]['runtime_modules']=['collection_core.py','record_lifecycle.py']
    if _adapter=='catalog-images':
        REGISTRY[_cap]['preflight_recovery']='orchestrator.product_photos:preflight_recovery'
        REGISTRY[_cap]['revision_preview']='orchestrator.product_photos:revision_preview'
    if _adapter=='record-slides':
        REGISTRY[_cap]['review_workload']='orchestrator.sourcing_slides:review_workload'
        REGISTRY[_cap]['data_revision']='application/json'
for _cap in ('web.sources','web.sources.prepared'):
    REGISTRY[_cap].setdefault('companions',{})['records.merge']='registered-record-partitions'
REGISTRY['pptx.create']['companions']['collection.slides']='registered-record-projection'

# These adapters produce only local versioned artifacts. Recovery may propose
# new reviewed work from their confirmed receipts; this never replays a host
# action or makes the previous candidate accepted.
for _cap in ('sourcing.slides','collection.slides','sourcing.merge','records.merge',
             'pptx.create','pptx.edit','pptx.render'):
    REGISTRY[_cap]['completion_recovery']='local_artifact'
REGISTRY['images.catalog']['completion_companions']={'images.merge':'partial-photo-composition'}
for _cap in ('images.collect','images.fetch','images.products','images.catalog','sourcing.merge','records.merge','web.sources.coverage'):
    REGISTRY[_cap].setdefault('runtime_modules',[]).append('collection_core.py')
    REGISTRY[_cap]['runtime_modules']=list(dict.fromkeys(REGISTRY[_cap]['runtime_modules']))

for _cap in ('images.collect','images.fetch','images.products','images.catalog','web.sources','web.sources.prepared','web.sources.coverage'):
    REGISTRY[_cap]['support_modules']=['task_relay.orchestrator_web']
for _cap in ('web.sources','web.sources.prepared'):
    REGISTRY[_cap]['support_modules'].extend(['orchestrator.search_outcomes','orchestrator.provider_cooldown'])

# Separate versioned capability preserves existing primitive-only plan contracts.
REGISTRY.update(CLOUD_MEDIA)
REGISTRY['gemini.image'] = {
    'version':1,'kind':'api','input_types':[*TEXT_TYPES,'image/png','image/jpeg','image/webp'],
    'output_type':'image/png','max_inputs':20,'input_bytes':11000000,'seconds':600,'output_bytes':50000000,
    'criteria':['One complete valid generated image was saved as PNG; its visual and geometric fidelity requires separate review.'],
    'parameters':{'model':'Exact configured image model ID','max_output_tokens':'Integer 1–4096','aspect_ratio':'1:1, 16:9 or 9:16'},
    'external_requests':1,'cancellation':'Stop local waiting; accepted API work cannot be undone. Unknown submissions are never replayed.'}
REGISTRY['openai.image'] = {**copy.deepcopy(REGISTRY['gemini.image']),
    'parameters':{'model':'Exact configured GPT Image model ID','size':'auto, 1024x1024, 1536x1024 or 1024x1536',
                  'quality':'auto, low, medium or high'}}

REGISTRY['openrouter.image'] = {**copy.deepcopy(REGISTRY['gemini.image']),
    'parameters': {'model': 'Exact configured OpenRouter image model slug', 'aspect_ratio': '1:1, 16:9 or 9:16'}}

REGISTRY['blender.mesh_scene']={**copy.deepcopy(REGISTRY['blender.scene']),
    'input_bytes':20000000,
    'criteria':['The validated mesh scene is saved, reopened in a separate Blender process, checked against its geometry data and rendered to PNG.'],
    'permissions':'Host Blender process with normal OS permissions; fixed Relay code and bounded mesh/primitive data only; no arbitrary host scripts or existing blend inputs.'}

REGISTRY['blender.inspect']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/x-blender'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':120,'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact selected Blender scene has a complete bounded inventory, embedded auto-execution disabled and unchanged source-copy hash.'],
    'parameters':{},'external_requests':0,'cancellation':'Terminate the local process group; retain receipt and do not retry.',
    'permissions':'Host inspection of one selected .blend using fixed Relay code with embedded scripts disabled. Native linked libraries may resolve on the host; this is not dependency isolation.'}

# Fixed inspections may supply evidence to an already-declared reviewer.
REGISTRY['blender.inspect']['review_evidence'] = True

REGISTRY['blender.geometry']={**copy.deepcopy(REGISTRY['blender.inspect']),
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json','delivery/geometry.json':'application/json'},
    'output_bytes':12000000,
    'node_ui':dict(title='Export Blender geometry',inputs={'files':'Blender scene'},outputs={'geometry':'World mesh geometry'}),
    'description':'Export exact evaluated world mesh coordinates from the selected Blender scene without changing it.'}

REGISTRY['blender.run_python']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/x-blender','text/x-python','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/before.png':'image/png',
               'delivery/after.png':'image/png','delivery/edit.py':'text/plain','delivery/checks.json':'application/json',
               'delivery/execution.json':'application/json'},
    'criteria':['The exact approved script ran against the selected scene copy; a candidate reopened independently, passed the declared preservation/dimension checks and produced matching-camera previews; original input copies remain unchanged.'],
    'node_ui':dict(title='Run Blender Python',inputs={'scene_sha256':'Scene (empty for create)','script_sha256':'Python script','checks_sha256':'Scene checks'},outputs={'candidate':'Blender model','after':'Render preview'}),
    'parameters':{'scene_sha256':'Exact source scene reference; null for create. Legacy SHA-256 bindings remain supported.','script_sha256':'Exact Python input reference; bytes are bound at approval',
                  'checks_sha256':'Exact checks input reference; bytes are bound at approval','permissions':'unrestricted_host'},
    'external_requests':None,'cancellation':'Terminate the local process group; preserve partial results and never replay. Host script side effects cannot be undone.',
    'permissions':'Explicit exact-script host approval required. Python has normal host filesystem/network access; no workspace or network isolation is enforced. Embedded scene auto-execution stays disabled.'}


REGISTRY['blender.import_asset']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json','application/x-blender','image/png','image/jpeg'],
    'output_type':None,'max_inputs':50,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/preview.png':'image/png',
               'delivery/bundle.zip':'application/zip','delivery/manifest.json':'application/json',
               'delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['Exact selected assets were appended/packed into a candidate; the retained source bundle preserves paths, hashes and supplied provenance; its candidate reopened after relocation with matching scene and packed image hashes; original inputs remain unchanged.'],
    'parameters':{'manifest_sha256':'Exact registered asset manifest SHA-256'},'external_requests':0,
    'cancellation':'Terminate the local process group; preserve partial files and receipts; never replay automatically.',
    'permissions':'Fixed host append/packing code with embedded auto-execution disabled. Normal host permissions, not filesystem isolation. Only declared selected files are staged; no downloads, persistent links or arbitrary scripts.'}

REGISTRY['blender.animate']={'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/json','application/x-blender','application/zip'],
    'output_type':None,'max_inputs':30,'input_bytes':150000000,'seconds':1200,'default_seconds':1200,'output_bytes':100000000,
    'outputs':{'delivery/candidate.blend':'application/x-blender','delivery/animation.mp4':'video/mp4',
               'delivery/preview.png':'image/png','delivery/checkpoint.zip':'application/zip',
               'delivery/frames.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected scene and numeric animation contract produced an independently reopened candidate, verified frame/FPS and transform checks, hashed per-frame receipts and an encoded video with the exact frame count/dimensions/FPS; original inputs remain unchanged.'],
    'parameters':{'manifest_sha256':'Exact animation manifest input path or SHA-256',
                  'scene_sha256':'Exact Blender scene input path or SHA-256'},
    'optional_parameters':['scene_sha256'],'external_requests':0,
    'cancellation':'Terminate the local process group. Explicit continuation can reuse verified completed frames from a confirmed stopped attempt. Unresolved frame intents block; no automatic retry.',
    'permissions':'Fixed native Blender and ffmpeg operations with embedded scripts disabled, normal OS permissions. Numeric transforms only; no arbitrary Python, downloads or simulation. Output remains unselected.'}


REGISTRY['rhino3dm.create'] = {
    'version':1, 'kind':'procedure', 'input_types':[*TEXT_TYPES,'application/json'],
    'output_type':None, 'max_inputs':20, 'input_bytes':20000000, 'seconds':120, 'output_bytes':50000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/checks.json':'application/json',
               'delivery/execution.json':'application/json'},
    'criteria':['The bounded geometry specification produced a new .3dm, reopened with rhino3dm and checked for valid geometry, coordinates, topology, names, layers, colors, units and tolerance; source inputs are unchanged. These are library checks, not native Rhino or visual/source-fidelity verification.'],
    'parameters':{}, 'external_requests':0,
    'permissions':'Fixed local rhino3dm library code and bounded geometry JSON only. No user scripts, native app launch, plugins, rendering or network requests.',
    'cancellation':'Stop the local operation; preserve partial files and receipts; never automatically replay or fall back to Rhino.'}

REGISTRY['rhino.startup'] = {
    'version':1, 'kind':'host', 'input_types':list(TEXT_TYPES), 'output_type':None,
    'max_inputs':20, 'input_bytes':2000000, 'seconds':120, 'output_bytes':200000,
    'outputs':{'delivery/execution.json':'application/json'},
    'criteria':['The selected Rhino 7/8 runtime has an identity-bound interpreter result and transport evidence.'],
    'parameters':{}, 'external_requests':0,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. A shared script may continue; no automatic retry.',
    'permissions':'Fixed startup script with normal host permissions; macOS Rhino 7/8 desktop session required. No Grasshopper.'}

REGISTRY['rhino3dm.run_python'] = {
    'version':1,'kind':'host','execution_mode':'standalone_library',
    'input_types':[*TEXT_TYPES,'application/vnd.rhino','text/x-python','application/json','application/octet-stream','image/png','image/jpeg'],
    'output_type':None,'max_inputs':50,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/model.py':'text/plain',
               'delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved standalone Python used the installed rhino3dm API to create/edit a File3dm; the candidate reopened in a separate Python process with the approved archive version, valid geometry, declared preservation checks and unchanged input copies. Library checks do not establish native Rhino, visual or source-fidelity verification.'],
    'parameters':{'scene_sha256':'Exact primary source .3dm SHA-256 or null for create','script_sha256':'Exact reviewed Python SHA-256',
                  'checks_sha256':'Exact reviewed library checks SHA-256, including target file version','permissions':'unrestricted_host'},
    'requires_registered_inputs':True,'external_requests':None,
    'permissions':'Exact-script approval for standalone CPython and the full pinned rhino3dm Python API. Normal filesystem/network permissions, not OS isolation. The runner never launches Rhino; scripts must stay within their approved scope.',
    'cancellation':'Stop the supervised local process tree; preserve receipts and partial files. Uncertain script outcomes require reconciliation. Never automatically replay or switch to native Rhino.'}
REGISTRY['rhino.inspect'] = {
    **copy.deepcopy(REGISTRY['rhino.startup']), 'input_types':[*TEXT_TYPES,'application/vnd.rhino'],
    'input_bytes':100000000, 'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact selected .3dm has a complete bounded geometry/document inventory and unchanged source-copy hash.'],
    'permissions':'Fixed native .3dm inspection in an owned process or a separate document in connected Rhino 8. Native dependencies/plugins use normal host permissions; not filesystem isolation. No Grasshopper.'}
REGISTRY['rhino.inspect']['review_evidence'] = True

REGISTRY['rhino.run_python'] = {
    'version':1, 'kind':'host', 'input_types':[*TEXT_TYPES,'application/vnd.rhino','text/x-python','application/json'],
    'output_type':None, 'max_inputs':20, 'input_bytes':100000000, 'seconds':600, 'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/preview.png':'image/png',
               'delivery/model.py':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved Rhino Python created/edited an assigned document; the saved candidate reopened in a fresh headless document, passed declared geometry/preservation checks and produced a viewport preview; input copies remain unchanged.'],
    'parameters':{'scene_sha256':'Selected .3dm SHA-256, or null for a new model',
                  'script_sha256':'Exact reviewed source SHA-256 for the selected Rhino interpreter', 'checks_sha256':'Exact Rhino checks JSON SHA-256',
                  'permissions':'unrestricted_host'}, 'external_requests':None,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. A shared script may continue; retain its pending receipt and never replay. Script side effects cannot be undone.',
    'permissions':'Exact-script approval required for IronPython 2.7 (Rhino 7) or CPython 3 (Rhino 8)/RhinoCommon with normal host filesystem/network access. No OS isolation. Grasshopper authoring requires the separate rhino.grasshopper operation.'}

REGISTRY['rhino.document'] = {
    'version':1,'kind':'host','input_types':['application/json'],
    'output_type':None,'min_inputs':1,'max_inputs':1,'input_bytes':2000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.3dm':'application/vnd.rhino','delivery/preview.png':'image/png',
               'delivery/document.json':'application/json','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['Typed geometry, text, dimensions and named views were built by fixed code, saved and independently reopened in Rhino. Exact content and native geometry checks passed; visual fidelity and source assumptions require review.'],
    'parameters':{},'external_requests':0,
    'runtime_modules':['rhino_execution.py','rhino_contract.py','rhino_worker.py','rhino_document.py'],
    'permissions':'Fixed data-only document construction in Rhino 7/8; no model-supplied scripts, existing-document edits or arbitrary API calls.',
    'cancellation':REGISTRY['rhino.run_python']['cancellation']}

REGISTRY['rhino.render'] = {
    'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/vnd.rhino','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':10000000,
    'outputs':{'delivery/render.png':'image/png','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected model rendered through built-in Rhino Render from the exact named-view/resolution manifest; PNG dimensions and source-copy preservation were checked.'],
    'parameters':{'manifest_sha256':'Exact registered render manifest SHA-256'},'external_requests':0,
    'cancellation':'Stop the owned process or shared-session client only; never kill an existing Rhino. Retain partial files and pending receipts; no automatic replay.',
    'permissions':'Fixed host rendering with model materials/lighting and normal OS permissions. No arbitrary script, third-party renderer or model save; Grasshopper is outside this operation.'}

REGISTRY['rhino.grasshopper'] = {
    'version':1, 'kind':'host', 'input_types':[*TEXT_TYPES,'text/x-python','application/json','application/octet-stream'],
    'output_type':None, 'max_inputs':20, 'input_bytes':100000000, 'seconds':600, 'output_bytes':100000000,
    'outputs':{'delivery/candidate.gh':'application/vnd.grasshopper','delivery/candidate.ghx':'application/vnd.grasshopper',
               'delivery/definition.py':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The exact approved interpreter-specific Rhino 7/8 Python authored a new Grasshopper definition; official SaveQuiet wrote .gh and .ghx, both independently reopened and solved with preserved graph identities/wires, no runtime errors and exact declared output counts. Inputs remain unchanged; candidates await independent review and selection.'],
    'parameters':{'scene_sha256':'null; new definitions only','script_sha256':'Exact reviewed authoring Python SHA-256',
                  'checks_sha256':'Exact reviewed Grasshopper checks SHA-256','permissions':'unrestricted_host'},
    'requires_registered_inputs':True, 'external_requests':None,
    'permissions':'Exact script/checks/input approval for Rhino 7 IronPython 2.7 or Rhino 8 CPython 3 and installed Grasshopper/GhPython APIs, including embedded code during build and verification solves. Normal host filesystem/network permissions, not isolation. No edits to existing definitions, baking or UI control.',
    'cancellation':REGISTRY['rhino.run_python']['cancellation']}


REGISTRY['sketchup.startup'] = {
    'version':1,'kind':'host','input_types':list(TEXT_TYPES),'output_type':None,
    'max_inputs':20,'input_bytes':2000000,'seconds':120,'output_bytes':200000,
    'outputs':{'delivery/execution.json':'application/json'},'parameters':{},'external_requests':0,
    'criteria':['The owned SketchUp process has a matching embedded Ruby startup receipt; failure remains diagnostic evidence.'],
    'cancellation':'Stop only the owned process; no automatic replay.',
    'permissions':'macOS desktop SketchUp 2025/2026 with normal host permissions; no attachment to existing user sessions.'}
REGISTRY['sketchup.inspect'] = {
    **copy.deepcopy(REGISTRY['sketchup.startup']),
    'input_types':[*TEXT_TYPES,'application/vnd.sketchup.skp'],'input_bytes':100000000,'output_bytes':2000000,
    'outputs':{'delivery/inspection.json':'application/json','delivery/execution.json':'application/json'},
    'criteria':['The selected .skp has a bounded native inventory and unchanged source-copy hash.'],
    'review_evidence':True}
REGISTRY['sketchup.run_ruby'] = {
    'version':1,'kind':'host','input_types':[*TEXT_TYPES,'application/vnd.sketchup.skp','text/x-ruby','application/json'],
    'output_type':None,'max_inputs':20,'input_bytes':100000000,'seconds':600,'output_bytes':100000000,
    'outputs':{'delivery/candidate.skp':'application/vnd.sketchup.skp','delivery/preview.png':'image/png',
               'delivery/model.rb':'text/plain','delivery/checks.json':'application/json','delivery/execution.json':'application/json'},
    'parameters':{'scene_sha256':'Selected .skp SHA-256 or null for create','script_sha256':'Exact reviewed UTF-8 Ruby SHA-256',
                  'checks_sha256':'Exact SketchUp v1 checks SHA-256','permissions':'unrestricted_host'},
    'criteria':['The exact approved Ruby created/edited a candidate, saved it and reopened it in an independent owned process; declared dimensions/preservation and viewport evidence passed; input copies remain unchanged.'],
    'external_requests':None,'requires_registered_inputs':True,
    'permissions':'Exact Ruby/script/checks host approval. Normal filesystem/network access, not an OS sandbox. Desktop session and license required.',
    'cancellation':'Stop only owned work; preserve partial outputs. Script side effects cannot be undone. Never automatically replay.'}

# These operations need already registered versions before execution approval.
for _capability in ('blender.run_python','blender.import_asset','blender.animate',
                    'rhino.run_python','rhino.render'):
    REGISTRY[_capability]['requires_registered_inputs'] = True


# Explicit scope for older adapters whose implementation already enforces these
# restrictions. New registrations must provide this metadata themselves.
for _capability in ('text.bundle','pptx.create','pptx.edit','sourcing.merge','records.merge','sourcing.slides','collection.slides'):
    REGISTRY[_capability]['permissions']='Local reads of declared inputs and writes of declared artifact outputs; no provider calls, network or host-application automation.'
REGISTRY['gemini.text']['permissions']='One configured text-provider request using declared text inputs; no tools, accounts, messages or host execution.'
for _capability in IMAGE_PROVIDERS:
    REGISTRY[_capability]['permissions']='Configured image-provider generation using declared prompts/references; bounded image retrieval and local conversion. No provider switching or uncertain submission replay.'


from .document_compose import PARAMETERS as COMPOSE_PARAMETERS
REGISTRY['document.compose']={
    'version':1,'kind':'procedure','input_types':['application/json','image/png','image/jpeg','application/zip'],
    'output_type':'application/json','min_inputs':1,'max_inputs':100,'input_bytes':100000000,
    'seconds':60,'output_bytes':10000000,'parameters':COMPOSE_PARAMETERS,'external_requests':0,
    'criteria':['Saved sections retain literal content, source notes and exact image versions; appended previews use full-page contain layouts. Composition makes no semantic or visual acceptance claim.'],
    'permissions':'Local deterministic document composition; no provider, network or native-app calls.',
    'cancellation':'Stop local composition; retain original section versions.',
    'support_modules':['orchestrator.document_compose','orchestrator.pptx_document','orchestrator.slide_templates','orchestrator.table_layout','orchestrator.image_sources'],
    'data_revision':'application/json'}
for _cap in ('collection.slides','sourcing.slides','pptx.create'):
    REGISTRY[_cap].setdefault('support_modules',[]).append('orchestrator.document_compose')
REGISTRY['pptx.create']['companions']['document.compose']='registered-record-projection'

# Literal prompts share the existing provider adapters; historical file prompts remain valid.
for _cap in ('gemini.text','gemini.image','openai.image','openrouter.image'):
    REGISTRY[_cap]['parameters']['prompt']='Literal generation prompt; source documents are optional context'
    REGISTRY[_cap]['optional_parameters']=['prompt']
    REGISTRY[_cap]['min_inputs']=0
    REGISTRY[_cap]['input_defaults']={'prompt':'',**({'max_output_tokens':4096} if _cap.startswith('gemini.') else {}),
        **({'aspect_ratio':'1:1'} if _cap in ('gemini.image','openrouter.image') else {}),
        **({'size':'auto','quality':'auto'} if _cap=='openai.image' else {})}
# These registered adapters already construct text-only requests. Runway video
# retains its image requirement because its adapter uses image_to_video.
for _cap in ('runway.image','higgsfield.image','higgsfield.video','meshy.mesh'):
    REGISTRY[_cap]['min_inputs']=0

# Adapter definitions are trusted code registrations, never model-provided imports.
from .operation_adapters import builtins as _adapter_definitions
ADAPTERS = _adapter_definitions(REGISTRY)
from .codex_sources import register as _register_codex_sources
_register_codex_sources(REGISTRY, ADAPTERS)
from .public_read_operation import register as _register_public_read
_register_public_read(REGISTRY, ADAPTERS)
from .perplexity_search import register as _register_perplexity
_register_perplexity(REGISTRY, ADAPTERS)
from .browser_render import register as _register_browser_render
_register_browser_render(REGISTRY, ADAPTERS)

# Human names for the existing ports. These are presentation metadata only:
# stored references, adapter parameters, output paths and execution stay fixed.
for _cap,_title,_bundle,_result in (
    ('text.bundle','Combine text','Text documents','Combined text'),
    ('web.fetch','Read a web page',None,None),
    ('web.sources','Search public sources (Gemini)',None,None),
    ('web.sources.codex','Search public sources (Codex)',None,None),
    ('web.sources.prepared','Search a query plan (Gemini)','Query plan',None),
    ('web.sources.prepared.codex','Search a query plan (Codex)','Query plan',None),
    ('web.sources.coverage','Search for coverage gaps (Gemini)',None,'Source pack'),
    ('web.sources.rendered','Read source pages (HTTP / rendered)','Source pack',None),
    ('web.sources.native','Read source pages (native browser)','Source pack',None),
    ('images.collect','Acquire candidate images','Reference images','Candidate image bundle'),
    ('images.fetch','Download recorded images','Image request manifest','Image bundle'),
    ('images.products','Acquire product images',None,'Product image bundle'),
    ('images.catalog','Acquire catalog images',None,'Catalog image bundle'),
    ('images.crop','Crop an image','Source image','Cropped image'),
    ('images.merge','Combine image bundles','Image bundles','Combined image bundle'),
    ('images.pptx','Export candidate cards to PowerPoint',None,'PowerPoint'),
    ('images.gallery','Export candidate gallery',None,'Gallery'),
    ('collection.slides','Build catalog slides',None,'Slide specification'),
    ('sourcing.slides','Build sourcing slides (legacy)',None,'Slide specification'),
    ('records.merge','Merge catalog partitions',None,None),
    ('sourcing.merge','Merge sourcing partitions (legacy)',None,None),
    ('document.compose','Compose a document',None,'Document specification'),
    ('pptx.create','Create PowerPoint','Slide specification and assets','PowerPoint'),
    ('pptx.edit','Edit PowerPoint','Presentation, edit specification and assets','PowerPoint'),
    ('pptx.render','Render PowerPoint','Presentation and supporting files',None),
    ('hyperframes.preview','Preview a video project','Project and assets',None),
    ('media.compose','Compose a video','Scene specification and assets',None),
    ('gemini.text','Generate text (Gemini)','Prompt documents','Generated text'),
    ('blender.scene','Create a Blender scene','Scene specification and supporting files',None),
    ('blender.mesh_scene','Create a Blender mesh scene','Mesh specification and supporting files',None),
    ('rhino.document','Create a Rhino document','Geometry specification and supporting files',None),
    ('rhino3dm.create','Create a 3DM file','Geometry specification and supporting files',None),
):
    REGISTRY[_cap]['node_ui']=dict(title=_title,inputs={'files':_bundle} if _bundle else {},outputs={'result':_result} if _result else {})
for _cap,_spec in REGISTRY.items():
    _ui=_spec.setdefault('node_ui',{})
    if _cap.endswith('.startup'):_ui['inputs']={'files':'Probe context documents'}
    if _cap.endswith('.inspect'):_ui['inputs']={'files':'Native file and inspection evidence'}
    if _cap in IMAGE_PROVIDERS or _cap in CLOUD_MEDIA:
        _ui.update(inputs={'files':'Reference files'},outputs={'result':'Generated image' if _cap.endswith('.image') else 'Generated media'})
REGISTRY['sourcing.merge']['node_ui']['replaced_by']='records.merge'
REGISTRY['sourcing.slides']['node_ui']['replaced_by']='collection.slides'
for _cap in ('images.pptx','images.gallery'):
    REGISTRY[_cap]['node_ui']['inputs']=dict(photos='Candidate image bundle',recommendations='AI recommendations (advisory)')
REGISTRY['images.collect']['node_ui']['inputs']['subjects']='Subjects to find'
for _cap in ('blender.scene','blender.mesh_scene'):
    REGISTRY[_cap]['node_ui']['output_details']={
        'scene':dict(label='Blender model',role='primary',open_with='Blender'),
        'preview':dict(label='Render preview',role='preview'),
        'scene-script':dict(label='Generated script',role='technical'),
        'execution':dict(label='Execution receipt',role='technical')}

# Explicit model dependencies, separate from external HTTP page/image reads.
# Used when an executor contract forbids a hidden second inference provider.
MODEL_PROVIDERS={cap:provider for provider in ('gemini','openai','openrouter','runway','higgsfield','meshy')
                 for cap in REGISTRY if cap.startswith(provider+'.')}
MODEL_PROVIDERS.update({cap:'gemini' for cap in ('web.sources','web.sources.prepared','web.sources.coverage')})
MODEL_PROVIDERS.update({cap:'codex' for cap in ('web.sources.codex','web.sources.prepared.codex')})


def adapter(capability):
    value=ADAPTERS.get(capability)
    if value is None:raise ValueError('Missing registered admission adapter: '+capability)
    return value


def parameter_schema(capability):
    """The same registered wire shape is used by planning and admission."""
    return adapter(capability).schema(REGISTRY[capability])


def catalog(capabilities=None):
    from .connector_protocol import capture
    selected=list(REGISTRY) if capabilities is None else list(capabilities)
    if any(ident not in REGISTRY for ident in selected):raise ValueError('Unknown operation in catalog scope')
    context={};result=[]
    for ident in selected:
        spec=REGISTRY[ident]
        definition=adapter(ident)
        entry=dict(id=ident,**copy.deepcopy(spec),available=bool(definition.handler),configured_model=None,
            availability_evidence='Local implementation; provider configuration only, not authentication proof.',
            connector_interface=capture(ident),parameter_schema=parameter_schema(ident),
            data_owner='registered code' if spec['kind']=='procedure' else 'provider or host execution')
        definition.describe(entry,context)
        result.append(entry)
    return result


def validate_inputs(a,*,complete=True):
    """Same native consumption bounds for planning, admission and dispatch."""
    cap=a['execution']['capability'];spec=REGISTRY[cap]
    inputs=a.get('inputs');minimum=spec.get('min_inputs',1) if complete else 0;maximum=spec['max_inputs']
    if not isinstance(inputs,list) or not minimum<=len(inputs)<=maximum:
        raise ValueError('Invalid registered-operation input count for '+a.get('id','<task>')+' ('+cap+'): expected '+str(minimum)+'–'+str(maximum)+', received '+str(len(inputs) if isinstance(inputs,list) else 'non-list')+'. Inputs are consumed operation data; keep background evidence on the author/reviewer.')
    for item in inputs:
        if not isinstance(item,dict):raise ValueError('Registered input must be an artifact descriptor')
        if item.get('media_type') not in spec['input_types']:
            from .artifact_roles import CompatibilityError
            raise CompatibilityError(item,'operation_input',dict(kind='selected'),
                'Registered input media types do not match '+cap,
                'Choose operation data with a supported type: '+', '.join(spec['input_types'])+'; keep background evidence on the inspecting worker')


def validate(a):
    e=a.get('execution')
    if not isinstance(e,dict) or set(e)!={'capability','version','parameters'}:
        raise ValueError('Execution needs an exact capability, version and parameters.')
    spec=REGISTRY.get(e['capability']) if isinstance(e['capability'],str) else None
    if not spec or type(e['version']) is not int or e['version']!=spec['version']:
        raise ValueError('Unknown capability or unsupported execution version.')
    from .connector_protocol import interface,verify
    interface(e['capability'])  # Every registered operation must conform.
    verify(e['capability'],a.get('connector_interface'))
    params=e['parameters']
    if not isinstance(params,dict) or not set(spec['parameters'])-set(spec.get('optional_parameters',[]))<=set(params) or not set(params)<=set(spec['parameters']):
        expected=set(spec['parameters']);actual=set(params) if isinstance(params,dict) else set()
        issues=[]
        required=expected-set(spec.get('optional_parameters',[]))
        if required-actual:issues.append('missing '+', '.join(sorted(required-actual)))
        if actual-expected:issues.append('unsupported '+', '.join(sorted(actual-expected)))
        if not isinstance(params,dict):issues.append('expected an object')
        raise ValueError('Invalid registered-operation parameters for '+e['capability']+': '+'; '.join(issues)+'.')
    if a.get('review_of'):raise ValueError('Registered operations cannot impersonate an independent agent reviewer.')
    if a.setdefault('tools',[])!=[]:raise ValueError('Registered operations have no agent tools.')
    if a.get('criteria')!=spec['criteria']:raise ValueError('Use the registered operation criteria; semantic review is a separate agent step.')
    validate_inputs(a)
    if spec.get('outputs'):
        if any(i.get('path','').split('/')[0]=='delivery' for i in a['inputs']):
            raise ValueError('Operation inputs must stay outside the reserved delivery directory.')
        outputs=a.get('outputs')
        if (not isinstance(outputs,list) or len(outputs)!=len(spec['outputs'])
                or any(not isinstance(o,dict) for o in outputs)
                or {o.get('path'):o.get('media_type') for o in outputs}!=spec['outputs']):
            raise ValueError('Use the exact registered '+('host ' if spec['kind']=='host' else '')+'output paths and media types.')
    elif not isinstance(a.get('outputs'),list) or len(a['outputs'])!=1 or not isinstance(a['outputs'][0],dict) or a['outputs'][0].get('media_type')!=spec['output_type']:
        raise ValueError('Registered operation needs one output with its declared media type.')
    admission=adapter(e['capability'])
    admission.validate(a,spec)
    limits=a.setdefault('limits',{})
    for key,maximum in [('seconds',spec['seconds']),('output_bytes',spec['output_bytes']),('tool_calls',1)]:
        limits.setdefault(key,maximum)
        if type(limits[key]) is not int or not 1<=limits[key]<=maximum:raise ValueError('Registered operation exceeds its '+key+' limit.')
    correction=a.get('review_correction')
    if correction is not None:
        if (not spec.get('review_correction') or spec['kind']!='procedure' or spec['external_requests']!=0
                or not isinstance(correction,dict) or (set(correction)!={'producer'} and not (set(correction)=={'producer','kind'} and correction['kind'] in admission.correction_kinds))):
            raise ValueError('Correction requires a supported local data-only operation.')
        from .contracts import label
        label(correction['producer'])
        if a.setdefault('max_attempts',2)!=2:raise ValueError('Local document correction permits two operation attempts.')
    elif admission.max_attempts==2:
        if a.setdefault('max_attempts',1) not in (1,2):raise ValueError('Native sourcing assembly permits at most two bounded layout attempts')
    elif spec.get('preflight_recovery') and a.get('revision',{}).get('kind')=='registered_input_preflight':
        # This is only structural admission. Runtime rechecks the committed
        # cycle, exact finished receipt, adapter proof and unchanged inputs.
        if a.setdefault('max_attempts',1)!=2:raise ValueError('Native preflight continuation permits one allocated successor')
    elif a.setdefault('max_attempts',1)!=1:raise ValueError('Registered operations permit one attempt; uncertain calls are never replayed.')
    return spec


def available(a):
    spec=validate(copy.deepcopy(a))
    adapter(a['execution']['capability']).check_available(a,spec)

for _cap in ('sourcing.slides','collection.slides'):
    REGISTRY[_cap].setdefault('support_modules',[]).extend(['orchestrator.table_layout','orchestrator.product_evidence'])

for _cap in ('images.fetch','images.products','images.catalog','images.collect','images.merge','collection.slides','sourcing.slides','document.compose','pptx.create'):
    REGISTRY[_cap].setdefault('support_modules',[]).append('orchestrator.image_representation')

for _cap in ('images.products','images.catalog','collection.slides','sourcing.slides','records.merge','sourcing.merge'):
    REGISTRY[_cap].setdefault('support_modules',[]).append('orchestrator.discovery_evidence')
    REGISTRY[_cap]['support_modules'].append('orchestrator.subject_contract')

for _cap in ('web.sources.rendered','web.sources.native'):
    REGISTRY[_cap].setdefault('support_modules',[]).extend([
        'orchestrator.discovery_evidence','orchestrator.product_photos'])

for _cap in ('blender.scene','blender.mesh_scene','rhino.document'):
    REGISTRY[_cap].setdefault('support_modules',[]).append('orchestrator.spatial_contract')
