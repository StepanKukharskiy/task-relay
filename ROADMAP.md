# Task Relay roadmap

Task Relay coordinates bounded project work across agents, APIs and tools, preserving
requests, artifact versions and human decisions. Telegram is the initial common
interface. The implementation is in active development; implemented scope does not
mean every provider, platform or delivery path has live qualification.

### Accumulated public beta — 0.13.89

Release candidate includes all implemented updates through 0.13.89, the previously
published first-run planning fix, contract diagnostics, standalone 3DM operations
and SketchUp adapter source. Public source documentation and release notes now
cover the accumulated scope. Host qualification and human execution/selection
boundaries remain unchanged. Release preparation and validation evidence is kept
under `outputs/release-0.13.89/`; publication is recorded there after verification.

### Ordinary reel requests — 0.13.89

Implemented: conversational routing maps a plain reel request to the local video
capability, resolves selected source context and carries prior guides through an
existing completed-stage handoff. MP4 remains a declared outcome while encoding is
pending. Compact context retains current video availability and its actual blocker.
Users need not supply operation IDs, a renderer, worker type or a technical prompt.
Source ambiguity still requires clarification; explicit provider/tool and planning
restrictions remain authoritative. No keyword-triggered dispatch or new execution
authority is introduced. Controlled checks: `outputs/reel-request-routing/`.
55 routing/context/planning checks pass, including a short-request handoff with a
selected prior source and required pending MP4. Model responses are controlled;
no paid model trial is claimed. Installed 0.13.89 with 237 matching runtime files,
verified signature, fresh service health and installed local-video discovery readback.
All prior production records and the 478 R045 workflow files remain unchanged.

### Full HyperFrames authoring across providers — 0.13.88

Implemented: agents author full front-end source and local asset bindings through
`hyperframes.preview`; diagnostics and independent review can use an explicitly
planned bounded source-correction loop. Human selection preserves the complete
preview set. `hyperframes.render` encodes the exact registered preview bundle and
receipt with pinned hashes. Existing completed content and legacy template plans
are preserved. The shared macOS adapter scopes authored project file access and
retains its clean environment, deadline/cancellation supervision and no uncertain
replay. No provider-specific video worker or shell capability is required.

Qualification and focused validation records are under
`outputs/hyperframes-authoring/`. 118 distinct focused cases pass across the
recorded runs after correcting test-only fixture errors, including all five provider
bindings and confirmed failure/review correction paths. Actual authored-project
preview and exact-bundle H.264 rendering pass on a three-layer 320×568/15 FPS/2-second
fixture; the legacy image/audio render also passes. Early sandbox/fixture failures
are retained. No model calls, bot messages or R045 content rendering were performed.
See `docs/reels.md` for the contract and limits.
Installed 0.13.88 with 237 matching runtime files, verified signature and fresh
Telegram/production/orchestrator/Messages service health. A read-only query through
the installed runtime confirms both new operations and legacy composition available.
All 478 files of the existing R045 workflow and all 183 prior production attempts
remain unchanged, along with saved runs/tasks/artifacts/assignments/decisions.

### Provider-independent local reel composition — 0.13.87

Implemented: `media.compose` accepts bounded scene JSON from any supported text
provider and runs a shared, qualified local HyperFrames renderer. Deliveries include
H.264 video, editable source/assets, contact sheet and identity-bound verification.
Text authors receive asset references; binary review can use the same provider's
code profile. Equally narrow worker choices prefer the current provider. Existing
locked executors, independent reviews and human visual selection remain enforced.
The macOS adapter has a clean environment, external network denial, owned-process
cancellation, bounded execution and no automatic replay. Initial scope is existing
images, text, simple entrances and optional supplied audio; no arbitrary composition
code, generated voice or footage. See `docs/reels.md`.

Controlled evidence: `outputs/provider-neutral-reels/`. 71 focused contract,
planning, worker-selection and registered-execution tests pass, plus two targeted
owner-death and missing-receipt tests. The two planner tests passed again after the
final instruction change. A real two-scene 320×568/15 FPS fixture with a PNG and
supplied WAV passed HyperFrames checks and H.264/frame-count/audio verification;
its decoded contact sheet was inspected. Earlier qualification failures remain
recorded. No paid model calls or changes to previous content productions were made.
Installed 0.13.87 with 235 matching runtime files, verified signature and fresh
service health. A read-only check through the installed Python/runtime confirms
`media.compose` is available against the qualified HyperFrames 0.8.46 installation.

### Long text generation recovery — 0.13.86

Implemented: local API text workers can recover once per confirmed incomplete
generation kind inside their existing allowance, preserving prior tool results
and discarding every call in the incomplete response. Text append uses the last
confirmed byte count to prevent duplicate sections and retains exact output grants
and byte limits. No provider/response-budget increase, uncertain replay, media
generation or automatic acceptance is introduced. Evidence:
`outputs/storyboard-generation-recovery/`.
78 focused worker, generation-recovery, shared-provider and report-contract tests
pass on the final rerun; an earlier cancellation timeout is retained in the logs.
Installed 0.13.86 with 232 matching runtime files, verified signature and fresh
service health. The reported storyboard run was resumed using its existing second
producer attempt after confirming the failed response executed no tools and no
storyboard file existed. All 181 prior attempt records were unchanged at recovery;
the model, per-attempt limits and downstream decision gate are preserved.
Live recovery verified: another malformed response on request 2 was discarded;
the producer completed in five requests using write plus append, delivering a
28,031-byte storyboard. Review completed in three requests. The automated review
accepted, but a local narration count found 172 words rather than its claimed 118
(about 246 words/minute at 42 seconds). A Telegram selection was subsequently
recorded and the workflow completed. Pacing correction is still recommended before
rendering; the user's selection is preserved. No video or audio was generated.

### Text delivery integrity and exhausted-review continuation — 0.13.85

Implemented: API text workers receive a bounded exact source pack upfront rather
than spending most requests on file discovery. Review candidate text comes first;
omissions retain explicit read offsets. Local guards require complete candidate
exposure and reject placeholder-only delivery/acceptance. They do not substitute
for independent editorial judgment. Explicit continuation after a failed terminal
text review creates a fresh same-scope stage, preserving its full failure receipt
and original attempts; pending/uncertain work remains blocked.

Validation and deployment evidence: `outputs/content-text-integrity/`.
85 focused text-worker, shared-provider, continuation and workflow integration
checks pass. Two broader presentation-capability tests fail before their assertions
because `pptx.create` is unavailable in the test environment; both failures also
reproduce using the installed 0.13.84 runtime. No presentation/media work was run.
Installed 0.13.85 with 232 matching runtime files, verified signature, fresh service
health and app reopening. Both workflows and all five prior attempts match the
pre-recovery snapshot. The user's saved continuation dispatch was recovered into
one same-scope successor with the original provider and limits; live outcome is
recorded separately from controlled checks.
The live successor produced a 2,024-word article (16,286 bytes); producer and
reviewer each completed in two requests with complete source packs and no pending
responses. The reviewer accepted, but manual source comparison found unsupported
verification/implementation claims, inconsistent timing attribution, retained
product branding and missing citations. The stage is awaiting user decision;
runtime recovery is verified, editorial acceptance is not. All four earlier runs,
eight task records and five attempts remain unchanged. Exact findings are retained
in ignored private storage; `live-outcome.json` records the qualification limit.

### Gemini report transport — 0.13.84

The two approved comparisons completed: the saved request succeeds when only
file_list can be called, but changing nullable-check JSON Schema encoding still
returns HTTP 400 with all tools callable. The previously accepted synthetic
probe restricted callable tools, so it did not verify unrestricted report use.

A Gemini-only finish(report_json) transport keeps the
full frozen report schema in the assignment and validates the decoded report
locally without changing criteria, evidence, role or acceptance rules. Shared
provider definitions remain unchanged; raw envelope arguments are retained.
57 focused worker, report-builder and shared-provider tests pass. The subsequently
approved live check retained all callable tools, returned STOP and a blocked
diagnostic report, and passed the full unchanged local report validator. Gemini
reported 4,367 total tokens (3,981 prompt, 70 candidate, 316 thinking); no tools
executed. This verifies the report transport, not article completion. Failed
production attempts remain stopped. Evidence:
`outputs/content-gemini-report-transport/`.
Installed locally as 0.13.84 with all 232 runtime files matching source, verified
signature, fresh service health and app reopening. Both content workflows and
all three failed attempts match the preinstall backup; no production restarted.
Private installation/rollback records: `private/content-report-install-0.13.84/`.

### Continuation after rejection before drafting — 0.13.83

Implemented: explicit text-stage continuation can start from retained original
inputs when the first API attempt was definitively rejected with HTTP 400 before
tools or outputs. Missing, uncertain, executed or conflicting receipts do not
qualify. A failed local setup can be explicitly recovered, preserving the full
failed row in an event before requeueing the same bounded successor. Existing
attempts, scope, providers and user selection gates remain intact. No automatic
replay or draft acceptance is added.

57 focused continuation/pipeline checks passed, with the continuation suite rerun
after a malformed-receipt guard. Evidence: `outputs/content-no-draft-recovery/`.
The reported saved attempt passes the read-only eligibility check. Deployment
and execution are tracked in the same evidence directory. Installed locally with
232 matching runtime files, verified signature, fresh service health and app
reopening. Using the user's saved explicit continuation request, the same bounded
successor registered and attached to its workflow; original failed attempts and
the previous content workflow remain unchanged. The successor's first drafting
request was also rejected with HTTP 400 before tools. The synthetic diagnostic
therefore did not reproduce the full request issue. Two bounded comparisons of
the actual saved tool/report schema were subsequently authorized and completed;
see the report-transport investigation above. No further production retry is
scheduled. Private rollback: `private/content-no-draft-install-0.13.83/`.

### Gemini request diagnostics and parameterless tools — 0.13.82

Implemented: parameterless Gemini function declarations omit the empty OpenAPI
parameters object. Shared tool definitions and nonempty report schemas remain
unchanged. Bounded structured HTTP diagnostics retain provider messages/status
after credential and URL redaction; unstructured and oversized bodies are omitted.
Worker outcome receipts retain the diagnostic without changing rejection,
uncertainty, retry or approval policy.

91 controlled transport, worker, shared-provider and service-unavailability checks
passed. An initial test run exposed two incorrectly configured new test fixtures
and an older pause-notice fixture missing its run identity; corrected fixtures
passed. The reported run rejected its first request before any tools executed.
Its original HTTP body was discarded by the old transport, so the precise cause
cannot be recovered from the saved receipt. Parameterless-schema compatibility
is a candidate cause, not a confirmed historical diagnosis. Evidence and live
verification status: `outputs/content-gemini-400/`. No failed attempt is reset.
Installed locally as 0.13.82 with 232 matching runtime sources, verified signature,
fresh service health and app reopening. The current failed attempt and both
content workflows were unchanged at installation. The user subsequently approved
one synthetic diagnostic: Gemini accepted it, returned STOP, and reported 778 total
tokens; no returned tools executed. This establishes acceptance of the corrected
tool declarations, not the lost historical rejection reason. Private rollback
receipts: `private/content-gemini-install-0.13.82/`.

### Workflow operation and worker distinction — 0.13.81

Implemented: new workflow schemas offer captured graph operations instead of
unconstrained capability strings. Saved production-stage proposals that redundantly
declare `files.text` compile it as the baseline agent ability with a receipt retaining
the original declaration. Other worker abilities are not silently dropped; unknown
operations, duplicate declarations, and registry drift still block. Human selection
gates, planning-only state and exact attachments remain intact.

88 focused builder, pipeline, uploaded-planning and correction tests passed,
including an attached-text planning-only regression. The reported saved proposal
validates locally without another provider call. Its reviewable plan and source
manifest are saved privately; neither the rejected request nor the earlier failed
production was recovered or replayed. Evidence: `outputs/content-workflow-capabilities/`.
Installed locally as 0.13.81: all 232 runtime sources match, the signature verifies,
services report fresh health and the app reopened. The rejected request, its error,
the previous workflow and its failed attempt match the preinstall database backup.
Private install/rollback receipts: `private/content-workflow-install-0.13.81/`.

### API worker startup, workflow inputs and scoped blockers — 0.13.80

Implemented: shared API workers use package-qualified imports in their script
entry point. Workflow pause notices select the exact production from the recent-run
inspection catalog. New workflows freeze request-bound uploads as immutable sources
and pass them to first and later stages; changed originals cannot replace them and
corrupted registered copies block dispatch. Existing executed workflows are not
retroactively rebound. The real supervisor fixture now exercises the script entry
point with controlled provider transport, covering draft/review handoff, cancellation
and uncertain outcomes. Failed attempts are preserved; no workflow is replayed.

77 focused worker, pipeline, attachment and uploaded-planning tests passed using
the presentation-enabled test environment. An initial system-Python run passed 55
and failed two checks because PPTX dependencies were unavailable; the complete
rerun passed. Startup, notice-scope and missing-upload regressions reproduced the
original failures before their fixes. Read-only inspection
of the reported content run confirms that corrected pause text excludes unrelated
native failures. Its generic continuation passes the initial eligibility check but
cannot build without a prior draft; a fresh explicitly requested plan is needed for
this zero-request failure and its missing original handoff. Evidence and exact
commands: `outputs/content-worker-startup/`. Installed locally as 0.13.80 with all
232 runtime sources matching, a verified signature, fresh Telegram/Messages health
and app reopening. The blocked content attempt remains byte-for-byte identical to
the preinstall database backup, with zero provider requests. No live generation,
workflow replay or message-delivery test was performed. Private installation and
rollback records: `private/content-worker-install-0.13.80-final/`.

## Jobs, pipelines and capabilities — design requirements

- **Job:** the user's intended outcome, references, scope and recorded decisions.
- **Pipeline:** a versioned plan with dependencies, execution attempts and decision boundaries.
- **Capability:** an operation with declared inputs, outputs, availability and limits.

Use direct capabilities for simple work. Plans may come from a known template, an
adaptation or a newly generated bounded graph. Preserve their origin and version;
changes to one job do not silently modify a reusable template. Validation and
existing authorization govern execution, regardless of plan origin.

A job should expose its outcome, completed/current/blocked stages, exact available
outputs and next decision. Distinguish waiting for a human from missing input,
missing capability, failure and uncertain submission. Never infer acceptance from
an ambiguous response or replay an uncertain external operation.

### Procedural contract boundaries — tracked follow-up

The [contract boundary tracker](docs/contract-boundary-tracker.md) records ten
remaining model-to-contract boundaries, their existing safeguards, source anchors,
proposed procedural ownership and focused completion checks. The initial priorities
are field-scoped corrections, registered-operation construction, artifact/port
binding and derived worker requirements. This audit does not expand existing stage
authorization or make deferred milestones prerequisites.

Implemented tracking support: `scripts/audit_planner_contracts.py` opens an existing
database read-only and groups saved planning rejection signatures, separating failed
calls from affected plans and capability/provider failures from contract categories.
Unknown messages remain explicit. Four small-fixture tests pass; instance-specific
audit evidence is retained under `outputs/contract-boundary-audit/`. Router/worker
telemetry and the remaining builders are backlog items, not completed features.
No service change, scheduled monitor, provider execution or failed-job replay is
part of this audit.

First operation builder: **installed locally in 0.13.78**, `rhino3dm.run_python` v1 execution/review
stages with captured script/checks. The model supplies typed artifact slots and
review concerns; Relay constructs registry constants, hashes, ports, worker needs,
review edges and companion selection. Frozen registry drift and invented fields
fail with structured code/field receipts. Exact-code delivery/Start and immutable
source checks remain mandatory. Preparation recovery restores its generic schema;
other builders and script/check authoring remain tracked work. Focused controlled
validation: 99 integration tests and one additional source-fidelity regression
passed across builder, planner/schema, mixed planning, host input paths, review
corrections and worker capabilities. Commands and limitations:
`outputs/operation-builders/`. Signed app build/install completed with 229 matching
runtime source files, fresh Telegram/Messages service health and verified app reopening.
Private rollback records remain under `private/operation-builder-install-0.13.78/`.
No live provider or geometry execution was tested.

Artifact, stage and report extensions: **installed locally in 0.13.79**. Compact
artifact references now compile canonical paths/authority, dependency edges,
reviewer coverage and companion sets. Semantic workflow details compile output
types, descriptors and handoffs. New non-operation assignments expose frozen
criterion slots; Relay binds assignment identity and serializes typed source
observations/measurements. Legacy saved forms remain supported; no approval,
acceptance or replay policy is weakened. The remaining router, checks-authoring,
operation and correction boundaries stay in the tracker. Focused qualification:
211 integration checks plus one additional format regression passed (212 distinct
checks, including 19 new regressions); evidence in `outputs/contract-extensions/`.
Provider transports and runtime collection used controlled small-file fixtures;
no live provider request or actual media/native model generation was performed.
Deployment verified all 232 runtime source files, the installed signature, fresh
Telegram/Messages service health and app reopening. The first install stopped
before replacement because bundled-interpreter tests wrote unsigned bytecode caches;
those 61 caches were retained privately, the original signature restored, and a new
verified installation completed. Recovery evidence is under
`private/contract-extensions-install-0.13.79-retry/`; no workflow replay occurred.

### Full standalone rhino3dm API and Rhino 7 files — unreleased

Implemented in source after the user's request for complete library support:
`rhino3dm.run_python` exposes the full installed Python API without Relay's JSON
geometry whitelist. Reviewed scripts create/edit File3dm documents with declared
additional assets. Explicit `file_version` supports Rhino 7/8 archives and the
library's earlier writable formats. The selected library/Python runtime and exact
script/checks/inputs bind to a separate execution approval. Native Rhino operations
remain distinct; file-format compatibility does not claim a native application ran.

Independent process reopening, preservation checks, user review for serialization
or dimension differences, correction preparation and no replay are integrated.
The existing JSON builder remains a convenience operation. Scope is the installed
rhino3dm Python API, not RhinoCommon commands, desktop plugins or unapproved Compute
calls. Other document tables, opaque plugin data and external dependencies require
task-specific review beyond the generic object/metadata verifier. Source changes
have not been installed into the running service. Controlled check evidence:
`outputs/rhino3dm-full-api/`.
21 focused tests and 116 affected integration tests passed. Real standalone
CPython workers wrote/reopened Rhino 7 and 8 archives with NURBS curves/surfaces,
BReps, annotations, extrusions and block instances; an actual supervised run also
passed. Approval drift, source preservation, failed/uncertain outcomes, quality
gates and correction preparation were checked. No native Rhino or live provider ran.

### Standalone 3DM generation — unreleased

Implemented in source at user direction: `rhino3dm.create` is a separate local
procedure for new `.3dm` models from bounded geometry JSON. Points, polylines and
triangle/quad meshes (including terrain) retain named layers, colors, units and
double-precision coordinates. Library reopening compares saved geometry/topology
and metadata to the specification; receipts explicitly distinguish this from
native Rhino execution/verification. Preparation and output review, selection,
dependency blockers and no-replay recovery remain part of the existing workflow.

No silent substitution for an approved `rhino.*` stage or a requested native
operation. NURBS construction, existing-model edits, Rhino commands/plugins,
previews and rendering are outside the new procedure. Dependency is pinned for
source extras and future desktop builds. The running service is not updated by
these source changes. Controlled check commands and results: `outputs/rhino3dm/`.
19 new tests passed, including real library round trips and one supervised local
worker, review/selection identity, failed-candidate retention, no replay, planning
scope, dependency blockers and native-inspection handoff. The affected integration
run passed 79 of 80 tests; one photo-bundle routing test also fails with the new
capability removed and remains outside this change. Working-source publication
scan and diff whitespace checks passed. No Rhino app or live provider ran.

### Shared result review policy — 0.13.76

Implemented: typed findings use one scheduler policy across worker outputs.
Usable quality concerns require explicit user acceptance of exact files/previews
or correction feedback. AI acceptance cannot clear the gate. Execution, integrity
and authorization failures block; uncertain outcomes require reconciliation and
are never replayed automatically. Native dimension measurements and exceeded
source-geometry tolerances use the quality gate; missing or invalid evidence
remains a failure. This supersedes the warning-and-continue behavior below.

Rhino/Blender feedback retains exact requests and existing evidence in a new
correction preparation proposal, with separate approval for native execution.
These changes do not retroactively approve or reset existing failed attempts.
Validation evidence and exact commands: `outputs/outcome-policy/`.
Controlled coverage includes 145 policy, adapter, handoff and review tests (one
legacy guidance assertion corrected; its 48-test Rhino subset then passed) and
62 scheduler/control/correction tests, all resolved. No live CAD or provider
execution was performed. Installed locally as 0.13.76, with fresh service health
and all 222 runtime files matching source (200 unchanged, 21 changed, one added).

### Advisory Rhino dimensions — 0.13.75

Implemented at user direction: expected bounding-box size differences no longer
block Rhino execution, preview creation or handoff. They remain visible warnings
with expected/measured values, tolerances and units. Source-fidelity, required
geometry, preservation and integrity checks remain separate. Review guidance must
not reject solely for these size warnings.

68 targeted tests passed for worker preview completion, non-blocking receipt/status
warnings, retained hard failures, and explicit recovery of legacy dimension-only
blocks without changing source inputs or resetting history. An in-memory rehearsal
of the reported production produced a ready unchanged-input runtime recovery plan,
with no native dispatch, provider request or message. Evidence and commands:
`outputs/rhino-dimension-warnings/`. Corrected native execution is not yet qualified
by this rehearsal; a fresh exact-code Start is still required for the old failure.
Installed locally as 0.13.75; fresh service health confirmed. All 221 runtime files
match source (214 unchanged, seven changed).

### Native verification correction — 0.13.74

Implemented: confirmed Rhino/Blender execution failures can propose correction
preparation before an independent review exists, including standalone productions.
Explicit Continue and Plan correction retain original source geometry, exact
script/checks, failure receipts and measured outputs. A separate preparation Start,
independent review, selection and exact-code execution Start remain required.
Uncertain outcomes never enter this correction path. Diagnostic candidates do not
replace source geometry. Proposed expectation changes require evidence; tolerances
and failed geometry are not silently accepted.

79 targeted native recovery, review correction, source-geometry and Rhino operation
tests passed. The reported saved failure also produced a valid preparation proposal
on an in-memory database copy, preserving all four source-fidelity metrics; no
provider, message or native model execution was dispatched. Evidence and commands:
`outputs/native-verification-recovery/`. The terrain itself remains unapproved;
these checks qualify correction routing, not a successful corrected model.
An additional four-test native-failure run passed with a new Blender fixture.
Installed locally as 0.13.74; all 221 runtime files match source (214 unchanged,
seven changed), with fresh service health confirmed by the install receipt.

### Rhino connection discovery latency — 0.13.73

Implemented: read-only script-server discovery has a 20-second ceiling instead of
five seconds. Errors distinguish timeout, failed CLI launch/exit, malformed JSON
and no matching connection. Exact selected-process/version binding remains strict;
no script submission or retry follows from connection discovery.

The reported live session timed out at five seconds and returned a valid connection
in 8.072 seconds with the longer ceiling. A subsequent direct adapter probe passed
in 1.912 seconds, confirming variable discovery latency and an already-running
script server. No user model was executed. Evidence:
`outputs/rhino-connection-discovery/`.
29 targeted host, recovery and routing tests passed, including slow discovery,
error categories, exact process selection and no automatic script submission.
Installed locally as 0.13.73 with fresh service health and all 221 runtime files
matching source (218 unchanged and three changed from 0.13.72).

### Started-plan continuation routing — 0.13.72

Implemented: an invalid planning revision targeting a started plan can be resolved
procedurally to that plan's exact blocked production, provided its saved scope,
inputs and limits are unchanged. The normal continuation/recovery path remains
responsible for eligibility and approval; no execution starts from this correction.
Original provider responses, requests, attempts and started plans are preserved,
with a separate routing receipt. Changes to scope, new sources, unknown targets,
non-blocked runs and scheduler-generated stage requests are not converted.

81 targeted routing/recovery, chat and planning tests passed, including rejection
when the execution changes during interpretation. Read-only replay of the reported saved
request resolves to its exact failed execution, retaining the user's original
message; no provider, host operation or live message was sent by that check.
Evidence: `outputs/continuation-routing/`.
Installed locally as 0.13.72 with fresh service heartbeats; all 221 runtime files
match source (217 unchanged, four changed from 0.13.71). The failed user request
was not automatically replayed.

### Shared recovery classification — 0.13.71

Implemented: trusted adapter evidence feeds one recovery policy, used by native
pre-execution continuation and the existing bounded script-repair preparation.
Rhino and Blender continuations preserve exact selected inputs, operation limits,
review requirements and history. A new delivered Start is required for execution.
Unknown/contradictory evidence requires reconciliation, never speculative replay.
Recovery proposals retain the policy decision and immutable failure receipt identity.
Host readiness remains adapter-specific; terminated Rhino startup requires a live
script connection before re-proposal. No plug-in settings are changed automatically.

99 targeted tests passed, including shared policy, Rhino/Blender continuation,
script repair, immutable attempts, new Start and Rhino coexistence coverage.
Read-only classification of the reported startup receipt selects unchanged-input
recovery. A live Rhino startup-only check passed after a modal plug-in error was
dismissed; the landscape script was not rerun. Evidence: `outputs/shared-recovery/`
and `outputs/rhino-cold-start/connected-startup/`.
Installed locally as 0.13.71 with backups and fresh service heartbeats; all 221
runtime files match source (213 unchanged, six changed, two added). No live
workflow retry or messenger delivery test was dispatched.

Scope: native script recovery is integrated for Rhino and Blender. SketchUp receipt
translation has controlled coverage, but its successor/repair planner is not wired
by this change. Browser and provider recovery retain their existing bounded paths;
the shared policy does not grant blanket retries or automatically resolve licensing,
credentials, user dialogs or unknown external effects.

### Recovery across registered criteria updates — 0.13.70

Implemented: newly proposed recovery graphs refresh same-version registered
operation criteria and their matching independent review requirements together.
Changes are retained in the new context and disclosed in the Start card; old
assignments, attempts and receipts remain immutable. Parameter/output/limit checks
remain strict and unsupported version changes cannot migrate silently. Applies to
host, input-path, browser/preparation and exhausted-review successor planning.

Read-only validation of the reported saved landscape plan reproduced the old
criteria error and passed after refresh with the same script, checks, limits and
three tasks. No user workflow execution or provider call was dispatched.
30 targeted tests passed, including Rhino and PPTX recovery across criteria
changes. Installed locally as 0.13.70 with backups, fresh service heartbeats and
all 219 runtime files matching source (214 unchanged from 0.13.69).
Evidence: `outputs/recovery-criteria/`.

### Rhino 8 session coexistence — 0.13.69

Implemented: an already-open, connected Rhino 8 uses the bundled script server,
with separate task documents and per-session dispatch locking. Existing user
sessions are never exited by the worker. Matching completion receipts distinguish
submission from completion; unresolved/time-limited submissions block further work
without replay. Exact code approvals and old failure receipts remain unchanged.
Rhino 7 still requires an exclusive process; Windows coexistence is unqualified.
Rhino 8's script server must be enabled. Shared work can occupy the UI.

76 controlled tests passed for transport, worker boundaries, recovery, planning,
handoffs and continuation. Live Rhino 8.35 fixtures passed startup,
create/verify/preview, inspection and edit.
The pre-existing user document remained open with its name, object count and
unmodified status retained; no claim of full semantic equivalence is made.
The initial separate-process probe timed out and only its new process was stopped.
Evidence and actual commands: `outputs/rhino-coexistence/`.
Installed locally as 0.13.69 with app/database backups and fresh Relay service
heartbeats. All 219 installed runtime files match source; 212 remain unchanged
from 0.13.68. No live workflow execution, paid provider call or public release
was dispatched by this maintenance task.

### Rhino availability before Start — 0.13.68

Implemented: an open selected Rhino session is detected before Start commits a
production, preserving the ready plan and attempt budget. The launch-time guard
still prevents operating on an existing session. Explicit continuation of a
confirmed no-launch refusal can propose the unchanged script/checks for a new
exact-code Start, without another planning/provider call or resetting old attempts.
Launched, ambiguous, changed or still-busy states do not qualify. Relay never
closes another Rhino session; other installed Rhino versions are unaffected.

28 controlled planning, continuation, handoff and process-boundary tests passed.
Evidence: `outputs/rhino-running-block/`. The reported receipt records a before-
phase refusal with launched=false; no model, preview or Rhino execution is claimed.
Installed locally as 0.13.68 with retained app/database backups and fresh service
heartbeats. All 219 runtime files match source; 214 are unchanged from 0.13.67.
No public release, live recovery dispatch or existing Rhino session closure occurred.

### Review allowance after a corrected draft — 0.13.67

Implemented: cards distinguish scheduler attempt exhaustion from missing worker
failure reasons and identify an unreviewed current candidate. Explicit continuation
can propose one additional local API review, with a delivered Start review approval,
exact current input hashes, unchanged task/provider limits and retained attempts.
The producer is not rerun and acceptance/selection/native execution remain separate.
Active/uncertain work, changed inputs, started downstream work and attempts beyond
the three-attempt contract ceiling are rejected. No budgets are silently reset.

66 controlled tests passed across recovery, status, continuation and runtime.
An in-memory copy of the reported database qualifies for one review of the new
candidate with eleven verified input bindings. No live mutation, paid review or
messenger send was performed by that check. Evidence: `outputs/terrain-review-block/`.
Installed locally as 0.13.67 with app/database backups and fresh service heartbeats.
All 219 installed runtime files match source; 213 are unchanged from 0.13.66.
No public release or live review dispatch was performed.

### Code-worker file and review finalization — 0.13.66

Implemented: shared file-tool initialization prevents code workers from missing
state introduced by browser image sourcing. Ordinary text writes and automatic
review-report saving retain declared output grants and limits across providers.
Code workers retain their binary input rules and gain no browser authority.
Controlled tests reproduce the reported AttributeError and cover its correction,
file/browser boundaries and explicit review recovery without replaying preparation.
51 relevant tests passed. Built, signed and installed locally as 0.13.66 with
app/database backups and fresh service heartbeats. All 219 runtime files match
source; 215 remain unchanged from 0.13.65. No public release was made.
Evidence: `outputs/code-files-init/`. No live review retry or native execution is
performed by these checks; the reported candidate remains an unapproved draft.

### Source-derived native geometry — 0.13.65

Implemented in source: explicit project-file capture, immutable author/reviewer
handoffs, required geometry basis in new native modeling proposals, and separate
preparation/source-comparison review contracts. Terrain plans require contour,
boundary, elevation-span and zero-missing-entity checks. Proposed tolerances are
shown before execution; missing evidence, source-version mismatches and reported
errors above tolerance prevent acceptance. No source data or tooling means a
blocker, not permission to invent a replacement surface.

143 controlled tests passed across source contracts, routing, planning, native
integration, stage transitions and runtime review. Evidence:
`outputs/source-geometry-fix/`. Existing requests, selected artifacts and executed
assignments remain unchanged. Installed locally as 0.13.65 with app/database
backups and fresh Telegram, production, orchestrator and Messages heartbeats.
All 219 installed runtime files match source; 212 are unchanged from 0.13.64.
Installation evidence: `outputs/source-geometry-fix/app-update/`.
Not yet qualified with a live terrain run.
Intent classification and measurement truth remain model judgments; deterministic
DXF/native surface comparison is still needed to certify geometry independently.

### Host input aliases and execution-plan recovery — 0.13.64

Implemented: the planner compiler stages reserved host input aliases under
source-inputs/ before approval. Artifact identities, upstream output references,
script/check bytes and hashes, limits and approval boundaries remain exact.
Path bindings are recorded in plan provenance; collisions and traversal fail.
Plan execution now recovers a blocked saved proposal if it validates, preserving
the failed record and replacing only an unexecuted stage link. Repeated clicks
reuse that successor. Recovery makes no provider call and starts no worker.

Seventy-two controlled tests passed across host path binding, native inspection,
Rhino planning, generic planning, registered handoffs, stage recovery and status.
The reported saved proposal also validates read-only with its original sources.
No live provider, Rhino execution or messenger delivery is claimed by these checks.
Installed locally as 0.13.64 with fresh app-owned service heartbeats. All 217
runtime files match source; 213 are unchanged from 0.13.63. Only planner/status
logic and two version declarations changed. No public release was made.
Evidence: `outputs/host-input-paths/`.

### Planning metadata defaults — 0.13.63

Implemented: an omitted unused reference-pack field is normalized locally to null
only when no ready pack exists. All other action validation and explicit source
selection boundaries remain. Original responses and applied defaults are retained
atomically with dispatch; malformed/duplicate JSON is not repaired into an action.
Action-validation errors now report their actual reason rather than calling every
rejection invalid JSON. Forty-six controlled planning/routing tests passed. The
reported saved action validates with only this null default using full current
context; no live planning/model call or messenger send was made by the check.
Installed locally as 0.13.63; all 217 runtime files verified, with 213 unchanged
from 0.13.62, and fresh app-owned service health.
Evidence: `outputs/planning-null-reference/`.

### First-run production worker selection

Implemented in source: a fresh installation without a saved production policy or
previous run can select a verified file worker, preferring the conversation
provider. Exact configured models are frozen before planning; saved assignments
and explicit executor choices retain their existing boundaries. Missing workers
produce actionable connection-check guidance instead of an internal policy key.
Planning still requires the existing execution approval and does not start workers.

Controlled validation covers eight fresh-state cases plus affected planning,
worker composition, workflow recovery and desktop integrations: 99 distinct tests
passed across the recorded runs. Two integration cases required the project's
presentation environment because system Python lacks python-pptx. Commands,
results and limitations are under `outputs/first-run-planning/`.

Published as 0.13.60 beta from the public 0.13.54 baseline in an isolated release
checkout. The release passed 131 planning/updater integrations, 11 UI/website
checks and eight fresh-state cases using the bundled interpreter. All 209 bundled
runtime files match release source, and the signing certificate matches 0.13.54.
GitHub macOS/Linux release CI passed; installer, updater ZIP/manifest and matching
CLI source are published. Evidence is under `outputs/release-0.13.60/`.
No local service replacement or installation on the affected external Mac is claimed.

Subsequent local installation: 0.13.61 preserves the installed 0.13.59 features
and adds the same planning fix. Of 211 runtime files, 208 retain their exact prior
bytes; only the planner and two version declarations change. Fifty-five controlled
planning tests and eight bundled-runtime regressions pass. Local installation
completed with retained app/database backups, fresh app-owned Telegram/Messages
service health and app restart. Evidence is under `outputs/local-first-run-0.13.61/`.
This local build is separate from the published 0.13.60 baseline; no 0.13.61 public
release or external Mac qualification is claimed.

### S01 — shared native application contract and SketchUp

Implemented in source: Rhino, Blender and SketchUp share native profile metadata,
exact-code approvals and registered dispatch. SketchUp 2025/2026 on macOS adds
startup, exact `.skp` inspection and approved Ruby create/edit operations, with
separate baseline/save/reopen phases, bounded geometry checks, viewport preview,
independent review and explicit candidate selection. Process ownership, retained
receipts and uncertain-outcome recovery prevent automatic replay or attachment
to an existing user session. See [SketchUp scope and qualification](docs/sketchup.md).

Controlled integration checks passed. The local SketchUp 2026 startup check
reached the sign-in/subscription screen and timed out before Ruby startup.
Native create/edit/reopen/preview qualification remains blocked on activation;
Windows, textures, rendering and broad extension/model compatibility are deferred.
No installed-service reload, provider execution or message delivery is claimed.
Evidence and exact check commands are retained under `outputs/sketchup/`.

### Telegram album handoff — 0.13.62

Implemented: unassigned albums use unique local filenames in a shared folder,
coalesced receipts and a once-only exact caption request bound to that upload set.
A three-second quiet interval accommodates Telegram's separate album updates;
late members are reported without replaying or changing a dispatched request.
Partial failures and differing captions retain files and require clarification.
Production guides retain their explicit revision boundaries. Existing upload paths
and historical requests are unchanged. Controlled checks: 70 passed, including
atomic rollback, duplicate delivery, late files, failures and exact input hashes.
The first local album build was mistakenly numbered 0.13.60 after the separate
0.13.61 installation. Corrected build 0.13.62 retains the same runtime features
and first-run planning fix; the local installer now rejects version downgrades.
Installed 0.13.62 verified: 217 runtime files match, 215 unchanged from the album
build, fresh app-owned service health. Fifteen installer/first-run checks passed.
Correction evidence: `outputs/version-correction-0.13.62/`. Evidence: `outputs/telegram-albums/`. No live
caption/model dispatch test was run.

### Automatic source selection — 0.13.59

Implemented in source: shared availability-based defaults select browser discovery
for generic reference-photo requests when Browser use and a verified worker are
available, otherwise Commons. Routing, workflow interpretation and production
planning use the same policy. Instructions require preplanned alternate sites for
unrestricted browser searches, within the existing budgets. Explicit source,
licence and provider constraints take precedence; approved scopes are not expanded.
No new cross-operation retry loop or automatic replay of failed stages is implied.
Controlled checks: 110 passed. Installed locally as 0.13.59; all 211 runtime
files match and app-owned services reported fresh health. Evidence:
`outputs/automatic-image-sourcing/`.
Autonomous model/site choice and alternate-site success remain live-unqualified.

### Browser image discovery — 0.13.58

Implemented in source: browser workers export observed original image/publisher
references through reserved JSON grants. images.fetch downloads bounded public
JPEG/PNG candidates into the existing immutable ZIP handoff. Independent review
and exact downstream artifact versions are retained. Unknown reuse rights remain
unknown; no search API, thumbnail substitution or generated-photo fallback.
Controlled checks cover Gemini/OpenAI/Qwen tool contracts, stale/ref/grant checks,
private-address/redirect rejection and exact PPTX image-byte handoff. One live
Google Images result was exported through Relay's managed Chrome and downloaded
by the real registered executor. Evidence: `outputs/browser-image-sourcing/`.
Bing/DuckDuckGo and fully unattended model-driven discovery remain unqualified.
Installed locally as 0.13.58; all 210 runtime files match and app-owned services
reported fresh health. Existing decks and workflow selections were preserved.

### Photo search fallback — 0.13.57

Implemented: generic phrase-to-keyword fallback retains all query terms, short-name
phrase identity, optional explicit identity, source licences and independent review.
Two searches / two distinct candidate downloads stay within eight HTTP GETs per
subject, including redirects. Empty collections retain diagnostic bundles and fail
visibly; partial collections retain explicit omissions. No generated substitutes.
Controlled tests and live collector diagnostics are in `outputs/image-sourcing-fallback/`.
The unchanged six-query live check returned two metadata candidates versus zero
before; this does not establish visual suitability or complete seasonal coverage.
Installed locally as 0.13.57; all 209 runtime files match and app-owned services
reported fresh health. Existing workflow bundles and decks were not regenerated.

### Synchronous model service failures — 0.13.56

Implemented: received HTTP 503 errors on local-tool model endpoints are terminal
service failures, distinct from missing responses, unfinished code actions and
browser/media submissions. One bounded retry retains local drafts and tool history
inside the approved request/time limits. Persistent failure exposes its reason.
Legacy receipts can be interpreted without rewriting their original evidence;
stopped preparation can propose a successor preserving completed upstream work.
Workflow pause messages include the failed task and reason while machine recovery
codes remain stable. Controlled and copied-state evidence is in
`outputs/provider-unavailable/`; no content quality or provider uptime guarantee.
Installed locally as 0.13.56 with 209 runtime files verified and fresh app-owned
service health checks. The affected workflow has a ready presentation recovery
proposal; completed upstream steps and original provider evidence are retained.

### Registered workflow handoffs — 0.13.55

Implemented in source: single-output operations own their handoff media types;
downstream edges inherit the registered type before dispatch without another LLM
call. Image sourcing retains its ZIP (photos plus manifest) and direct independent
review. Explicit user formats and ambiguous multi-output mappings remain guarded.
Type-only recovery of the current blocked, unexecuted stage preserves completed
steps, original proposals and failure receipts; changed future edges are recorded,
and the recovered proposal requires Start. No operation is replayed by recovery.
Installed locally as 0.13.55; 209 packaged runtime files match the source and
app-owned services passed fresh health checks. The affected saved workflow was
recovered to a ready proposal without repeating research or provider calls.
Controlled tests and copied-state evidence are under `outputs/registered-handoffs/`.
This does not qualify future image identity, provider availability or slide content.

### Automatic website release discovery — 0.13.54

Implemented a shared server-side release resolver for website version labels, Mac
downloads, CLI source and checksum links. It includes complete published betas,
ignores drafts and incomplete asset sets, coalesces refreshes every five minutes
and retains the last valid release on GitHub failures. Legacy download routes
remain immutable. Five controlled website tests pass; publication verification
is recorded separately under `outputs/release-0.13.54/`.

### Native inspection after correction — 0.13.54

Rhino and Blender inspectors now receive only explicit model arguments; historical
native files remain evidence for reviewers. Missing or ambiguous model selections
still fail validation. This completes the corrected-script selection → execution
planning transition without weakening exact-version checks.

Controlled validation: 46 planning, stage, native handoff and review-correction
tests passed using small fixtures. A copied-state preflight recovered the saved
execution proposal with unchanged selected script/checks, one upstream inspection
model and preserved historical review evidence. No provider or native execution
was performed. Local 0.13.54 installation completed with fresh service health and
all 209 packaged source hashes matching. The linked recovered execution proposal
and its exact script/checks attachments were delivered; native execution awaits
Start. Evidence: `outputs/native-inspection-binding/`.

### Actionable native review corrections — 0.13.53

Registered native-operation reviews now retain a completed revision verdict and
block the unapproved candidate with its actual findings, without replaying native
execution or invalidating completed inspection evidence. Status and terminal cards
explain the next step and expose Plan correction for script-backed Rhino/Blender
candidates. That action proposes a bounded preparation/review pair using the exact
saved evidence, requires Start preparation, and retains the separate exact-code
Start before native execution. Existing affected review receipts are recognized
without edits; stale or uncertain execution cannot enter this recovery.

The Rhino contract now distinguishes input checks from the output verification
report, avoiding the schema mismatch produced by generic review instructions.
All 122 affected controlled tests passed; 14 status/recovery checks passed again
after the final wording adjustment. A copied-state preflight preserved the saved
model, review and inspection receipts with no provider/native calls. Local 0.13.53
installation completed with fresh service health and all 209 packaged source
hashes matching. The affected job now has a delivered correction-preparation card,
awaiting Start; corrected native geometry has not been executed or qualified.
Evidence: `outputs/review-correction-handoff/`.

### Uploaded references in production planning — 0.13.52

General chat uploads now have an explicit production source selector. Exact IDs,
bytes, hashes, captions and media types reach the author and independent reviewer;
clarification retains these sources. Images require a worker capable of inspecting
pixels, rather than treating Python binary-file access as visual understanding.
An explicit recovery can restore omitted uploads to an unstarted needs-input plan
from its saved request snapshot, preserving the original failure and request.
All 101 targeted controlled tests pass. Local 0.13.52 installation completed with
fresh service health and all 208 packaged source hashes matching. The saved photo
request was recovered with unchanged bytes and original receipt. Relay delivered
the new plan and started script preparation with the exact image; independent
review and native Rhino execution were not yet complete at this check.
Evidence: `outputs/upload-planning-handoff/`.

### Pre-dispatch stage rate-limit recovery — 0.13.51

The live trial completed research and native modeling, then received Gemini 429
while interpreting the visualization stage. Explicit continuation incorrectly
required an existing production plan. Recovery now classifies the phase before
retrying: a confirmed undispatched stage rejection queues one successor with the
same prompt, model/provider and frozen inputs. Failed records and completed stages
remain unchanged; retries require explicit continuation or the bound Retry stage
button. This does not add automatic retry or qualify general provider failover.

All 48 initial stage-setup/pipeline tests passed; a subsequent six-test retry
selection also passed, including added stale-button coverage (49 distinct tests).
A copied-state preflight preserved
the real selected model/preview and completed stages, with zero provider calls.
Evidence: `outputs/stage-rate-limit-recovery/`.
Local 0.13.51 deployment completed with fresh service health and all 208 source
hashes verified. The already-saved explicit continuation was recovered atomically;
Relay dispatched the new stage interpretation; it succeeded, and the image job
completed. Its candidate selection card was delivered. Presentation work still
awaits the declared image-selection gate; full workflow completion is not claimed.

### Script repair review allowance — 0.13.50

The live trial exposed a repair-policy gap: preparation inherited eight API
requests and allowed no revision after the first independent review. The rejected
candidate was byte-identical to the failed script and its diagnosis contained
placeholders. New versioned grants allow one bounded revision/re-review, explicit
request/response budgets, and unchanged-script/placeholder checks before host
planning. Normal code planning and automatic repairs share the budget helper.

Existing grants are preserved. A delivered preparation Start card can approve
extra bounded attempts for an exhausted repair review, retaining old assignments,
receipts, original checks and exact draft/review inputs. It resumes the same saved
workflow; corrected native code still needs its separate execution Start.
RhinoViewport camera API guidance is shared with author/reviewer contracts.

Twenty-five controlled repair tests pass, alongside 96 affected integration
checks. The initial combined run had one new fixture error (an oversized Gemini
tool allowance), corrected before the repair suite passed. Commands, results and
a read-only copied-state preflight are recorded in `outputs/script-repair-review/`.
These do not qualify live repaired geometry, provider success or later image/deck stages.

Local 0.13.50 installation completed with the app reopened and fresh Relay/Messages
service health. All 208 bundled source hashes match. No repair/provider/native
execution was dispatched during this update; the saved run awaits explicit
preparation recovery and subsequent exact-code native Start.

### Workflow contract audit — qualification gaps (2026-09-16)

Exact artifact identity and bounded operation contracts are implemented; arbitrary
cross-capability chains are not fully qualified. Declared whole-job type/capacity
preflight and concrete artifact binding are now implemented in development source
(see below). Semantic handoffs, large-document section assembly and unified structured
recovery eligibility need further work. The PPTX builder remains limited to 50 slides; a single 600-slide deck
has no qualified automatic batching/assembly path. Do not advertise unrestricted
workflow composition or scale based on individual tool availability.

The initial targeted contract audit passed 51 of 54 checks; three Rhino handoff tests failed
because preparation fixtures omitted current deferral declarations (two failures also
had a masked assertion error). Coverage was restored without weakening
execution/selection gates. Evidence and prioritized follow-up are recorded under
`outputs/workflow-contract-audit/`. That audit changed no live workflow. The fixture
failures are repaired and pass in the implementation checks below.

### Declared workflow handoffs — 0.13.48

New workflows declare each deliverable's type, upstream edges, companions and known
capacity requirements. A shared compiler checks the complete declared sequence
before workers start, then binds stage plans to exact selected artifact identities
and delivery requirements. Unknown sizes remain explicit and require later checks;
natural-language intent and semantic use still depend on interpretation/review.
Managed visualization consumes declared image versions rather than every prior image.
Concrete PPTX plans retain requested counts through pre-build and delivery checks.
Existing approved workflows keep their original contracts and execution gates.

Controlled tests cover research context → native-model/preview fixture → exact
visual reference → presentation handoffs, capacity/type/companion failures, actual
PPTX count rejection, clarification, and native preparation lineage. Rhino adapters
remain mocked in these checks. Evidence: `outputs/handoff-contracts/`; contract details:
[workflow handoffs](docs/workflow-handoffs.md). This increment does not add 600-slide
assembly, universal automatic repair, live semantic/fidelity qualification, or
Windows native execution qualification.

Local deployment: 0.13.48 is installed with all 207 bundled source files matching
the source inventory, application startup verified, and fresh Telegram/Messages
service health. Build, installer backup/receipt and source audit evidence are under
`outputs/handoff-contracts/deployment/`. No new live qualification workflow was
submitted by this update; the controlled and live qualification scopes remain separate.

### Workflow declaration correction — 0.13.49

A first live proposal declared managed output as JPEG and used a noncanonical
Rhino media type. Preflight correctly stopped dispatch but lacked a bounded
structural correction path. Complete type-invalid proposals now get one tool-free
correction using registered output contracts. Only media-type fields may change;
quantities, providers, instructions, decision gates and limits remain exact.
Explicit format requirements cannot be satisfied by relabeling. Preserve both
responses; second failures and uncertain calls stop without automatic replay.
Confirmed pre-dispatch rejections can use a validated, idempotent successor while
retaining the original request/error. Checks: `outputs/workflow-type-correction/`.
This corrects workflow declarations; it does not qualify downstream live execution.

Procedural planner contract follow-up: **implemented in development source**.
New stage proposals freeze a machine-readable response schema, use Gemini native
structured output and validate field shapes locally across providers before
compilation. The service owns locked worker configuration, records exact redundant
selectors and rejects conflicts. Corrections receive field paths; missing validator
execution capability is reported explicitly. Raw responses and legacy assignments
remain intact. Controlled-check evidence is under `outputs/planner-contract/`;
this does not establish deployment, live provider schema acceptance or model creation.

Local deployment follow-up: **0.13.77 installed and verified**. All 228 bundled
runtime files match the release-source inventory; the installed signature passes
strict verification, the app reopened, and Telegram/Messages health refreshed
after restart. The maintenance flow retained verified app/database backups and
the failed planning records remain unchanged. Evidence:
`outputs/planner-contract/deployment/`. No live provider schema request or model
execution was submitted as part of this update.

Local deployment is verified at 0.13.49 with 208 matching runtime files and fresh
service health. The confirmed live pre-dispatch rejection was recovered atomically
as a successor after copied-state validation, preserving its original request and
error. Research execution and later host/model/review stages require their own
receipts; recovering the plan is not completion of the cross-provider workflow.

### Registered builder planning boundaries — 0.13.47

Registered operations use their own frozen output contracts rather than an inherited
browser/text-agent file limit. Explicit optional source bindings receive the same
metadata compilation as required bindings, retaining artifact identities and aliases.
Validate against both saved and current operation bounds, with precise task/field
errors. Saved unexecuted proposals can recover without new model calls; changed
worker approvals remain required. Checks: `outputs/school-deck-recovery/`.

### Late-bound input and status audit — 0.13.46

Check actual upstream outputs and revision evidence again at dispatch, because they
do not exist at initial planning. Invalid sources block only their assigned task
without using an attempt; current assignment receipts expose the precise cause.
Unreadable or changed text artifacts no longer crash conversation status. Keep
original bytes and approved limits; correction, source scoping or user input may
still be required. Controlled checks: `outputs/input-boundary-audit/`. This does not
qualify live providers or websites and does not resume paused workflows.

### Worker input selection and setup recovery — 0.13.45

The Philadelphia workflow exposed a pre-planning source-catalog check that counted
a retained photo ZIP against a browser worker's text allowance. Enforce limits on
the actual per-worker bindings; preserve incompatible prior outputs in the workflow
catalog for later compatible stages. Keep explicit incompatible bindings rejected.
Surface the saved failure cause and support explicit local setup recovery from an
undispatched plan_production response, retaining original failures and exact sources.
No uncertain action or completed source stage is replayed. Controlled tests and
copied-state qualification are recorded under `outputs/stage-input-routing/`.

### Cross-layer alignment audit — 0.13.44

Correct four boundary gaps: retain selected image-bundle sources during deck edits;
reuse completed upstream work during exhausted-review recovery; keep older pending
completion handoffs visible; preserve approved legacy image procedures in a new
reviewable plan. Browser and review recovery now share completed-source retention.
Exact artifact identities, old attempts, independent review and Start boundaries
remain enforced. Controlled integration checks and limitations are recorded in
`outputs/alignment-audit/`. This is targeted qualification, not proof that every
provider, operating system and workflow combination has passed end to end.

### Workflow correction budgets and reference imagery — 0.13.43

Align pipeline validation with the registered local document correction graph.
Freeze its bounded authorization in new workflow receipts and keep older grants
unchanged; valid extended plans wait for exact Start rather than a false attempt
expansion blocker. Do not grant extra attempts to external or unrelated operations.
Route factual reference imagery to authentic source collection by default, with
explicit reference/synthetic intent and a generation guard for new workflow stages.
Semantic intent remains model-interpreted. Existing saved image stages are retained,
not retrospectively rewritten. Controlled checks and read-only saved-plan preflight
are recorded under `outputs/colorado-routing/`; no new live research/photo sourcing
or presentation completion is claimed.

### Image grids and stable styles — 0.13.42

Add an eighth layout, image_grid, with deterministic four/six-item pagination and
an explicit clean_minimal_v1 style. Preserve source order, image identity, editable
captions and attribution. Existing defaults remain unchanged; whole-image fitting
is the default, with optional native center cropping. Authors provide content lists,
not per-item geometry. Longer content and total-deck bounds fail explicitly rather
than silently losing data. Native master import and a template Settings UI remain
separate work. Controlled checks and a rendered preview using all 35 existing plant
photos are recorded under `outputs/image-grid/`; no live provider token-saving claim.

### Slide layouts and result handoffs — 0.13.41

Implement reusable named slide layouts and explicit brand/custom-layout data compiled
into editable objects. Preserve v1 specifications and independent review; no native
PowerPoint master import, font installation, or Settings template library is claimed.
Complete selected-output delivery through deterministic folder export and a deduplicated
completion handoff, including standalone plan recovery lineages. Display grouping never
changes workflow ownership or execution permission. Existing installations do not replay
historical completion notices. Typo interpretations remain visible with the exact original
message retained. Checks and deployment evidence: `outputs/templates-handoff/`.

The subsequent 0.13.40 live presentation completed and the user selected its PPTX.
Saved independent review reports 39 slides with the map and 35 sourced plant photos;
Codex verified the selected artifact's hash when exporting it. This establishes the
live production/selection path, not native Keynote or visual quality qualification.

### Task response budgets — locally installed 0.13.40

The subsequent live author again exhausted formatting recovery: both final tool
calls reached the fixed 4,096-token generation ceiling and ended mid-code.
Retry guards alone did not address this per-response limit. New Start plans now
freeze and display response_tokens (up to 16,384 for code authors, 4,096 for
reviewers), and Python argument bounds follow that approved allowance. Legacy
assignments retain their old limits. Checkpoints allow meaningful partial drafts
instead of requiring placeholder outputs. Repeated machine-added recovery
preambles are consolidated while retaining all exact historical inputs.
All 68 focused checks passed. A copied-state preflight verified the new author
allowance, unchanged request counts and exact saved-source continuity. Installation
completed with fresh service heartbeats and 204 matching runtime source hashes.
Evidence is under `outputs/response-budgets/`; subsequent live completion is recorded above.

### Compact edits and readable blockers — locally installed 0.13.39

The next attempt used 0.13.38 and recovered from its generation limit, but then
returned `MALFORMED_FUNCTION_CALL` while rewriting existing content into one large
code call. Local workers now use bounded incremental Python edits and compact
model-facing stdout, retaining full tool receipts. Generation length and malformed
calls each get at most one recovery within the unchanged request allowance.
Terminal/status cards separate task sections with blank lines and show a readable
blocker plus technical detail. Legacy generic failures can show their exact saved
provider finish reason without rewriting historical receipts. Evidence is under
`outputs/compact-worker-recovery/`. The copied-workflow preflight also caught a
repeated-recovery input-path collision; draft paths now include the originating
attempt ID so distinct historical versions remain addressable. Live deck
completion is still unqualified. Controlled worker/status checks (46), scheduler
integration checks (36), and updated lineage checks (12) passed. Installation
completed with fresh service heartbeats and 204 matching runtime source hashes.

### Incomplete generation and persistent draft progress — locally installed 0.13.38

The next live preparation stopped on a received Gemini `MAX_TOKENS` response.
It also resumed broad inspection after copying the baseline into draft outputs.
Local code workers now discard incomplete generations and may continue once
inside their existing request allowance, across supported API providers. Unknown
outcomes and safety refusals remain blockers. Draft checkpoints continue tracking
changed bytes after initial file creation; independent review still verifies
substantive completion. Explicit Continue can prepare a new Start for stopped
generation-limit attempts while retaining exact drafts and completed sources.
Controlled worker checks passed (the subprocess cancellation check required an
unsandboxed rerun); 26 recovery/integration checks passed. A copied-database
preflight verified the remaining four tasks and retained source identities.
Installation completed with fresh service heartbeats and all 204 runtime source
hashes matching. Evidence is under `outputs/generation-recovery/`; live deck
completion remains unqualified.

### Bounded document correction and authorized image omissions — locally installed 0.13.37

New Start proposals support a local document correction loop: specification review
can request one correction; a confirmed local PPTX failure or final review can
request one further correction and rebuild. Each version is independently reviewed,
with at most three specification attempts and two builds. All earlier artifacts,
reviews and failure receipts remain immutable. Existing plans keep their approved
allowances; browser, host and external API operations do not gain automatic replay.
Recovery now includes exact user feedback for author and reviewer. User-permitted
missing photos can be omitted while retaining the subject's research/text and a
summary of omissions. The 153 focused checks passed; six scheduler-only checks also
passed without optional presentation dependencies. The saved-workflow preflight
retains the exact user decision and completed map/photo sources. Installation
completed with fresh service health checks and 204 matching runtime source hashes.
Evidence is under `outputs/correction-loop/`; live model completion is not yet qualified.

### Preparation checkpoints and asset bindings — locally installed 0.13.36

The 20-request live continuation also failed: nineteen inspection calls produced
no draft. Text/script producers now enter an explicit draft checkpoint after
four inspection calls; ordinary Python validation resumes after files are saved.
Presentation authors/reviewers receive exact creator image and bundle bindings.
Exhausted local preparation can propose a new Start without resetting attempts,
repeating completed work, or increasing provider request limits. Selected original
deck images can be retained through verified creation provenance. This remains
bounded planned work, not general procedure extraction or inferred acceptance.
The 89 focused controlled checks passed, followed by targeted retention and Start
checks. The saved workflow preflight retains both map and photo deliverables with
four remaining tasks. Installation completed with fresh service health checks and
all 203 runtime source hashes matching. Evidence is recorded under
`outputs/preparation-checkpoint-repair/`; live deck completion is not yet verified.

### Preparation request budgets — locally installed 0.13.35

The live map and visual review completed. Slide preparation then exhausted an
independent eight-request cap after 24 seconds, without writing outputs. New code
plans freeze explicit request budgets within tool limits (maximum 24), and worker
prompts expose missing outputs and reserve writing/reporting requests. Explicit
Continue offers a bounded recovery using the remaining attempt and retaining all
completed dependencies. The saved workflow preflight uses 20 preparation requests
and 12 for each queued code review, without changing their time or tool limits.
Controlled tests passed; the installed app matched all 202 runtime sources and
passed fresh service health checks. Live preparation subsequently exhausted all
20 requests without outputs; the checkpoint and source-handoff repair is above.

### Screenshot visual review — locally installed 0.13.34

Live map capture now produced a readable PNG; the independent reviewer stopped
because the previous worker interface exposed only container metadata. Explicit
visual_inputs grants now attach selected PNG pixels to configured vision models,
while legacy scopes stay metadata-only. A delivered review Start card adds one
review attempt to the same saved graph without regenerating the candidate or
resetting old attempts. Controlled tests cover provider payloads, exact input
identity, no-navigation review, and stale/duplicate/undelivered Start controls.
The installed 0.13.34 app matches all 201 runtime sources and passed fresh
service health checks. The subsequent live visual review passed; slide preparation
then reached its request cap, addressed in 0.13.35 above.

### Managed Chrome startup and partial recovery — locally installed 0.13.33

A live launch published its connection after ten seconds, beyond the old eight-
second wait. The bounded wait is now 30 seconds with one process and a neutral tab.
Explicit Continue can propose unchanged-scope startup recovery and reuse completed
outputs/reviews by exact artifact identity, including completed deliverable records.
Controlled tests and a private copy of the failed workflow validate the six remaining
tasks without re-collecting photos. The installed app matches all 200 runtime
sources and passed fresh service health checks. Live map capture remains unverified.

### Saved browser session and operation input repair — locally installed 0.13.32

General browser scopes can explicitly select the same saved Chrome session as
Settings Browser use. Existing scopes are not silently migrated. Shared locking
and sign-in/off controls apply to both standalone and graph jobs. Planning exposes
that session; consent origins belong in proposed scopes, while challenges remain
manual. Photo collection uses literal subject parameters without implicit history
files, and known oversized operation inputs fail before Start. A bounded setup
recovery preserves confirmed read-only browser failures and pre-dispatch photo
failures in the old run; it proposes new session/origin settings for exact Start.
The installed app matches all 200 runtime sources and reports fresh service health.
The saved failed workflow has a delivered repair card using the Settings Chrome
session, the observed consent origin, and no history inputs for photo collection.
The subsequent photo collection and independent review completed. Map capture
failed before browser actions during Chrome startup; see the 0.13.33 repair above.

### Current capability visibility and screenshot handoff — locally installed 0.13.31

Large context summaries retain a bounded, complete current capability index when
the detailed catalogs are excerpted. Historical blocked-plan catalogs no longer
serve as the only visible evidence. Exact repeated requests can propose a new
unlocked, unexecuted plan when worker capabilities improve, preserving old
receipts and sources. Controlled context/routing tests cover the list-tail browser
regression and recovery without a conversation-model call or worker execution.
The live renewed request exposed omitted PNG/provenance types and old implicit
PPTX sources lacking MIME metadata. Version 0.13.31 compiles explicit capture
output types and excludes incompatible implicit browser inputs; the saved eight-
task response now validates without repeating its provider calls. The installed
0.13.31 runtime matches all 199 release files and reports fresh service health.
Relay recovered the saved proposal as ready and delivered its plan/source files
and Start card. Map capture and deck execution remain pending that Start.

### Browser eligibility recovery — locally installed 0.13.29

Browser model metadata stays valid for matching credentials, endpoint and model;
website login and origin/action permissions remain separate runtime checks. A
follow-up to blocked planning with no executable plan discovers available workers
in a new proposal, retaining the prior receipt and explicit executor locks.
Controlled tests cover aged verification, changed connections, absent runtimes,
failed checks and proposal recovery without dispatch. The installed build matches
all 199 runtime sources, reports fresh service health, and exposes the configured
Gemini browser worker as available. The saved blocked request remains intact; live
map capture remains a separate execution result.

### Sourced image handoff — locally installed 0.13.28

Generic image collection searches Commons using planned subject names and saves
bounded photo candidates with source, author, licence and hash receipts. Exact
reviewed bundles can feed PPTX creation, with credits retained in slide notes.
Independent review covers identity and gaps; metadata alone is not visual proof.
Missing images never silently become generated substitutes. Combined plans can
include the requested map service's browser viewport capture and exact PNG/provenance
handoff. New mixed scopes allow twelve tasks, preserving six for older scopes;
browser roles omit incompatible implicit document inputs. A controlled eight-task
photo/map/deck plan qualifies these edges; live autonomous Google Maps capture
is not qualified by that test. The final build is installed with all 199 runtime
files matching source and fresh messaging/service health. The browser metadata
expiry blocker observed in that build is addressed by the 0.13.29 work above.
Public release remains separate.
See [sourced-image handoff](docs/image-sourcing.md).

### Document worker selection and correction recovery — locally installed 0.13.27

Automatic roles prefer suitable configured API file/Python workers over a general
CLI shell; explicitly selected executors remain fixed. File/code verification is
credential/model-bound instead of expiring after fifteen minutes. New local
draft/review plans include one bounded correction, with visible attempt limits.
An exhausted mixed-graph draft review can propose a successor using exact saved
candidates and review receipts, with no old attempt reset or downstream replay.
PPTX preparation carries the creator’s actual stdlib schema validator. Structural
validation does not establish visual layout or Keynote compatibility.
The installed build completed a saved deck recovery with the configured Flash
API worker and local PPTX creator, retaining the selected image and prior attempts.
Independent review passed; the 26-slide deck imported into Keynote and its PDF
render was inspected, including the corrected table. Final user selection remains
pending. This qualifies this recovery case, not every document or provider; public
release of 0.13.27 remains separate.

### Package entry points and beta refresh — locally installed 0.13.26

Source launchers, child workers, installed services and tests use canonical package
calls. Root forwarding modules and their packaging entries are removed. The local
installer migrates legacy service commands with rollback records. App update
protocol 2 requires a one-time manual upgrade from older installers; subsequent
compatible updates retain Install and restart. Website downloads are versioned
alongside prior immutable assets and are fetched with pinned checksums during
the website build. The signed app is installed with 197 matching runtime files,
verified backups and fresh Telegram/Messages health. GitHub release checks passed;
publication and website deployment remain separately verified steps. Windows
native execution remains O12.

### App access settings and Windows CI correction — locally installed 0.13.25

Settings groups installed apps and tools, shows detected versions and paths, and
provides persistent family/installation switches. Discovery and new registered
operations honor disabled choices; exact approved code keeps its selected runtime.
Codex and Claude dispatch respect their controls. External agent OS permissions
and already running work are unchanged. Bundled Python/document tools default on,
qualify on first use, and preserve explicit Off or failed qualification.
Windows CI now separates POSIX grant fixtures from Windows fail-closed checks and
closes the usage fixture database. Native Windows file/code execution remains O12.
Controlled macOS integration, settings and native document checks pass; the app
was installed with verified backups and fresh messaging-service health. Windows
runner validation and a public release remain separate.

## Implemented foundations

| ID | Scope | Boundary |
| --- | --- | --- |
| O01 | Existing-task routing and explicit local Codex task creation | Preserves exact requests; new-task and first-turn receipts are separate. Connected creation remains unqualified. |
| O02 | Versioned reference collection | Immutable copies, hashes and source/version decisions; discovery is bounded and does not prove completeness. |
| O03 | Request-derived workflows and bounded production, with bundled starter catalog | Model-generated ordered workflows retain the full request and automatically advance through completed/selected stages. Exact host-code Start remains separate; live extraction/rollout qualification is pending. |
| O05 | Decisions and continuation | Exact file/set selection, pause/resume/cancel, status and bounded successor stages; saved workflows resume after selection without another prompt. Standalone stages retain existing controls. |
| O06 | Mixed execution | Codex/Gemini workers, registered text bundling and bounded Gemini text API operations share artifacts and receipts. |
| O07 | Shared-runtime evaluation | Bounded preparation/recovery coverage across three workflow types; no general efficiency or quality advantage established. |
| O04 | Second execution provider | Gemini declared UTF-8 file workers with fixed provider choice and bounded requests; shell/media execution is outside this worker profile. |
| O09 | Source boundaries and paths | Central resolver, explicit overrides and preserved data bindings; changing a path is not migration. |
| O10 | Python packaging | Runtime packages, CLI, tests and maintained assets have explicit distribution boundaries. Source launchers, services, workers and tests call the package directly; root forwarding modules are removed in development source. Legacy service definitions remain readable for explicit migration and recovery. Apache-2.0 license text and package metadata are included. |
| O11 | Host and access adapters | macOS lifecycle, POSIX process groups/locks, credential sources and file grants; shell workers retain their separately declared boundaries. |

O03–O07 have controlled planning, handoff, decision and recovery coverage. Live
acceptance remains specific to each provider, channel and platform. Historical
private trials do not establish general product acceptance.

O01 routing correction: fresh Telegram messages always reach the orchestrator;
old direct-task preferences and busy selected tasks cannot intercept them. Replies
retain their explicitly addressed task/workflow, and `/use` only selects command
targets. `/routing` and task/status confirmations expose the routing contract.
Controlled checks include the exact create-and-research path with a busy old task,
deduplicated creation/start, provider replies, approvals and Messages parity.
LLM interpretation remains responsible for choosing validated actions; this does
not introduce keyword-based task creation or prove live model selection quality.

### Request-derived workflow continuation — installed locally, live qualification open

The orchestrator can extract ordered stages, capabilities, deliverables and decision
boundaries from the initial request. A durable scheduler links real research, media
and production receipts, resumes after exact selections, freezes downstream source
versions and blocks uncertain work without replay. Ordinary bounded preparation can
start under the saved workflow scope; unknown native code still requires exact Start.
See [request-derived workflows](docs/request-derived-pipelines.md). This corrects the
manual transitions exposed by the architecture experiment. Version 0.13.4 is
installed locally with all 241 packaged runtime sources verified, fresh Telegram/
Messages health, and a reviewed four-table additive schema change preserving old
data. Sixty-five workflow/integration checks and 26 update checks passed. Existing
standalone trials were not converted; live end-to-end qualification remains open.
A subsequent live request exposed rejection of a numeric-leading stage ID. The
0.13.5 repair accepts such IDs without rewriting them and distinguishes workflow
validation from JSON-format errors; the saved five-stage response validates unchanged.
Version 0.13.5 is installed locally with 29 focused tests, 26 update checks, packaged
response validation and fresh service health verified. No failed workflow was replayed.
A subsequent modeling-stage trial exposed a host-group deferral gap. Version 0.13.6
retains related host operations for the later exact-input execution phase, adds
explicit saved-proposal recovery without resetting history or calling the provider,
and removes duplicate workflow result delivery. The local 0.13.6 build passed 69
focused tests and 26 update checks, with packaged runtime and service health verified.
The live blocked stage recovered its original valid proposal and resumed preparation
without repeating completed research or replacing its selected concept. Native
execution and full-pipeline acceptance remain open.
The 0.13.7 deadline revision removes the universal 10-minute planning ceiling.
Each proposed worker task has an independent approved wall-clock budget up to
30 minutes; existing plans and attempts are not edited. New workflow time grants
are frozen at creation, and longer legacy stages require exact plan approval.
A timeout still preserves unaccepted drafts and requires scoped recovery.
Version 0.13.7 is installed locally after 76 focused tests, 26 update tests and
packaged runtime/signature/service health verification. The house preparation
subsequently hit its original 10-minute deadline; its drafts remain unaccepted
and the workflow remains blocked pending recovery. No native model, visualization
or presentation was generated by this deadline update; full-pipeline acceptance
remains open.

## Current work and next steps

**0.13.24 local app checkpoint:** the combined procedure/discovery, worker,
document-runtime and browser screenshot additions are packaged and installed on
the existing Mac. All 252 packaged runtime files match source; native isolation
and document fixtures pass. Both messaging services reported fresh health after
the update. This establishes local installation/runtime readiness, not live
provider output quality, message delivery, a public release or Windows execution.

O03/O06 shared provider file/code workers are implemented in development source.
Gemini, OpenAI, Qwen, DeepSeek and OpenRouter can use a common declared-file loop;
qualified macOS Python workers also author and inspect binary documents/data with
the bundled libraries. Settings checks the runtime and provider connection without
requiring Docker or end-user package installation. Known code failures can be
corrected within task limits; uncertain outcomes preserve their receipt and stop.
Seven native qualification checks pass using the generated desktop interpreter,
including exact XLSX producer/reviewer handoff and owner-death cleanup. The shared
provider checks use scripted transports. Windows native code isolation, installed
app rollout, live provider qualification and a verified reel composition renderer
remain open. See [shared code workers](docs/shared-code-workers.md).

O03/O06 capability-driven workers are implemented in development source. Each new
planning scope captures eligible executor profiles; the planner can create role-
specific assignments with text, binary-file, local-code or scoped-browser needs.
Relay freezes the resolved model/tools per task and preserves those choices across
dispatch, restart and recovery. Explicit executor choice remains fixed; a different
worker backend requires stage approval before automatic workflow continuation.
The five starter definitions now use provider-neutral requirements. Composition
does not install missing integrations or qualify the reel renderer. See
[capability-driven workers](docs/capability-workers.md). Installer rollout and live
multi-provider qualification remain open.

A follow-up to 0.13.23 fixes planning successor handoffs in source. A retry had
updated the workflow target while leaving the completed preparation stage linked
to the failed plan, causing Start to reject the valid new card. The correction
verifies and moves both identities atomically, with history and rollback checks.
Forty-two controlled stage/pipeline tests pass. The affected live handoff is
repaired and its same approval card remains valid; no host operation was started.
The general code correction is not yet included in the installed 0.13.23 package.

Version 0.13.23 is installed locally: a user-requested retry can recover
confirmed Gemini planning rate-limit rejection without a saved proposal. It
retains the original failure, selected inputs, provider/model and preparation
lineage, creating a bounded successor while completed workflow steps stay intact.
A direct command and stale-safe Retry planning card avoid interpretation dependency.
Unknown submission outcomes and native execution approval boundaries are unchanged.
Thirty-four pipeline tests, 62 related checks, 28 exact-command integration checks
and four packaged regressions pass. The installed app has 245 matching runtime
files, the same identity, compatible data and fresh service heartbeats. Saved
workflow steps and the failed planning receipt are unchanged; live planning retry
has not been dispatched.

The 0.13.22 iMessage recovery fix is installed and its watcher is running. An uncertain
reply holds its remaining parts and controls without disabling new intake or
independent replies. Held exports do not consume the export batch; Channels
retains the warning while connected. Seventy focused controlled tests pass.
Existing migration fixture failures reproduce against installed 0.13.21. No
uncertain message was replayed or marked accepted. The user confirmed receiving
a fresh /ping reply after installation; no AI-provider or workflow run was tested.
Sixteen export/shared-storage checks and three packaged regressions pass. All
245 runtime files, matching signing identity, data compatibility and fresh service
heartbeats were checked after installation.

Version 0.13.21 fixes host/provider visibility: the orchestrator receives both
installed Rhino versions, distinct from its preferred runtime; Models by task
offers a Rhino version preference, visible disconnected media providers and
explicit image-model discovery. Existing approvals/defaults remain unchanged
until an explicit settings action. Sixty-seven focused Python tests and one
local UI fixture pass; the older provider busy-state fixture fails against both
source and installed 0.13.20. Version 0.13.21 is installed: all 245 runtime files,
signature, data compatibility, both Rhino versions and media menu choices are
verified. Relay service health is fresh. iMessage already required review of an
uncertain delivery before replacement; that state remains unchanged. No media
generation or Rhino operation was run to qualify this settings change.

CI follow-up: two older tests still expected hidden disconnected providers and
the previous OpenRouter discovery path. Updated expectations retain disconnected
default rejection and image filtering. The complete 145-test browser/media
selection passes locally; Linux CI confirmation remains separate.

Automatic script repair is installed locally in 0.13.20 with controlled qualification.
New workflows freeze a one-cycle-per-stage repair allowance: diagnose a confirmed
Rhino/Blender script failure, prepare a changed script, independently review it,
deliver the exact-code Start card, then rejoin the saved workflow after approval.
Original checks, execution limits, requests, attempts and output selections are
preserved. Repair artifacts join the workflow folder. Startup/environment and
uncertain failures remain stopped; prior workflows receive no implicit new
budget. Eighty-three focused tests pass, including an approved recovery followed
by the next workflow stage with exact selected files. This is a controlled test,
not live modeling or provider acceptance. The signed local package, all 244
runtime source hashes, reviewed one-table migration and fresh Relay/Messages
service health are verified. Existing records and prior workflow grants remain
preserved; installation dispatched no repair or modeling jobs. Public release
and live repair qualification remain open.

The 0.13.19 Rhino startup repair checks the selected app before launch, requires
an owned startup acknowledgment with a separate 60-second ceiling, and reports
missing worker responses without crashing failure reporting. Existing app
sessions remain untouched and failed attempts are not replayed. Fifty-three
focused operation/planning tests pass; three legacy handoff tests also fail
against unchanged 0.13.18 and are recorded as pre-existing. A real Rhino 8
startup diagnostic passed in 8.7 seconds with Rhino 7 left open. No modeling
script ran in that diagnostic. The verified 0.13.19 package is installed with
fresh service health and preserved prior receipts. Relay delivered the recovery
card and exact script/checks attachments; the new model attempt awaits Start.

Version 0.13.18 adds production activity visibility: current task, exact frozen
AI model or native executor, elapsed time, task limit, tool activity and reported
token usage. Unknown usage stays unknown; cache/reasoning fields are not added
to token totals. Task transitions produce one notice per attempt, while status
checks read progress without dispatch. Installed locally after controlled
worker/status checks (50), affected integration checks (74), telemetry-write
failure coverage, final activity checks (6), and update checks (26). Packaged
runtime/service verification passed, and installed model/token display matches
a recorded worker receipt. New provider progress remains qualified with local
fake-worker fixtures; telemetry cannot authorize or replay execution.

The 0.13.17 folder layout revision organizes results by saved workflow stage,
with readable selected files, producer/version drafts, reviews and support files.
It applies to native formats such as Rhino and Blender without prescribing a
pipeline. Existing exports move into this structure; internal receipts and
snapshots remain under `.relay/`. Version 0.13.17 is installed locally after 98
focused tests, 26 update tests and packaged runtime/service verification. All 65
existing workflow files moved with their hashes and file identities intact; no
workflow attempts, decisions or messages changed. This qualifies folder migration,
not new native generation.

The 0.13.16 workflow file view provides a stable local folder and index across
all stages and recorded recoveries. Paths appear in status/delivery messages;
inspection copies preserve exact source versions without changing acceptance or
dispatch. The installed build passed 94 focused tests, 26 update tests and
packaged runtime/service checks. The existing workflow and linked follow-up
export has no missing files; installed status and catalog expose the same folder.
Display-only follow-up ancestry confers no workflow execution authorization.

The 0.13.15 presentation compatibility repair addresses Keynote rejection of
decks with speaker notes. The bundled library omitted the presentation-level
notes master reference. A regression now rejects that defect before delivery.
The original rejection was reproduced in Keynote; a new copy changing only
the presentation XML imported with all 11 slides and speaker notes intact.
Version 0.13.15 is installed after 20 relevant presentation tests, 26 update tests
and packaged runtime/service verification. Earlier structural review did not
establish native-app import compatibility; the old delivery is retained unchanged
and the repaired copy is supplied separately without inferring user selection.

The 0.13.14 binding repair preserves declared operation paths, including image
names referenced by reviewed slide specifications. A local recovery reuses the
completed slide preparation/review and changes only the dropped input aliases.
A controlled build of the unchanged saved specification produced an 11-slide
PPTX that reopened with editable content and exact images. Version 0.13.14 is
installed after 106 relevant tests, 26 update tests and runtime/service checks.
The live recovery reused completed preparation/review with zero planning calls;
Relay created the 11-slide editable deck; independent structural review passed
and the deck/review were delivered. Final user selection remains pending.
Visual layout and Keynote import have not been tested; these results do not
constitute user acceptance of the full workflow.

The 0.13.13 routing repair separates stage context from operation inputs. Authors
and reviewers retain the selected model and all workflow sources; registered
operations receive compatible implicit sources according to their input contract.
The existing deck proposal can be recovered without re-planning or changing the
selected outputs. Version 0.13.13 is installed after 66 relevant checks, 26 update
tests and packaged runtime/service verification. The live four-task deck plan
was recovered with zero new planning calls and slide preparation started.
Presentation delivery remains pending.

The 0.13.12 handoff repair reconciles completed, reviewed/selected production
with a parent workflow that retained an earlier production blocker. It preserves
the original stage order, exact selected file set and attempts; next-stage queueing
remains atomic and unique. Paused/cancelled workflows and failed or uncertain
production remain stopped. Version 0.13.12 is installed after 54 focused tests,
26 update tests and packaged runtime/service verification. The live workflow
recorded the selected native model and generated its photorealistic visualization
through Gemini using the exact selected preview. The image and selection card
were delivered; the saved PPTX stage waits for image selection. No model attempts
were repeated.

The 0.13.11 scheduler repair addresses a review dependency deadlock after
successful native modeling. Registered inspections may read the unaccepted
candidate when their results feed its own reviewer; downstream production remains
gated. Validation detects cycles involving review completion. Explicit recovery
preserves the started plan, successful model and all attempts; paused/changed or
failed operations cannot resume through this path. Version 0.13.11 is installed
with package/service verification complete after 132 focused tests and 26 update
tests. The existing run resumed without changing its modeling attempt; native
inspection completed and the independent reviewer is running. Full-pipeline
delivery and the model selection decision remain pending.

The 0.13.10 verifier repair inventories hidden/locked Rhino geometry and hidden
references. A read-only native check of the existing saved model found all 128
objects, passed all 100 named-dimension checks and produced a preview without
changing the model hash or rerunning its script. This is verification evidence,
not acceptance of the prior failed attempt. Runtime-change recovery keeps the
same script/checks and requires a fresh assignment approval; repeated repairs
preserve distinct request paths. The local build is installed and service health
verified after 100 focused tests and 26 update tests. The recovery card and four
exact attachments were delivered and the user started the plan. Modeling passed;
the subsequent inspection/review deadlock is addressed by 0.13.11 above. Full
workflow presentation delivery remains open.

The 0.13.9 host-script repair adds receipt-backed recovery planning for a confirmed
failed Python operation: registered candidate script, unchanged old attempts,
completed dependency reuse, preserved review and exact new Start. Rhino failures
now surface their underlying exception. Native execution and repair planning retain
the workflow's model/preview selection set. This does not qualify a repaired script's
native geometry before its newly approved host execution.
The local 0.13.9 build passed 100 focused tests, 26 update tests, a saved-state
repair probe and complete packaged runtime/service verification. The live repair
card and corrected script/checks attachments were delivered; it proposes the three
unfinished tasks without repeating startup. The user subsequently started it;
modeling saved a candidate, but verification incorrectly omitted hidden objects.
The 0.13.10 repair above addresses that failure. Visualization and editable
presentation delivery remain pending.

The 0.13.8 continuation repair preserves workflow ownership across explicitly
registered preparation successors. It resolves original planning context through
their recorded ancestry and uses exact selected successor artifacts to plan pending
execution, without resetting failed attempts or automatically approving host code.
Ordinary file continuations can advance to their next saved stage. Paused/cancelled
workflows and unregistered or cross-channel successors are not resumed.
Installed locally after 87 focused tests, 26 update tests and packaged runtime and
service health verification. Live reconciliation retained the selected continuation
files and delivered one ready execution plan with all pending Rhino operations.
One provider structural correction was used; no failed production attempt was
replayed. Native execution is awaiting exact Start, and full workflow delivery
through visualization and editable presentation remains unqualified.

| Order | Milestone | Status | Completion gate |
| --- | --- | --- | --- |
| 1 | **O13 — installation and onboarding** | **In progress; prioritized for product onboarding** | Clean installation, channel/provider/project setup, interrupted-setup recovery, safe upgrades and explicit reversible data migration. |
| 2 | **O12 — native Windows/Linux qualification** | Windows 10+ foundation active by user priority | Native process ownership, locking, access enforcement, service recovery, an authorized provider text task and Telegram delivery on each host. |
| Active by user priority | O08 — reusable procedures | Extraction and history discovery implemented in development source | Discover repeated stage contracts, shared sequences, requests and failures with source evidence; promote completed exemplars into immutable reviewed procedures. Cross-project quality, standalone component contracts and benefit over a reusable-script baseline remain to qualify. |

### Status review — 2026-09-14

- Public GitHub beta: **0.13.0**. Working source: **0.13.3**, with uncommitted
  updater and other follow-up changes. Source, local installers and published
  releases must be tracked separately.
- A locally signed **0.13.1-beta.1 updater candidate** passed 76 Python tests,
  nine UI tests and native signature/package/database-copy checks. It has not
  been published, and this build did not exercise live replacement or recovery.
  It deliberately excludes the concurrent PDF/research and website changes.
- The later Settings cleanup leaves one App updates section and a separate
  Troubleshooting section. Its nine UI checks pass, but it is not in that DMG.
- **O13 remains active:** integrate the intended release scope, build from that
  exact source, qualify a real update/restart/recovery cycle and complete the
  clean-Mac setup/provider/Telegram acceptance path. Public signing/notarization
  remains open. Additional providers are not prerequisites.
- **P01 is complete — user-confirmed working on 2026-09-14.** The selected
  app-managed Chrome/Perplexity workflow is no longer an open milestone. This
  status records the user’s confirmation, not a new agent-run acceptance test.
  Next product integration: reuse the working research flow in a brief/PDF →
  research → editable presentation workflow; O13 remains the release priority.
- O12 Windows 10+ foundation remains active. O08 resumed by user priority using
  the repeated research → model → visualization → presentation cases. This first
  implementation saves completed Relay workflows as reviewed procedures with
  explicit variables, fresh run identity and existing gates/recovery. It does not
  record desktop demonstrations. See [scope and workflow audit](docs/reusable-procedures.md).
  Local `/opportunities` discovery now measures repetition, recorded outcomes,
  interventions and available planning usage, retaining immutable evidence for
  review. It never approves a repair or procedure. Shared-sequence promotion
  retains a complete exemplar until standalone input contracts are implemented;
  see [history discovery](docs/automation-opportunities.md).
  Cross-project live quality and measurable benefit over a reusable script remain
  qualification work; neither becomes an O13 release prerequisite.

## Current build: O13

**Browser screenshot capture — implemented in source.** General browser workers
can save explicitly granted viewport PNGs and provenance, register their exact
bytes, and supply PNG metadata to downstream browser reviewers. Planning and CLI
preparation expose the grants; old browser scopes grant no screenshot authority.
Local Chromium capture and controlled provider/collection/recovery checks exercise
the path. Visual reasoning, canvas interactions and installed-app/Google Maps
qualification remain open. See [browser screenshots](docs/general-browser.md#viewport-screenshots).

**Direct beta distribution and guided first launch.** The primary website route
is an Apple Silicon/macOS 14+ DMG; matching CLI source is secondary. Disk images
contain the app, Applications shortcut and beta instructions. Downloads use fixed,
versioned filenames with checksums and resumable transfer. Four saved setup steps
cover AI access, Telegram, explicit service start and pairing. Source/CLI and app
reuse the companion's explicit data binding; existing services retain their owner
until reviewed handoff. Public Developer ID/notarization and clean-host end-to-end
acceptance remain open; first-time Messages setup remains a separate pilot.

**Public website — deployed on Railway.** The hero leads with getting things done
with existing tools, connected jobs and user choices. Cross-tool examples and
version-change review precede the detailed programs/formats catalogue. The overview
explains connected briefs, files and decisions; examples name their intended outcomes
and highlight editable native outputs. A real case study awaits user-provided material.
Telegram is the starting interface; each next stage keeps its authorization boundary.
A public `/llms.txt` provides an overview
and curated documentation links for AI readers. The text-first page lists supported
programs and their input/saved file formats, including implemented editable PPTX
generation. The media program entry names Gemini, Veo, Runway and Higgsfield. A specific beta.1 download notice distinguishes package contents from
implemented support; other document exports remain worker-dependent. Five development
workflow examples retain their version boundary. macOS links to the beta DMG and
matching CLI source; Windows remains unavailable. The existing desktop logo is
used throughout. Public signing and installation acceptance retain their release
gates. See [website setup](website/README.md).

**Practical workflow guides — source implemented; publication open.** Five
capability-audited guides cover site research decks, precise Rhino model revisions,
named-view rendering, Blender asset handoffs and editable design presentations.
Each ties a reported problem to required inputs, current operations and limits.
The bundled 0.13.24 audit is distinguished from the public 0.13.0-beta.1 download
and from full live workflow qualification. Earlier invoice/CSV/complaint recipes
remain accessible as noindex archives, outside the current hub and sitemap.
The sourced Barcelona deck and original request retain their versions; the
revised request has a separate v2 URL. The website route/download check covers
the current collection and archived links. Full installed Relay execution of
these prompts and website publication remain open; this work does not close O13.

Implemented: a source installer with a dedicated environment and interrupted-install
retry; guided local API-provider/model, Telegram and first-project setup; saved
credential/pairing retention; and local diagnostics independent of Codex desktop.
The installer refuses unrelated environments and changed-source upgrades. Setup
prints a first-task command; it does not dispatch a task or infer live acceptance.
See [onboarding](docs/onboarding.md).

Implemented next: explicit stable-release installation in a separate environment,
owned Telegram service switching with a startup gate, compatible-code rollback
that retains newer history, and recovery receipts. Daily release checks produce
at-most-once Telegram notices and can be disabled. The release workflow prepares
reviewable draft releases. Controlled macOS fixture-service checks cover successful
switch, rollback and failed-start restoration; Linux adapter checks remain controlled.
See [updates](docs/updates.md) for the conservative compatibility boundary.

Implemented migration slice: explicit plans for additive SQLite schema changes,
application bound to reviewed code/schema/path identities, atomic migration receipts,
and guarded reversal that preserves newer records. Recovery distinguishes committed
from uncommitted migrations. Populated added fields/tables block reversal; arbitrary
record rewrites, destructive conversions and cross-database consolidation need their
own explicit transformations. Channel-storage consolidation has a separate
offline scope.

**Desktop launcher — implemented controlled setup slice.** The source installer
opens a loopback HTML page with project information, public source download,
step-by-step project/provider/Telegram setup, installed version and cached update
status, local diagnostics and detected tool availability. It uses the existing
blue-on-white logo and explains that the installer installs required Python packages
after the host supplies Python 3.11+; optional application runtimes remain separate.
The direct-open HTML page gives a static install guide; macOS `Setup.command`
locates its source folder, runs the installer and preserves errors for retry without
typed terminal commands. Live status appears only after the local server responds.
Settings are saved per step and can be resumed after interruption. Provider catalog
and bot identity checks run only on explicit form submission; no task, message or
update install is triggered by page load. Windows retains read-only status until its native setup
adapter is qualified. Controlled checks do not establish live provider generation,
Telegram delivery or background-service acceptance.

**Minimal companion — user-selected product direction; controlled implementation.**
Settings now show configured folders and the actual permission limits. This is
visibility only; enforcing an allowlist across connected tools remains open. Usage
loads only when expanded, with cleanup kept under troubleshooting.

The desktop is now a menu-bar companion for setup, status, connections, settings
and focused local decisions. Messenger is the primary work surface. The companion
uses the existing Messages Relay transparent template menu-bar icon. The packaged
UI no longer exposes Jobs/Tasks, workflow libraries, tool catalogs, a conversation
composer or startup usage/storage panels. Existing records and backend operations
remain intact. The source installer's loopback page remains supported. A command
palette is deferred until repeated local capture work justifies another entry point.
Runtime restaging clears retired generated sources; unused platform icon exports
are removed from the macOS pilot. Active standalone helpers remain required until
a successful reviewed handoff verifies their bundled replacement.

**Shared channel controls — implemented; existing-install deployment observed.** Channels exposes
Telegram and Messages switches, a global messaging pause and a separate proactive
release-notice destination. Intake and transport check the shared, revisioned
policy. Paused channels retain queued replies at their original destination;
resuming does not replay old requests or uncertain sends. Telegram drains its
first callback batch after resume because clicks have no reliable timestamp.
The UI requires fresh intake/delivery acknowledgement before reporting controls
as active. Reviewed Telegram and Messages handoffs have now completed on the
existing macOS installation, with fresh healthy bundled services and both intake
and delivery acknowledgements. Live pause/resume transport behavior remains
unqualified; adding WhatsApp, Slack or Discord adapters remains deferred.

The companion runs optional Messages through its main executable. Existing Relay and
Messages services are preserved until an explicit reviewed handoff: exact service
and runtime identities, in-flight-work checks, unload before replacement, a fresh
startup heartbeat, prior-definition restoration, and durable interruption receipts.
Data and pairing remain in place. First-time Messages enrollment retains the
text-only pilot setup; the merger does not claim channel parity or permission
transfer. The companion itself is not yet registered as a login item.

The superseded multi-tab workspace remains part of implementation history, not the
current product acceptance target. Its task/plan/usage APIs remain available to
existing integrations. Exact local approvals remain an on-demand exception view;
production selections remain in the supported messenger channel.

Desktop Settings now exposes only the app updater described below. Cached stable
source-package metadata and its checker are no longer shown in the companion;
source installation tools retain their own update path.

Local identity/update repair: Messages uses the main app executable, local builds
retain a signing certificate, and local maintenance replaces Contents while keeping
the installed app root. Recovery copies are verified ZIPs outside Applications.
The older ad hoc identity may require a one-time Full Disk Access refresh. These
changes do not establish Developer ID signing, notarization or clean-host grants.
The existing installation was updated with its app root preserved, old runnable
backups archived, and fresh Telegram/Messages heartbeats observed after inspection.
Controlled checks passed: 57 Python tests and one native service test. Live phone
delivery and permission continuity across a subsequent update remain unqualified.

**Next O13 work: finish the macOS app and qualify it as an installation path.**
Keep the source installer supported while these gates are completed in order:

| Gate | Status | Reviewable completion |
| --- | --- | --- |
| 1. Minimal companion | Installed local QA; menu-bar check open | Compact setup/status/settings, one menu-bar instance, close-to-hide, messenger opening and on-demand exact decisions. No second task inbox, workflow catalog or startup storage scan. Controlled read-isolation and approval checks pass. Installed native status reads the running Relay and connected channels. Closing and reopening from Finder retains the same companion process; the installed signature passes local verification. Direct menu-bar interaction remains unverified because UI inspection times out. Refreshing the existing macOS Full Disk Access grant restored native status reads; clean-host permission setup remains open. |
| 2. Install and service handoff | Existing-install handoffs passed; clean-host qualification open | Reviewed Telegram and Messages handoffs completed with fresh startup evidence and healthy desktop-owned services after permission refresh. Failed earlier starts restored the prior service; the retired standalone helper was removed only after verified replacement. Data and pairing were retained. Controlled tests cover changed identities, in-flight work, interruption, stopped-service preservation and rollback. The installed bundled bridge also passes isolated fresh-status and saved-setup resume checks; this is not a clean-host GUI installation. Existing services are never automatically adopted. |
| 3. Packaged updates | App flow implemented; deployment qualification open | Source update plan/apply/rollback/recover refuse the bundled runtime or matching companion-owned installation before downloads or state changes. Bundled startup ignores old source-release redirection; notices distinguish source releases from app updates. App metadata checks, beta opt-in, verified download, Install and restart, detached helper, exact approval, unchanged-data probes and explicit recovery are implemented with controlled fixtures. Dedicated ZIP/manifest assets are required. Published 0.13.0 requires a manual bootstrap upgrade. Developer ID signing/notarization, clean-host update/recovery and permission continuity remain distribution gates. Schema-changing updates require a separate reviewed migration. Source-update commands do not update the app bundle. |
| 4. End-to-end acceptance | Open | On a clean supported Mac, verify interrupted setup, messenger pairing, closing/reopening the companion, service restart, an explicitly authorized provider task, an exact decision and actual messenger output delivery. Record each observed receipt separately; controlled tests do not satisfy live delivery. |

Immediate remaining work: directly exercise the native menu bar, qualify clean-host
setup/permissions and qualify the implemented packaged update path described in the
[desktop release plan](desktop/README.md#packaged-release-implementation-order).
Installed local ad hoc signature checks do not qualify public distribution.

Earlier installed workspace/usage screenshots qualify only the superseded UI. They
do not qualify companion startup, service adoption or messenger task delivery.

Windows/Linux desktop packages and native service qualification remain O12 work
after the macOS O13 path is proven.

Native Linux service switching, separate Messages deployment updates, fresh-install
provider execution and Telegram delivery remain open qualification or adapter work.
Controlled migration checks do not establish those gates. O13 remains incomplete.

### Shared database consolidation — implemented

All channel records now use the main `state.sqlite`: Messages pairing/delivery has
namespaced tables, and direct Gemini requests use the shared provider queue and
worker. An offline migration preserves records atomically, checks backups, retains
channel ownership, prevents duplicate usage counts and archives retired stores.
Uncertain work is preserved without replay; unknown tables or conflicting identities
stop the import. Controlled migration and delivery recovery checks cover this scope.
This is a targeted offline storage migration. O13 release updates and additive-schema
migration are implemented separately; a combined release needs its own migration
plan and live acceptance.

### Storage cleanup and large approvals — implemented

- `cleanup plan` lists regenerable caches and verified duplicate retired database
  copies; `cleanup apply` removes only the listed unchanged files and saves receipts.
  Generated build cleanup is opt-in. Source, projects, artifacts and unique backups
  are excluded. General artifact retention and backup expiry require a separate
  reference-aware policy; age alone never establishes that a file is unused.
- Large file-change approvals use a full text attachment and one compact card.
  Granting requires successful document delivery and an unchanged pending request.
  This does not expand Messages approvals or automatically grant any permission.

### Bounded conversation context — implemented

An oversized project/workflow history no longer blocks the model before it can
read the user's message. Initial overviews are bounded to 160 KB of UTF-8 JSON;
marked excerpts and list tails can be inspected through paginated `context_read`
against the same captured evidence. Exact user requests, worker contracts and
revision checks remain unchanged. Reads share the existing per-turn tool budget.
This does not automatically replay failed messages or accept incomplete evidence.
At the read limit, the final answer turn removes tool declarations and restores
Gemini JSON response mode. Providers that still request reads receive an explicit
research-limit error rather than a misleading request-interpretation failure.
The completed read journal and original request remain preserved. Controlled
coverage: 43 file-conversation, answer-recovery and chat tests pass. Direct `pdf_read` now extracts version-bound PDF page text in the same scoped
file-tool path, with continuation cursors and explicit empty-page/OCR limitations.
The actual 29-page local competition brief was read in four calls. PDF/file/tool
integration checks pass (83 controlled tests); encrypted, malformed, oversized,
changed-source and timeout cases retain explicit failure behavior. The local macOS
app includes the reader; installed source hashes and fresh Telegram/Messages
service health were verified. Live model choice of the tool is not established
by the controlled tests.

### O01 routing follow-through — implemented correction

Work requests and contextual continuations are LLM decisions: select a suitable
existing destination, use the relevant workflow, or ask where to run the work.
When a routing response omits source selections, one model correction can select
exact files, explicitly exclude unrelated files, or ask a source question. It
cannot change the destination or prior choices. No task is dispatched until the
whole action validates; interrupted submissions remain uncertain without replay.
Controlled routing tests cover these boundaries; live model intent recognition
and launcher live acceptance are not established by those tests.

### O01/O03 requested extension — implemented, controlled validation

Relay can queue a new Codex task in a known local project through the supported
app-server control protocol. Creation-only and creation plus the exact original
request have separate durable boundaries. A saved ID survives later failures;
uncertain calls are never replayed. Model and permission settings are inherited;
worktrees, remote creation, sidebar project reassignment and model overrides are
outside this adapter. Creation now performs a full history read on the creating
connection before desktop handoff: installed Codex defers empty rollout writes
until that read. Isolated checks with the installed binary reproduced the missing
history and verified materialization without model runs. Thirty-eight focused
creation/handoff tests pass, including deferred persistence, mismatched history,
read failure, interruption and inactive-window activation. The creating connection
closes before desktop handoff. macOS activates Codex only when owner discovery
fails. A supervised live recovery verified saved history, desktop ownership and
one confirmed research-turn submission. This recovery needed manual activation
before the activation fix; it does not claim a fresh fully automatic channel run.

Five bundled starters cover research/report, architecture/presentation, native
model revision, carousel/reel, and data/presentation. CLI and messenger catalogs
show tools, inputs, outputs and review points. A selected stage and exact catalog
definition are frozen into planning; revisions retain that version. Templates do
not install missing integrations or authorize later stages. Native Keynote/Slides
and environment-specific media tooling remain explicit qualification gaps.
See [project tasks and starter workflows](docs/project-tasks-and-starters.md).

## O12 remaining platform work

**Compatibility target: Windows 10 and later.** Shared workflow, provider and UI
code remains common; native mechanisms stay behind host adapters. The first
source implementation adds atomic Job Object worker containment, descendant
cancellation, supervisor recovery by process birth identity and exclusive file
locks. Every launch freezes the native support bytes. Native Windows tests now
cover these mechanisms in the CI profile; they have not run on this development
Mac and are not evidence of Windows execution support.

**Next implementation: junction/reparse-point file grants and credential ACL
enforcement, then per-user background startup.** Extend qualification to an
installed text task as these mechanisms become available. Windows 10 and Windows
11 desktop runs remain separate release gates; Windows Server CI cannot replace
them. Installer, browser and native modeling integration checks follow the core
runtime. Do not require users to run terminal setup commands in the desktop app.

Linux has controlled native text-runtime, cancellation, access and installed-wheel
coverage. Its optional systemd user-service adapter preserves a foreground path for
hosts without a user manager. Native service activation remains an open gate.
Earlier Windows installed imports and explicit unavailable-operation checks pass;
the new process implementation remains natively unqualified. Complete Windows
execution remains unsupported. A green boundary check does not qualify execution.
See [native qualification](docs/native-qualification.md).

For each native host, verify restart without duplicate submission, descendant
cancellation, permitted-folder operations and denial of ungranted access. Record
OS/runtime/provider evidence, including uncertainty. macOS checks and mocks do not
qualify another operating system. Provider calls and live messages require their
own authorization; roadmap entries do not grant it.

## Additional implemented capabilities

**R01 — direct Rhino integration; Rhino 7 and Rhino 8 locally qualified on macOS.**

PR integration checks now cover reuse of detected application records: adding
catalog context leaves those records unchanged and cannot create circular planning
JSON. The affected Rhino planning and failure-repair fixtures pass.

Drawing handoff correction: prepared script bounds are now enforced before review,
with the same check at host approval. Named-view previews support face-on CAD
drawings. Preparation status lists pending deliverables, and **Plan execution**
queues the remaining scope after exact selection without starting the host. The
focused Rhino, preparation, selection/stage and shared Blender-host checks pass
(109 controlled tests; 35 focused checks rerun after the Rhino 8 shutdown fix).
The installed macOS runtime completed a separate authorized facade recovery:
three Rhino 8.35 phases exited cleanly, 1,529 objects passed reopen checks, an
independent reviewer accepted the readable four-elevation candidate, and Telegram
delivery records confirm the native file and preview were sent. User selection
remains pending. Prior script versions, reviews and failed attempts remain
preserved. This supervised recovery does not qualify every conversational plan.
Registered startup, exact `.3dm` inspection, interpreter-specific approved modeling
and built-in Rhino Render share production planning, exact artifact versions,
atomic approval and review/selection. The macOS adapter supports explicit 7/8
selection, IronPython 2.7/CPython 3 launch paths and version-bound grants; it checks
runtime/implementation again between phases. Each phase owns a separate process.

Rhino 7.32 and Rhino 8.35 each passed a continuous saved-project chain: four native versions, three
revisions, repeated inspection, three actual renders from two named views, and a
rejected undeclared edit followed by recovery from the last good version. Earlier
versions remained unchanged across Relay restarts. This exposed and fixed
named-view inspection and unstable native material archive comparisons. Native
material property checks replace transient archive hashes; arbitrary plugin
material graphs remain outside the preservation contract. Rhino 7 qualification
also exposed a Mono shutdown crash and a save-changes prompt. The macOS adapter
now exits owned workers after closing outputs and the result receipt, without
managed finalizers or UI save prompts. Clean exit codes and matching successful
worker receipts remain required. The 13-stage Rhino 7 run and retained-file audit
passed, including actual V7 native files and both final camera renders.
The local service was subsequently reloaded after an orchestrator response exposed
a stale capability registry. Its heartbeat now identifies the process and loaded
operation IDs; all four Rhino registrations were verified in the running worker.
This service check did not submit a live planner prompt or replay the request.
R01 preparation handoff subsequently exposed a missing worker schema: the planner
had the Rhino catalog, but script authors did not. Rhino modeling and render
preparation now freeze contract/validator files into both workers' inputs.
Controlled dispatch checks validate the copied support files and reject malformed
draft checks; this does not establish a successful live tower production.
The subsequent handoff qualification covers a blocked preparation, new recovery
stage, explicit script/checks/manifest set selection, native modeling, render
review and preview/original delivery through controlled channel adapters. The
host phases passed in real Rhino 7.32 and 8.35; Rhino 8 created and rendered the
repaired twisting tower. Missing/tampered members, restart/rollback and unchanged
old attempts are covered. Selected artifact IDs now prevent historical identical
scripts from becoming duplicate host inputs. Render preparation requires a named
camera, with optional required-view checks on independent reopen. Blender Python,
asset and animation preparation also receive frozen schemas and validators.
Live provider judgment and actual channel transmission remain unqualified.
See [Rhino](docs/rhino.md) for limits and reproducible commands.

Grasshopper definitions, scripts, component execution and authoring remain paused.
This does not close O13, qualify other operating systems, run a long-duration soak
test, or establish live planner judgment/channel delivery.

**Editable PPTX creation — implemented in source.** The local `pptx.create`
operation and `presentation create` CLI build native editable text, shapes,
tables, charts and selected images from bounded slide JSON. Planning freezes the
schema and requires specification review, actual-deck review and candidate
selection. Reopen checks preserve source/output identities; runtime dependencies
are declared for installation and desktop rebuilding. Controlled qualification
covers creation, rejection, restart and the supervised worker: 37 focused and
affected integration tests pass. A three-slide
synthetic deck was also rendered with LibreOffice and visually inspected.
Installed-app deployment, live model planning and Keynote import remain unqualified.
PDF/previews need a separate renderer of the actual PPTX. See
[PPTX creation](docs/presentations.md).

**Architecture competition pipeline — proposed live benchmark.** User-prioritized
integration qualification: Perplexity research → concepts → Blender model → one
bounded revision → final imagery → editable presentation → channel delivery.
The [benchmark specification](docs/architecture-pipeline-benchmark.md) defines
version/geometry/source checks and bounded scope. First delivery target is
PowerPoint; native Keynote/Google Slides are subsequent qualifications. Actual
brief, account availability and execution budgets must be frozen before live work.
No live end-to-end architecture benchmark is claimed. P01 is user-confirmed
complete; passing its research artifacts into this pipeline and completing the
presentation handoff remain integration work.

**Media-to-CAD routing and image operations — implemented, controlled qualification.**
Ordinary Gemini image replies now reach the LLM intent router with exact media
versions; confirmed image edits keep their native task/history. Generated media
can be frozen into Rhino planning or other handoffs without re-uploading it.
Image history exceeding the local request cap uses a recorded new-context handoff
with exact prior requests, visible responses and latest pixels; original native
responses/signatures remain unchanged. Image/video download names include the
task and job version. Registered `gemini.image` and `openai.image` operations
support dependent previews, frozen models, independent review and selection;
planning rejects omission of a selected image operation. OpenAI's image default
is configured separately from its text model through `/providers`.
See [media workflows](docs/media-workflows.md) for bounds and qualification.
Desktop capability defaults are implemented with controlled qualification:
Settings → Models by task reuses provider connections for conversation, images
video clips and Meshy 3D assets. Versioned atomic preferences reach existing adapters and
the intent router; explicit selections and frozen work take precedence. A shared
read-only generation status view retains original job/attempt and artifact IDs,
including uncertain state and pending review. Runway and Higgsfield image/video
adapters and Meshy text-to-untextured-GLB generation are implemented with controlled
qualification, independent review and candidate selection. One generation POST
retains its remote task identity for polling; uncertain submissions never replay.
Settings includes their API connections; Browser use shares the channel switch
style. Blender/Rhino modeling uses its existing application workflows.
Live compound planner/provider/Rhino/channel acceptance remains open. A general
project-level media-profile preference hierarchy, additional provider models,
Meshy texturing/image-to-3D and Gemini graph video generation remain pending; existing Gemini/Veo video commands
retain their configured model. Text credentials alone never establish media support.
Shared handoff follow-up implemented in source: all selected operations require
coverage or explicit exact-input preparation deferral. Declared deliverables map
to actual independently reviewed output paths, retained in the frozen plan; older
planning envelopes remain readable. The LLM is instructed to enumerate every new
requested deliverable. This validates its declared interpretation, not whether it
understood every phrase correctly; cross-domain live selection qualification remains open.
One context archive/projection contract now serves Gemini text/image and direct
OpenAI/Qwen/DeepSeek/OpenRouter text conversations. Text agents retrieve omitted
responses through bounded hash-checked context_read. Exact user requests stay
visible, native records stay untouched, and active tool exchanges are not spliced.
OpenRouter images joins the shared image execution path with a separately discovered
image catalog/default and no provider fallback. More provider wire formats and
video adapters require their own implementation and qualification. Live Runway,
Higgsfield and Meshy account/generation qualification remains open.
Packaged image execution includes the hash-pinned decoder and checks availability
before external submission. Task Relay runs Messages through its main executable and identity; permission
guidance targets Task Relay.app. The nested Messages bundle is retired.

Production-to-image reuse is implemented: the orchestrator can select exact
generated image artifacts directly for Gemini image requests, including `/image`
on production replies. Hash verification and request-owned copies preserve the
selected version; no production acceptance is implied. Descriptive download names
include the job, step and artifact version. Controlled tests cover actual request
bytes, stale/type-invalid sources, duplicate dispatch and reply context; this
change has not launched a paid image generation or tested live image delivery.

Blender pipeline qualification is implemented; run
`python3 scripts/qualify_blender.py --host` before qualifying changes across its
planning, execution, review and delivery paths. The September 12 check passed 148
controlled tests and eight real-host scenarios across the final recorded runs,
covering all seven registered operations. It found and fixed a false preservation
failure caused by unused materials disappearing on save/reopen. Planner/reviewer
responses and channel transport are deterministic fixtures; live model judgment,
network delivery and other operating systems remain separate qualifications.
See [coverage and commands](docs/blender-qualification.md).

Intermediate-review scheduling recovery is implemented: exact grant/epoch checks
allow selection to resume remaining tasks in the approved graph. Legacy stuck
reviews have an explicit guarded resume action and status button. Plans, task
attempts and source selections are preserved; no new stage or retry is implied.

Prior-output revision planning now has an explicit source decision: the planner
can select immutable candidates omitted upstream, and modifications must declare
their baseline as a producing-step input. Preapproval and Start checks validate
selected hashes; reviewers receive the same versions. Controlled handoff and
clarification tests cover this slice. Semantic identification of "it" remains an
LLM decision; ambiguous/missing baselines require a question, not a worker run.

Blender scene-data workers now receive frozen operation contracts and a standalone
standard-library validator, with explicit separation from the subsequent host
execution. Controlled fresh-workspace tests verify both primitive and mesh data
handoffs without Blender startup. The connected host qualification now covers
producer-to-host generation, native output delivery and a rendered height revision;
previously blocked assignments remain unchanged.

Blender planning now completes fixed operation metadata before approval: registered
output types, unambiguous upstream scene JSON types, direct file dependencies and
the fixed operation invocation budget. Explicit conflicts remain blocked. Controlled
planning regression checks cover missing metadata without launching Blender; this
does not establish live tower generation or automatically retry stopped plans.

| ID / feature | Scope | Remaining boundary |
| --- | --- | --- |
| B01 | Registered Blender scene inspection | Exact input identity and read-only inspection; unfamiliar embedded/external behavior requires explicit handling. |
| B02 | Candidate scene edits | Exact script/input/output authorization, execution receipts and independent reopen/checks; review alone is not a sandbox. |
| B03 | Asset bundles | Versioned imports, dependency checks and native bundle receipts; no implicit external downloads. |
| B04 | Bounded animation/rendering | Registered scripts, scene versions, frames, limits and recovery; additional animation modes need their own qualification. |
| A01 | Artifact dependency inspection | Versions and downstream relationships are recorded; inspection does not authorize regeneration. |
| A02 | Scoped artifact replacement | Exact selections and impact precede a replacement decision; prior versions and executed assignments remain immutable. |
| Usage tracking | Local Codex/Claude logs and recorded Relay calls | Missing usage is explicit; this is not account-wide billing or subscription quota. |
| Apple Messages | Optional macOS text integration | Separate pairing/history and a smaller feature set than Telegram. |

## Account-browser pilot

**Current status: P01 complete, confirmed by the user on 2026-09-14.** The
implementation and trial notes below retain their original evidence boundaries.
Earlier “completion open” statements describe those historical trials and are
superseded for P01 milestone status by this confirmation. P02 remains separate.

**Research-query handoff — installed locally; controlled checks passed.**
The orchestrator prepares a scope-preserving research question for the website,
removing Relay/browser instructions. The original message stays unchanged in
request history; the separate query is frozen in the execution receipt and shown
in the queue confirmation. Source/dispatch/query/result identity remains atomic,
and duplicate input cannot change a queued query. Literal slash-command questions
stay literal; all natural language uses intent interpretation, including the former
shortcut. The same site-neutral translation instructions reach the orchestrator
and general Gemini/OpenAI/Qwen browser workers. Exact quoted content is preserved,
and non-search tasks keep their own scoped actions. This is a common handoff rule,
not qualification of every website or a new general-site adapter.
No location, budget, deadline or other new requirement is inferred. Existing
browser records remain historical; this change does not replay prior research.

**Empty-page guard correction — installed locally; controlled checks passed.**
The whole-page fingerprint could reject a new search when homepage labels changed
between observations. New empty searches now compare URL and turn state alongside
sign-in, draft and mode checks; existing threads retain their text check. Context
is rechecked after filling. Completed turns permit the composer to return to voice
mode, while a visible stop-response control prevents completion. Certified stops
before the submission control are blocked without automatic retry; old uncertain
receipts remain unchanged. Read-only comparison against the reported baseline
showed homepage text differences with unchanged URL, turn state and empty draft.
Live end-to-end completion remains open.

**Submission correction — installed locally; live completion still open.**
The first chat-routed managed-profile attempt timed out without a conversation
URL while the request remained in the composer. The driver now clicks the
recognized Submit button once instead of relying on Enter. Controlled DOM tests
cover Enter being ignored, one completed submission, duplicate receipt handling
and ambiguous controls. Live read-only inspection identified the empty composer's
voice control; Submit appears only after entering text. The driver now waits for
that transition, covered by a delayed-control DOM regression. Receipt diagnostics
inspect only existing matching tabs in Relay's browser without navigation or clicks.
The existing uncertain receipts are preserved without
resubmission; this correction does not establish a new live research result.

**Orchestrator routing correction — installed locally; worker session check passed.**
Ordinary chat can select the app-managed browser research action for Perplexity
Search. The original request is preserved verbatim alongside its separate website
query, original reply channel and durable receipt. Stale model-browser checks and the separate
accounts-profile catalog do not block this route. Worker sign-in checks still
apply; configuration is not live authentication evidence. Other websites retain
their supported executor requirements. The installed app matches the changed modules, both messenger services restarted
with fresh health, and the worker recognized the saved authenticated Search UI
without submitting a query. A new live messenger research completion remains open.

**App-managed Chrome setup — installed local setting verified.** Settings → Browser use
(requires Chrome) now saves the user's choice, creates/reopens a dedicated
persistent Chrome profile, and provides an in-app sign-in entry point. The macOS
desktop runtime bundles the browser driver. New Perplexity chat requests use this
profile automatically through the existing scheduler, with transport ownership,
atomic request/dispatch and result/outbox records, and no uncertain replay.
Disabling blocks new managed jobs and retains login data. Controlled setup,
native-bridge, queue/recovery and Chrome restart-cookie checks pass. The updated
local app is installed; Browser use and its sign-in action are visible in Settings,
and both previously running messenger services reported fresh health after the
update. A subsequent worker preflight recognized the signed-in managed profile;
live messenger research completion remains open. No terminal setup or extension is part of this
selected app flow; non-macOS lifecycle qualification remains deferred.

Sign-in correction: the app now describes generic webpage access and opens a
new tab for manual website sign-in. This mode runs ordinary Chrome without the
worker's debugging connection; queued managed research stays paused until the
user chooses Done signing in. Switching modes retains the same profile and
refuses to close a browser used by active work or with unverified ownership.
The installed app's generic controls and live manual Chrome launch are verified:
the owned process has no debugging flags or connection descriptor, and access is
paused. Live verification-loop resolution remains a separate check from this fix.

Standalone Chrome connection: the local Perplexity worker now accepts an explicit
loopback debugging endpoint or Chrome 144+'s permission-based `--chrome` connection,
reuses the browser-owned login and retains its own
task tab on disconnect. It uses the existing submission/recovery journal without
an extension or per-click model. Twenty focused controlled checks pass;
installed-channel integration remains separate from the local CLI trial.

Live existing-Chrome trial: the standalone worker reused the signed-in session
with Chrome's connection approval and submitted the exact research once. A
temporary post-submit URL caused capture to stop; observation-only reconciliation
then returned the matching completed answer and saved conversation URL. The
transition handling is fixed and regression-tested. A fresh end-to-end submission
after the fix, unattended reconnect and deployed channel delivery remain open.

Second existing-Chrome trial: a fresh submission captured its saved URL but timed
out because a Copy control inside quoted answer content was counted as another
answer. The standalone counter now recognizes the Copy/Share/Fork answer action
group. Eighteen focused checks and the standalone CLI integration check pass;
read-only reconciliation recovered that same query without resubmission. Fresh
completion without recovery remains open; no additional query was sent merely
to retest the counter change.

### P01 — Perplexity account-visible conversations

**Complete — user-confirmed on 2026-09-14:** “P01 is done. it is working.”
The selected app-managed Chrome/Perplexity workflow is accepted as working.
No new browser run or receipt inspection was performed to record this update.
Follow-up/recovery hardening can address concrete defects when found; it is not
a prerequisite for closing this milestone.
The earlier Firefox/Zen extension and native helper remain a separate prototype:
explicit `/perplexity QUESTION` or “Use Perplexity to research …” intake, durable
request queue, one submit attempt, saved answer/URL and originating-channel outbox.
It uses the browser's own session, with no Codex calls or cookie export. Follow-ups
require the exact saved URL. Disconnects preserve uncertainty and require explicit
observation; reconnecting never resubmits an uncertain request.

**Next:** use the working research capability in the brief/PDF → research →
editable presentation integration. O13 release work remains active. The extension/
native-helper setup is historical prototype scope, not a prerequisite for the
selected app flow. The Firefox/Zen prototype remains unqualified and would need
its own signed distribution if revived. See [standalone setup](docs/perplexity-browser.md).

**Historical trials and implementation evidence:** the following observations
predate the user-confirmed completion above and do not reopen P01.

Previous desktop pilot: research through an existing Codex desktop task using
its Browser/Computer Use tools and the user's signed-in browser. Relay's existing
task intake, dispatch and reply watcher are reused. This is a separate executor
path from the dedicated Playwright pilot below; it does not require an extension
or a per-site credential adapter. The live Telegram → Codex desktop → signed-in
Perplexity Search → Telegram pilot passed: the worker reported one submission,
the completed answer and saved conversation were observed in the browser, and
Relay's completion outbox records delivery. This used explicit task selection
and user-approved Computer Use calls; fully unattended operation is not qualified.
Routing fixes retain explicitly named tasks outside a
truncated catalog and distinguish unverified desktop plugins from missing tools.
The 34 targeted context, routing and capability tests pass; installed modules
match the tested source. Live natural-language destination selection, session
permission setup, follow-up and interrupted-browser-submission recovery remain
open. Task-dispatch receipts do not guarantee browser-level exactly-once execution.
See [desktop browser workflow](docs/desktop-browser.md).

User-prioritized pilot alongside the existing installation work. The earlier
interactive browser check demonstrated saved Search creation and continuation;
it did not run through an independent Relay browser driver.

Implemented first slice: optional local `task-relay browser` commands, dedicated
profile, exact prompt/URL journal, durable pre-submit intent, duplicate receipt
protection and observation-only reconciliation. Uses the existing state database.
Controlled recovery tests pass. Chat-initiated sign-in now queues a supervised
setup worker from Telegram Providers or `/browser connect` in either channel; it
detects completion and routes status back without terminal input. The user signs
in on the Relay computer with that setup mode. An experimental Telegram
`/browser chat` flow now accepts a reply to a specific, expiring login prompt,
passes it once through an in-memory worker pipe and excludes it from task history
and model routing. The first adapter recognizes bounded Perplexity email/code
forms; browser verification and unrecognized forms still require local interaction.
The 78-check controlled browser gate passes. Live chat-login qualification and
deployment remain open: two user-authorized verification-checkbox clicks each
started verification and returned to an unchecked challenge, before the login
form. No credential or Search submission has been made in this trial.
No automatic replay, general browser tool access,
file upload, Computer workflow or subscription change is included.

Standalone-driver gate: qualify the authenticated driver against one new Search
conversation and one follow-up, including interrupted submission recovery. The
native adapter has controlled queue/channel integration; its live qualification
is next. The dedicated Playwright profile remains blocked at browser verification.
Keep authentication/account limits explicit; do not infer this capability from a
worker having shell access. See [browser pilot](docs/perplexity-browser.md).

### P02 — general website execution

Provider choice: implemented in source `openai-browser` and `qwen-browser` alongside
Gemini, using the same browser driver, reviewed plans, action journal and recovery.
Explicit `/browser openai TASK` and `/browser qwen TASK` retain the selected API
provider/model without requiring Gemini or Codex. Controlled native API envelope,
planning and recovery checks are covered; deployment and live provider/Perplexity
qualification remain open. Qwen uses the existing Model Studio API connection.

Independent Gemini/Perplexity live trial: the configured Gemini model drove the
Relay Chromium worker through six API requests without a Codex worker. Perplexity
showed Cloudflare security verification before a query field was available; the
worker recorded a blocker and submitted no research query. Successful independent
Perplexity research and authenticated-session qualification remain open.

Account-site expansion: implemented in source an explicit site list, per-site
manual sign-in confirmation and optional attachment to an existing local Chromium
session. Account tasks use the `accounts` profile and retain their separate frozen
origin/action scope. New sites, revoked access and recognized login challenges
stop for manual verification; confirming a site never replays uncertain work.
The 92-check controlled browser gate and 119 affected integration checks pass.
Deployment and real-account qualification remain open. See
[Account sites](docs/account-sites.md).

User-authorized expansion alongside P01. **Implemented bounded first slice;
controlled qualification passed, public-site trial partly qualified,
real-account qualification open.** The
`gemini-browser` executor reuses the fixed-model worker loop, scheduler and usage
records with dedicated profiles, managed tabs, visible DOM observations and exact
origin/action/file scope. Natural-language plans display that scope before Start;
local commands prepare a plan, sign in and inspect/resolve action receipts.

Committed action intents, stale-page checks, profile serialization and terminal
uncertainty prevent blind replay. Independent reviewers can read/navigate only.
Controlled tests cover the worker/scheduler and a real local Chromium form with
two tabs and declared text transfers. `/browser TASK` now enters the reviewed
planning queue from either channel. A real public information trial with the
configured Gemini model exposed missing finalization, missing date context and
review without website inspection. Those boundaries now have regression checks;
the final pair produced route evidence and an independently browsed review, but
exact-date fares remained unverified and some model claims still needed scrutiny.
The installed Telegram service was reloaded and fresh worker heartbeats verified;
no live chat test message was sent, and a separate Messages pilot was not restarted.
These P02 trials do not qualify O13 or change P01’s user-confirmed completion.
The next qualification must establish task-specific information quality, not merely
worker completion or model reviewer acceptance. See [general browser](docs/general-browser.md)
for the UTF-8/DOM limitations and the model's responsibility for action scope.

Implemented a repeatable complete browser regression gate: nine browser CLI
commands and their operational flags, 12 tools, real local Chromium, normal
producer/reviewer execution, output export and recovery without replay. Parser/tool
coverage checks reject untested additions; each run retains per-test outcomes and
command receipts. The initial 49-check controlled run exposed and fixed false-success exit
codes, missing select choices and stale draft detection. Model transport and the
Perplexity page are fixtures. The current 58-check gate also covers channel intake,
finalization and rejection of review acceptance without a page observation.
Live-account qualification remains open. Run
`.venv-browser/bin/python scripts/test_browser_pipeline.py` before browser changes
are treated as ready for use.

A subsequent live flight request exposed an inadequate redirect test: the fixture's
nonexistent destination failed regardless of origin enforcement. HTTP redirects
could bypass the interceptor and a consent page was mislabeled as generic unknown
browser work. The worker now checks each hop and returns known navigation scope
blocks to the model without clearing uncertain submissions. A reachable second
server verifies zero forbidden requests, permitted chains, and single POST delivery.
The corrected gate passed 61 checks; this strengthens the tested failure boundary,
not the claim that every website or flight search works. Historical uncertain runs
remain preserved and are not automatically replayed.

## Deferred work

- B05 application UI automation, unless a selected task demonstrates a UI-only need.
- Broad autonomous workflow extraction or context maintenance without prospective evidence.
- Additional hosted workflow/application adapters without a concrete workflow need.
- General media generation, rendering or browser tests as unrelated acceptance prerequisites.
- Channel parity, account-wide billing and domain-specific verification beyond supported adapters.

## Maintenance

Continue the active milestone without turning parked work into prerequisites.
Fix blocking runtime defects when found. Update status for demonstrated behavior,
record only relevant checks actually run, and preserve original requests, decisions,
artifact versions and recovery receipts. Keep personal trial records and operational
state outside the public repository. See [publication policy](docs/publication.md).

## 0.13.0 release baseline

The published 0.13.0 beta aligned source and companion versions. That release
includes managed browser setup, media defaults/providers, presentation and modeling
handoffs, and the app/service identity fixes described above. It is published as
a Mac beta: local signing is available, while Apple notarization, clean-host
installation and live media provider qualification remain open. Source update
protocol remains 2; the packaged app must use its own update path. Current
0.13.1 work and its local candidate are tracked separately above.

Website beta distribution: 0.13.0-beta.1 uses the reviewed app and matching CLI
source, versioned immutable downloads and checksums. Prior download URLs remain
supported. Stable GitHub publication and notarization remain separate steps.


## Desktop app updater follow-through

Implemented the app-specific check/download/install/restart flow, independent of
source-package releases, with opt-in betas and signing-certificate continuity.
App updates is the single desktop update section; Troubleshooting contains
diagnostics, service recovery and cleanup without a source-package checker.
A copied helper survives Contents replacement and retains per-attempt receipts,
previous code and a database backup. Unchanged-data compatibility, exact service
ownership, idle work and fresh readiness are required. Recovery never restores an
older database or replays uncertain work. Packaging emits matching ZIP/manifest
assets; existing DMGs alone are not installable updates.

Controlled metadata, transport-failure, stale approval, duplicate dispatch,
interrupted replacement, data-preservation, native-readiness and UI tests pass.
No live app replacement or release was performed. The published 0.13.0 needs one
manual installation of a build containing this updater; subsequent compatible
releases can update in-app. Deployment qualification remains as documented in
[desktop app updates](docs/app-updates.md).


### Packaged runtime repair — 2026-09-14

A live competition request failed before workflow dispatch because the installed
0.13.1 candidate omitted the PDF module/dependency while the running worker used
the prior PDF-enabled code. This is a packaging regression, not an ambiguous
request. The 0.13.2 repair includes the current approved runtime/UI changes as one
snapshot. Both packagers now gate release assets on an actual bundled PDF read,
dependency imports and matching app/runtime versions. Controlled failure checks
preserve the request and prevent replay; deployment is tracked separately.

Repair deployment: 0.13.2 is installed locally with matching source inventory
(240 runtime files), bundled dependency/PDF checks, four reads of the 29-page
competition brief, unchanged source PDF, matching signing identity and fresh
Telegram/Messages service health. The historical failed request remains failed;
no workflow was replayed. A corrected local DMG and updater ZIP/manifest exist;
GitHub publication, notarization and full workflow acceptance are separate.


### Conversational selection continuation — 2026-09-14

A saved short concept selection reached the model, but Gemini stopped at the
4,096-token output limit before completing its planning response. Its raw response
and original choice remain preserved. Bounded overviews now retain the latest two
exchanges separately with original history pointers; older list prefixes cannot
hide the latest choices. The 8,192-token conversation allowance leaves more room
for a complete structured reply. Explicit provider truncation is rejected before
reads/actions and reported accurately; no uncertain response is replayed. This is
controlled continuation/recovery coverage, not full architecture-pipeline acceptance.

The 0.13.3 continuation repair is installed locally. Eighty controlled conversation/
context/source-update checks pass; all 240 bundled runtime files match the recorded
snapshot, PDF reading still works, and restarted Telegram/Messages services report
fresh health. The failed selection remains saved without replay. A fresh live
continuation and the full research/Rhino/image/PPTX chain remain unverified.
