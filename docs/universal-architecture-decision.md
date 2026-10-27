# Decision: compose Relay from universal interfaces

Accepted 2026-10-08. Applies to future implementation and incident recovery.
Requested by the user after repeated room-sourcing handoff failures: build reusable
schemas and connectors, compose compatible workflows, and qualify them with
synthetic data before replacing that data with live model observations.

## Execution-loop reliability review

The 2026-10-08 user-requested [execution-loop review and replacement contract](execution-loop-redesign.md)
is the priority follow-up. Collection-interface consolidation and passing individual
recovery tests do not establish a reliable composed execution process. That review
specifies durable operation sessions, structured outcomes and local recovery,
atomic review finalization, and one qualification harness through the actual
worker tool loop and final delivery. It is a design specification, not an installed
migration. Preserve the useful existing components and replace overlapping control
paths; do not treat this as authorization for another incident-specific branch.

## Governing architecture

The [cross-tool boundary audit](cross-tool-execution-audit.md) adds controlled
counterexamples for repeated visual context and terminal owner capacity. Its
shared dispatch/observation/outcome contracts refine the implementation order;
the consolidation and composed visual qualification remain open. This audit
does not change saved grants or establish installed or live reliability.

The job-owner simplification in [the execution architecture](architecture-contract.md#job-owner-with-optional-delegation)
refines this decision: one logical owner remains responsible for the full request
and can launch multiple agents as needed. Intermediate model reviews are justified
by semantic work, not by the existence of a tool boundary. Registered code checks
may establish structural composition without another model gate. This is a
prospective migration; existing executed assignments and verdicts remain intact.

Relay is a registry of typed operations and record contracts, a compiler of
compatible workflow graphs, and one durable execution/recovery controller.
The model expresses intent and contributes bounded data fragments. Code owns
the envelopes, IDs, paths, artifact versions, literal evidence extraction,
validation, projections, handoffs, budgets, checkpoints and delivery state.

Plants, furniture, components and later domains select content schemas, field
definitions and source policies. They use the same collection, record lifecycle,
batching, review, recovery and delivery interfaces. Source adapters handle real
transport differences; format adapters handle real output differences. Neither
is permission to introduce a domain-specific scheduler or parallel collector.
Historical interface names remain compatibility aliases with their saved scope.

The graph is composed by a model from registered compatible ports. We do not
hardcode a separate end-to-end workflow for each use case. The compiler expands
compact intent into exact input bindings, procedural criteria, code projections,
dependencies, review companions and capacity-derived partitions. Workers supply
small fragments through registered operations rather than rewriting envelopes.

## Rules for changes and incident fixes

The tool-authority boundary is provider-neutral. Validate the whole received
call batch against the current registered declarations before any call executes;
recovery does not grant a tool-name prefix or bypass the current surface. A denied
batch returns explicit no-effect results to the proposing transport, including
persistent sessions, while code records bounded recovery independently of tool
execution. Hosted execution observations are retained as uncertain, never silently
filtered into a claim that nothing ran.

Provider adapters must distinguish proposed calls executed by Relay from tools
executed inside an autonomous provider runtime. An autonomous runtime without a
qualified pre-execution gate is unavailable for this contract. Prompts, hidden
tools, sandbox settings and after-start detection alone do not qualify it. The Codex adapter selects a separately built, byte-bound runtime that enforces
this contract before registering or dispatching local tools. Its immutable grant
contains exact dynamic declarations and separately authorized hosted tools.
Native handlers cannot acquire authority by sharing a granted name. An offline
qualification receipt binds the executable, pinned upstream revision and maintained
patch. Missing or stale receipts still stop before launch. Actual-runtime local
fixtures qualify enforcement; they do not establish live model quality or full
native workflow completion. See [gate build and qualification](codex-tool-gate.md).

1. Identify the failed shared boundary and preserve the exact run and receipts.
   A new domain-specific wrapper is not the default remedy. Search the registry
   and lifecycle/compiler/controller interfaces before adding an abstraction.
2. Fix the shared implementation or its declared contract. If a domain needs new
   semantics, register a content validator, field configuration or source/format
   adapter. Explain why existing interfaces cannot express it.
3. Use small synthetic compatible graphs to exercise the affected boundary and
   meaningful failure/recovery behavior. Reuse the same graph with multiple field
   configurations when claiming a universal change. Do not test only the happy
   path or mirror implementation details in assertions.
4. Keep deterministic checks in code: schemas, duplicates, count policy, exact
   versions, paths, report envelopes and evidence-span extraction. Model review
   judges meaning and visual correspondence on the exact candidate version.
   It cannot invent a new procedural requirement or approve unsupported facts.
5. Quantity goals are targets unless explicitly required. A collection may return
   zero, one or more alternatives; supported records and explicit missing outcomes
   continue downstream under that policy. Unknown data is representable. Invalid
   claims need correction; missing target data does not create a human approval.
6. Derive allowances and partitions from declared work units and adapter costs
   within frozen scope. Never conceal additional work behind an arbitrary tiny
   tool limit or silently expand an already executed assignment's allowance.
7. Commit intent before external dispatch and confirmed outcomes afterward.
   Checkpoints are durable; confirmed outcomes are reused. Reconcile uncertain
   effects from exact receipts instead of resubmitting them. Recovery carries the
   current catalog, source pack and photo versions to dependent stages.
8. Internal specification, creation, review, correction and delivery are part of
   an authorized end-to-end run. Continue eligible bounded recovery automatically.
   Preserve explicit authorization limits, hard requirements and real provider
   stops; never imply a synthetic test proves live page availability or quality.
9. Track timing and reported usage over the entire graph, including planning,
   review, corrections and recovery. Unknown usage is unknown, not zero.
10. Update the registry/documentation and affected roadmap/changelog when behavior
    changes. Label source tests, exact installed-package tests and live checks
    separately. Never claim a deployed fix or live success from source tests alone.

## Assignment artifact roles

The compiler distinguishes operation-consumed inputs, worker inspection evidence,
retained provenance and assignment results. Registered evidence representations
must bind exact versions through native receipts; inspection access does not
widen a native operation's accepted inputs. See [artifact role handoffs](artifact-role-handoffs.md).
Runtime-created compatibility gaps produce an explicit hold; an actionable wrong
selection remains in existing bounded proposal recovery. Neither path drops
required review evidence or expands execution authority.

## Evidence and remaining acceptance

[The interface implementation record](universal-interface-consolidation.md)
describes the implemented boundaries and the shared synthetic harness. The exact
maintained package passed 219 controlled tests and was installed with matching
signed bundle and overlay hashes. Those checks used scripted public transports
and model judgments, with real record and native PPTX code. They prove the
exercised structural behavior, not universal live reliability.

A fresh full-room run was requested after installation. Its live intake,
attachments, graph, attempts, recovery, timing and usage receipts belong in
ignored private storage. Keep this decision public and free of personal source
research or installation identifiers. Record live failures as evidence for the
specific failed boundary; do not use them to abandon the universal architecture.

The first fresh live check exposed a shared controller gap: a file-worker's
independent review stopped after two explicitly received generation-output-limit
responses. Its exact candidate and confirmed no-pending-response receipt were
preserved. The existing local-review continuation interface could queue its
remaining original attempt, but the owning workflow did not invoke it itself.
This required supervisor intervention and is not unattended delivery evidence.
The follow-up belongs at the common response-budget/confirmed-review-continuation
boundary: account for reasoning and report size, use concise report recovery,
and invoke eligible continuation inside unchanged authorization and allowances.
Qualify generation truncation, exhausted allowances, changed candidate versions
and uncertain responses through that shared path. Do not add a room-only retry.

The continued run then stopped at catalog planning, before product research.
The generic reference schema offered `role: asset`, but its implementation only
permits that tag for Rhino additional inputs. The model used it on ordinary
image/inventory references. A read-only check removing those tags then exposed
an inconsistent producer/reviewer attempt budget. The original proposal was not
changed or dispatched. These are common compiler/interface gaps, not furniture
collector failures: expose only compatible reference shapes in the compact
schema, and derive paired review capacity from declared producer attempts within
frozen limits. Add synthetic admission cases for both before claiming this
boundary is qualified. The earlier controlled checks did not qualify these live
gaps.

The shared admission and review recovery update now covers these boundaries.
Generic schemas omit incompatible asset annotations; the compiler projects
historical annotations on local references without changing their selected
sources or raw replies. Paired review attempts and missing response allocations
derive from declared work within frozen ceilings. Local API reviewers can submit
small schema-checked report fragments bound to the exact assignment and candidate.
Confirmed generation failures can consume a remaining original review attempt
automatically after code verifies completed journals, unchanged artifacts and no
pending response. Changed journals, uncertain outcomes, exhausted allowances and
unsupported executors remain held; incomplete response tools are never executed.

The exact maintained package passed 311 controlled checks, without exclusions or
live provider calls. Normal desktop intake fixtures include a malformed planner
reply, corrected compact proposal, confirmed review truncation, restart,
collection, native PPTX creation, review/correction and delivery. The unmodified
saved catalog reply also validates read-only with zero provider calls. These
checks qualify the exercised common boundaries; live collection yield, image
correspondence and unattended room delivery still require the resumed live run.
The signed installed package matches the qualified bundle and all 65 cumulative
runtime overlays, with fresh core service health observed. On restart its normal
controller recovered that saved proposal without a planning call and started
query preparation using the completed inventory. No manual recovery control was
executed. The earlier inventory intervention remains part of this run's history;
this continuation does not turn it into unattended end-to-end evidence.

A subsequent query review found a concrete missing pattern. The controller sent
that local defect through whole-graph replanning despite unused original producer
and reviewer attempts; both replies were incomplete JSON. The common recovery
path now distinguishes this case from graph reconstruction: use the unchanged
local pair and its remaining original capacity for an explicit requirements or
integrity correction. Keep the rejected candidate unaccepted, carry its exact
review evidence, recheck the committed baseline before dispatch, then independently
review the new version before releasing downstream work. Browser/host effects,
typed record workers, uncertain outcomes, user choices, exhausted attempts and
already dispatched descendants do not qualify for this local path. A failed,
unexecuted replan can rebind to the exact unchanged original run without erasing
its paid replies or recovery receipt. This is a shared controller operation,
not a furniture-specific recipe or permission to edit a live assignment's limits.
The follow-up maintained package passed 314 affected controlled checks, including
the normal desktop-to-PPTX chain with that required query correction, and was
installed with matching signed bundle/overlay hashes and fresh core health.
The normal controller then recovered the stranded local pair and started its
remaining producer attempt automatically, without another planner request or
manual control. Both incomplete planning replies and the spent recovery receipt
remain preserved. The corrected queries passed independent review and native
product-source collection started. Photos and final room delivery remain pending.

The live continuation exposed another unqualified shared boundary after source
collection and rendered browser fallback finished: the fallback producer may
emit a valid source pack larger than a plain API reviewer's aggregate text-input
ceiling. Its independent reviewer was blocked before dispatch, with no attempt
or provider call. The current indexed-artifact policy applies to registered
record operations, while saved-page review batching applies only to CLI workers;
neither covers this plain API reviewer. Existing admission recovery also expects
a plan-backed stage and unchanged original assignments, so it cannot recover this
production-run stage with compiled fallback tasks. This was an open gap at that
observation, not a delivered or independently reviewed catalog.

The required fix belongs to the common evidence-context interface: preserve full
immutable evidence artifacts locally, expose bounded indexed reads and literal
page batches to compatible reviewers, and validate producer-to-consumer capacity
when composing fallback steps. Distinguish local artifact capacity from individual
model-request capacity; do not increase frozen allowances, discard evidence or
accept candidates to bypass the limit. Extend confirmed pre-dispatch recovery to
both registered stage binding forms, with exact current assignment/artifact and
authorization proofs. Qualify oversize original-plus-rendered packs, changed
versions, bounded reads and both binding forms using text fixtures before claiming
this handoff works in the installed runtime or resumed live workflow.

The shared saved-page API text-review context is now implemented and qualified
in a maintained-package candidate. Code derives the local artifact index from
registered producer metadata and exact candidate versions, measures serialized
read workload, and allocates missing request capacity inside the original tool
allowance. Explicit request ceilings remain binding. Literal batches cover every
declared text input; code rejects incomplete review, changed bytes or versions
and oversized model requests. Provisional model notes retain their observed
intervals without becoming accepted evidence. Prior bulky tool responses are
archived losslessly across supported provider history formats. Single Markdown
or text review outputs are rendered from the final validated report, without an
extra model write request. Typed record reviews keep their existing interface.

Confirmed zero-dispatch input recovery now supports plan and production-run stage
bindings. It requires an unchanged started graph under the original stage grant,
no control epoch or uncertain peer, an identical unexecuted assignment, and
artifact registrations preceding the stopped boundary. Dispatch rechecks the
committed input versions. Historical attempts, reports and captures are retained;
recovery spends the reviewer's first attempt rather than replaying collection.
The exact maintained-package candidate passed 237 affected controlled checks,
including compatible graph delivery and correction fixtures. A zero-provider,
read-only check of the saved live evidence reconstructed all exact versions in
eight batch reads plus finalization within the original twelve-call allowance.
The signed installed native package matches the qualified bundle and all 66
cumulative runtime overlays, with fresh core service health observed. The normal
controller recovered the existing stage automatically and dispatched the original
reviewer's first attempt. Live journals confirm eight successful bounded reads,
with no unobserved text remaining and no collection replay or manual recovery
control. The independent review completed and released catalog authoring under
the original target policy. Retailer access restrictions and option shortfalls
remain explicit advisories, not verified purchasing facts. This proves the live
evidence-review handoff; final catalog/photo quality and PPTX delivery remain
distinct, incomplete qualification steps.

This decision constrains future fixes. It does not claim that arbitrary data can
satisfy every contract, that external services cannot fail, or that all compatible
graphs have been tested. Compatibility, evidence validity, explicit requirements
and authorization remain enforceable.


## Typed review observation and capability closure

The later live catalog review exposed a different shared boundary: the worker
received exact parsed item evidence and committed all item judgments, but its
final whole-candidate observation guard also required literal projection text.
The fragment-only tool filter hid file reading, and archive retrieval could not
resolve a declared input path. This was an executor/interface mismatch; changing
the model or repeating product collection would not correct it.

The shared API loop now supplies bounded literal candidate projections, including
companion summaries, using frozen candidate ownership and hashes. It exposes
read-only declared-file access for omitted suffixes. Generic writes remain
unavailable for fragment-owned projections. The complete-candidate observation
and independent semantic record checks remain mandatory. Execution feasibility
includes outstanding candidate reads, typed judgments and finalization within
frozen capacity; it cannot silently raise an allowance.

Confirmed local tool/observation failures can consume a remaining original review
attempt under the existing completion grant. Code verifies the actual rejected
finish receipt and absent tool declaration, immutable provider/tool journals,
unchanged candidate and input versions, scope and no pending or downstream work.
The previous item judgments and failed final report remain historical unaccepted
artifacts. A fresh independent review must complete; recovery never manufactures
acceptance. This is shared by compatible configured collection interfaces, not a
room-specific controller.

Small fixtures exercise actual tool filtering, from-task candidate bindings,
omitted companion text, configured plant/furniture/component records, changed
input holds, exact controller recovery, unchanged ceilings and successful fresh
review completion. Initial broader source checks retain missing document-runtime
dependencies and unrelated historical audit-fixture mismatches. Final maintained
package checks, deployment and live recovery are recorded separately under
outputs/review-input-interface/ and ignored private run storage.

The final maintained candidate passed 251 affected checks in 39.014 seconds,
without live provider calls. The exact saved catalog and companion text passed
a read-only preflight through the whole-candidate guard, with zero provider
requests and database mutations. The signed installed native package and all 66 cumulative runtime overlays match
the qualified candidate; fresh core health was observed. The controller
automatically committed the exact input-review continuation and started the
remaining original review attempt. Live receipts confirm complete candidate
projection text and successful declared-file reading. Searches, browser captures,
prior attempts and original limits remain preserved. The corrected independent seed review
completed successfully in 10 calls under its original 13-call ceiling, and
catalog coverage authoring started. Final catalog/photo quality and PPTX
delivery remain pending.

## Planner finalization after discovery

The unattended pilot exposed a shared admission-loop boundary: the planner used
all discovery rounds and then returned a schema-invalid proposal. The loop already
had two bounded proposal corrections, but its discovery-round condition prevented
either from running. The fix separates discovery from response-only correction
inside that same loop. It does not add a scheduler or relax the compiler.

Corrections retain the frozen request and captured catalog, journal the exact
rejected response, and expose only final response data. Further reads are rejected
even if a provider disregards the tool declaration. The original correction
ceiling remains binding; uncertain submissions do not auto-replay. Explicit received generation failures now use the common classification described below.
Tests cover every supported provider wire format at the last discovery round,
read reopening, exhaustion and uncertainty. Qualification and live trials remain
separate; the failed pilot is preserved, not relabeled after the implementation fix.

## Confirmed provider candidates and final outcome review

The shared provider-response classifier now runs before tool parsing in both
planning and API workers. Only explicit received output-limit or malformed-call
results qualify for bounded local correction. Planning uses its existing intake
and proposal correction ceilings; schema and generation failures spend the same
allowance. The full rejected reply and structured no-effect outcome are retained
before another submission. No call from the rejected candidate is executed.
Unknown, pending, safety and transport outcomes do not grant retry permission.

New planning snapshots bind final file outcomes to an independent final-quality
contract. The compiler owns outcome identity, exact candidate inputs and registered
inspection companions. The reviewer supplies separate judgments for requested
requirements, reference fit, factual evidence and usability. Acceptance requires
complete judgments bound to unchanged frozen inputs; defects cannot be hidden as
advisories. Usability must cite the candidate and its registered inspection
evidence. Reference fit must cite supplied visual references when bound. Explicit
target gaps remain representable without waiving hard requirements or suitability.
The existing report validator, correction loop and persistent controller retain
acceptance and recovery ownership; there is no separate final-quality scheduler.
Historical plans keep their captured policy rather than acquiring new obligations.

These checks enforce complete, version-bound review, not the truth of a model's
judgment. Source facts and visual correspondence still require live independent
inspection. Controlled checks use small scripted candidates and provider replies;
package qualification and fresh unattended results are recorded separately.

The next live admission exposed an incorrect dependency between contract versions:
review capacity and response allocation were enabled only for record-schema v1,
so generic record-schema v2 silently skipped them. Admission now depends on its
own declared capacity policy, independently of record content schemas. Unchanged
hard ceilings still reject unaffordable work. The saved-proposal reconciliation
identity covers both runtime packages, including added adapters, so a handwritten
module list cannot miss a relevant compiler change. A changed identity only permits
revalidation of the preserved proposal; atomic successor creation and ordinary
authorization checks still own dispatch. The exact failed reply validated read-only
after this change. This does not erase the failed live trial or establish delivery.


Typed file handoffs use the same registered family identity whether the producer is
a fragment worker or an exact native operation/version/output port. Native merge
validates its bound input family; candidate delivery still validates actual bytes
and independent semantic review remains required. Planner intent has one owner:
legacy and generic selectors cannot coexist on one task. Interface compatibility
is explicit and finite; a backward-compatible planner extension retains captured
connector definitions while unknown future versions gain no implicit authority.

Evidence pagination is a transport allocation, not an authorization limit. The shared indexed review interface derives a bounded batch size from exact serialized evidence and the unchanged request allowance, accounting for provider string escaping. Full original intervals and independent judgments remain mandatory. If the workload cannot fit the registered transport capacity, admission still holds; increasing a preferred read size cannot increase requests, tools, local input capacity or acceptance authority.

Confirmed pre-dispatch capacity holds use stable outcome codes. Historical receipts retain their original wording and pass a narrow compatibility reader; recovery still revalidates exact pre-existing artifacts, unchanged assignment/grant and actual current feasibility before the same controller commits a queue transition. An implementation fix alone does not authorize another attempt or acceptance.

Indexed local review follows registered content ports across worker and native producers. Code may share literal observations between declared input paths only when their exact byte hashes agree; all artifact identities remain frozen, aliases are explicit, and every alias is reverified before use. This reuses observed evidence without inferring semantic equivalence or acceptance. Unknown native operation versions do not inherit the interface.

Local review admission measures the logical session across its original authorized
attempts, while every invocation retains its frozen request and tool ceilings.
Only supported persistent local reviews receive this accounting; speculative
recovery cycles are not capacity. A terminal read tool result is not yet model
observation. Checkpoints preserve only intervals supplied before a confirmed
response, so a restart supplies the undelivered tail again. The existing controller
validates exact versions, confirmed journals and committed allocation before
continuation; it neither repeats collection nor infers semantic acceptance.

Confirmed provider rejection recovery is independent of the request's position
inside a typed operation. Every earlier response and local tool receipt must be
accounted for, bound to the original provider/model, and retained by hash. A later
billing rejection cannot resolve an earlier uncertain submission. Billing recovery
still requires an explicit new continuation grant, retains committed provisional
records, and uses the existing controller rather than collecting sources again.


## Shared agent and registered-operation runtime

The source implementation now follows [universal-runtime.md](universal-runtime.md): separate provider transport from one agent loop and the registered operation lifecycle, retaining historical aliases. Prospective version 2 work grants compose compatible local, host and external operations, with exact bindings, committed approvals, resource ownership, durable pending handles and code-owned terminal decisions. Qualification distinguishes scripted graph/transport evidence, real local document artifacts, controlled native adapter checks, installed applications and live outcomes.


Review obligations follow exact candidate derivation and compatible registered output identity. Partitionable interfaces declare their source and range scope, so unrelated record partitions or native artifacts do not acquire one another's findings. A unique requested format can identify successive candidates for that output; ambiguous roles require explicit derivation. Missing candidate identity remains conservative. Final delivery must collectively cover every recorded finding using accepted, exact-version reviews; a scoped review is never permission to drop an unresolved branch.

Generated reviewers reserve current candidate paths before assigning stable aliases to inherited evidence. The shared compiler binds native preparation through its named parameter reference, canonicalizes only byte-identical aliases, and resolves completed task/output references to exact saved artifacts. Raw intents, earlier bytes, reviews and failed attempts remain preserved. These are shared compiler/review interfaces, not domain-specific recovery controllers.

All registered record submissions and amendments validate their advertised fragment schema before normalization and semantic hooks. Invalid input returns the exact nested path, expected type or violated bound without committing state. The provider-facing schema and runtime wire validation have one registry authority; semantic evidence checks remain separate and mandatory.

Native dependency checks distinguish serialized embedded metadata from unresolved external or opaque content. Rhino object/geometry user strings remain in the native fingerprints and are supported; other opaque entries, references and external textures remain blocked. Failure receipts identify offending object identities and entry counts. This is shared host validation, not a workflow-specific drawing exception. Controlled and actual-host preservation checks remain distinct from unattended workflow qualification.

Registered named hash ports may declare compatible source media and a canonical consumer role. Compilation binds that role on the selected consumer descriptor without changing producer bytes or descriptors; the policy is pinned in the interface. Binary identity/provenance routes are admitted as artifact_inspect evidence without UTF-8 decoding, visual acceptance or implicit operation consumption.

Resumable record families must expose outstanding work to the shared controller, including mandatory finalization. Bounded fragment batches may include an explicit completion record atomically; code never infers that the model has finished semantic work. Confirmed checkpoint continuation preserves the original inputs, record versions, limits and attempt grant.

Persistent transports register a finite union of shared lifecycle declarations before opening a thread. Each exchange still validates the complete proposed batch against its current, potentially narrower surface before effects. Recoverable authority denials return explicit no-effect results to ordinary workers as well as owners and reviewers, within the unchanged request allowance. A transition may not introduce an undeclared tool or silently widen current execution authority.

A committed operation candidate and a successful delivery are distinct proofs. Recovery/review may inspect original committed candidate bytes through exact input/output hashes even when the producer withheld delivery; this grants no acceptance and does not bypass uncertain-operation, stale-input or changed-output checks. Successful delivery keeps its complete-step and observation requirements. Format bounds constrain both producer defaults and native validation before execution, while the original user request stays lossless. Fully exhausted task grants produce a typed terminal outcome rather than model-correctable admission feedback.

Tagged union diagnostics are chosen only after all alternatives fail validation. A uniquely matching set of required enum tags selects the relevant error explanation; it cannot narrow the accepted schema language. Object diagnostics report bounded sets of missing/invalid fields and allowed enum values, without coercion, content repair or partial commits.

Captured observations retain separate literal-text, structured-metadata and image-candidate surfaces; metadata is not a downloaded or visually verified asset. Registered layouts own lossless readable pagination and explicit visual density. Batch-aware admission uses the same registered fragment count as transactional submission, including explicit finalization; this preserves calls for inspection without changing authorization or inferring completion.

Live qualification rejected automatic fixed-box text continuation because it separated claims, captions and citations. Fixed-layout overflow therefore rejects before commit with slot-specific geometry diagnostics; collection/table pagination remains code-owned. Literal HTTPS citations retain exact text and native hyperlink identity. A prospective graph-capacity policy binds the validated plan size to an explicit frozen owner grant (bounded at 127 delegated tasks); legacy plans retain their 30-task limit. This grants capacity, never automatic retry, authority expansion during a run, or acceptance.

## Automatic composition and typed native intent — 2026-10-13

Registered typed operations should absorb mechanical host API differences. `rhino.document` is the bounded data-only counterpart to arbitrary script execution, using the same host resource, frozen implementation, intent receipt and independent native reopen lifecycle. Its current vocabulary is boxes, polylines, text, aligned dimensions and named views. Unknown operations reject; no exception text is translated into an arbitrary new call or replay. Existing Blender and script operations retain their scopes. This is extensible operation support, not universal geometry coverage.

Saved section composition belongs to code. `document.compose` consumes registered section projections and exact image inputs, retains literal claims/notes/order, and appends contained full-page previews. Section projections record consumed pixel hashes; composition changes a path alias only when identical pixels are present. Changed pixels require a new section version. Original documents remain immutable. Mixed page sizes/fonts reject instead of silently losing fidelity. Models choose narrative and semantic corrections; final visual judgment remains independent.

A declared preceding result supplies a downstream single JSON preparation/content port. Other JSON remains inspectable context rather than becoming an accidental second manifest. Reference-list schemas preserve registered cardinality. Preparation allocation counts registered batches and reserves finalization capacity under the original tool/provider grant. These are shared compiler/lifecycle rules, not Rhino or furniture controllers.

Qualification records live in ignored `private qualification records`. An actual Rhino fixture and affected controlled checks passed; fresh unscripted Y and reference-PDF comparison are recorded separately. No deployed-runtime or broad artifact-quality claim follows from these checks alone.

Completed tool evidence and model generation status are separate facts. The shared `observation_outcomes.retained_reads` rule permits retention only of completed read IDs under a correlated failed terminal with no outstanding read. The Codex search adapter applies it to hosted URL discovery, preserving the original terminal error, raw journals, usage limitations and explicit non-acceptance. The shared source collector carries that provenance into its source pack. It performs no search replay and makes no claim about an unfinished read or missing final synthesis. Other transports must meet the same evidence rule before producing this normalized outcome; no cross-provider live qualification is inferred. Y exposed this distinction, exact journal replay passed offline, and Z is the fresh composed attempt.


Declared evidence routing also applies to standalone registered record authors. Native binaries remain exact, inspectable inputs through registered representations or explicit identity-only receipts; neither route grants Python or semantic acceptance. New native composition routes inherit registered assets, while missing routes in historical grants are not backfilled. Display representations retain exact originals and separately bind their transformation and output identity. Native image regions and literal text flow belong to the common presentation contract; automatic projections consume saved bounds and facts, and independent rendered review remains required.


Physical coordinate meaning is shared data, not an inferred host default. Compatible native preparations declare units, measurement basis and a bounded disclosure; host adapters map that declaration to native settings and metadata and verify it after independent reopen. Unit conversion uses a common meter factor and retains original coordinates. Existing explicit native units remain unchanged; an absent unit or measurement basis stays unspecified. This does not infer fabrication accuracy, cross-object correspondence or semantic acceptance from a successful native check.

Fixed multi-output operations expose an exact execution family. New owner grants capture that registered mapping; selecting one output carries its co-outputs into compatible inspection/review ancestry. Composed native consumers still receive only their registered asset subset. Existing artifacts resolve peers by exact producing attempt, never current task/latest, filenames alone, or matching bytes. Historical inputs remain historical; family membership is neither representation equivalence nor acceptance. Missing historical policies stay absent and cross-run peers require explicit authorization. Declared inspection files use a bounded local-file store separately from model-request serialization.

A declared inspection route must exist in the actual initial worker tool surface before inference. Specialized fragment interfaces may hide generic writes, but may not hide a granted reader needed for prior candidates, correction evidence or independent review. Missing reader declarations fail before provider dispatch; identity-only inspection never substitutes for reading content.

Selectable literal spans and normalized values must share one parser. Parse complete tokens against the original observation before applying caller selection bounds; otherwise a shortened span can silently drop fractional digits. Preserve raw text/offsets, reject ambiguous representations, and keep literal normalization separate from semantic claims about offers, variants or availability. A corrected parser must reject known incorrect historical projections without rewriting their original journals.

Native literal text remains immutable intent. A format adapter owns explicit encoding and compares reopened content with the deterministic native representation of that intent; lossy plain-text extraction is not the original content. Native formatting, rich content and plain projection must not be “repaired” by stripping whitespace or asking a model to rewrite valid text. Actual unchanged-input and post-save corruption checks qualify this boundary separately from semantic layout review.

Compiler-created inspection evidence resolves completed task-output references to
exact collected artifact identities before reusing inherited inputs. Distinct
evidence receives deterministic collision-free aliases without rewriting prior
bindings or producer bytes. Shared work intent construction normalizes unambiguous
reference placement while preserving raw proposals; conflicting choices remain
errors. This avoids spending model corrections on code-owned envelope mechanics,
without increasing any retry, capacity, provider or acceptance authority.

Registered content recovery exposes an exact baseline reference in the declared
owner schema and catalog. Construction normalizes reference placement and records
direct intent before inherited provenance is added. Only an explicit selection,
or a unique directly supplied compatible candidate, can seed recovery; older
inherited catalogs remain evidence. Equal bytes do not merge artifact identities.
Conflicting, unsealed, incompatible, tampered, active or uncertain baselines reject
without admitting work. The lifecycle binds retained sources and independent
review within existing scope and capacity; semantic correction stays with models.

Shared database observations follow [the read/write boundary](database-lock-boundary.md):
record progress, evidence verification and projection reads must not promote a
WAL read snapshot to a writer. Actual mutations retain their original atomic
transaction, request identity, timeout and revision checks. Never replay a whole
transaction or external effect merely because SQLite reported contention.
