# Task Relay roadmap

Task Relay coordinates bounded project work across agents, APIs and tools, preserving
requests, artifact versions and human decisions. Telegram is the initial common
interface. The implementation is in active development; implemented scope does not
mean every provider, platform or delivery path has live qualification.

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

## Implemented foundations

| ID | Scope | Boundary |
| --- | --- | --- |
| O01 | Existing-task routing and explicit local Codex task creation | Preserves exact requests; new-task and first-turn receipts are separate. Connected creation remains unqualified. |
| O02 | Versioned reference collection | Immutable copies, hashes and source/version decisions; discovery is bounded and does not prove completeness. |
| O03 | Request to a bounded workflow, with bundled starter catalog | Versioned starter stages feed existing planning and approval; no automatic whole-pipeline execution. |
| O05 | Decisions and continuation | Exact output selection, pause/resume/cancel, status and bounded successor stages; one output per producer gate and one successor per stage. |
| O06 | Mixed execution | Codex/Gemini workers, registered text bundling and bounded Gemini text API operations share artifacts and receipts. |
| O07 | Shared-runtime evaluation | Bounded preparation/recovery coverage across three workflow types; no general efficiency or quality advantage established. |
| O04 | Second execution provider | Gemini declared UTF-8 file workers with fixed provider choice and bounded requests; shell/media execution is outside this worker profile. |
| O09 | Source boundaries and paths | Central resolver, explicit overrides and preserved data bindings; changing a path is not migration. |
| O10 | Python packaging | Runtime packages, CLI, tests and maintained assets have explicit distribution boundaries. Apache-2.0 license text and package metadata are included. |
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

## Current work and next steps

| Order | Milestone | Status | Completion gate |
| --- | --- | --- | --- |
| 1 | **O13 — installation and onboarding** | **In progress; prioritized for product onboarding** | Clean installation, channel/provider/project setup, interrupted-setup recovery, safe upgrades and explicit reversible data migration. |
| 2 | **O12 — native Windows/Linux qualification** | Partial; resume after current onboarding work | Native process ownership, locking, access enforcement, service recovery, an authorized provider text task and Telegram delivery on each host. |
| — | O08 — reusable procedures | Parked | Resume when a repeated operation demonstrates a measurable benefit over a simple reusable-script baseline. |

## Current build: O13

**Direct beta distribution and guided first launch.** The primary website route
is an Apple Silicon/macOS 14+ DMG; matching CLI source is secondary. Disk images
contain the app, Applications shortcut and beta instructions. Downloads use fixed,
versioned filenames with checksums and resumable transfer. Four saved setup steps
cover AI access, Telegram, explicit service start and pairing. Source/CLI and app
reuse the companion's explicit data binding; existing services retain their owner
until reviewed handoff. Public Developer ID/notarization and clean-host end-to-end
acceptance remain open; first-time Messages setup remains a separate pilot.

**Public website — deployed on Railway.** The text-first page lists supported
programs and their input/saved file formats, including implemented editable PPTX
generation. A specific beta.1 download notice distinguishes package contents from
implemented support; other document exports remain worker-dependent. Five development
workflow examples retain their version boundary. macOS links to the beta DMG and
matching CLI source; Windows remains unavailable. The existing desktop logo is
used throughout. Public signing and installation acceptance retain their release
gates. See [website setup](website/README.md).

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

Desktop release wording now distinguishes the installed app version from cached
stable source package metadata, including check time and version comparison.
This does not implement desktop app update discovery or installation.

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
| 3. Packaged updates | Source-update isolation implemented; app updater open | Source update plan/apply/rollback/recover refuse the bundled runtime or matching companion-owned installation before downloads or state changes. Bundled startup ignores old source-release redirection; notices distinguish source releases from app updates. Next: signed/notarized macOS packages and an explicit app update with compatible migration, receipts and rollback. Developer ID signing and notarization access are release prerequisites. Source-update commands do not update the app bundle. |
| 4. End-to-end acceptance | Open | On a clean supported Mac, verify interrupted setup, messenger pairing, closing/reopening the companion, service restart, an explicitly authorized provider task, an exact decision and actual messenger output delivery. Record each observed receipt separately; controlled tests do not satisfy live delivery. |

Immediate remaining work: directly exercise the native menu bar, qualify clean-host
setup/permissions, then deliver the packaged release/update path described in the
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

**Next implementation: Windows process-tree ownership and recovery.** Then implement
native locking, junction/reparse-point file grants, credential ACL enforcement and
service support. Extend the Windows CI profile to actual text execution as these
mechanisms become available.

Linux has controlled native text-runtime, cancellation, access and installed-wheel
coverage. Its optional systemd user-service adapter preserves a foreground path for
hosts without a user manager. Native service activation remains an open gate.
Windows installed imports and explicit unavailable-operation checks pass; Windows
execution remains unsupported. A green boundary check does not qualify execution.
See [native qualification](docs/native-qualification.md).

For each native host, verify restart without duplicate submission, descendant
cancellation, permitted-folder operations and denial of ungranted access. Record
OS/runtime/provider evidence, including uncertainty. macOS checks and mocks do not
qualify another operating system. Provider calls and live messages require their
own authorization; roadmap entries do not grant it.

## Additional implemented capabilities

**R01 — direct Rhino integration; Rhino 7 and Rhino 8 locally qualified on macOS.**

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
No live end-to-end run is claimed; Perplexity and presentation handoffs remain open.

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

**Current priority: qualify the app-managed Chrome flow**, including real account
sign-in and a complete research request returned to its originating messenger.
The earlier Firefox/Zen extension and native helper remain a separate prototype:
explicit `/perplexity QUESTION` or “Use Perplexity to research …” intake, durable
request queue, one submit attempt, saved answer/URL and originating-channel outbox.
It uses the browser's own session, with no Codex calls or cookie export. Follow-ups
require the exact saved URL. Disconnects preserve uncertainty and require explicit
observation; reconnecting never resubmits an uncertain request.

**Next:** register the reviewed native helper, load the development extension with
user approval, verify its connection and qualify one new ordinary Search plus a
follow-up. Then deploy the qualified channel intake. Controlled queue, protocol,
page DOM and channel tests pass; live Zen selectors/native messaging and deployed
channel delivery are still unverified. A temporary Firefox extension lasts only
until browser restart; signed distribution remains a release requirement. This
does not complete P01. See [standalone setup](docs/perplexity-browser.md).

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
This does not change P01's separate qualification gate or O13's other work.
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

## 0.13.0 release preparation

Current source and companion versions are aligned at 0.13.0. The release candidate
includes managed browser setup, media defaults/providers, presentation and modeling
handoffs, and the app/service identity fixes described above. PR review and CI
precede a tagged release. Recommend a Mac beta/prerelease first: local signing
is available, while Apple notarization, clean-host installation and live media
provider qualification remain open. Source update protocol remains 2; the
packaged app must use its own update path. Preparation does not publish a release
or replace the existing website downloads.
