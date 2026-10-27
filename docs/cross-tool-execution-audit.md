Implementation follow-through (2026-10-12): the requested shared runtime is now implemented in source. The historical findings and design discussion below are retained; current behavior and exact qualification boundaries are documented in [universal-runtime.md](universal-runtime.md). No installation or paid execution is implied.

# Cross-tool execution: boundary audit and implementation contract

Status: source audit and controlled counterexamples, 2026-10-12. Proposed
consolidation; no runtime migration, installation, live resumption or new grant.
This refines the [universal architecture decision](universal-architecture-decision.md)
and [execution-loop redesign](execution-loop-redesign.md), using the current
working tree, including its uncommitted changes.

## Decision

Keep one durable job owner, the existing compiler/controller, registered operation
adapters and immutable artifact store. Consolidate context preparation and recovery
into contracts used by every role and transport. Delegate coherent outcomes whose
workers can inspect, build and correct within their original allowance. Return
versioned artifacts, evidence and typed outcomes to the owner.

The organizing unit is an assignment with a completion contract. A model exchange,
application launch or file conversion is a step inside that assignment when its
registered interface and authorization permit it. Separate assignments remain
useful for dependencies, independent judgment and host/resource isolation.

### Scope clarification: providers and applications are independent axes

The requested universal design includes Blender and Rhino from the outset.
Their existing composed-workflow qualification is incomplete; that observation
does not justify designing a PPTX-only runtime and postponing generality.

`gemini_worker.execute` is the current shared entry point, despite its name.
`adapters.py` selects that script for file/code worker profiles, with separate
browser/computer entry wrappers calling the shared loop;
`executors.provider_for` selects Gemini, OpenAI, Qwen, DeepSeek, OpenRouter or
Codex from the frozen backend. The loop chooses their clients and wire formats.
Thus this name does not mean every job uses Gemini, but its many provider branches
show that lifecycle and transport concerns still share one implementation.

The target dependency structure is:

```text
Model transport adapter ↔ Provider-neutral agent session ↔ Operation interface
 Gemini / OpenAI / Qwen       owner / worker / reviewer      source / PPTX / Blender / Rhino
 OpenRouter / DeepSeek /      context, journals, budgets      schema, effect receipts,
 Codex                       and typed outcomes             inspection and host bindings
                                      ↕
                         Existing durable controller
                         assignments, dependencies, leases,
                         admission, recovery and completion
```

Extract the common lifecycle into a neutrally named module such as `agent_loop`.
Transport adapters own request preparation, exact wire measurement, response/tool
decoding, protocol-specific opaque fields, observation confirmation and session
continuation. The shared loop consumes normalized events and artifact references.
Simply renaming the current file does not establish this separation. Preserve
legacy entry points and frozen implementation identity through an explicit
migration; do not replace the implementation underneath an executed assignment.

Operation adapters own application-specific execution and content validation.
Provider selection must not select a different Blender or Rhino controller.
Changing a tool must not select different context retention or recovery rules.
Model capabilities belong to the selected provider/model profile: the current
registry, for example, excludes OpenRouter and DeepSeek from its image profiles.
That is a current Relay capability restriction, not a claim about every model
available from those services. Unsupported capabilities need explicit admission
results; the runtime must not infer them from a provider name or silently switch.

The five contracts below are internal code contracts. Keep a small model-facing
surface: inspect evidence, submit/edit content, invoke a granted operation,
delegate an objective where appropriate, and finish with exact results. Code
supplies operation argument schemas and computes envelopes, hashes, paths,
capacity, leases and recovery. The model does not construct five new protocols.

## How the current owner path runs

| Boundary | Current code | Responsibility |
| --- | --- | --- |
| Admit job | `job_owner.create` | Freeze exact request, inputs, operation/worker profiles, limits and policy versions. |
| Delegate | `job_owner.Session.delegate`, `owner_intents`, `owner_compilation`, `producer_binding`, `handoff_closure` | Compile intent, bind evidence/ports, add required reviewers, check scope/capacity and atomically add future tasks. |
| Dispatch | `Runtime.claim`, `Runtime.tick` | Freeze exact input versions and commit assignment before factory submission. |
| Execute | `gemini_worker.execute`, `worker_tools.Session`, `step_runner` | Shared model/tool loop; local registered work retains intents, results, versions and cumulative capacity. Native host adapters execute application-specific operations. |
| Collect/review | `Runtime.collect`, report/record validators, correction and continuation interfaces | Validate receipts and outputs, preserve failures, apply exact-version review and qualified recovery. |
| Return to owner | `job_owner.collect`, `job_owner.wake`, `Session.restore` | Collect the owner checkpoint, wait for child outcomes, then resume within remaining owner invocations. |
| Complete | `job_owner.Session.complete` | Bind requested deliverables to exact artifacts and required independent review. |

Workers exchange artifacts through committed controller bindings. They do not
transfer authority by sending one another conversation transcripts. The older
pipeline routes also remain; a shared fix must cover their compatible workers
without creating a second scheduling authority.

## Findings

1. **Image retention is outside the owner working-view fix.**
   `gemini_worker.py:573–589` inserts initial pixels; `936–946` and `1003–1008`
   append subsequent image views to provider-shaped history. The working-view
   projection at `725–732` applies only when `owner` is present. Workers and
   reviewers have other specialized retention paths. There is no single
   role-independent image/context preparation boundary.

2. **Logical history is measured as an API request after a received exchange.**
   `api_providers.continue_request` appends replies and immediately calls
   `encode_request`, which applies a 16 MB serialized-payload ceiling.
   `gemini_worker.execute` uses that path for Codex too. In contrast,
   `codex_transport.Client.request` sends initial context once and then sends the
   pending tool result and new context on a retained thread. A full history can
   therefore fail the shared guard even though it is not the next wire message.
   Codex persistence here lasts for the active client; a restored worker starts
   a fresh client/thread. Resume and initial-context capacity must remain distinct.

3. **A terminal capacity refusal becomes a model correction request.**
   `job_owner.Session.delegate` correctly refuses delegation on the final owner
   invocation. `Session.call` catches that `ValueError`; `reject_submission`
   generally classifies it as `correction_needed` and requests another proposal.
   Only a specific compatibility diagnostic and later no-progress counters stop
   correction. The model cannot repair the exhausted authorization.

4. **The lifecycle foundations are useful but fragmented.**
   Owner checkpoints, work checkpoints and review sessions each retain different
   context/observation state. `visual_files.confirmed_pixels` already distinguishes
   delivered image data from a queued Codex tool call; preserve that protection.
   `operation_session.outcome/transition` already provides typed transitions, but
   `supported` restricts its session implementation to compatible local reviews.
   These are integration points for consolidation, not evidence that every worker
   already uses one lifecycle contract.

5. **Cross-tool availability is broader than the productive worker interface.**
   Blender and Rhino adapters exist. The in-assignment `work_run` contract currently
   enables only `text.bundle`, `pptx.create` and `pptx.render`, with `build/inspect`
   steps. Blender reconstruction and Rhino drawing work cannot be declared covered
   by the PPTX worker test. A compatible file type also does not establish geometry
   fidelity, units, scale, editability or drawing correctness.

6. **The cited composed test exercises a different path.**
   `test_codex_owner_uses_explicit_relay_search_provider_and_completes` combines
   quote-heavy owner history, scripted search, restart, text authoring and review.
   The visual build/correction fixture is separate and does not exercise a large
   repeated reference throughout that composed lifecycle. Passing both does not
   establish their interaction.

## Controlled evidence from this audit

The retained probe enters normal owner compilation and the actual shared worker
loop. Its subprocess runs `tests/codex_protocol_fixture.py`, not the installed CLI.
The PNG is deterministic local noise; no model-generated media or native app ran.

| Probe | Observed result |
| --- | --- |
| 5,042,803-byte PNG, initial attachment plus two `image_view` calls | Logical payload grows 6,759,942 → 13,484,716 → 20,209,490 bytes; retained image counts are 1 → 2 → 3. |
| Actual CLI turn/tool-result messages in that probe | 6,731,726 / 6,725,384 / 6,725,384 bytes. After three received exchanges and three tool receipts, the shared API history guard raises. |
| One authorized owner invocation, three delegation proposals | All three return `correction_needed` for the same exhausted finalization capacity; zero children are queued; no-progress handling then stops the owner. |
| Nine focused existing checks | Pass: owner context retention, composed mixed-provider text delivery, queued-pixel observation protection, work result reuse after restart, unresolved generation hold, terminal compatibility hold. |
| Static connector conformance | 49 interfaces, 5,292 directed port pairs: 1,988 require runtime validation and 3,304 are incompatible. No missing parameter schemas or producer bindings; this is metadata conformance, not executed workflows. |

Two initial probe attempts exposed fixture setup mistakes: an ordinary text worker
did not expose `image_view`, then the deck graph lacked a binary reviewer profile.
Both failed-attempt logs remain retained. The corrected probe declares the existing
work interface and reviewer capability; it stops before any build/render operation.
These counterexamples reproduce current defects; their successful assertions do
not qualify a fix. Commands, original journals and limits are recorded under
ignored `outputs/` audit storage. No installed or live behavior was checked here.

## Five shared contracts to implement

### 1. Assignment

Extend the existing frozen assignment: exact objective/request reference; grant
and policy identity; operation interfaces; input roles; required output contracts;
review requirements; reserved completion capacity; resource ownership. Models
supply bounded intent/content. Code resolves IDs, versions, paths and dependencies.

At handoff, bind each input as an operation input, inspectable evidence or
provenance, with its exact version and inspection representation. Preserve the
current role distinction and extend it through compatible native interfaces.
Unresolved future bytes receive a late admission check before their consumer runs.

### 2. Artifact and observation

Reuse immutable artifact storage. Represent context images by references to bytes,
with source artifact/version, byte hash, representation/transform identity,
dimensions and media type. Keep aliases and source relationships even when bytes
deduplicate. A crop or a new render is a distinct representation.

Track separately: available, selected for a dispatch, sent, and confirmed supplied
to a subsequent model response. Bind the receipt to assignment, session and
transport exchange. Confirmation proves exposure, not semantic understanding.
Independent reviewers need their own observation evidence. Historical observation
does not mean pixels remain available in a new or compacted provider session.

Store each image once in the working projection. An explicit reread may send its
pixels again, but must not append another permanent copy to local working history.
Keep original request/response/tool journals lossless and independently verifiable.
Do not retroactively rewrite the failed run's journals to achieve deduplication.

### 3. Prepared dispatch

Use one pure preparation boundary for owners, workers and reviewers:

```text
prepare(assignment, durable_session, pending_results, transport_capabilities)
  -> exact_dispatch + measured_capacity + observation_candidates + source_bindings
  | typed_hold
```

The adapter compiles the provider wire representation before any side effect.
Stateless providers get bounded complete request context; an active persistent
thread gets only the proper tool replies/new inputs. Restart explicitly prepares
initial context unless the adapter can prove supported safe thread resumption.
Keep tool-call/result pairing and provider-required opaque fields valid.

Measure serialized wire bytes, image bytes/count/dimensions, tool declarations,
response reserve and known provider context limits separately. Token estimates
must say they are estimates; unknown internal usage remains unknown. Small wire
messages do not prove the server's retained context is small. Use only supported,
receipt-backed compaction/session rollover at a safe boundary without pending
effects, and charge it to the original grant. Otherwise return a typed hold.

Preparation must be repeatable without dispatch or mutation. Journal the prepared
identity, commit the dispatch intent, send that exact representation, then retain
the receipt. Existing unknown submissions remain reconciliation work. Applying a
new retention policy to saved grants requires an explicit version/migration rule.

### 4. Outcome and next action

Extend `operation_session` outcomes into the shared worker/owner boundary. Use
stable codes, effect certainty, exact version bindings, progress/checkpoint and
remaining capacity. The controller selects the action; diagnostic prose explains it.

| Condition | Code-owned disposition |
| --- | --- |
| Invalid bounded content, corrected content can still fit | Local correction within remaining allowance. |
| Received result, crash before publication | Verify and publish the saved result, without re-execution. |
| Exact checkpoint, sufficient scope/capacity | Resume with preserved cumulative usage. |
| Unknown external/provider effect | Reconcile; no duplicate submission. |
| Missing supported inspection/conversion route | Capability hold; no proposal rewrite loop. |
| No affordable authorized path to completion | Capacity hold; no model request to invent more allowance. |
| Exact validated outputs and required review | Advance or complete. |

Compute action eligibility before owner wake and before each dispatch. Reserve
known downstream inspection/review/finalization costs when admitting work. Costs
that depend on future output remain explicit and are checked when known. Exhausted
delegation does not prevent completion of already-reviewed outputs; the controller
must determine which actions remain possible. Do not convert every admission error
into a request for another proposal.

### 5. Operation adapter

Keep the existing registry authoritative. Each compatible adapter declares consumed
ports, produced ports, inspection, validation, effects, resource locks, capacity
and recovery semantics. Generalize the existing work session to a registered set
of granted operations as part of the shared runtime change. Replace the
`text.bundle`/`pptx.create`/`pptx.render` allowlist and fixed `build/inspect` shape
with explicit registered execution traits. Do not add a Blender or Rhino delegation controller.
Host applications continue behind their existing host adapters and authorization
rules. Native calls commit intent before dispatch and publish only verified results.

The current `worker_tools.contract` also requires `kind == procedure` and no
external requests. Its local runner waits for a child process, and its error path
can label local exceptions as confirmed failure. Enabling host or API operations
by changing `worker_tool=True` would bypass necessary lifecycle distinctions.
Use these declarations and transitions instead:

| Declaration | Common runtime behavior |
| --- | --- |
| Typed inputs/outputs, content contract and inspection representations | Resolve exact permitted artifacts and validate bindings before dispatch. |
| Execution/effect mode and completion protocol | Handle synchronous results or durable pending handles; polling/status inspection is code-owned. |
| Required host/resources and isolation scope | Acquire the existing controller's resource lease; serialize conflicting native edits and release safely. |
| Permission/provider/cost scope and limits | Check the existing grant; never infer permission from operation availability. |
| Idempotency, cancellation and reconciliation support | Reuse a matching committed result; an interrupted/unknown effect remains uncertain until proven. |
| Content validation and review obligations | Run technical checks, bind previews and preserve required independent semantic review. |

All operations follow the same durable sequence:

```text
prepare → admit/reserve → commit intent → dispatch → observe result
          → validate/register exact versions → continue/review/hold
```

The existing controller owns queued/pending native work and wakes the same logical
worker on a confirmed result. Waiting does not require repeated model calls.
An in-assignment call can execute inline when its registered traits allow that;
a long native or external operation uses a durable controller-owned dispatch
record under the same parent grant. It is not a second graph-planning decision,
extra independent review merely for crossing a process boundary, or another scheduler.
Reserve child resources without holding a conflicting parent lease.

Blender-specific scene editing and Rhino-specific drawing commands belong inside
their adapters. They may need implementation and tests as application capabilities
grow. Their addition must not require a provider branch, new history policy,
application-specific scheduler, recovery loop or model-authored handoff envelope.

## The requested image → deck → model → drawings workflow

```text
Reference images → subject inventory → sourced records + linked image assets
                                             ├→ deck worker → PPTX + previews
                                             └→ model worker → model + geometry checks + views
                                                                  ↓
                                                        drawing worker → CAD + sheets
Each required deliverable → independent exact-version review → owner completion
```

The deck and model can share accepted source artifacts. If the user requires
strict serial order, retain that dependency; otherwise independent branches may
use the existing scheduler. Blender receives original linked images and evidence,
not just images extracted from a presentation. The owner receives compact results
and unresolved findings; it need not read every captured page or intermediate file.

A geometry handoff must declare stable object/source identities, units, coordinate
frame, scale evidence, tolerances, editable geometry versus mesh representation,
and unknown or inferred dimensions. The Rhino adapter must consume a registered
interchange representation with explicit conversion checks; MIME compatibility
alone cannot authorize an arbitrary `.blend` → drawing conversion. Check drawing
views, dimensions and correspondence to the exact model independently. A single
photo does not establish measured dimensions or hidden geometry.

These are content/format contracts under the same controller. Reconstruction,
conversion and native drawing qualification remain open for this composed path;
this audit does not claim they already work unattended.

## Implementation order and qualification gate

1. Introduce shared observation identities and prepared dispatch in the current
   loop. Replace overlapping owner/worker/reviewer preparation paths; preserve
   frozen historical policy and original journals. Qualify the image lifecycle
   and both stateless and persistent transport accounting together.
2. Route capacity and capability refusals through typed dispositions. Qualify
   immediate termination and restart alongside successful correction/finalization.
   This and step 1 form the next boundary release, not separate incident patches.
3. Generalize operation invocation for local, host and external execution traits
   in this same architecture; bind existing Blender/Rhino adapters and typed
   geometry handoffs to it. This replaces the prior proposal to defer the native
   interface extension. Native participation is part of the requested universal
   solution, while actual application behavior still needs its own conformance
   evidence. A narrower release may be called a context/recovery repair, but must
   not be called the completed universal runtime.

Universal qualification must exercise both axes. Run shared lifecycle scenarios
against every declared transport shape (including each configured provider's
normalization and capability rules), and local/host/external operation traits.
Use small synthetic host/external peers to inject pending completion, resource
contention, cancellation and ambiguous effects through real controller code.
Compose representative PPTX, Blender and Rhino operation chains with typed
handoffs and the same context/recovery path; simulated application outputs prove
orchestration only. Real app adapter conformance must separately check native
files, geometry, previews and drawing outputs before claiming those capabilities
work. Do not run unrelated native workflows merely to qualify a transport change.

An extension acceptance check should register a synthetic additional operation
with a different input/output family and asynchronous effect mode, then exercise
delegation, inspection, correction, restart and review without modifying the core
loop/controller. Failure of this check indicates the abstraction is incomplete.
Coverage is by transport shape, execution traits and content family, with explicit
cross-boundary scenarios; an all-provider × all-application smoke-test count alone
is not evidence of lifecycle reliability.

Before another paid run of the affected deck path, one composed offline scenario
must use normal admission, actual model/tool loop, controller, version binding and
final review: large reference → repeated/multiple image reads → bounded source
results → build/inspect → correction → interrupted/restarted worker → new exact
candidate → independent review → completion. Script only providers/external
sources; exercise the affected native adapter when claiming its implementation.

Vary boundary size, escaping, unique/repeated images, changed images at the same
path, previews of changed candidates, queued tool calls, tool failure, confirmed
rejection, lost response, restart and exhausted allowances. Inject interruption
before/after intent, response, result commit, publication and collection. Assert:

- Every attempted dispatch passed its own transport preflight.
- Repeated views do not grow retained pixel storage for one exact representation.
- No observation/acceptance transfers to another candidate or independent reviewer.
- Confirmed results are reused; uncertain effects are never automatically replayed.
- Capacity and elapsed-time accounting survive restart without an implicit grant.
- A terminal outcome causes no further model proposal cycles for that action.
- Original requests, evidence, artifact versions and recovery receipts stay intact.

Publish a path matrix: exact graph, roles/transports, faults exercised, assertions,
artifact/receipt evidence, source/package identity and untested boundaries. Mark
controlled, installed and live results separately. The gate proves the exercised
paths and invariants; it cannot guarantee future model quality or external services.
