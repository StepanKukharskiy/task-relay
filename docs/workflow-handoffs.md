# Declared workflow handoffs

## Versioned job view and stage context

For a saved pipeline, the workflow folder now retains a versioned
`.relay/snapshots/<snapshot>/job-state.json`. This is a readable projection of the
committed Relay database, alongside the existing manifest and exact stage records.
It lists the original objective, stages, registered artifact identities and hashes,
saved selection decisions, attempts, and potential dependency edges derived from
frozen inputs. Scoped replacement heads and advisory outdated-output records are
included when they exist. A new snapshot is written after a committed change.
Editing the export does not change the job or grant an agent permission to act.

Before calling the orchestrator model for a pipeline stage, Relay compiles a
`job_context` from the same committed records. It includes that stage, its exact
selected source artifacts and their recorded upstream artifact ancestry, relevant
selection decisions, and known missing evidence. Current replacement warnings for
its inputs are included without changing past acceptance or scheduling. The
complete captured job view is available through `context_read` when the overview
omits a relevant relationship. An oversized stage stops with an explicit error
rather than silently dropping a selected source. Existing stage approval and
dispatch checks still use the canonical database.

This first contract covers registered pipeline work. A declared input is a
*potential* dependency, not proof that a worker used it in a particular claim,
slide or cell. It does not yet maintain a general entity/fact registry, discover
unregistered manual file edits, or support catalog-scale context retrieval.

## Controlled XLSX fact revision pilot

The O14 source implementation adds opt-in, explicitly reviewed product material
bindings. Each binding records the exact source artifact/hash, sheet, product key,
cell, evidence and review state, plus the exact catalog artifact/hash and output
cell. Output coverage is declared separately; a cell with missing evidence is
`incomplete`. No binding is inferred from a declared workflow input.

Given an explicitly registered source replacement, `plan_impact` compares the
fact under the stable product key and reports covered output locations as
affected, supported as unaffected, or unknown with reasons. Missing or duplicate
keys, stale artifact bytes, incomplete review and conflicting sources prevent an
unaffected claim. This read neither approves nor starts a revision. An explicit
candidate writer changes only the reviewed affected direct-value cells in a
simple XLSX, verifies untouched values, formulas and styles, and registers a
distinct artifact. A separate reviewer identity can record `accept` or `revise`
after candidate revalidation. Only an independently accepted exact artifact may
receive an explicit selection receipt. The candidate writer alone does not accept
or select it. The development desktop review screen now presents these exact
candidate decisions. Workbooks with unsupported embedded features are rejected without
a partial rewrite.

For an external XLSX producer, `impact_handoff.record_xlsx_change` freezes the
exact request, registered old/replacement/catalog artifact IDs and current
reviewed impact plan in authoritative SQLite before dispatch. The equivalent
desktop-independent CLI action is `python -m task_relay.impact_handoff
create-xlsx-change`; `inspect` returns the immutable handoff with its digest
and a current/stale status. An agent can consume that JSON plus the exact
registered workbook versions. It must return an XLSX candidate and a
location-level explanation; the handoff does not authorize editing or selection.
`fact_revisions.submit_external_xlsx` admits a returned file under an idempotent
submission key only after rechecking the frozen plan, exact affected values and
all untouched values, formulas, styles and links. The candidate artifact and
submission checks project into the job's JSON/SQLite views. A separate technical
review may accept the exact bytes; user selection remains distinct. External
agent dispatch/attempt receipts are marked as outside Relay's runtime until
Relay itself owns that dispatch.

The blind controlled case (private evidence)
froze the evaluator answer before an independent producer received the handoff.
One affected material cell changed, one supported cell stayed valid, and two
unknown cells remained unchanged. The returned candidate passed admission and
technical review without user selection. This tests explicit cell links in tiny
synthetic XLSX files; it does not establish source discovery or a real-job
provider dispatch.

Each workflow export now includes `.relay/job.sqlite` and a versioned SQLite copy
beside `job-state.json`. These queryable files project committed job artifacts,
fact bindings, coverage, candidate revisions, reviews and selections. They are read-only views;
editing them cannot change Relay's database or grant execution authority. The
process projection and media ownership extension were installed in local 0.13.107
and remain in 0.13.108.
One completed media pipeline was backfilled and its published JSON/SQLite views
verified against the same snapshot.

The local app also projects a versioned process ledger into both
the JSON view and SQLite `process_records`. It covers exact requests, stage plans,
assignments, attempts, checks, decisions, exceptions and recovery receipts, plus
general events and unacted decision controls. Each row keeps its source table,
source ID, stage/run scope, relationship scope and the committed row as JSON. `process_coverage`
reports complete, empty, pending, not-recorded, external or incomplete for each
category; `process_gaps` names missing
plans, runs, assignments, attempts, receipts, checks and artifacts. `complete`
means the registered pipeline and its resolved plan/run ancestry were projected
without a missing expected record. It does not mean the work passed validation
or that a pending attempt has finished. `empty` means no row was found in the
declared scope, not that no event ever happened outside it. Shared channel
conversation history has an explicit `external` marker because it is outside
this job-local scope. For a media stage, `relay_pipeline_task_links` records the
exact stage request, backend job and separate agent task. The projection includes
that task's execution records, frozen media references and attributable outbox,
attachment and channel receipts. It leaves unrelated turns on the same task out
of the job view and names the unassignable shared-message boundary. Older media
stages need an explicit verified backfill; absent or conflicting links are
reported as gaps. These links alone do not grant pipeline Delete authority over
the separate agent task or shared conversation.

This export currently covers saved pipelines and standalone production-result
folders. Ordinary watched agent chats do not yet receive a `.relay` job folder;
the saved-work inventory lists them separately.
For a selected standalone result, local 0.13.109 records the exact root plan,
original request hash, channel and current run in `relay_standalone_jobs` before
export. The process ledger includes that ownership row or explicitly reports its
absence in an older export.

The process collector and SQLite builder have no desktop dependency. A standalone
reader can inspect a published view with
`python3 -m task_relay.job_record /absolute/path/to/.relay/job.sqlite`. Relay
Desktop remains the reference UI for reading the same records. The shared
`state.sqlite` remains the only execution authority; editing any `.relay` file
cannot approve, dispatch, select or delete work. Older job SQLite files without
the process tables report `legacy_process_missing` until republished from their
committed records; the reader does not silently upgrade or modify them.

Saved-job deletion is a separate runtime operation used by Relay Desktop.
`job-delete-preview` resolves the exact database rows owned by a selected
pipeline or registered standalone result, including linked plans, runs, attempts,
reviewed evidence and decisions. The legacy `pipeline-delete-preview` action
remains available for existing clients. The confirmation carries a digest of those rows; Delete
recomputes the graph inside one write transaction and rejects changed, active,
uncertain, missing or shared downstream work. Owned rows are deleted atomically
with a minimal cleanup receipt. The service retries pending cleanup at startup,
and Saved work offers Retry cleanup if a file operation still fails. Cleanup
uses the workflow export lock; an in-progress publication leaves cleanup pending
for retry. It removes `.relay` and Relay-generated request, manifest and handoff metadata in
the managed workflow folder. Native deliverable copies and external project
folders remain. A blocked preview does not authorize deleting a subset of the job.
For a standalone result, Relay can explicitly register an older selected job
before preview only when its exact plan/run ancestry, sent result handoff and
Relay folder ownership marker agree. It preserves the shared conversation and
sent delivery records; pending delivery or another job's use of a plan, run or
artifact blocks deletion. A real-database in-memory copy gave one unblocked
preview and one blocked preview for active work. The installed read-only inventory
showed two historical registration candidates during installation qualification.
After explicit user approval, one completed Rhino result was registered and
deleted in the installed app; its 155 owned rows and private job view are gone,
while selected native files and shared sent delivery remain. The other historical
candidate blocks on active or uncertain work. Shared channel history and ordinary watched
agent chats require a separate lifecycle contract.
In installed 0.13.107, a completed Gemini image task can be removed with its
pipeline only when Relay proves a single stage and backend turn, exact dispatch,
provider history, artifact ownership, idle task state and completed delivery.
The task's local reply routes and provider traces are deleted; private trace
paths and hashes are frozen in the durable cleanup receipt for safe retry.
Another turn, task owner, pending delivery, missing record or unknown reference
blocks deletion. Shared channel conversation history and external messages remain.
Ordinary watched agent tasks are still outside this action. This media deletion
rule passed an isolated copy of a real pipeline and is installed in 0.13.107.
Its read-only Delete preview is unblocked for that pipeline. No live media
pipeline deletion has been performed.

Installed local 0.13.110 has a separate managed-task Delete contract. It previews one
idle provider task's exact completed turns, local message routes, delivery and
provider records, selected preferences and private provider trace hashes. One
direct image/video request may join when its request, dispatch, provider turn and
attachment handoff have exact single-owner evidence. Completed attachment
batches and uploads stay with a permanent receipt link so late members cannot
resubmit the original caption. A
changed digest or any active, uncertain, missing, cross-job or unclassified
reference blocks deletion. Proven rows commit atomically with a cleanup receipt;
trace deletion can retry after interruption. External channel messages, external
provider conversations, native/input files and project folders remain. Codex
tasks and pipeline-linked media tasks are outside this standalone task action.
Saved work shows Delete only for an unblocked task. An isolated copy of a real
independent image task passed deletion of 28 owned rows and three copied traces;
its attachment batch and upload remained. A read-only scan found four eligible
tasks among the 18 managed tasks in the current live database. The installed
bridge verified one unblocked preview; no live task was deleted.

Local 0.13.112 includes a separate Telegram shared-history action for a standalone
job deleted under its new receipt format. Job Delete freezes exact retained
request and sent-event IDs in its receipt; it does not remove that shared history
automatically. Saved work offers a second confirmation only when all retained
requests are terminal, every sent event and part is acknowledged, incoming-update
deduplication remains, and no new event or other typed record claims the request
or delivery. The action removes the local `orchestrator_chats` request rows and
clears `outbox`/`outbox_parts` text in one transaction with a permanent receipt.
Event identities, sent flags, incoming deduplication, channel and reply routing,
external Telegram messages, native files, uploaded inputs and already frozen
copies in other jobs remain. It neither recalls a Telegram message nor starts
new work. The prior live deleted job has a legacy receipt without frozen event
ownership; Relay refuses to infer that relationship from event prefixes. Messages
delivery and histories outside proven standalone ownership are still open.

The bounded revision adapters also project one normalized `reviewed_links` model with
typed source and output locators, exact hashes, evidence and declared coverage.
Each new candidate saves a normalized impact record in the authoritative database;
`reviewed_impacts` in the job JSON/SQLite export is its read-only copy. Only
explicitly covered locations appear. An unaffected claim requires complete
reviewed links, and an unknown retains its reason. The desktop evidence preview
reads this shared model. File readers, source-change interpretation and candidate
writers remain adapter-specific.

### Frozen change-plan handoff (development source)

`task-relay impact create-native-withdrawal` records the exact UTF-8 request
from a file, caller-provided request key and actor, typed subject, registered
baseline artifact, and a digest of the conservative pre-agent plan in the
authoritative database. The same key and unchanged evidence return the same
handoff ID; a changed request or plan requires a new key. Export runs only after
the commit, and retrying the same key retries a failed `.relay` export without
duplicating the plan. `task-relay impact sync` retries job-view export from
already committed records even if the old plan is now stale. Relay's existing
export rules preserve a user-modified copy. `task-relay impact inspect` opens the authoritative
database read-only and recomputes whether the frozen plan is current. Neither
command edits a deliverable, selects a result, or dispatches an agent.
Inspection distinguishes a changed plan (`stale`), an unavailable verifier or
source (`unverifiable`), and a corrupted frozen record (`invalid`). Only
`current` is suitable as a continuation input.
The source readers required by reviewed links must be present in the inspecting
runtime. A missing PDF reader reports `unverifiable`, without changing the saved
plan or implying that the source itself changed.

The handoff is copied to `impact_handoffs` in `.relay/job.sqlite`, the JSON job
view, and the job-process ledger. The copy is for agent context; commands that
change Relay state use the authoritative database and revalidate freshness.
The first typed change is a `native_subject_withdrawal` from a PPTX deck. Later
change kinds can use the same envelope while keeping source interpretation and
native validation in their adapters. Relay Desktop is not required for the
recording, inspection or export contract.

### External-agent native candidate (development source)

Any agent with the frozen handoff and registered baseline can prepare a PPTX and
a version-1 `pptx.edit` manifest. `task-relay candidate submit-native` takes the
authoritative database, handoff ID, caller submission key, candidate file, manifest
file and agent identity; picture edits also need an images root containing the
declared relative paths. The command rechecks the handoff and baseline,
requires one declared edit for every affected native locator and no extra edit,
reconstructs the edit with Relay's bounded text/table/picture/notes adapter, then compares
all OOXML member names and uncompressed bytes. ZIP ordering and compression metadata
may differ. The original file is never overwritten. The returned artifact hash and
plan digest identify the exact version for the next decision.
Removing a whole table row or shape is admitted only when every nonempty run or
embedded picture in that object is an affected reviewed location. An unreferenced
picture part can be removed from the package. Notes runs have exact indices and
must be included in the plan before a candidate may change them.

`task-relay candidate verify --database DB --artifact ID` rechecks the registered
candidate and image inputs read-only. `task-relay candidate review` requires a
different reviewer, `--decision accept|revise`, `--note-file`, and the expected
candidate SHA-256 and plan digest. `task-relay candidate select` requires an
independent acceptance of those exact versions, an explicit selector,
`--receipt-file`, and the same expected hashes. Submission never implies approval;
these commands neither dispatch an agent nor select a candidate automatically.
Review and selection are separate authoritative records. A failed `.relay` export
can be retried with the same submission key or `task-relay impact sync` after commit.

The bounded check certifies that the submitted package contains only the declared
native edits. It records semantic review as pending and visual review as not
performed. A changed table cell or picture can still be wrong for the user's
purpose; a reviewer must inspect that independently. Charts, masters, slide order
and PowerPoint edits outside the declared adapter are unsupported. A controlled
removal-only Oleander candidate has been admitted on a copy of the real deck;
it is unreviewed and unselected, and the empty right half of the photo slide
needs a treatment decision before it becomes a finished deliverable.

The separate motorcycle translation pilot accepts only the exact ten rows of the
user-selected XLSX and its verification report. It records each original Yamaha
TXT or Harley XLSX source row, output row, saved catalog locator and selection
receipt. A registered source replacement reports changed supported names,
supported unchanged names and unresolved rows. For a changed English source name,
the candidate blanks only that row's Russian name and name-confirmation URL,
changes its status to `требует проверки`, and records a review note. The saved
catalog title remains visible as historical evidence, not a fresh validation.
The writer checks all other cells, formulas, styles and hyperlinks and leaves the
candidate unselected. It does not perform a new catalog search or translation.
In local 0.13.108, an explicitly accepted and selected translation candidate
carries its exact row links into the new workbook version atomically with the
selection. Changed Russian names remain unresolved; unchanged reviewed names
retain their evidence. Each continued link includes a machine-readable parent
link and selection receipt. A supported row with an unresolved replacement source
blocks selection. A controlled second change worked after database restart; a
failed post-commit export was repaired by retrying the same decision request.
This has not been exercised on a real selected candidate.
The separate frozen Yamaha real-file holdout produced one unselected candidate
after a changed part name and source-row moves. It preserved six supported names
and three unresolved names. Its strict predeclared cell set omitted three
provenance locator updates; `outputs/o14-holdout/report.md` records that scoring
discrepancy and the isolated export recovery. This is not a selection or a fresh
catalog verification.
An independent general-agent control on the same frozen files reached the same
conservative translation decision. The exact-cell rule and the separately
adjudicated provenance rule gave different strict outcomes, documented under
`outputs/o14-independent/`. Installed 0.13.107 listed this isolated candidate
but its older translation adapter could not verify the new plan digest. Installed
0.13.108 lists and verifies it in a disposable read-only bridge check, with review
available. No decision was made.
The isolated real-file replay is described in `ROADMAP.md`. Local app 0.13.102
includes the review controls. Its installed screen displayed that earlier
candidate and its evidence in a disposable copy of the job database. The
candidate is not in the live app's database. No accept, revise or selection
action was exercised.

## Shared revision review contract

The development desktop companion now lists registered revision candidates
from the material-cell and parts-translation adapters. Both expose the exact
candidate and plan digest, affected locations, supported unchanged locations,
unknowns, file checks, and any recorded review or selection. A reviewer can accept
or request revision with a note; selection is a separate explicit action available
only after acceptance. Each decision rechecks the candidate and plan, records an
idempotent request receipt, and refreshes the read-only workflow export after the
database commit. These controls do not run a worker or infer missing evidence.

This is a shared review surface, not a universal source parser or file writer.
Other job types need an adapter that records reviewed links, plans impact and
validates its native candidate. A bounded presentation adapter now links reviewed
XLSX source cells to exact PPTX text runs by slide and shape ID. It plans only
declared locations and uses `pptx.edit` to create a separate candidate. The
controlled three-slide transfer case changed one plant run, preserved the
independent climate slide and left an unlinked run unknown. The read-only job
JSON and SQLite exports include the presentation links, coverage, impact and
candidate. The installed 0.13.103 screen displayed this synthetic candidate in
a disposable job copy, and the 0.13.104 bridge verified it read-only. A source
with no reviewed link to the deck is rejected. No review or selection action was
taken. Chart data,
layouts, pictures and unlinked slide content remain outside this adapter's
revision claim. The real motorcycle candidate remains unreviewed
and unselected in its isolated development database. Packaged and installed
bridge checks passed, and the installed screen's read-only click path was
inspected. Decision actions remain to be qualified.

New `plan_pipeline` actions use `contract_version: 1`. Every stage has a `handoff`
with `outputs` keyed by its existing deliverable IDs, and an `inputs` list of edges.
This contract applies to inferred workflows as well as templates; it does not
prescribe research, modeling or presentation as a fixed sequence.

An output declares `media_type` and may declare `max_bytes`, `slides` (PPTX only),
and `companions` (other output IDs from the same stage). Unknown byte sizes and
slide counts are reported as unknown, not presented as verified capacity.
An input names an earlier `stage`, `deliverable`, matching `media_type`, and
`consumer`: either `context` for worker preparation or the exact selected operation
for a direct file input. Research/conversation results are inline context; a worker
must prepare a file before a registered operation can consume them directly.

For example, a Rhino stage can declare a native model and a separate PNG preview.
A visualization stage can consume that preview; a presentation stage can consume
the resulting image and research context. Raw native model files cannot be used
as direct image-generation or PPTX inputs. Companion declarations require paired
edges, such as an image and its provenance document.

The compiler checks declared edges, operation versions/availability, types, known
byte bounds and input counts before the first workflow stage starts. A single
PPTX currently supports 50 slides and 50 MB; a declared 600-slide requirement is
rejected before workers start. The planner must retain explicit requested quantities.
It must not omit the quantity, shrink it or substitute multiple final decks to pass
validation. Automatic section assembly is not implemented.

At stage planning, logical outputs are bound to exact task outputs and input edges
to the exact upstream artifact IDs. Equal hashes do not authorize substituting a
different selected version. Clarification and preparation-to-execution retain those
bindings. Registered operations and workers retain their existing source checks,
schemas, limits, review and approval requirements. Declared byte bounds, UTF-8 text
and exact PPTX slide counts are also checked when outputs are collected. The PPTX
builder checks declared count against expanded slides before creating the file.

Managed image stages produce one selected PNG and accept up to six exact image
references. They use the declared image edges rather than every previous image.
Textual context remains in the saved request; native files remain available for
appropriate consumers without being forwarded as image references.

Saved workflows and legacy procedure exemplars are not silently upgraded. Their
original contracts remain in effect. New typed procedures preserve their saved
handoffs when proposed for review.

If a complete new proposal has incompatible or noncanonical type declarations,
Relay allows one structural correction before dispatch. It supplies registered
operation types and keeps both responses. That correction has no research/file
tools and may change only media-type fields and corresponding edge types. It
cannot change quantities, stage instructions, providers, gates, limits or explicit
user format requirements. Unsupported capacity and uncertain provider responses
are not automatically retried. A confirmed saved rejection can be recovered through
a validated type-only successor without overwriting the failed request.

These checks establish declared compatibility and artifact identity, not semantic
correctness. They do not prove that an AI used research accurately, that a generated
image preserves geometry, that native files are valid outside their host validators,
or that every provider/OS combination works. Unknown future sizes and task schemas
still need execution-time checks. Unified repair eligibility and large-document
assembly remain separate work; uncertain external submissions are never replayed.

## Native picture replacement handoff in development source

`python -m task_relay.impact_handoff create-native-replacement` freezes the exact
request, old entity, baseline PPTX artifact and a previously registered PNG/JPEG
replacement artifact. The image is verified and its SHA-256 is part of the
immutable plan. `agent_candidate submit-native` admits a distinct PPTX only if
its declared picture edit uses those pinned bytes, all edits cover the reviewed
affected native locations, and every OOXML member matches Relay's reconstructed
edit. `fit: contain` centers a portrait picture within the prior bounds without
changing image bytes. The prior embedded image is removed only if unreferenced.
The handoff input is projected into `.relay` and included in job deletion
ownership. A candidate still requires independent review and explicit selection.
The user's exact visual layout feedback can be pinned to a candidate hash and
plan digest as `visual_layout` feedback. It appears in the job process ledger but
does not authorize semantic acceptance or selection.

The controlled Bullhead City case replaced Oleander content with a user-provided
rose image in a copied job. Render review found two additional sourcing footers;
they were recorded as exact affected runs before an 18-location handoff. A
later source audit found a misleading speaker note on slide 18, which is covered
by a 19-location handoff and PPTX candidate. Its visible slide package members
match the layout-reviewed version byte for byte; only the slide 18 notes member
differs. The exact companion `slides.json` and photo-manifest revisions are
registered as a versioned bundle in `.relay`, with 13 declared cross-file checks.
The photo manifest pins the user's image hash and records the unknown rights
fields. An exact user review accepts the provisional candidate set and a later
response attests permission to use the pinned image; author, license terms and
source remain unsupplied. The set was selected in the isolated job copy. The new
selection contract requires independent acceptance of
both the bundle and native candidate, then records one atomic decision and
projects all revised files as selected. The photo does not establish
a species, cultivar, site suitability or reuse rights. The original deck and
installed app were untouched. See the complete revision record (private evidence).

A second bounded continuation starts from that exact selected bundle. It freezes
native PPTX text/notes edits and JSON patches before producing files. The plan
pins the selected parent, its receipt and every baseline hash, and can project
an exact decision value into a companion location. Admission reconstructs the
allowed edit, compares all OOXML package members, rejects image/media or
relationship changes, checks cross-file values and records new artifact versions.
Unchanged companion roles can reuse their parent artifact IDs. The controlled
rose continuation changed only the two affected slide XML members and their
notes members; the image and 258 other members stayed byte-identical. Its
candidate and receipt (private evidence)
were independently reviewed by the user. The exact review and
selection receipt (private evidence)
promote all three candidate files together and supersede the parent in the
isolated job view; the parent versions and selection receipt remain historical.
This adapter covers exact text/notes and JSON patches; it
does not infer arbitrary semantic dependencies from the whole deck.
