# Execution loop review and replacement contract

## Architecture consolidation, 2026-10-09

The current consolidation is specified in [Relay execution architecture](architecture-contract.md).
It adds generic subject contracts, registered execution/availability/binding/receipt
hooks, registered continuation detection and proof, and one atomic stage/attempt
continuation path. Historical records below describe their evidence at the time;
remaining-work statements in those entries are superseded where this contract
explicitly describes the completed boundary. Source, package and live evidence
remain separate.

Status: first execution-boundary migration implemented, 2026-10-08. Exact-package
qualification and installed/live observation are recorded under
`outputs/`; completion of a controlled harness is not a
claim about live output quality.

## Implemented ownership

The existing worker/runtime owns version-1 outcomes and exact-version review
sessions (`orchestrator/operation_session.py`). Local API text reviews retain
observed intervals, provisional notes and check fragments across physical
invocations. Complete input inspection and the normal semantic/report validators
still govern final disposition. Explicit terminal check replacements validate
without changing provisional history or publishing partial acceptance.

Registered resumable record reviews use the same local review session and report
fragments. Record completion is a `finalize` phase, not acceptance. Its checkpoint
binds the exact record revision and content digest alongside candidate versions,
observed intervals and provisional checks. A successor inherits those records
atomically and still needs every final check and the normal report validator.
Received truncated responses are retained but none of their tools execute.

If a continuation makes confirmed record/check progress and then yields during
finalization, the same controller can consume an unused worker allocation in its
current recovery cycle. It revalidates the original allocation, counts previous
worker allocations, and retains exact invocation limits. This adds neither a cycle
nor authority; missing responses, changed checkpoints, exhausted allocations and
no new progress do not qualify. Controlled tests exercise restart, finalization,
missing checks, changed records, transaction rollback and exhausted capacity.
Unscripted delivery quality remains a separate live qualification.

`task_relay/local_review.py` supplies review proofs, checkpoint validation and
workflow projections for these continuations. The shared runtime transition
described below now owns their assignment and queue mutations. Historical
generation/input helpers are read-only receipt adapters;
their duplicate queue branches were removed. Legacy already-queued assignments
retain their validation path. Native/browser/typed collection effect adapters and
their existing reconciliation policies remain authoritative for their own effects;
this migration does not pretend all adapters use a text checkpoint.

An exhausted invocation records a structured yield; a received invalid envelope
or tool submission receives bounded local validation feedback. Unread indexed
intervals use the terminal turn for progress rather than forcing a semantic
blocked verdict. Exact input and journal hashes, committed attempt receipts,
provider identity and current candidate are rechecked after commit and before
dispatch. Missing provider outcomes never become retry permission.

A session uses remaining task capacity first. If that is exhausted, one existing
completion-recovery worker allocation may supply one invocation under the same
limits; the receipt records the task-attempt limit before/after, allocated cycle,
and unchanged aggregate grant. A failed, unexecuted historical replan may return
its unused worker allocation to the unchanged original review. Planning replies,
spent cycles, candidate versions and earlier attempts remain immutable. There is
no new recovery allowance created by installation.

New saved-stage planners can repair one code-identified structural field against
a hash-bound received proposal (`task_relay/planner_correction.py`). The original
reply and raw patch remain separate receipts; the complete patched proposal still
passes all frozen checks. An unparseable first reply cannot supply a patch base
and retains the existing bounded whole-response correction. Semantic replanning
and arbitrary error strings do not acquire field-edit authority.

Registered review obligations now distinguish authored candidate projections from
indexed evidence through lifecycle metadata (`orchestrator/review_inputs.py`).
The same source pack can be a composer's output while remaining source evidence
for a typed reviewer. Exact source-version validation and all per-item independent
judgments remain mandatory; the catalog JSON and companion summary are inspected
in full. This prevents producer provenance from accidentally making the entire
source archive an additional full-file review obligation. Actual late-bound costs
are checked before starting a worker. Historical zero-provider-call capacity
stops are projected read-only into the same local continuation path only when the
old cost is reproducibly impossible and the registered current work fits unchanged
limits. A new composed-source, zero-dispatch-stop-to-PPTX test and multiple data
schemas qualify this distinction.

A confirmed zero-effect launch can use a remaining worker slot in its existing
local-review cycle after the worker implementation changes. Its immutable
invocation baseline is stored separately from the original cycle; uncertain
responses, unaccounted writes, same-build failures and exhausted worker slots cannot take
this transition. Exact code-owned empty initialization projections are verified
byte-for-byte against the registered projection generator. This separates infrastructure startup from semantic correction
without adding cycles or replaying possible effects.

The packaged harness executes API workers through their standalone script entry
point, including typed review and terminal validation. An earlier in-process
harness missed a package-relative import at this boundary; the installed failed
launch made no provider calls, and its receipt is retained.

The new combined harness uses normal desktop intake, actual API tool calls,
real record/report validators, controller restart and recovery, real sandboxed
binary inspection, a controlled Codex executable through the real supervisor,
and native PPTX assembly/delivery. It does not call `factory.finish` or directly
submit accepted records to bridge model workers. Model semantics, visual judgments
and external reads remain scripted. Separate tests cover altered checkpoints,
unknown responses, absent grants, spent-cycle migration, terminal evidence reads,
invalid replacements and scoped planner repair. Broader adapter migration and
an uninterrupted live quality run remain explicit qualification work.

The installed saved workflow completed its formerly blocked coverage review and
catalog authoring. Its final review passed startup after the runtime correction,
then received a confirmed first-request HTTP 402 billing rejection with zero tool
calls. This is an external dependency hold, not automatic retry permission.
The existing explicit billing-resume path now supports an empty typed checkpoint
as well as an inherited partial one. Provider rejection receipts and candidate
versions remain immutable. Live photo/PPTX completion is still unverified.

A later live catalog-to-photo handoff exposed a projection mismatch: literal
source evidence can contain line breaks while image display fields require one
printable line. The adapter now owns that whitespace projection, preserving all
literal source bytes and hashes, and validates all subjects before committing a
collection intent. Registered read adapters can supply a pure preflight recovery
proof to the shared recovery owner. A historical initial intent is recoverable
only when its exact binding reproduces, no transport entry/output exists and the
corrected input projection validates. No error-message match selects recovery.
A qualified follow-up queues one unchanged native successor directly under the
existing recovery allocation, without asking a planner to reproduce the graph.
Dispatch rechecks the committed proof, exact inputs and prior receipts. The
first installed correction used bounded replanning, whose initial malformed reply
was corrected before photos completed; this is retained as an intervention, not
uninterrupted success. Installation status is recorded separately under outputs/.
Broader consolidation of native continuation remains open.

## Shared continuation transition (2026-10-09, source-qualified)

Typed-record checkpoint continuation and local-review session continuation now
commit through `Runtime.continue_attempt`. The record adapter and local-review
adapter no longer mutate their task queue independently. The completion-cycle
record branch also delegates assignment creation, lifetime allowance accounting
and queueing to that same transition. No scheduler, queue or recovery grant was
added.

`orchestrator/continuations.py` supplies read-only proposals from the existing
adapter proofs and verifies references to committed cycle allocations. The
runtime owns latest-attempt identity, confirmed disposition, active-run checks,
remaining capacity, idempotence and one transactional `continuation_committed`
receipt. Assignment changes, queue state and the receipt commit together; the
ordinary scheduler dispatches afterward. Historical adapter receipts remain for
compatibility and checkpoint provenance. Existing failed-planner and confirmed
zero-dispatch allocation reuse preserves its original grants and audit history.

Before a new physical attempt is created, the runtime rechecks the committed
parent receipt, adapter proof, assignment, remaining allowance and allocation.
Changed checkpoints, grants or receipts hold without spending another attempt.
Unknown external effects never become continuation authority.

The composed test revealed an additional lifecycle defect: after a yielded
review resumed and rejected a candidate, the next candidate's review inherited
the old invocation's continuation instructions. All existing runtime/native
correction paths now explicitly create a fresh review obligation. Inherited
invocation revision/checkpoint state is omitted; newly authored correction
instructions remain. Earlier assignments and provisional judgments stay in
history. Normal correction also checks remaining review capacity before spending
another producer attempt.

`tests/test_continuation_controller.py` exercises both migrated adapters through
the same commit-failure, restart/idempotence and changed-evidence boundaries.
Its composed worker test executes yield → restart → semantic rejection → producer
correction → independent review of the new exact version → downstream delivery,
using actual file-worker tool loops and scripted model replies. A separate case
holds when the final permitted review rejects, without producing an unreviewable
new candidate. The affected suite passed 125 tests, including existing controlled
native PPTX delivery. Commands and initial failed runs are preserved under
`outputs/`.

This initial migration was source-qualified, not installed. The next migration
below extends the same transition to three further adapters.

## Native, browser and legacy-budget continuation migration (2026-10-09)

All five supported single-attempt recovery kinds now use
`Runtime.continue_attempt`: record checkpoints, local-review sessions, registered
native preflight, public-browser setup and legacy saved-review budgets. The
three additional paths no longer create assignments or change task queue state
independently. Their existing proof readers and bounded successor builders
remain adapters; the shared runtime checks the committed allocation, owns the
state transition and revalidates it before dispatch.

Capacity is checked on the authorized successor. Native preflight preserves its
operation scope. Public-browser recovery requires the existing no-submission
proof, retains the same public-read permissions and provider, creates an
isolated signed-out profile and narrows elapsed time. Legacy review may use the
larger invocation allowance already authorized by its completion grant, while
retaining exact sources and an unaccepted draft. The shared receipt explicitly
records invocation limits before and after; no new grant is inferred.

The same failure matrix runs against all five kinds. Grouped browser recovery
rolls back the entire allocation and all queued tasks if a later member fails
to commit. A composed native-preflight → budget-limited independent review →
review continuation sequence preserves the exact candidate and consumes two
distinct existing cycle allocations with no planner call. These are controlled
fixtures, with scripted judgments and public reads, not live browsers/providers.

The worker-to-PPTX integration check exposed a receipt-contract omission:
`CodexFactory.inspect` legitimately reports `launching` during its bounded startup
grace, but the shared guard treated it as malformed and changed it to uncertainty.
A deterministic regression using the actual factory and runtime failed before
the fix. The guard now preserves `launching`; the test also proves that after
the existing 30-second deadline a missing receipt remains uncertain across
restart and is not resubmitted. This explains the failure in this source
revision, without asserting that historical package failures had the same cause.

Process completion has a second boundary: a final receipt can arrive after the
inspector's first file check but before its process-identity probe returns. The
inspector now rechecks the exact terminal receipt before declaring a disappeared
supervisor uncertain. It still refuses missing or foreign-attempt receipts.
A deterministic race test failed before the change; this is receipt reconciliation,
not inference of successful completion from a dead process. The local fake CLI
fixture also quotes interpreter paths with spaces so bundled-Python tests can
actually launch their controlled child process.

Qualification commands, initial failures and final results are kept in
`outputs/`. This change remains source
qualification until packaging and installation are separately verified.
Registered whole-graph revision and external delivery effects still use their
existing dedicated transaction/proof paths. Arbitrary host-script replay,
unknown effects and universal live reliability are not qualified by this work.

## Finding

Registered operations, immutable evidence, transactional commits and native
PPTX assembly are useful foundations. The current control loop does not yet make
those parts a reliable autonomous process. Local execution errors too often
become task-level `blocked` states. Recovery recognizes particular historical
errors, and a generic budget stop can fall through to a new whole-stage proposal.
That proposal introduces another large model output and another failure surface,
even when the original graph and remaining reviewer attempt are usable.

The observed sequence crossed inventory review, compact proposal admission,
query correction, large saved-evidence review, typed candidate inspection and
coverage review. Individual repairs let work advance, but they did not establish
closure of the execution protocol. The latest coverage review completed its
literal reads, then rejected its final judgment because its evidence wording
differed from a provisional saved check. The last call exposed only `finish`;
the error required a separate amendment. Recovery then requested a replacement
graph and both planning replies failed JSON parsing. No photos or final deck
were delivered by that observation. Private identities and receipts stay ignored.

A controlled two-call text fixture reproduces the protocol defect: unchanged
final evidence succeeds; explicitly refined final evidence fails. It uses the
actual API worker loop and a scripted transport, with no provider calls.

## What the previous qualification establishes

`tests/test_desktop_sourcing_delivery.py` exercises real intake, compilation,
scheduling, records and native PPTX code. Its `complete_agent` helper directly
submits records and finishes many agent sessions. It is useful orchestration
coverage, but does not execute those sessions through `gemini_worker.execute`.
Separate tool-loop tests do not establish composition of the two layers across
a sequence of interruptions, corrections and context changes.

A count of passing tests therefore does not establish unattended reliability.
Keep existing checks, describe their seams accurately, and add combined protocol
coverage before another deployed claim. Deterministic responses remain appropriate;
substitute only the model/transport boundary, not worker completion or recovery.

## Ownership and state

Retain the existing durable database, operation registry, artifact identities,
host adapters and delivery contracts. Migrate the existing scheduler rather than
add a second scheduler behind another facade. A logical operation session owns
its progress independently of each physical worker invocation. The pipeline
observes that session's disposition; it does not interpret worker exception text.

A session records the exact request/contract/input versions, authorization,
provider, remaining allowance, committed units, outstanding obligations, provisional
review judgments and any unresolved external intent. Physical attempts and their
original immutable journals remain separately addressable. Continuing a session
never rewrites its earlier attempt, acceptance state or allowance.

Use a versioned outcome envelope with these code-owned fields:

- `phase`: compile, observe, produce, validate, review, materialize or deliver.
- `status`: progress, completed, correction_needed, yielded, waiting_external,
  needs_user or failed.
- `code` and `path`: stable adapter/validator identifiers and a precise affected
  field, unit or artifact; human-readable detail is additional data.
- `effect`: none, confirmed or uncertain, linked to the original intent/result.
- `checkpoint`: exact committed version and outstanding obligation IDs.
- `usage`: actual consumed calls/time/tokens where observed; unknown stays unknown.

Adapters classify facts about execution. Models provide content and semantic
judgments. The central transition function chooses the permitted next action
from the outcome, checkpoint, graph and remaining grant. Models do not declare
an external effect safe to replay or grant themselves another allowance.

| Outcome | Controller action | Pipeline disposition |
| --- | --- | --- |
| Valid progress / voluntary yield | Commit progress; schedule remaining obligations within the grant | Working |
| Malformed received model/tool output | Preserve reply; return typed local validation feedback; apply no invalid output | Working while repair allowance remains |
| Candidate semantic defect | Reopen affected producer units and independent review; retain valid unrelated units | Correcting |
| Request/context capacity boundary | Continue or partition registered work units from the checkpoint within remaining authorization | Working, or needs user if no permitted capacity remains |
| Confirmed transient transport failure | Adapter-permitted bounded retry/backoff with recorded outcome | Waiting / working |
| Unknown external outcome | Reconcile the original intent; never repeat it blindly | Waiting for reconciliation or needs user |
| Required information, scope, credentials or grant unavailable | Explain the concrete missing prerequisite | Needs user |
| Completed reviewed outputs | Resolve exact downstream bindings; materialize/deliver required outputs | Working until delivery contract is satisfied |
| Invariant violation or exhausted authorized recovery | Preserve state and report a specific terminal reason | Failed / needs user |

A task-level validation error is not automatically a workflow-level stop. Nor is
all failure automatically retryable. The controller must prove the transition is
allowed, make progress measurable, and terminate when its actual grant is spent.

## Complete protocols at the interfaces

### 1. Planning and compilation

The model selects compatible operations and supplies intent, references and
semantic parameters. Code derives output descriptors, dependencies, review
companions, required tools, IDs and accounting. Structural repair edits the
small affected proposal field against its immutable base; it does not regenerate
unrelated valid graph portions. Failed or truncated proposals never authorize
work. Whole-stage replanning is reserved for a demonstrated graph/capability
change, not a failed report envelope or an exhausted local invocation.

### 2. Evidence and task capacity

Store original evidence once, with exact hashes and source receipts. Registered
projections offer bounded work units, claim/source bindings, literal spans and
needed context. Raw evidence remains retrievable. Code validates structure,
identity, duplicate/version rules and coverage; an independent model judges
meaning, correspondence and disclosed uncertainty.

Distinguish complete review of declared obligations from forcing a model to
reread every byte of every upstream container. Navigation arrays and duplicate
serialization are not independent semantic claims. A registered projection must
prove which fields/spans it preserves and disclose omitted material. If the
contract actually requires whole-artifact inspection, partition that inspection
explicitly; do not silently weaken it or claim that supplied text was understood.

At each late-bound handoff, derive read, submission, review and finalization cost
from actual data and registered costs. Account for repeated inspection and repair
inside an explicit reserve. If a unit cannot fit, partition before invocation or
return a typed capacity outcome. Do not admit a producer whose valid output has
no consumable downstream protocol. Capacity estimates are not model guarantees;
progress checkpoints remain necessary when a model consumes the reserve.

### 3. Review and finalization

Expose one versioned review state: outstanding obligations, provisional checks,
exact candidate IDs and permitted amendments. A model may revise provisional
judgments after further inspection. A final submission declares exact check
versions or explicit replacements and a verdict. Code validates all replacements,
complete required evidence and the final verdict, then commits the report and
its generated text artifact atomically. A rejected submission commits no partial
acceptance. Earlier provisional versions and raw submissions remain retained.

Finalization must have a legal path at the budget boundary. It must not ask for
a second tool after removing that tool, force the model to retype code-owned
metadata, or turn a report serialization correction into new source research.
A final submission still cannot override missing evidence, a changed candidate,
an unsupported fact or a required independent judgment.

### 4. Local continuation and semantic correction

Use the same continuation transition for compatible operations, parameterized by
registered effect/checkpoint capabilities. Stop adding a new controller branch
for each exception string. Local model repair, context yield and known generation
truncation retain the operation identity and committed progress; physical attempts
remain distinct. Semantic rejection returns to the affected producer and triggers
fresh independent review of the changed version. Review progress can be reused
only for identical candidates/obligations; old verdicts cannot bless changed data.

Reserve existing original attempt capacity before invoking a graph planner.
When an earlier failed replan stranded original work, recovery must bind the
unchanged historical checkpoint, original authority and confirmed planner outcomes.
Do not erase spent cycles, reset attempts or use a deployment to mint new budget.
Historical journals need a read-only adapter to the new outcome envelope; ambiguous
history stays held. Current grants govern whether this particular run can resume.

### 5. Photos, documents and delivery

Collection uses the same per-unit outcome/checkpoint interface for found,
missing, failed and uncertain results. Missing target counts/photos remain explicit
outcomes under the saved policy; false claims and wrong photos require correction.
The exact reviewed inventory/catalog/photo versions feed a declarative document
specification. Native format adapters create and inspect the editable output;
visual review applies to its exact version. Correct affected content/layout and
review again within the grant. The run completes only when the requested final
artifact and delivery receipt exist. A source pack or passed intermediate review
is not a substitute for that artifact.

## Qualification required before migration is called robust

One integration harness must drive normal intake, the actual model tool loop,
real validators/checkpoints, controller recovery, downstream binding and final
native delivery. Script provider responses and external reads only. Do not call
`factory.finish` or insert accepted intermediate records to bridge failed workers.
Use small text fixtures for control behavior and existing document fixtures only
when the changed boundary reaches document generation.

Run the same compatible graph with several content schemas. Exercise sequences,
not just isolated errors: malformed planning output; incomplete response; omitted
input suffix; redundant evidence read; late provisional-check revision; semantic
producer correction; yield at each permitted budget boundary; restart before/after
commit; failure immediately before final delivery. Vary where these occur.

Assert system properties:

1. Under sufficient authorized capacity and eventual valid responses, ordinary
   local failures reach the final artifact without a human action, skipped review
   or whole-stage replan.
2. Every invalid response leaves accepted state unchanged; every valid committed
   unit survives restart and continuation.
3. No unconfirmed external intent is duplicated. Known effect receipts govern reuse.
4. Candidates, reviews and delivery always share the exact current version chain.
5. Spending is monotonic across attempts and recovery. Exhausted grants stop with
   an accurate reason; a fixture cannot pass by silently enlarging them.
6. A new compatible schema requires no new controller branch or workflow runner.
7. A new error code within an existing outcome category uses its registered
   transition without a message-specific recovery patch.

Then qualify the exact packaged runtime. Only after that, conduct an authorized
live run with its declared budget, no code edits, manual stage completion or
installation between stages. Report accepted output quality, human interventions,
recovery events, extra planning calls, elapsed time and observed usage separately.
A live failure reopens a specific contract; passing fixtures does not overrule it.

## Migration order and removal criteria

1. Add the outcome envelope and a read-only projection of historical outcomes.
   Inspect transition decisions without dispatch; compare to saved receipts.
2. Implement durable review obligations and atomic final submission through the
   existing worker/runtime. Qualify protocol sequences and exact-version holds.
3. Consolidate current local-review/generation/input/budget continuation handlers
   into the common session transition. Move useful guards into shared validation;
   remove superseded dispatch branches rather than preserve two owners.
4. Route late-bound capacity, source/photo units and scoped producer corrections
   through the same transition; retain transport and format adapters.
5. Run the combined tool-loop-to-delivery harness and exact-package qualification.
   Migrate a stopped job only with an immutable migration receipt, remaining grant
   and no unresolved effect. Observe installed health and live results separately.

This is replacement of the execution boundary in place, not a rewrite of the
artifact store or PPTX engine. It is also not permission to disable validation,
continue indefinitely, switch providers or launch another paid trial.

## Entity/image association and planner response capacity

The live photo correction exposed loss of a source relationship: HTML capture
flattened images from multiple product records into page order, and the native
collector treated page provenance as product correspondence. Capture now retains
literal product names with each JSON-LD image; selection requires an exact
normalized name association on multi-entity pages. Historical ambiguous captures
remain immutable and produce missing coverage. No retailer-specific URL heuristic
or invented correspondence is used. Independent review still checks pixels.

Compact Gemini 3 graph planning now requests low reasoning within the same
10,000-token total response ceiling. The provider default consumed nearly the
whole allowance before serializing live plans. This change does not add calls or
raise frozen output limits. Qualification is controlled; live success remains
separate. Replanning alone cannot repair unchanged deterministic selection, as
the repeated rejected photo demonstrated. Maintenance holds subsequent dispatch
while the current review finishes; installation and resume are separately logged.

A capability-only planner cannot infer that deployed deterministic selection has
changed. Registered read adapters therefore expose optional pure revision
previews; the existing completion owner verifies a material selection change,
exact input/history identities and the current implementation before composing
the unchanged native producer and independent reviewer. This spends the existing
cycle worker allocation, including an unused allocation stranded behind a
confirmed unexecuted blocked planner. It does not claim semantic correctness or
add an attempt to historical assignments. Dispatch rechecks the committed graph
and proof; normal independent review owns acceptance of the successor version.

## Native preparation closure

Native transformations still compose a graph with semantic context and review
obligations. For an all-native producer graph with one independent reviewer, the
compiler supplies omitted already-declared context ports to that reviewer, never
to an incompatible operation wire. Ambiguous ownership remains an admission
error. Registered checks govern intermediate native operations as well as final
ones. Internal pure JSON projections receive their required independent review
before dependent procedures run.

Registered projection adapters can calculate output review units from exact
hash-verified captured text. Presentation review receives one image observation
per calculated slide plus bounded inspection/finalization capacity, within the
original stage ceiling. A smaller stage ceiling fails before dispatch; executed
assignments are never enlarged. Model-proposed tiny review allocations no longer
undercut this computable workload. Controlled complete-graph qualification and
live saved-proposal admission are recorded separately from final live delivery.

## Native correction applicability

A confirmed revise verdict does not imply that any available correction can resolve it. The deterministic readable-layout preset now requires the structured requirements finding `layout_readability`, with only advisory findings alongside it. Integrity, other requirements and subjective quality findings retain their distinct routes. Code never treats a layout change as factual correction. Registered slide aliases use the same dispatch boundary. Prospective workload includes the largest layout already granted by the graph before review limits freeze. Previously executed attempts and their limits remain historical facts. This change prevents an irrelevant replay; it does not itself resolve semantic findings.

The same applicability rule governs upstream recovery: only an explicit `missing_substantive_source` requirements finding may rewind source coverage. Unrelated factual defects do not acquire source-research authority merely because a catalog also has missing target options. Confirmed local artifact adapters declare their recovery semantics in the registry; the completion owner retains an independent completed rejection when its producer holds the blocked state. An unexecuted misdirected upstream plan can be compensated from its exact archived stage bindings only after checking unchanged review, artifacts, stage/control state, finished planning receipts and no dispatched work. The rejected plan, paid replies, cycle ledger and original attempts remain immutable. Normal semantic recovery then handles the consumer finding.

Human conversation and generated workflow journals are separate inputs. Refeeding the last twelve generated stage/recovery prompts into each new conversation snapshot recursively duplicates the durable workflow ledger and eventually violates the context ceiling. Conversation capture now selects actual conversation turns before applying its count limit. Exact generated prompts remain in the workflow tables and stage context; human drafts are neither summarized nor truncated.

## Prepared data correction without graph replanning

For a registered local JSON preparation, a factual correction changes bounded data, not the native executor. The existing registered revision owner can reuse the confirmed current output and immutable source evidence, assign its precise independent findings to the already authorized local reviewer executor as a data author, and retain the original independent specification review, native creation, preview and final review graph. The new worker writes only a new JSON output; it gains no research, provider, application or binary-authoring capability. No descendant may have started. Every task receives one invocation within an already committed completion cycle, and source/review/receipt/graph proofs are rechecked before dispatch. A blocked unexecuted planner can return its unused worker allocation to this path; paid replies and the spent cycle remain recorded. The mechanism is declared by adapter metadata and does not encode product-specific correction rules.

## Worker initialization ownership

Background services serialize their database schema initialization before independent work loops start. Transient SQLite busy/locked failures retry with cancellable exponential backoff capped at thirty seconds. Every failed State construction closes its partially initialized connection, releasing transactions and locks; unrelated failures remain errors. This is startup recovery before any dispatch, not an attempt retry or external effect replay. Fresh per-service health must verify deployment; matching application bytes alone cannot establish that the service is running.

Final-artifact findings follow the prepared-data lineage already authorized by a registered correction graph. The owner verifies all executed nodes stopped with confirmed receipts, checks the exact final review target, and replaces the author’s historical candidate input with the latest prepared version. Final findings reach both preparation and final review. The same native operation graph then renders a new artifact version. This retains executed artifacts and rejected plans, spends an existing recovery cycle, and cannot replay uncertain external effects or introduce a new producer. Historical graph serialization is preserved so prior grants remain independently verifiable.

Direct stage admission owns its committed plan pointer. Recovery clears obsolete pointers before invoking admission, never afterward; an already committed direct admission suppresses redundant admission. Historical lost pointers may be restored only from matching dispatch events, immutable request/context/baseline identity and confirmed failed unexecuted plan receipts. Restoration changes no plan or paid call and is idempotent. Full saved-state reconciliation must qualify pointer restoration plus continuation, rather than testing graph preflight alone.

The same prepared-data continuation applies when its own independent specification review rejects a corrected version. Confirmed completed nodes may be retained alongside never-dispatched descendants; any launching/running/uncertain node still prevents continuation. The next cycle always receives the latest JSON, and native dispatch remains gated on its independent review.

## Observed delivery and remaining qualification boundary

The recovered live workflow reached controller-recorded completion with an independently accepted editable 20-slide PPTX and exact-candidate compatible previews. The last content correction and both independent review boundaries ran through the installed registered lineage without a new graph-planning call. Partial research, absent photos and unknown purchasing facts were disclosed under the original target policy. Whole-workflow accounting retains planning, reviews, failed attempts and recovery; missing usage remains unknown. This establishes completion of the recovered run and tested controller paths. It does not establish uninterrupted unattended reliability, comprehensive sourcing quality, native PowerPoint behavior or user acceptance. Historical blocked attempts remain records, not the final workflow status.


## Remaining completion criteria after job visibility work

The job projection is read-only. It does not complete the shared lifecycle migration.
Finish the following before treating the universal architecture as robust:

1. Persist one owner and structured outcome for each current operation across
   original, corrected and restarted stage bindings. The UI must read its current
   activity, last progress, hold reason and next eligible action. A missing owner
   must be an explicit invariant failure, never an unexplained active status.
2. Apply the same workload admission to original and corrected work. Preserve
   obligations when replacing procedural preparation with an agent correction.
   Partition within the frozen aggregate grant or record a capacity hold; fixed
   fallback limits must not silently undercut required review capacity.
3. Supervise construction, execution and cleanup; capture observed budget excess
   even when a child exits before the next poll. Retain confirmed and uncertain
   effects and reconcile historical queued/delivery records before deletion.
4. Qualify composed failures through the actual worker loop and final delivery:
   repeated rejection, restart, lock contention, unknown effects, empty evidence,
   changed inputs, cancellation and exhausted allowances across effect families.
   Count named invariants and failure sequences, not overlapping passing tests.
5. Keep research quality distinct from workflow termination. HTTP success or
   captured page text is not useful item evidence. Bounded discovery should react
   to repeated unavailable sources and empty shells using alternatives within the
   grant. A target-policy shortfall may be deliverable, but it must remain visible
   as incomplete coverage rather than certify that adequate research was done.

The prior constructor, correction-capacity and fast-exit receipt counterexamples
remain unresolved as of this visibility change. Live quality checks are separate
from controlled protocol checks; do not authorize paid runs implicitly.


## Stage ownership and delivery follow-up, 2026-10-09

The canonical `relay_pipeline_steps` binding remains the execution owner. A durable
`relay_stage_state` projection records its phase, exact run/candidates, uncertainty,
remaining recovery cycles and next action. Recovery refusal is stored against that
exact binding; it cannot leak onto a successor. Pipeline events and the projection
commit together. Missing owners stop with an explicit reason. Existing effect
adapters still supply their own confirmed receipts and eligibility proofs; this
change does not claim those adapters have all been replaced by one implementation.

Corrections no longer replace a larger declared workload with a smaller fixed
allowance. Admission holds before dispatch when the unchanged recovery grant cannot
accommodate the work. Partitioning or a reviewed authorization change is required;
installation itself supplies no new budget. Worker service construction and cleanup
are inside supervision. Final child accounting checks the last drained events even
when the process has already exited. This records overruns; polling cannot undo a
tool call the child already issued.

Queued Telegram delivery now uses an intent/receipt journal. A confirmed receipt is
reused after parent-acknowledgment failure. Ambiguous transport outcomes and legacy
pending sends with no dispatch proof remain held. Explicit transport refusals retain
bounded retries. Direct interactive replies and other channel adapters are outside
this migration. Deletion distinguishes desktop file-index records from outbound
messages, can remove inactive unstarted history atomically, and retains shared,
live or uncertain effects. Confirmation still binds the exact reviewed row set.

Research collection records retrieval outcomes and schedules observed publishers
fairly within the original read allocation. Coverage follow-up can exclude failed
publishers without widening an allowlist or truncating authored constraints. A
successful HTTP read remains only source evidence; exact catalog coverage and
independent semantic review determine output quality. UI coverage is read from
verified artifact versions, separately from the workflow's execution status.

The qualification record is `outputs/`. It includes
controlled actual worker loops to native PPTX, constructor contention, fast-exit
budget overrun, delivery restart/uncertainty, safe deletion, query constraints and
copied historical state. It does not claim a fresh live research run or semantic
quality based on scripted external responses.
