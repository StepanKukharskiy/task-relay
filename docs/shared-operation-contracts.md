# Shared operation contracts and structured research

## Architecture consolidation, 2026-10-09

The current consolidation is specified in [Relay execution architecture](architecture-contract.md).
It adds generic subject contracts, registered execution/availability/binding/receipt
hooks, registered continuation detection and proof, and one atomic stage/attempt
continuation path. Historical records below describe their evidence at the time;
remaining-work statements in those entries are superseded where this contract
explicitly describes the completed boundary. Source, package and live evidence
remain separate.

## Visual reference search composition (deployed 0.13.191)

`images.crop` accepts one declared PNG/JPEG and an integer `[x, y, width, height]`
region measured after EXIF orientation. It returns exact source pixels as a bounded
PNG with source/output hashes. It does not generate pixels or infer product identity.
The standard browser upload grant accepts declared PNGs alongside its existing
text formats, preserves the actual MIME type and verifies the frozen bytes.
File-input and observed file-chooser controls use the same grant. A delayed,
recorded upload redirect is followed only within allowed origins; the upload is
never repeated to recover a missing page snapshot.

The compatible graph is crop → explicitly granted browser upload → observed
source manifest → `images.fetch` → independent review → `images.merge` → document
creation/render/review. Visual search is a website interaction through the existing
browser adapter, not a separate collector or controller. Verification challenges,
missing results and inaccessible source images remain explicit outcomes. Exact
product-name/SKU evidence can supply replacement candidates through the same
observed-source/download interface. Quoted dimensions in subject titles are data,
not executable search syntax.

Merging replacements preserves all usable base
photos byte-for-byte. Rejected original pixels and their exact prior receipts are
retained under hash-qualified history paths and are excluded from usable images.
Archive validation checks these retained bytes too; a replacement never erases the
rejection or changes the original subject identity. Identity and visual suitability
still require independent review on the new exact candidate.

Controlled qualification passed 76 checks against the exact maintained package,
including crop-to-upload byte fidelity, delayed redirect recovery, changed-byte
rejection, historical-photo tampering and native controller dispatch. Signed
installation, bundle identity and fresh core health were verified. Live Lens upload
reached a verification challenge; successful unattended reverse-image retrieval is
not established. Engineering-assisted source discovery and the registered photo
and presentation operations are recorded separately in private run evidence.

## Registered admission adapters (2026-10-09, source-qualified)

All 46 registered operations now expose parameter wire schemas. The existing
`execution.REGISTRY` remains authoritative for operation identity, ports, grants
and limits. `execution.ADAPTERS` supplies trusted admission definitions from
`operation_adapters.py`: parameter schemas, ordered content-validation hooks,
structural attempt ceilings and historical correction-kind compatibility.
`operation_validators.py` owns the former tool-specific admission checks. The
central validator now enforces common assignment structure and policy and calls
the registered adapter; it no longer selects content validators by tool name.
No adapter creates assignments, spends grants, queues work or accepts results.

The same schema is advertised to planners and enforced at admission. The small
stdlib `parameter_contracts.py` validator checks the explicitly supported JSON
Schema vocabulary, including nested objects/arrays, optional and nullable fields,
numeric bounds, patterns and uniqueness. Unsupported schema keywords fail
registration, rather than silently losing their constraints. Schema validity is
not semantic validity: exact input versions, source evidence, content validators,
host approvals and independent review retain their existing checks. The original
parameter descriptions and operation IDs remain; no sourcing contract is renamed.

Captured connector identities now include the admission manifest as well as the
operation definition and parameter schema. A changed validator registration,
adapter version or attempt policy invalidates the saved capture. The worker
checks all three new implementation files against its frozen hashes before
execution; native exact-script approval also includes those files. Existing
pinned captures are not silently upgraded. Historical assignments without a
capture retain legacy identity handling, but still pass current validation.
Deployment must account for existing saved assignments before any installation.

An extension fixture registers a new schema and content hook, composes it with
an existing text operation, and preserves exact artifact ownership through a
controller restart, using controlled worker receipts. It establishes the admission
extension boundary, not arbitrary new transport support. The real child runner
now rejects missing execution handlers instead of silently treating an unknown
procedure as text bundling or an unknown API operation as Gemini text generation.
This rejection occurs before provider submission or output creation.

Qualification: 123 affected tests passed with the bundled interpreter importing
this source checkout, including controlled worker/native-PPTX, continuation,
compiler and host-approval checks. The conformance report has 46 schemas with no
missing entries and 4,830 directed port checks; 1,858 still require bound-content
validation, and 2,972 are incompatible. The initial system-interpreter run had
three presentation-dependency failures; the complete history and commands are in
`private qualification records`. No provider/browser/native application
was used live, no package was installed, and no active workflow was modified.

Remaining consolidation is explicit: canonical generic subject/data contracts;
adapter-owned transport dispatch, availability and remaining catalog metadata;
registered recovery proofs; and persistent job-level completion/capacity ownership.
Whole-graph revision and delivery still retain specialized effect paths. This
admission migration does not establish those migrations or uninterrupted autonomy.

## Connector-wide admission and receipt boundary (2026-10-09)

`orchestrator/connector_protocol.py` derives a versioned interface from every
entry in the existing execution registry. It validates ports, capacities,
parameter declarations, technical criteria, permission scope and cancellation
behavior. A compact reference hashes the complete registered definition and its
parameter schema. New catalogs, compiled plans and admitted assignments retain
that reference; compilation, admission and execution reject definition drift
even without an operation-version change. Claiming a worker never replaces a
saved reference. Historical assignments without a reference retain legacy
validation; they are not rewritten or represented as fully pinned.

The workflow compiler uses the same directed-port classifier. Unsupported media,
capacity and explicitly mismatched content versions fail before dispatch.
Potentially compatible edges still require exact artifact versions, complete
input sets, bound parameter/content validation and required review. A matching
MIME type does not establish semantic compatibility. Existing aggregate input
limits, companion requirements, authorization and review gates remain enforced.

Every factory inspection now passes through a common receipt guard in the
existing runtime. A finished process cannot conceal a pending request or an
explicitly unknown API, browser, computer or registered-operation effect.
Malformed receipts hold the affected task while unrelated tasks continue.
Changed receipts retain the original fields and hash. Reconciliation can collect
the original attempt when the adapter later supplies conclusive evidence; it
does not create another submission. Explicit cancellation can end confirmed
local work while retaining an unknown remote effect. It does not confirm that
effect or publish the candidate as completed.

Run `python3 -B scripts/check_connector_conformance.py --output REPORT.json`
for all interfaces and directed port pairs, with no provider or host execution.
The generated test exercises those pairs through the actual workflow compiler
and runs restart, contract-drift and receipt-isolation regressions through the
existing controller. The publication CI workflow includes this check.

Source qualification covers 46 registered operations and 4,830 directed port
pairs: 2,972 structurally incompatible and 1,858 requiring runtime validation.
The affected integration suite passed 106 tests. After the compact reference
change, 73 affected contract/recovery/tool-loop checks passed, including a
controlled native PPTX delivery fixture; the standalone CI command passed eight
tests locally, and three mock host-authorization fixtures passed. These
overlapping counts are not a unique-test total. Commands,
initial failures and limitations are recorded in
`private qualification records`. No installation or live provider
qualification was performed by this change.

Remaining work is explicit: 23 operations still have procedural parameter
validators without a complete wire schema. Transport-specific reconciliation
and retry proofs remain in their existing adapters/controller owners; this
change centralizes terminal-effect enforcement, not all recovery logic. The
matrix qualifies declared edges, not every graph permutation, semantic result,
external service or host application. New parameters/content contracts and
recovery paths need composed fixtures before a broader qualification claim.

Status: the research contracts, JSON handoffs and bounded campaign controller
were installed locally in Task Relay 0.13.129. The sourcing inventory/options/review
families and native slide assembler below were installed locally on 2026-10-07
with exact signed-candidate byte and service-health verification. A fresh live
room experiment has been admitted; full provider/source/photo/PPTX qualification
is pending. Installation/check details: outputs/typed-room-live/qualification.md.

## Provider independence

Contract IDs, versions, JSON Schemas, job parameters, domain validation,
checkpoint transactions, completion checks and serialized artifacts are provider
agnostic. The common tool definition exposes ordinary JSON Schema under
`parameters`. Only the provider adapter translates that schema and the request/
response envelope (for example, Gemini uses `parametersJsonSchema`; OpenAI and
compatible endpoints use their own function-tool envelope). Existing backend
bindings still prevent silent provider switching.

A scripted parity test exercises Gemini, OpenAI, Qwen, DeepSeek and OpenRouter:
the same frozen audit data, invalid-source rejection, successful submission,
identical retry receipt and byte-identical assembled audit. This verifies local
adapter/contract parity, not live model availability or response reliability.

## Implemented contract boundary

`orchestrator/operation_contracts.py` is the shared registry and validation boundary.
`operation_records.py` owns attempt-bound checkpoints in the existing shared
SQLite database. The existing planner, worker, supervisor and handoff compilers
use these modules; this is not a separate executor or database.

| Contract | Version | Current adapter |
| --- | --- | --- |
| `research.audit` | 1 | Submit at most three next claim verdicts; code builds the existing audit JSON and worker builds the Markdown review. |
| `research.candidates` | 1 | Submit one entity with its identity references and every job-required field, explicitly labeled observation, inference or unknown. Code builds a candidate ledger. |
| `research.batch` | 1 | Campaign discovery or assessment records, including one decision per frozen criterion. Empty discovery is valid when independently audited coverage supports it. |
| `geometry.specification` | 1 | Typed JSON handoff delegates validation to the existing standalone geometry specification validator. It grants no new geometry or host execution. |
| `sourcing.inventory` | 1 | Submit visual observations with consecutive slots, labels, normalized boxes and uncertainty, then an explicit completion fragment. Code assigns VIS IDs, binds the exact PNG and builds JSON/Markdown. Source candidate. |
| `sourcing.options` | 1 | Submit one inventory item's options as saved-page references and field spans, or explicit unknowns/gaps. Code extracts values and builds JSON and Markdown. Source candidate. |
| `sourcing.review` | 1 | Submit up to eight independent item verdicts, each bound to its exact projected item version, within the 16000-byte submission ceiling. Code builds the review and checks its completion decision against all saved verdicts. Source candidate. |

New research plans select `research.mode` explicitly (`profile` or `discovery`).
Discovery parameters are `entity_type`, `required_fields` and `max_records`.
The existing profile/post producer format remains supported. New reviewers use
research-audit assignment version 2, which binds the record operation; historical
version-1 reviewers keep their original file-writing contract.

`operation_submit` takes a request key, current revision and a small typed record
batch. The family schema is selected by the frozen assignment, never by a tool
argument. Claim IDs come from the frozen evidence pack. Relay derives checkpoint
record IDs, source hashes, output paths and serialized files. The prompt includes
current progress and only the next three audit claims. Generic writes/appends
cannot modify a contract-owned output.

Each submission validates the whole batch before an atomic commit. Identical
request-key retries return the saved receipt; conflicting keys, duplicate record
identities, stale revisions, foreign claims and invalid source quotes fail.
Exports happen after commit and can be repaired with `Store.export` without a
provider or browser call. `Store.verify_export` runs again in the supervisor.
This does not automatically restart an interrupted worker or reset its attempts.
Job deletion includes owned checkpoints and submission receipts.

## Typed sourcing boundary (source candidate)

`orchestrator/sourcing_contract.py` defines the two sourcing families, while
`task_relay/sourcing_planning.py` compiles an explicit `sourcing` intent into
producer/reviewer assignments. New planning contexts freeze
`sourcing_records_version: 2` (version 1 only admits catalog intent); historical contexts and assignments retain their
existing contracts. A workflow declaring a sourcing content contract must bind
the actual record operation, rather than attaching a label to agent-written JSON.

The model selects inventory IDs, saved-page references and character spans for
product name/variant, price, dimensions, order terms and US context. It also
supplies comparison text, unknown-field reasons and coverage gaps. Code owns
source hashes, captured excerpts/values, URLs, option identities, item versions,
JSON structure and the Markdown schedule. Price fields are extracted from the
selected saved text, rather than independently retyped. Literal extraction alone
does not prove variant suitability, currency, current stock or US availability.

Preflight requires an exact completed native `web.sources` or
`web.sources.prepared` receipt for the source pack. It checks resolved inventory
capacity and minimum request/tool capacity before creating a paid attempt.
Grounding snippets are not saved page evidence. A completed empty native pack is
valid under target-count policy when every item has an explicit gap; an uploaded
or authored pack cannot substitute for a native receipt. Code groups exact URL
and captured-text versions, preserving changed versions and distinct URLs.

Producer submissions commit one new item to the existing transactional checkpoint store.
Explicit compatible correction baselines initialize their assigned records at revision
zero, without model resubmission. This includes completed sealed catalogs; failed
checkpoints additionally require their original exact terminal/collection proof.
New selection tasks without an authorized correction baseline still start empty.
Initial state is read-only and materializes atomically with the first mutation.
Code-owned JSON and Markdown cannot be replaced through generic file writes.
Guarded producer amendments require the current revision and prior fragment
hash, retain superseded fragments and original receipts, and reject new writes
after the attempt finishes or stops. Identical retries return the saved receipt.
Projection repair and checkpoint reopening require no model call.

Independent review receives a bounded prefix of next items and their exact versions.
Both `sourcing.review` and `collection.review` can commit up to eight individual
judgments within the original 16000-byte bound. Every judgment remains independently
required; one stale member rejects the entire batch without partial commitment.
Unsupported or
uncertain saved verdicts cannot be contradicted by an `accept` report. The
original semantic criteria remain required; this typed review replaces an extra
whole-catalog factual-report authoring step for these families only. It does not
grant user acceptance or certify pixels through a text-only worker.

Typed workers receive the same bounded literal initial text mechanism as ordinary
file workers, with paths, hashes, exact text and omission offsets. Missing suffixes
remain unread; candidate completion and visual-observation checks still apply.
Progress can report unchanged/changed/absent/added raw-record identities relative
to the frozen baseline. These are deterministic equality facts, not semantic
judgments or permission to omit independent review.

Controlled qualification passed 145 focused tests, including native scheduler
dispatch/completion, planner admission, source provenance, interruption,
amendments, stale review rejection and variable-count gaps. A synthetic
13-item/39-option fixture checks checkpoint/projection/review scale with scripted
source spans; it does not qualify the cost or feasibility of researching 39 real
products. Exact command and limitations: `outputs/typed-sourcing/qualification.md`.

The inventory/assembly/continuation integration below closes the three source
implementation gaps. Deployment and actual-model/full-room qualification remain
separate. Existing blocked workflows are not silently rewritten, retried or reset.

### Inventory pixels and code-owned slide assembly

`sourcing.inventory` uses an explicitly declared visual PNG with a compatible
Gemini/OpenAI/Qwen file-worker envelope. Code attaches the exact bytes, path and
hash to model requests; metadata is not presented as visual inspection. This
adapter declaration does not certify that every configured model accepts vision.
Other binary inputs remain outside the file-worker grant. Original JPEG/AVIF
uploads use their recorded decoded PNG version rather than relabeled bytes.
An independent image-capable reviewer receives the same original image and
checks labels, bounding boxes, omissions and uncertainty. A zero-item observation
requires an explicit sealed count and explanation; legacy empty inventories do
not gain acceptance.

The model supplies visual labels/categories, normalized boxes, confidence and
notes, followed by a completion fragment. Code assigns consecutive VIS IDs,
binds the image version, rejects invalid boxes/slots and records after sealing,
and generates the JSON/Markdown inventory. The slot ceiling reserves requests
for completion and finish; a valid schema cannot guarantee that all visible
objects were found.

Registered `sourcing.slides` reproduces the typed catalog from its original
inventory and saved-page versions, verifies the room-image hash and constructs
slide JSON without a model call. It creates editable numbered image-map markers,
paginated option cards, captured prices, retailer hyperlinks, uncertainty and
coverage/photo gaps. Photos join only by exact option ID and product URL; the
currently bound ZIP version is hash-validated and passed to `pptx.create`.
There is no fallback to invented URLs or unrelated product photos. Original
catalog fields retain the full source context; long display text is shortened
visibly. Existing 50-slide and document bounds still apply.

New PPTX planning scopes expose this local operation as a companion to
`pptx.create`; historical planning scopes do not gain that capability. Automatic
finished-file workflows retain specification review and final deck review without
an invented selection gate. Under a newly compiled local-correction grant, a
final revise decision can select one deterministic standard-to-readable layout
correction. Exact facts, source and image versions stay fixed; unresolved factual
or visual defects cannot be accepted merely because the layout changed. Broader
authored document corrections retain their existing contracts.

### Confirmed-stop continuation

Inventory, options and item-review operations can automatically continue after
a confirmed timeout or request/tool exhaustion when they committed additional
progress and still have an attempt in their existing grant. The owning run must
be active; the receipt must be finished with `no_pending_response` and an empty
pending-request list. Cancellation, unknown outcomes, no-progress failures and
exhausted limits do not authorize continuation.

Code checks exact source/artifact versions, operation parameters, backend, limits,
criteria and review target before dispatch. It copies committed fragments into
the successor's transactional record set and records an immutable parent proof.
Original records, amendments, provider receipts and failed attempts remain
unchanged. Imported uncertain/unsupported review verdicts remain effective;
continuation cannot forget them or turn them into acceptance. A changed input or
review version is refused before spending an attempt. Attempts and budgets are
never reset. Timing/token aggregation retains both old and successor attempts.

Qualification: 272 focused controlled checks passed in 101.897 seconds. A native
synthetic image → inventory → source fetch → catalog → review → slide assembly →
actual editable PPTX → final review → layout correction → delivery chain completed
with zero user decision records; a separate recovered-photo fixture verifies the
actual photo bytes embedded in the PPTX. Source transport, observations and review
judgments are scripted seams, not actual model/retailer qualification. Exact
commands and limits: `outputs/typed-room-chain/qualification.md`. Final image-metadata
guards passed a further overlapping 53 focused checks in 10.903 seconds.

The planner rejects oversized batches and insufficient declared budgets rather
than raising them. A discovery batch can contribute at most 30 identity/field
claims plus ten summary claims; all are independently audited. Discovery needs
one submission per possible candidate plus summary, finish and reserved URL
actions. Review plans reserve 16 requests/tools for up to 40 claims. These are
capacity checks, not a guarantee of yield. Empty results remain blocked; a record
ceiling is not a promised number of qualified entities. Identity deduplication is
by exact URL; aliases and real-world identity conflicts still require review.

Workflow outputs and consumer edges may carry `content_contract: {id, version}`.
Typed consumers require the same identity/version, and delivered files are
validated by that family. A posts-only object cannot cross a candidate-ledger
port. Untyped legacy handoffs retain their existing behavior. Content validation
never promotes an artifact to independently reviewed or user accepted.

Controlled qualification used small prospect/supplier fixtures and the saved
20-claim evidence pack in an isolated database. The latter assembled seven batches
and a review in eight scripted responses, with every verdict deliberately
uncertain. It did not call a provider, read X again, mutate production state or
accept research. See the private check log under `outputs/shared-operation-contracts/`.

## Remaining research lifecycle work

The campaign controller now implements qualification, target/yield tracking and
bounded replenishment; see [Research campaigns](research-campaigns.md).
Dedicated workbook/draft renderers remain separate work; existing final production
stages receive the campaign ledger and exact source artifacts. No twenty-person completion or live Gemini
reliability improvement is inferred from scripted tests. Other operation families
retain their existing validators until a concrete integration needs migration.

## Planning and review boundaries

The shared family registry does not replace every planner compiler. Request
outcome binding, operation wiring and source-review policy still compose a graph
before assignment validation. Those compilers must respect the same ownership:
fixed operations own procedural completion checks; independent reviewers own the
requested semantic checks.

New planning contexts freeze `outcome_review_policy_version: 1`. Registered
deliverables keep their exact catalog criteria. Version-2 output contracts retain
each outcome's semantic validation verbatim; graph validation requires the
independent reviewer to check those requirements alongside the procedural criteria.
Procedural file checks remain on delivery. Missing or failed semantic checks
cannot promote an output to accepted. Known text output types propagate to
consumers, including review reports supplied to document builders; explicit type
choices remain authoritative and conflicting edges fail.

New contexts also freeze text-evidence policy version 2. A source-backed choice
adds factual source checks to final text authors and explicitly requested text
deliverables, including specifications passed to registered renderers. Intermediate
preparation does not acquire that requirement automatically. An explicit factual
promise at any text stage still requires independent evidence. Images cannot
serve as quote-based text evidence. Version-2 text audits bind every declared text
candidate and forbid any reviewed output from serving as independent evidence.
Mixed binary/text deliveries audit their text
companions; ordinary artifact review still checks the binary output. Binary-only
deliveries retain their operation-specific review and do not acquire a text audit.
These structural checks do not classify every factual claim or guarantee research
coverage; independent review remains necessary.

Historical contexts, assignments, failed attempts and receipts retain their frozen
policies. These fixes do not replay work or authorize a provider request.

## Decision

Extend the existing shared contract/compiler layers with reusable operation-family
contracts. Do not create a new contract for every user request, and do not replace
domain validators with one unrestricted universal JSON object.

The model chooses strategy, selects known inputs, proposes bounded domain data
and makes attributed judgments. Relay constructs executable assignments, binds
versions, validates records, persists progress and renders artifacts. Semantic
truth and suitability still require independent review; structural validation
does not establish them. Native/provider calls can still fail or return malformed
data, so bounded recovery and no-replay rules remain necessary.

## Existing pieces to reuse

| Layer | Source | Existing responsibility and limit |
| --- | --- | --- |
| Planner wire contract | `task_relay/planning_contract.py` | Versioned proposal schema, local validation, provider structured output. Some domain payloads remain opaque to this outer schema. |
| Assignment/runtime contract | `orchestrator/contracts.py`, `orchestrator/runtime.py` | Frozen tasks, declared inputs/outputs, dependencies, worker limits, attempts, review and selection. Does not guarantee the model can construct its output. |
| Workflow compiler | `task_relay/workflow_builder.py` | Compiles semantic outputs and uses into workflow ports; binds registered operation outputs and companion files. Model still designs stages. |
| Artifact binding compiler | `task_relay/artifact_bindings.py` | Model selects captured artifact IDs, named frozen stage ports or producer outputs; Relay constructs paths, authority, dependency edges, explicit registered input-path parameters and reviewer inputs. |
| Compact stage view | `task_relay/planner_view.py` | Model composes any compatible graph from scoped connector contracts. Planning receives input manifests/ports rather than copied source bodies; exact provider views and full execution evidence are both retained. Legacy and exact-code/design builder guidance remain versioned. |
| Cross-tool handoffs | `orchestrator/handoff_contracts.py` | Checks media types, operation versions, capacity, declared producers/consumers and companions. Generic JSON ports do not distinguish a candidate ledger from an audit or geometry specification. |
| Registered operations | `orchestrator/execution.py` | Versioned operation IDs, parameters, inputs, outputs, limits, checks and execution adapters. Includes `web.sources`, `pptx.create/edit`, `rhino3dm.create/run_python`, image collection and media rendering. Registration alone does not establish live qualification. |
| Typed operation builder | `task_relay/operation_builders.py` | Currently scoped to `rhino3dm.run_python`: model selects captured script/check/model IDs; code builds assignments, paths, hashes, criteria, limits, reviewer and selection gate. Best existing pattern for research. |
| Domain validators/writers | Geometry, PPTX, browser/computer and media contract modules | Own actual format, native-action and domain-specific rules. Keep these validators; do not flatten them into a generic schema. |
| Evidence and revisions | `task_relay/reviewed_links.py`, `native_links.py`, `impact_handoff.py`, `revision_review.py` | Normalize explicit evidence/output links, conservative impact and exact-version review/selection across bounded adapters. They do not discover all dependencies or validate arbitrary research claims. |
| Research checks | `orchestrator/research_quality.py`, `computer_review_inputs.py` | Frozen raw captures, post citation checks and complete claim audits. Model still authors audit JSON through generic file tools. |
| Reusable workflows | `task_relay/procedures.py` | Reviewed immutable templates extracted from completed workflows. A saved workflow template is separate from an operation/data contract and does not prove quality on a new job. |

## Shared framework responsibilities

The implemented registry follows these shared rules:

- Contract ID and version, typed input/output ports, record schema and semantic
  validator, fixed construction/serialization code and completion checks.
- Existing job/task/attempt identity and authorization, artifact IDs and hashes,
  declared side effects, time/request/tool/record limits and recovery behavior.
- Bounded record submissions with stable request keys. Identical duplicate
  submission returns its receipt; conflicting reuse fails. Code assigns internal
  IDs and source/candidate hashes rather than asking the model to reproduce them.
- Transactional record persistence in the existing shared `state.sqlite`.
  `.relay` and JSON files remain projections/artifacts, not a second authority.
  External dispatch remains after commit. Export failures can be repaired from
  committed records without another model or browser call.
- Code-generated final JSON/Markdown/native artifacts, bound to exact record
  versions. Existing independent-review and user-selection gates remain separate.

Extend handoff descriptors with an explicit optional content-contract identity
and version. A typed consumer must require the right contract, not merely
`application/json`. Check compatibility at planning and actual record validity at
handoff. Legacy frozen plans keep their historical behavior. Conversions must be
declared operations; no implicit conversion or trust promotion.

Freeze contract versions in new plans. The model cannot invent a runtime schema,
validator or executable operation as a way to gain capabilities. New operation
families require implementation and tests; ordinary jobs configure existing ones.

## Reusable research family

Use related explicit contracts for distinct objects:

1. Source observation: captured URL, retrieval time, snapshot hash and locator.
   The native/public-source adapter creates this record; the model cannot supply
   a replacement capture as authoritative evidence.
2. Entity/candidate: identity and source-linked discovery facts, aliases,
   provenance and unresolved identity conflicts. An observed post is evidence
   associated with a candidate, not a substitute for the candidate record.
3. Claim: entity, predicate/value or concise text, observation/inference/limitation
   label and exact source references. Missing, conflicting and unknown values
   remain explicit. Exact substring presence alone does not prove attribution or
   that the source supports the whole claim.
4. Audit verdict: frozen claim ID, supported/unsupported/uncertain, bounded
   explanation and source references from a separate reviewer assignment.
5. Qualification: explicit criterion decisions bound to a versioned policy,
   evidence and review state. Keep/hold/reject is separate from evidence quality
   and separate from user acceptance.
6. Progress: queued/researched/reviewed/qualified/rejected/held candidates,
   remaining authorized capacity and recorded reasons for a shortfall.

Job-specific data includes target count, geography/industry, criteria, required
fields, source scope, acceptable uncertainty and output columns. It does not
require writing a new validator for each request. A supplier shortlist, product
comparison and prospect study should reuse source/claim/audit primitives while
using appropriate entity types and qualification policies. Do not impose the
prospect schema on every URL-reading task.

The implemented model-facing tool is `operation_submit`, whose record schema is
selected by the frozen family contract. Separate claim authoring and candidate
qualification outside campaign batches remain future integrations. Submit small bounded records;
do not accept a string containing a complete audit document. The handler owns paths, hashes, assembly,
coverage bookkeeping and receipts. The independent reviewer owns its verdict.

The planner still chooses queries and batch strategy. Runtime feasibility checks
must reject unsupported actions, bare search landing pages used as executable
queries, missing producers, oversized batches and incompatible outputs before
Start. A scheduler tracks actual reviewed yield against the requested total and
the declared effort ceiling. Further discovery may occur only within an explicit
bounded batch/iteration grant; existing twelve-stage/task and provider limits
must not be silently expanded. If a fixed plan cannot cover the requested scale,
return it for correction or declare the limitation before paid dispatch.

For the prospect job, compose discovery, candidate enrichment, evidence audit,
qualification and deterministic workbook/draft export. Outreach remains draft
only. Producing twenty rows does not establish twenty qualified people.

## O15 sequence and remaining scope

1. **Typed audit submissions — implemented in source.** Add a versioned research-audit handler to
   the existing worker tool dispatcher. The runtime freezes the next bounded set
   of claim IDs. The model supplies verdicts, reasons and references only. Validate
   and checkpoint each set, track missing/duplicate claims, and assemble the audit
   and Markdown report in code. Disallow generic file writes to contract-owned
   audit outputs for new assignments. Reuse current capture bindings and literal
   quote/claim checks. Use the already-saved evidence for qualification of this
   change; no new Safari searches are required.
2. **Separate discovery and profile contracts — implemented in source.** Replace output-extension-based
   research binding with explicit operation identity. Keep the existing post/
   profile contract for historical assignments; add a candidate ledger contract
   and typed producer operations. Validate candidate/source linkage and unknowns.
3. **Typed cross-tool handoffs — JSON validation implemented; table exporters remain.** Carry candidate/claim/audit contract identity
   through the existing workflow and artifact builders. Generate JSON and output
   tables from records. Reject a posts-only object offered as a candidate ledger.
4. **Bounded batch lifecycle — implemented in the campaign controller.** Track candidate progress and remaining work;
   validate query feasibility and total capacity before dispatch. Implement any
   needed bounded iteration explicitly rather than encoding it in prose. Test
   replenishment and an honest shortfall at the declared ceiling.
5. **Reuse proof — controlled prospect/supplier fixtures pass.** Exercise the same research primitives with two small synthetic
   policies (prospects and suppliers/products). Add another domain family only
   when it has genuinely different invariants. Do not migrate all existing tools
   or rebuild unrelated artifacts as a prerequisite for this research fix.

## Acceptance and recovery checks

Use small captured-text fixtures and scripted provider responses to check:

- Interrupted audit resumes from committed claim records; no producer replay.
- Duplicate, stale, foreign-source and conflicting submissions do not corrupt
  records or advance completion. Identical idempotent replay returns the receipt.
- Oversized or malformed model responses execute no partial operations, preserve
  prior records and remain within original request/time/attempt limits.
- Completion requires every frozen claim to have an independent verdict. The
  model cannot self-approve, supply trusted hashes, overwrite source captures or
  turn unknowns into supported claims by changing the schema.
- Candidate identity, evidence freshness, citation attribution, required-field
  coverage and policy version are distinct from mere JSON validity.
- JSON-kind mismatch fails before downstream use. Missing output/renderer/worker
  capability fails before paid research for an undeliverable workflow.
- Batch exhaustion records a shortfall; it does not pad results, spend beyond the
  approved ceiling or create an endless discovery loop.
- Old frozen assignments/receipts remain readable and unchanged; any recovery
  creates an explicit new version/attempt under the existing authorization rules.

Installed 0.13.128 passed 21 controlled worker/planning checks, including provider
parity. The completed live twenty-person benchmark is not claimed.

## Synthetic workflow composition qualification

`tests/workflow_decoys.py` provides reusable reviewed-data and registered-operation
builders, plus deterministic LLM fragments and public source/image transport
fixtures. `tests/test_workflow_composition.py` assembles a complete sourcing graph:

`uploaded image → inventory → reviewed queries → source pages → catalog → observed photo manifest → photo ZIP → slide specification → PPTX → final review → delivery`

Unlike the earlier combined deck fixture, this scenario executes inventory,
source collection and photos instead of inserting completed stage results. It
uses ordinary request admission and stage dispatch, the native planning compiler,
production scheduler, artifact freezing, registered operation runners, independent
review transitions and final delivery checks. Registered source, photo and PPTX
operations execute locally; source/image transport and LLM responses are synthetic.
No live browser, provider or retailer is exercised. The root admission fixture
uses the existing bridge adapter and switches the saved parent to the desktop
channel before stage dispatch; desktop UI submission itself is not qualified.

The tests check three option records, fetched page identity, prices in the final
PPTX, exact photo bytes, whole-workflow timing/usage, automatic final correction,
and no repeated source/photo calls during correction. Unknown source submissions
must retain their single attempt and hold dependents; incompatible media edges
must fail before planning or worker dispatch. Upstream snapshots can have new
artifact IDs; their exact byte hashes must survive the native handoff.

This is the first complete synthetic sourcing recipe, not an arbitrary-workflow
composer. Other recipes can reuse the builders, but each supported composition
needs qualification. Current room inventory/catalog fixtures are job-shaped JSON;
they do not yet establish shared versioned content contracts for those families.
Semantic evidence judgments and real visual recognition remain provider boundaries.
Broader fault injection, photo-stage recovery through this full entry path, and
structured inventory/catalog record submission remain follow-up integration work.

### Sourcing count policy

A connector's collection length is not a business acceptance requirement. Final
coverage now supports explicit `count_policy:target`: `options_per_item` is a
search target, supported extras remain present, shortfalls and unresolved item IDs
remain disclosed, and count alone does not trigger recovery. `required` is the
historical default for frozen requests that require a specific count. Native
prepared-source review criteria follow the frozen policy. Structural validation,
identity/evidence checks and operation resource limits still apply. This change
is a tested source candidate; deployment and current live-scope migration are
separate from synthetic qualification.

### Bound input references and workflow files

The artifact registry is authoritative for an artifact ID and SHA256 version. Runtime resolves declared stage inputs and stages read-only copies into an isolated attempt workspace; user-visible workflow folders export those versions. Editing a display copy does not mutate a registered artifact or authorize work.

New factual-review report contracts (v3) expose `artifact_slots`, keyed by assignment-local input references (`i1`, `i2`, etc.). Slots bind artifact ID, SHA256 and workspace-relative path. The model supplies `candidate_ref`, `source_ref`, exact passages and review judgments; Relay inserts paths and hashes before the existing source/claim checks. Candidate and source reference enums are distinct. References apply only within their frozen assignment; they are not global artifact IDs. Existing v1/v2 reports retain their original schema. Native operation-specific file parameters retain their existing contracts.

The workflow `manifest.json` includes `input_bindings`: attempt/run/task, input reference, artifact ID, hash, workspace path and workflow-relative copy path. Missing or mismatched copies have `available:false` and no workflow path. User edits are preserved while bindings resolve to the exact exported registered version. The manifest is a traceable view, not a new source of dispatch authority.

### Mechanical source-page grouping

Native public-source packs include a code-owned mechanical index: exact observation locators, conservative URL groups, capture hashes, repeated-text warnings and fetched-page counts per target. URL grouping removes tracking parameters and fragments while preserving SKU/variant/unknown parameters, path case and query encodings. This describes fetched pages, not business product identity. Equal content on different URLs may be a shared template or error page; it does not merge products. Different captured versions remain distinct.

Within one collection operation, an already fetched URL may reuse its saved page with `reused_from`, the observed grounding URL and the original retrieval time. Queries, grounding lists, page observations and target mappings remain recorded. No fresh retrieval or product verification is implied by reuse. Query/fetch authorization and aggregate ceilings do not grow.

The compiled count policy replaces the exact superseded service-owned source-coverage criterion in fresh output contracts and reviews, instead of appending contradictory rules. Existing assignments/reports are immutable. Semantic evidence requirements and user-authored criteria remain intact; no minimum is silently waived outside an explicit target-count policy.

Confirmed read reuse recognizes both literal and prepared public-source operations as the saved web-source family, retaining each original frozen capability and receipt in the baseline. Reuse must bind exact saved bytes to a producer and independent reviewer; a fresh prepared lookup cannot be hidden behind a reused-operation declaration. Start rechecks pending requests and source version identity.

When an explicitly selected prepared operation is covered by saved-read reuse, admission requires its actual completed prepared capability, retained in the baseline or frozen original-plan metadata. A completed literal lookup cannot masquerade as a prepared operation. Recovered unexecuted proposals retain the original recovery-budget receipt through a bounded parent chain tied to the exact saved provider response hash and original channel; changed/missing proofs and pending source receipts remain rejected.


### Observed product pages and presentation review companions

New finished-file stages go directly from their frozen stage contract into graph planning.
The model still chooses compatible tasks; code preserves the stage capabilities, outcome
IDs, upstream versions and source ports. No second conversational routing call is needed.
Registered parameter schemas describe native path/count/layout data before model generation.
Legacy captured catalogs and executed assignments retain their original scope.

| Connector or boundary | Added by code | Supplied or judged by an agent |
| --- | --- | --- |
| Public page capture | Literal JSON-LD offers, image metadata, observed product links, raw/text hashes, bounded follow-up reads and capture reuse | Queries, visual correspondence, selected variant and purchasing meaning |
| `images.products` | Exact catalog/pack binding, observed image references, downloads, static WebP/AVIF pixel-preserving PNG conversion, manifests and partial/empty coverage | Optional missing-image discovery and semantic product/photo review |
| `sourcing.slides` | Fixed editable layout, conservative tracking-only URL association, source excerpts, unknowns and current input hashes | Inventory regions, source-span selections and comparisons |
| `pptx.render` | Frozen host executables, bounded compatible fallback, exact-candidate PDF/all-slide PNG previews and command receipts | Independent all-slide layout and source correspondence review |
| Presentation correction | Reserved local correction/preview attempts before Start; exact reviewed-version requeue, no attempt reset or uncertain replay | Precise revise findings; factual gaps remain gaps |
| Scheduler and library | Current-work priority plus fair historical reconciliation; stage/task states, errors, whole-workflow time/tokens and unknown records | No acceptance is inferred from status or accounting |

A compatible renderer opening is separate from visual approval. New presentation
reviews consume native preview evidence automatically; corrected PPTX candidates
receive new previews. Source-only and prepared-query reviews keep their own scope;
query preparation does not inherit a claim of verified product facts. Mechanical
URL/hash grouping never establishes distinct purchasable products. JSON-LD prices
retain explicit currency and source offsets, without asserting currentness or stock.

Controlled fixtures exercise the native rendering connector and normal stage
planning/correction/delivery, including one/five alternatives and an unknown source
submission that is never replayed. Packaged and live qualification are recorded
separately in ignored outputs; a controlled pass does not certify retailer evidence.

### Closed-loop compilation and connector recovery metadata

The model chooses a compatible graph; frozen outcome IDs, descriptions and exact delivery references are runtime data. A declared file port can bind to a frozen outcome when its registered format is uniquely compatible. Code records the original/compiled declarations and rewires only exact references. Duplicate or ambiguous same-format outcomes still need an explicit mapping; structural compatibility never establishes semantic correctness.

Before dispatch, new-work workflow proposals compile against the full captured catalog. Complete invalid proposals can receive at most two compiler-feedback turns inside the existing provider round budget, retaining the frozen request, original replies and the fact that no effects dispatched. Incomplete/unknown submissions are not retried. The full captured context is retained and hash-linked independently of its compact model view.

Registered connectors declare saved_evidence (reuse capability and pages/photos kind) and completion_companions. Recovery uses exact finished receipt/artifact identities from that registry; photo ZIP reuse cannot stand in for fetched-page evidence. Target-policy empty catalog-photo results remain explicit partial evidence. Unknown outcomes, stale bytes and expanded permissions stay outside automatic correction.

Desktop workflow attachments use the originating request's frozen manifest, independently of later stage request IDs. Original bytes remain registered; static JPEG/WebP/AVIF images can have a recorded RGBA PNG compatibility copy with original and decoded byte hashes, dimensions and pixel hash. This establishes conversion provenance, not visual interpretation. For an active workflow with its existing completion grant, an unexecuted needs-input planner that provably omitted these selected bytes can receive one immutable successor. The old result and calls stay retained, source recovery is appended, and later stages inherit the recovered versions. Unknown external outcomes and unrelated or genuinely absent inputs are ineligible.

The port-descriptor owner supplies the nested planner output-handoff schema. Empty optional descriptors in companion-enabled requests can be bound from the exact declared output MIME type, with a field-binding receipt; nonempty restrictions, unknown fields and conflicting types remain subject to their original validators. A completion-granted active or blocked workflow can recompile a finished, rejected, unexecuted proposal once per local compiler fingerprint and use an immutable successor with zero provider calls. The rejected context, response, calls and error remain retained. Paused/cancelled workflows and uncertain planning outcomes do not resume through this path; ordinary Start authorization and host-code checks still apply to the recovered plan.

Companion-enabled compilation distinguishes new-file sources from modification baselines: only redundant new-work baseline annotations whose exact IDs remain explicitly selected can be cleared. Native operation scheduler limits are bounded separately from their captured internal HTTP allowance. Registered native criteria are authoritative. Generated checks proposed on a native task remain in the compilation receipt as audit-only text; they are not promoted into reviewer requirements. The independent reviewer retains its explicit semantic criteria and the registered operation checks. This prevents a planner from adding an unsupported output format or stricter count policy through the review boundary. Unlocked generated worker hints can be corrected only to one compatible profile already in the frozen catalog; locked selections, unknown IDs and ambiguity are not changed. Typed record work reserves reading/submission/finish rounds and the registered response minimum within captured stage/API ceilings; explicit low ceilings remain binding. Agent consumers of a selected research pack receive its exact declared independent review output and dependency; native wire inputs remain unchanged. Every correction has a compilation receipt, and raw responses remain retained.


Indexed record contracts declare local artifact capacity separately from model request text. The registered sourcing option/review families admit up to4 MB of exact declared local text; their existing code index,12000-character saved-page reads,24000-character file reads, provider request budgets and response limits remain in force. Plain file/browser profiles retain512 KB text admission. Larger local artifacts are not copied wholesale into sourcing model prompts. Planning and late-bound preflight use the same registered policy.

An existing completion-granted workflow can requeue an unchanged never-dispatched assignment after a confirmed old512 KB admission failure when current indexed preflight validates every exact artifact and native source receipt. This does not create/reset an attempt or accept output. Original failure receipts remain; explicit workflow/run pauses, control interventions, uncertain work, changed assignments/plan/artifact bytes and expanded permissions are ineligible. The controller restores the existing started-plan grant atomically; ordinary workers dispatch only after commit.

### Optional completion helpers and preparation review

Finished-file completion stages distinguish selected operations from frozen optional completion companions. A companion is optional only when its owning connector actually executes and the frozen metadata declares that relationship. Every requested deliverable must still bind to a real producer and independent review; an optional helper cannot stand in for a deliverable or host deferral. Historical exact registered helper reasons are retained in compilation receipts. Legacy and stand-alone selected operations retain their obligations.

The compiler can supply a missing independent review for an internal agent preparation feeding a registered procedure, under the existing completion policy, task limit and worker/budget selection. The procedure waits for that review. Existing explicit reviews, final deliverable producers, human gates, host/API preparations and legacy workflows are preserved. Disabled empty historical design-intent annotations add no requirements and are normalized with a receipt; nonempty annotations outside scope remain errors.

Registered preparation checkers must be part of the exact worker input closure. Photo manifests use a frozen standalone copy of the production structure/public-URL checker; it cannot download images or execute the downstream connector. The existing delivery controller may admit missing same-version code support to a confirmed failed local preparation only with its remaining attempt allowance, preserved draft/source versions, exact workflow/stage ownership and unchanged grant. Active/unknown work, human intervention, exhausted attempts and already dispatched downstream work are held. Recovery receipts retain original assignments and unsuccessful unexecuted plans; schema supply is not acceptance.

Recovery identity is the exact confirmed parent-run/failure snapshot, rather than one permanent slot per parent run. Each distinct snapshot consumes another original stage/global cycle; repeated snapshots do not. Receipt migration preserves all historical contents and row IDs atomically. Lookups for carried artifacts use the frozen baseline digest; public-photo continuations use their exact stopped attempt. A changed confirmed defect after a registered local continuation may resume under the remaining original grant. Human intervention, unknown effects and exhausted allowances still hold work. Optional completion helpers of an exactly receipt-bound reused read remain optional; reuse provenance and exact input closure must validate before save or dispatch.
# Node catalog presentation

`operation_definition.catalog()` is the default UI inventory over existing
registrations. It excludes non-public record contracts and hides registrations
with `node_ui.replaced_by`; `include_legacy=True` exposes those historical
operations. Explicit lookup retains their original schemas and handlers. A
replacement hint never rewrites a saved workflow or grants a replacement action.

Registrations own `node_ui` labels. `operation_definition.presentation()` pairs
those labels with exact input schemas, required/default flags, output media types
and stable binding IDs. For example `images.crop` displays “Source image” and
“Cropped image” while its saved keys remain `files` and `result`. Bundle ports stay
bundles: a readable title does not invent independently addressable subports or
claim MIME alone establishes compatibility. Custom model interfaces remain
workflow-defined. Presentation metadata is excluded from connector execution
fingerprints; parameters, permissions, limits and all other execution fields stay
bound. `node_spec.presentation()` and the read-only desktop `node-catalog` bridge
consume the same projection. The palette is not an installation or grant check.

Content `baseline` is exposed only for a registered recovery hook, and when a
grant is supplied it additionally requires coordination version 1 and delegation
version 4. `collection.subjects` and `document.layout` do not support this field;
other revision interfaces do not imply support for it. Graph validation and node
lowering share the eligible correction-subset schema. The compiler still verifies
exact baseline identity and immutable parameter inheritance. The exact two old
definition fingerprints remain readable only for saved nodes without the
unsupported field; arbitrary drift and invalid historical baseline requests fail.
