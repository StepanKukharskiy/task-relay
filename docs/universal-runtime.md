# Universal agent and operation runtime

Implemented in source on 2026-10-12. Scripted lifecycle qualification and an
opt-in composed check using installed Blender/Rhino and public image HTTP have
passed. This does not install Relay or establish live model judgment quality.

## Two independent interfaces

`agent_loop.execute` is the single owner/worker/reviewer loop. `AgentFactory`
launches it. `gemini_worker` and `GeminiFactory` remain compatibility aliases, not
second implementations. Gemini, OpenAI Responses, Qwen, DeepSeek, OpenRouter and
Codex use `agent_transport.Transport`; Codex retains its app-server thread.
New version 2 job grants can explicitly list workers from different providers.
Selection stays inside those captured profiles and capabilities. A failed provider
never authorizes fallback. Existing version 1 grants retain their restrictions.
Operation provider/model settings remain separate from the worker's model.

`worker_tools` version 2 compiles registered operations into the existing worker
assignment. `work_run` uses the same parameter contracts, connector snapshots,
input validation, availability, host bindings, child runner and receipt observers
as standalone operations. Local operations, registered external providers and
Blender/Rhino/SketchUp operations use this path. There is no per-application agent
loop. A new operation registers an adapter and compatible ports; it does not add
a worker controller.

An optional `work.steps` array names additional operations and `from_steps` edges.
The graph is validated topologically, independent of JSON object ordering. For
registered path/hash parameters, `{step: "build", output: "candidate"}` binds a
preceding output port. Code supplies its path and current hash at invocation.
External inputs still use the existing artifact/task references. Output names are
qualified by step when necessary to avoid collisions. MIME compatibility does not
replace a content validator or authorize an undeclared conversion.

The model supplies bounded content, operation choices and request keys. Code owns
output locations, artifact registrations, approvals, versions, resource ownership,
request/time/output ceilings and acceptance. Metadata inspection explicitly does
not claim pixels, geometry validity or semantic acceptance.

## One preparation and lifecycle boundary

`agent_context.prepare` applies registered text projections and image retention,
then measures the next dispatch. Owners retain their decision/history projection;
evidence readers retain bounded literal results with exact archive references.
Both enter the same preparation function as ordinary workers and reviewers.
Identical image representations retain one working copy at the latest inspection
exchange. Older distinct pixels share an 8 MB working retention allowance and
become exact archive references when it is full. The latest requested image batch
stays intact; an oversized batch holds before dispatch rather than falsely
recording an observation. Original requests, responses, pixels and observation receipts remain
available; older working copies become exact identity references.

Stateless providers measure their submitted envelope. Codex pending replies are
measured as incremental RPCs, not the accumulated audit history. Fresh Codex
bootstrap preparation is explicitly labeled an aggregate measurement; every actual
outgoing frame additionally has a byte/hash receipt and a pre-send ceiling check.
Provider-private context occupancy and missing usage remain unknown. A wire-byte
check is not a claim about a model's token window.

`operation_lifecycle` binds dispatch to the complete frozen sub-assignment. Pending
handles and the original deadline are durable. An optional registered `reconcile`
hook may read status; it must not resubmit the original action. Missing handles,
changed identities and uncertain effects stop the worker. Explicit reconciliation
can reuse a completed child only when its materialization receipt and every output
hash still match. Ordinary second execution calls remain rejected.

The parent assignment acquires the union of required host resources before model
or operation work starts. This is deliberately coarse: it prevents two workers
from concurrently using a singleton application without adding a second scheduler.
Unknown parent attempts continue to hold their resources. Native dispatch follows
committed input registrations and approval events.

Repeated invocation of a completed request key returns its receipt. Changed inputs
require a new key; downstream results with old input hashes are stale. All versions
share the original elapsed-time and cumulative output allowances. Registered
external-request maxima consume the same request allowance as model exchanges.
Unobservable script/provider internals are not reported as zero measured usage.

Impossible owner continuation and exhausted work capacity produce typed terminal
outcomes. They cannot spend further model exchanges proposing the same recovery.
Recoverable content errors can still be corrected inside the original grant.

## Exact native-code approval

Existing native script policy remains binding. Inline work saves an immutable
`host-proposal.json` before dispatch. The trusted `work_authorization.authorize`
entry point requires an explicit decision and a database transaction. Execution
requires both the matching local receipt and its committed event, then rechecks
script, inputs, application and implementation through `host_code.verify_frozen`.
A rolled-back approval cannot run code. The agent has no approval tool. A stopped
worker's saved response can continue only after that exact approval exists and
within its original allowance; this is not a new budget or automatic service wake.

## Qualification boundaries

The controlled matrix exercises:

- Large local images and repeated views through actual Gemini-shaped and Codex
  loops, real PPTX creation/rendering, correction, exact version checks,
  independent review and owner completion. The Gemini-shaped flow also interrupts
  and resumes after a committed correction.
- OpenAI, Qwen, DeepSeek and OpenRouter worker dispatch through the same operation
  lifecycle, with explicitly granted provider selection and scripted responses.
- Composed Blender/Rhino/SketchUp host peers, resource contention, exact output
  handoffs and independent-review admission, plus the existing adapter tests for
  native script phases, approval, failure, preservation and no replay.
- A newly registered operation, and a newly registered asynchronous operation,
  without controller changes: pending handle, interrupted status reading,
  checkpoint replay, materialization, changed-byte rejection and final reporting.
- Separate registered provider operation requests, durable approval rollback,
  exhausted owner/work capacity, uncertainty and cumulative allowances.

Fixtures prove the exercised execution paths and invariants. Scripted host peers
are not installed Blender/Rhino/SketchUp executions. They do not prove a photo's
scale, reconstruction fidelity, drawing accuracy, interoperability of arbitrary
native files, or the quality of a model's independent judgment. Those require the
relevant registered format adapters and native acceptance evidence. No arbitrary
`.blend` to `.3dm`/`.skp` conversion is inferred by this runtime.

Exact commands, results, intermediate failures and remaining limitations are in
`private qualification records`. Historical audit findings remain in
[cross-tool-execution-audit.md](cross-tool-execution-audit.md).

## Actual native composed qualification

`scripts/qualify_native_composed.py --host --output <new-directory>` runs one
isolated owner job through the actual worker loop and registered operations:
Blender scene creation, separate-process reopen/render, native inventory, exact
UTF-8 evidence bundling, Rhino authoring from that inventory, fresh-document
verification and preview, public Commons image collection, and PPTX/PDF creation.
The bounded geometry fixture transfers one axis-aligned cube's measured dimensions
and creates three projection outlines. It is not an arbitrary native-file converter
or an image reconstruction test. JSON inspection reports are now accepted by the
existing `text.bundle` format adapter without altering their bytes or identity.

The deck repeatedly reads the sourced pixels, builds v1, commits a correction,
restarts the controller/worker checkpoint, rejects an attempted stale finish,
builds and observes v2, obtains a separate scripted review, and completes through
the owner. Original versions, approvals, requests, responses and tool reactions
remain in the isolated runtime. The exact native-script approval is committed
before dispatch; resuming it reuses the saved proposal.

Actual pixel inspection exposed cropped Rhino evidence despite valid geometry.
The shared Rhino preview adapter now fits after native layout and captures at the
viewport aspect ratio, then centers the entire capture in the requested raster.
Its receipt records viewport, capture and output sizes. The audit exporter now
uses the scheduler’s shared derived run status instead of labeling a completed
job active from its stored control flag. The composed fixture
checks that object edges do not touch the preview boundary. This applies to the
adapter's previews, without a new workflow controller.

The successful run and failed attempts are indexed in
`outputs/native-composed-20261012-checks/CHECKS.md`. Model responses and final
quality judgments are scripted; the code reviewer's availability declaration is
a controlled peer and it calls no code tools. Actual application execution,
public HTTP, native files and PPTX rendering are real. No paid model calls,
service installation/reload, live messages, arbitrary-photo fidelity claim or
actual SketchUp qualification is included.

## Composed live result, 2026-10-13

Fresh source-runtime attempt X passed the complete original-image sourcing, actual Blender/Rhino, PPTX/PDF workflow. Codex owned source correction, native-script recovery, final-review-driven drawing crops and deck correction, and independent re-review. The scheduler restarted after committed delegation and resumed the same job. Delivery binds exact artifact bytes to accepted reviews covering 18 rendered pages and both native previews; no manual artifact/assignment rescue or acceptance override occurred. The run used ChatGPT-authenticated Codex only, with 39 recorded auth receipts, and no paid API provider. Internal provider request counts/usage are not inferred from silence.

X consumed 27 delegated task slots and 10 owner invocations under an explicitly new 60-slot grant; per-worker requests remained 24. Offline checks separately exercise expanded graph admission, atomic over-capacity rejection and durable idempotency. W remains a failed live qualification: automatic text continuation fragmented a deck, and its unchanged grant could not fit another correction/review pair. Fixed boxes now reject overflow before commit; collection/table pagination remains available. Literal HTTPS citations are clickable and verified after reopening.

This qualifies the exercised source-runtime graph, not all providers/tools or an installed Relay service. Retail alternatives retain unknown price/dimension/stock/photo fields; geometry uses labeled estimated dimensions. Final review used registered native saved/reopened evidence and previews, not a second application rerun. PPTX rendering used LibreOffice; native PowerPoint/Keynote fidelity and SketchUp were not exercised. Original failed attempts, exact requests/responses/reactions, final hashes and commands remain in ignored outputs/shared-boundary-20261013 and private qualification records
