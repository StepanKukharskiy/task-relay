# Relay execution architecture

## Canonical node document

[orchestrator/node.schema.json](../orchestrator/node.schema.json) defines current node
files. [examples/summary-named.node.json](../examples/summary-named.node.json) is a runnable
model-node declaration. The runtime validates that document, freezes it in the
existing run grant and derives its named outputs. The same schema supplies
`node_run` declarations, and the desktop displays the admitted document directly.
Authority, limits and current state remain runtime-owned; node files cannot grant
themselves providers or tools. The operation registry still owns native semantics
and generated output ports. This is a contract compiled by the existing runtime,
not another scheduler or independently maintained UI model.

New desktop tasks enter that runtime directly, with ChatGPT Codex and bounded
public reads, without an intake/planning model round trip. This initial desktop
root has a text result port; unsupported native work must remain explicit rather
than acquiring capabilities from the prompt. Saved plan/revision controls and old
node grants retain their historical contracts. Version 1 is immutable after release;
a future incompatible contract needs a new version, preserving old readers.

Version 2 uses one `operation` plus named `inputs`. Each input is a literal
`{value: ...}`, an exact `{artifact: ...}`, or a `{task: ..., output: ...}` binding.
The operation definition derives native parameter/reference inputs and output ports
from the existing adapter/registry. Registered content and review operations lower
into their existing compiler paths. Model nodes declare their requested outputs;
code supplies ports for registered operations. Native operations without individual
reference parameters expose their existing bounded file bundle as `files`.

The same `web.fetch` definition generates the current `web_fetch` tool declaration
and scheduled-node contract. Both invoke the same public reader and share one
run-level six-method receipt store, protected by the existing host lock. A tool
returns the `page` value directly; a scheduled node materializes that value as its
`page` JSON artifact. HTTP/rendered fallback, uncertainty and retained evidence are
unchanged. Switching interfaces does not acquire another read allowance.

Desktop admission exposes literal URLs as named values and attachments as exact
named bindings; it does not fetch or infer authority. Continuation retains literal
values and exact baseline inputs. The app displays the admitted operation definition.
Version 1 remains in `node.v1.schema.json` for historical captures; it is not rewritten.
Node lifecycle controls (`node_run`, `node_result`, history, cancellation) remain
runtime controls, not independently scheduled nodes. Native worker execution still
uses its registered operation handler. No second scheduler or executor is added.

This does not create arbitrary scalar extraction from JSON outputs, native authority
for text-only roots, or a graphical node editor. Named artifact connections use
existing exact-version resolution. Inline web reads are not independent reviews.

## Simplification target: one node interface

The public composition model is an operation with named inputs, named outputs and
visible execution state. Connections bind exact output versions to input ports.
A model, public-page reader, renderer or optional reviewer is an implementation of
that interface, not a separate layer of orchestration. The existing Runtime remains
the only scheduler. A small request can execute in one model node using its granted
tools; useful larger steps can be connected without a mandatory planning ceremony.

Code owns port compatibility, durable versions, limits, dispatch and receipt-based
recovery. Models own interpretation, content and judgments. A review is an explicit
operation when requested or required by the existing capability; it is not generated
merely because two nodes connect. Successful execution is distinct from independent
review and user acceptance. A missing external receipt remains uncertain.

Migration must replace redundant routing and state authorities within these existing
interfaces. A simpler graph display over unchanged mandatory production stages is
not sufficient. Existing runs keep their frozen obligations and evidence. This is
the architectural target, not a claim that all native production paths are migrated.

New job admission uses version 2 of the existing execution policy. Its model-facing
surface is `node_catalog`, `node_run`, `node_read`, `node_result`, `node_wait`,
`node_stop` and bounded history. It replaces the older owner tool declarations for
those jobs; it does not add a second queue, scheduler, compiler or finalizer.
`node_run` compiles registered operations/content/work/reviews through the same
owner-intent compiler. Code derives admission identities. Node names and port names
remain model choices because they express composition, not runtime bookkeeping.

`node_result` accepts named text outputs or exact existing output references. It
saves immutable versions and resolves bindings in code. A simple result takes one
call; no read-back of newly authored text or copied artifact-ID manifest is required.
Unfinished output can be saved, and a continuation supplies only changed ports.
Delegated outputs still require inspection. Required independent/native reviews,
procedural checks, unresolved findings and uncertain effects still gate completion.
Unreviewed text is explicitly labelled unreviewed; completion is not acceptance.
Historical execution policies retain their original declarations and obligations.

Isolated public reads use an owned temporary browser profile. Confirmed closure
removes only that scratch profile; captured DOM/text, network guard and operation
receipts remain durable. Unknown closure leaves scratch state for diagnosis. No
historical or authenticated profile is cleaned. HTTP/rendered reads retain the
same shared method allowance and no-replay rules.

The native/content adapters and frozen historical stage APIs remain compatibility
surfaces. Desktop conversational intake still has legacy planning routes for work
outside the bounded immediate text capability. This migration does not claim those
UI routes were removed or that every application can now execute without a review.


## Job owner with optional delegation

The target is one logical owner for the complete user request. That owner keeps
the exact request, current artifact versions, outstanding requirements and worker
results across turns. It may do work itself or launch multiple specialist agents,
then integrate their results and inspect the final deliverable. Delegation does
not transfer responsibility for completion to the user. A physical provider
session may end; the logical owner and its evidence must survive.

Workers and registered operations use the existing `Runtime` queue. There is no
second scheduler for the owner. Code commits assignments and dependencies before
dispatch, validates artifact identities, enforces the saved authorization and
chooses eligible continuation from confirmed receipts. Models choose useful work;
they do not choose between internal resume/recover mechanisms. Unknown external
effects still require reconciliation, and a genuine authorization or billing
failure may require user action.

The first source migration adds `Runtime.add_futures` and the trusted local CLI
`add-futures RUN ASSIGNMENTS_JSON --request-id ID`. A batch can contain parallel
workers, their integration task and a reviewer. Whole-graph validation and one
transaction prevent half-admitted delegations. Repeating an identical request
returns its saved admission receipt; reusing its ID for different work fails.
Existing assignments, request brief, concurrency and attempt history are retained.
This trusted interface is not exposed directly to untrusted worker replies and
does not grant additional scope. Its caller must enforce the owner's saved grant.

New planning captures also select structural review policy version 1. When the
compiler partitions a collection, the registered reviewed-record-merge adapter
already checks exact reviewed input versions, complete coverage and duplicates.
The compiler can therefore omit its generated structural-only model reviewer and
make consumers depend directly on that verified merge. Semantic partition
reviews, requested review documents, explicit user gates and separately declared
semantic output validation remain. Existing saved planning scopes retain their
old graph. No failed live reviewer is retroactively marked accepted.

This is a partial migration. The current production planner still uses stage
boundaries and mandatory intermediate reviews elsewhere. The next integration
must make a durable job-owner turn consume worker outcomes and delegate through
the existing runtime under a job-level grant; it must replace those planning
paths rather than wrap them in another controller. Source tests of admission and
composition do not establish that model decisions are efficient or that the full
job finishes unattended. Qualification requires an unscripted complete job and a
subsequent change, retaining final-artifact review and intervention counts.

## Ownership

`relay_pipeline_steps` is the durable owner of a workflow stage. Its exact binding
identifies a plan or production run. `production_tasks` owns logical assignments;
`production_attempts` preserves physical invocations, frozen inputs, receipts and
rejected results. These are layers of the same persisted workflow, not competing
queues. `workflow_state` projects the current binding, phase, uncertainty, remaining
recovery capacity and next action for the UI. Historical failed attempts do not
replace current job state.

The existing controller commits allocation, assignment, queue changes and recovery
receipts atomically. It dispatches workers after commit. Collection records and
review fragments commit to the same attempt-bound database. Correction produces a
new artifact version and a fresh independent review obligation. Neither a schema
pass, technical check, completion seal nor recovery receipt establishes acceptance.

## Registered tool adapters

The operation registry declares identity/version, ports, capacities, permissions,
companions and effect policy. `execution.ADAPTERS` supplies a trusted `Adapter`:

- Parameter wire schema and ordered semantic validators.
- Local availability and catalog metadata hooks.
- Exact-input preflight and host/runtime binding hooks.
- Execution handler and receipt inspection hooks.
- Structural attempt policy and supported correction kinds.

The catalog, central assignment validator, claim path and child runner delegate to
those definitions. Adding a transport does not require a branch in the central
runner. A new trusted module can produce a framework-written `Result`, or use an
existing format adapter that materializes its declared outputs and receipt. Unknown
operations have no fallback executor. Unknown binary media are not decoded as text.

The captured connector digest includes the adapter manifest. Claims freeze the
implementation modules used by execution, semantic validation, preflight, host
binding and receipt observation. The child verifies those hashes. A saved pinned
interface is never silently upgraded to new semantics.

Receipt inspection is transport-specific; the common controller independently
normalizes uncertainty. An external intent without a confirmed outcome remains
unresolved through restart. In particular, a generic worker exception cannot stand
in for a native host's matching terminal receipt. Reconciliation observes the
original attempt; it does not create a duplicate submission. An adapter that cannot
prove a remote outcome must expose a meaningful hold.

## Generic content contracts

`collection.subjects` v1 accepts bounded subject fragments from one exact text,
JSON or visual PNG source. Semantic field names are parameters, not furniture
categories. Unknown attributes are null. Text observations retain literal source
quotes; visual observations retain normalized boxes. Code assigns subject IDs,
source identity, JSON/Markdown projections and a completion seal. An independent
reviewer receives the exact source and candidate.

`collection.options` and `collection.review` use configured field definitions,
identity fields and count policy over those subjects and captured sources. Existing
merge, image and slide adapters consume the same version-bound artifacts. Empty
results under target policy remain explicit gaps; required quantities retain their
hard constraints. A successful HTTP response is not adequate research evidence.

Historical `sourcing.inventory` remains furniture-specific and immutable. Its
category enum is not part of the generic subject contract. New planning interface
version 2 advertises generic subjects; version 1 retains its previous choices.
Historical sourcing options and reviews remain compatible with saved assignments.
The record engine delegates context, fragment validation, progress, projections,
completion and recovery behavior to the registered content lifecycle. New content
families can supply assignment/document validation hooks without changing it.
The worker obtains context and implementation hashes from those registrations;
non-indexed records do not implicitly select a computer executor.

## Deterministic verification reuse

At worker claim, code binds supported mechanical checks to exact staged input
bytes. Persistent receipts key the input hash and length, check ID, parameters,
validator implementation and runtime dependencies. The initial checks cover strict
JSON parsing, image decoding and registered sourced-image archive integrity.
They do not establish schema validity, factual support, visual correspondence,
current availability or acceptance.

The claim transaction records new receipts and their assignment binding before
dispatch. A matching intact receipt can be reused after rejection or restart;
changed bytes, parameters or implementation require a new check. Failed checks
remain failed, and damaged receipts are retained while a new check is recorded.
Implementation invalidation is deliberately conservative: any orchestrator module
change invalidates these receipts until narrower dependency declarations exist.

CLI and API workers receive the same verification packet. Registered JSON
corrections also receive exact changed JSON pointers when comparison is safe;
array length changes invalidate the whole array. This is navigation assistance.
Every candidate still needs its independent semantic review. Reusing semantic
verdicts would require explicit per-criterion dependency and acceptance records;
the current implementation does not infer those from a prior report.

## Persistent continuation

`continuation_adapters.REGISTRY` declares stopped-work classification, proof,
successor construction, eligible gap kinds, grouping/gate constraints, authorization
checks and receipt projections. Adapters do not queue work or spend grants.

`continuation_owner` allocates a workflow cycle and delegates each continuation to
`Runtime.continue_attempt`; it updates the owning stage in the same transaction.
Native preflight, review sessions, saved review budgets, isolated public-browser
setup and typed checkpoints all use that path. Legacy entry points forward to it.
Dispatch rechecks exact parent receipt, evidence, assignment, adapter manifest and
allocation. No-progress and exhausted-capacity cases remain holds.

The blocked-stage scan uses its persisted owner and existing grant. Error prose and
an additional failure-kind allowlist no longer determine eligibility. The common
recovery admission decides whether a confirmed baseline supports continuation,
local correction, graph revision or a precise hold. Explicit control changes,
uncertain effects, changed evidence, human gates and unavailable authorization are
not retry permission. Historical zero-dispatch allocations retain their original
baseline while using separately proved current classification.

Whole-graph corrections and delivery remain specialized transitions under their
existing owners and transactions. They cannot be reduced to repeating one worker:
a graph revision changes dependencies and review obligations; delivery confirms an
external effect. Both retain exact identities and existing authorization.

### Local correction capacity reservations

A registered local prepared-data correction keeps the exact original admitted
stage and worker ceilings. When its workload requires more than one default
recovery worker slot, its immutable graph records a versioned reservation of
multiple slots from the existing per-cycle pool. Each task consumes the maximum
of its rounded-up time, tool and provider-request slot requirements. Total
reserved slots cannot exceed the saved pool; cycles and attempt counts do not
increase. Smaller explicit provider limits remain binding.

The reservation binds the original planner, context, options and worker profile.
Dispatch re-proves those identities, the rejected candidate and independent
findings. Missing authority, profile changes, lower original ceilings, uncertain
effects and insufficient total capacity remain holds. Small historical graphs
retain their existing identities. This is allocation for proven local data
correction, not permission to add external operations or infer acceptance.

## Extension and qualification contract

A new tool must declare compatible ports, limits, parameter/semantic validation,
execution and effect observation; a new recoverable failure must provide a
registered proof and bounded successor. Tool names supplied by a job cannot name
Python callables. Trusted registration is a deployment operation.

The controlled qualification fixtures cover:

- A previously unknown execution/inspection adapter composed with an existing
  operation through restart; an unresolved effect does not release descendants.
- Plant, furniture and component data through the same subject/collection path,
  idempotent fragments, invalid seals, changed sources and explicit missing data.
- Three configured collection graphs through native PPTX construction, independent
  review and a scoped correction, retaining source and photo versions.
- Continuation rollback, grouped allocation, repeated review, inherited capacity,
  adapter/receipt drift, first-failure discovery and historical replan recovery.
- Actual scripted worker tool loops, checkpoint/review recovery, native PPTX
  creation and final workflow delivery.
- Every registered operation's structural port pairs and parameter contract.

This is a bounded architectural contract, not a guarantee for every future tool or
sequence. Structural compatibility still requires bound-content checks and semantic
review. Controlled transports do not establish live website yield, model quality,
provider availability or native application compatibility. Installed-package and
live qualification are separate from source qualification; these changes alone do
not update the installed application or authorize paid work or outbound messages.

## Source qualification status

The main affected integration run passed 191 tests. After the final generic content
context and implementation-binding changes, 54 affected tests passed, including the
new visual-subject worker-to-PPTX path, existing full native chain, provider-neutral
record tests and continuation cases. The dependency-light CI command passed 30 tests;
six extension/host-preflight fixtures passed separately. Counts overlap. Initial
failures, fixture corrections, exact commands and limits are retained in the local
qualification log. This is source qualification; the installed application and
services were not modified by this consolidation.


### Integrated persistent-owner execution

`orchestrator.job_owner` is an ordinary Runtime task, not another scheduler. The
frozen grant bounds worker profiles, registered operations, tasks, invocations,
inputs and deliverable types. Its confirmed conversation is checkpointed at
yields. Delegation commits the batch, service dispatch digest and admission
checkpoint together before the scheduler can launch children. A confirmed local
stop can recover that checkpoint; a pending provider response remains uncertain.
Failed delegates return to the same logical owner, retaining their failed attempts.
Code supplies producer/reviewer criteria bindings and validates exact final
artifact identities and independent verdicts. Visual document completion also
requires inspected registered rendering evidence. `image_view` reads assigned PNG
files or bounded PNG members of assigned ZIPs without extracting or generating
images. Native structure checks do not imply semantic acceptance.

The trusted `create-owner` CLI accepts a frozen proposal; `--scheduled` admits it
to the existing desktop production service through `persistent_jobs.start`.
`revise-owner PREVIOUS RUN REQUEST.txt --scheduled` creates a new version through
the same service, preserving exact prior artifacts and the verbatim change request.
No new controller, provider fallback, recovery allowance or user acceptance is
created. The desktop Jobs list derives the logical owner state even when old
delegates failed. Existing executed graphs and natural-language planner routing
remain unchanged; new owner jobs use the explicit entry point during qualification.

Controlled tests cover retained conversation, atomic delegation, native and agent
composition, exact revision inputs, failed/uncertain workers, crash after admission,
service grants, terminal cancellation draft retention and document pixel inputs.
Live task quality and intervention counts are separate acceptance evidence.


### Owned code workspace

A delegated Python worker retains an assignment-local working directory between
calls. Each successful call commits a bounded snapshot with file hashes; the next
call copies that snapshot inside the existing host sandbox before executing.
Scripts and intermediate files are working state, while only declared outputs
enter the artifact store and delivery review. Failed calls retain the previous
successful state; uncertain calls require reconciliation and cannot replay.
The existing output-byte allowance covers working files, and filesystem grants
reject links or changed snapshots. No new scheduler or host authority is added.


### Registered data preparation in owner jobs

The owner catalog exposes the same `records` intent schema as ordinary planning.
Delegation invokes the existing record compiler: source references and semantic
parameters become exact fragment contracts, JSON/Markdown projections and paired
review bindings. The model does not author projection envelopes or search the
application filesystem for schemas. Registered subject-review criteria are
enforced by graph validation. Granted code-worker profiles include their existing
qualified library report. Capacity, artifact authority and dispatch remain owned
by the same Runtime and frozen job grant.


## Registered document authoring

New owner grants snapshot document-authoring routes independently of historical
connector snapshots. Admission rejects worker-created supported document formats
(including extension/MIME disguise), unless the trusted grant explicitly permits
that format and the assignment records its fallback reason. Missing renderer
authorization is a missing capability, never permission to generate custom code.
The same policy accepts registered format extensions without a new controller.

The `document.layout` record family reuses the transactional record store, exact
input hashes, immutable fragments, idempotent submissions, capacity checks and
completion seals. A declared-file worker selects registered layouts and supplies
content; it has no Python tool. Code serializes version-2 layout specifications,
checks image references and page bounds, and the existing `pptx.create` renderer
creates native editable objects. Content cards and image grids paginate ordered
collections without dropping entries. Registered layouts own geometry; hyperlinks
and images survive native save/reopen checks. The exact rendered output still
requires independent semantic and visual review. This does not verify retail
facts, manufacture missing photographs, or guarantee aesthetic quality.

Future renderer formats need their own registered content adapter and output
route. There is no promise of arbitrary future format support. Existing jobs keep
their original grants; installing the implementation does not rewrite a failed
trial or retroactively make it unattended.

## Bounded working context and deterministic handoffs

New owner grants freeze working-context and handoff policy versions. The owner
keeps its original request and latest durable state in a bounded provider-facing
view, alongside complete recent tool exchanges. Full journals remain unchanged.
Older exchanges are archived by content hash and paged through `job_history`,
including after owner restart. Catalog discovery returns compact operation IDs;
exact contracts and record schemas are fetched on demand. Source excerpts carry
exact hashes and explicit continuation offsets. These are transport bounds, not
new request allowances. An oversized mandatory exchange fails before submission.
The text-byte measurement excludes image payloads and is not a token estimate.
This policy currently applies to the owner; specialist workers retain their
existing context and evidence mechanisms.

The shared structural registry validates registered document formats before
review dispatch and at output collection. Receipts bind exact bytes and validator
implementation and can be reused without another model call. PPTX checks reject
empty decks and broken internal relationships; PDF checks reject zero-page files;
JSON checks parse the candidate. Draft progress for PPTX uses uncompressed content
identity, excluding package properties and ZIP ordering/timestamps. PDF still
uses raw-byte progress identity. Structural validity does not establish factual
support, useful slide content, visual quality or acceptance.

The handoff compiler follows exact artifact-producing assignments and future
output references, derives dependency edges and carries authorized evidence to
agent consumers and reviewers. An exact rejected artifact can be an input to a
correction without depending on the failed task becoming accepted. Agent evidence
path collisions receive stable aliases. Native asset paths must remain exact;
conflicts fail before dispatch. Registered renderer companion metadata selects
assets without feeding unrelated research files into a renderer's single data
port. Reviewers traverse the full ancestry even across those native boundaries.
Existing capacities and artifact authority remain enforced.

Registered record-family asset representation admits bounded exact PNG/JPEG/ZIP
inputs to declared-file workers without code execution. The layout context
validates bundles and exposes their exact image-member paths. Binary `file_read`
returns metadata, not fabricated observation. PNG pixels remain available through
the existing capable visual adapter; JPEG assets are selectable/renderable but
that adapter does not yet expose direct JPEG pixel inspection. Final review must
inspect the registered rendered pages. The existing structured final-quality
contract assesses requested visual deliverables; native render success alone
cannot satisfy semantic review.

Qualification uses scripted provider replies with real journals, database
transitions, record stores and native file construction. Passing those checks
does not establish efficient model decisions or unattended delivery. Source,
installed-package and live results must continue to be reported separately.

The installed worker may be launched as a script rather than imported as a
package. Qualification exercises both identities, including owner context and
code-output progress paths. A changed-worker startup failure can use the existing
continuation registry only with confirmed zero provider/tool dispatch, no outputs,
unchanged exact inputs and remaining original attempts. Code binds the original
receipt, journals and implementation change and rechecks them before dispatch.
This does not reset capacity, imply acceptance or replay an uncertain action.


Registered content ports distinguish a record contract from its JSON MIME type.
Adapter metadata declares the parameter-to-record-role mapping; the shared reader
validates the exact registered document and completion seal at owner admission,
late-bound scheduler claim and native child execution. Unknown versions, wrong
roles and unsealed data fail before effects. Available inputs are checked before
the delegation transaction commits; future bytes remain subject to the same
check at claim. Existing evidence-specific execution validators and independent
semantic review still own provenance and acceptance. New metadata changes the
captured connector definition; old grants are never silently recaptured.

The persistent owner receives bounded structured task-failure diagnostics. A wait
is valid only while a child is active, uncertain, externally gated or ready to
queue. Failed children and queued descendants with unsatisfied dependencies do
not constitute pending work. An invalid wait returns a tool error within the
existing invocation. If the owner spends that invocation without correcting it,
no yield checkpoint is created to buy another identical invocation. Successful
delegation, external uncertainty and existing capacity accounting are preserved.


## Compiled owner delegation

New delegation policy 3 is described in [the owner process review](owner-process-review.md). It composes the existing registered record, partition, review, native operation and runtime interfaces. Required graph expansion consumes the original grant and is admitted atomically; it does not add an execution controller. Discovery, admission and dispatch share their effective capacities and available-input checks. New readable history is separate from immutable provider journals. Legacy captured policies remain intact.

## Reusable input declarations (node version 3)

Version 3 preserves the named binding model and adds `input_definitions` for
custom model nodes. Each declaration supplies `type`, `label`, `required` and an
optional literal `default`. An artifact field declares its accepted `media_type`
(`*/*` explicitly accepts any artifact); artifacts cannot be literal defaults.
Registered operations continue to own their input/output definitions. Versions 1
and 2 retain their original schemas and frozen captures.

[examples/reusable-summary.workflow.json](../examples/reusable-summary.workflow.json)
is a saved batch of those same nodes with workflow-level input declarations.
`{workflow: "article_url"}` means the value is supplied for that run. Code validates
run values, applies defaults and replaces these bindings in a separate copy.
Missing required values or incompatible connections fail before dispatch. The
saved draft and prior run bindings are never edited. Setup inputs currently accept
literal values; uploading a file uses existing exact-artifact admission instead.

`node_spec.resolve_workflow` and `inspect_graph` are the shared draft/admission
validators. They use registered operation schemas and output ports, declared model
media types, and the Runtime's dependency/cycle rule. The read-only desktop bridge
action `node-validate` returns the same validation with `execution_authorized:false`;
actual admission still checks the frozen grant, capacity and artifact access.
No canvas, inspector, setup form or frontend control was implemented.

An explicitly supplied workflow file can be executed through the existing app's
attachment path: `node_run` accepts `{workflow: {artifact: id}, values: {...}}`.
Code reads the authorized hash-checked artifact (maximum 64,000 bytes), resolves
its graph and compiles it through existing owner admission. The same transaction
records the template artifact/hash, supplied request, resolved values and actual
assignments. This introduces neither an executor nor another scheduler. It avoids
asking a model to reconstruct a saved graph. The file cannot grant a provider,
operation, budget, acceptance or an uncertain replay.
