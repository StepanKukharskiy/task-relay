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
| O01 | Natural-language routing to existing tasks | Preserves the original request and resolves ambiguity; task creation is a separate capability. |
| O02 | Versioned reference collection | Immutable copies, hashes and source/version decisions; discovery is bounded and does not prove completeness. |
| O03 | Request to a bounded workflow | Planning, validation, registration and producer/reviewer handoff; broad autonomous planning is outside this scope. |
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

## Current work and next steps

| Order | Milestone | Status | Completion gate |
| --- | --- | --- | --- |
| 1 | **O13 — installation and onboarding** | **In progress; prioritized for product onboarding** | Clean installation, channel/provider/project setup, interrupted-setup recovery, safe upgrades and explicit reversible data migration. |
| 2 | **O12 — native Windows/Linux qualification** | Partial; resume after current onboarding work | Native process ownership, locking, access enforcement, service recovery, an authorized provider text task and Telegram delivery on each host. |
| — | O08 — reusable procedures | Parked | Resume when a repeated operation demonstrates a measurable benefit over a simple reusable-script baseline. |

## Current build: O13

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

The companion includes a hidden optional Messages helper. Existing Relay and
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

**Next O13 work: finish the macOS app and qualify it as an installation path.**
Keep the source installer supported while these gates are completed in order:

| Gate | Status | Reviewable completion |
| --- | --- | --- |
| 1. Minimal companion | Installed local QA; live checks partial | Compact setup/status/settings, one menu-bar instance, close-to-hide, messenger opening and on-demand exact decisions. No second task inbox, workflow catalog or startup storage scan. Controlled read-isolation and approval checks pass. Installed native setup reads existing Relay, Telegram and Messages state. Closing and reopening from Finder passed after adding the macOS reopen handler; the rebuilt installed signature passed. Direct menu-bar interaction remains unverified because UI inspection times out without a visible window. The folder-access error did not recur after unlocking; native permission recovery remains unqualified. |
| 2. Install and service handoff | Controlled implementation; live qualification open | Bundled optional Messages helper and reviewed source/helper service handoffs retain data, pairing and uncertain submissions. Tests cover changed identities, in-flight work, failed startup, interrupted recovery, stopped-service preservation and rollback. Existing live services are not automatically adopted. Clean-host installation, real helper permissions and actual handoff remain open. |
| 3. Packaged updates | Open | Build signed and notarized macOS packages; present verified releases in the app and apply an explicit update with compatible data migration, receipt and rollback. Do not reuse source-update commands against the app bundle. |
| 4. End-to-end acceptance | Open | On a clean supported Mac, verify interrupted setup, messenger pairing, closing/reopening the companion, service restart, an explicitly authorized provider task, an exact decision and actual messenger output delivery. Record each observed receipt separately; controlled tests do not satisfy live delivery. |

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

**Architecture competition pipeline — proposed live benchmark.** User-prioritized
integration qualification: Perplexity research → concepts → Blender model → one
bounded revision → final imagery → editable presentation → channel delivery.
The [benchmark specification](docs/architecture-pipeline-benchmark.md) defines
version/geometry/source checks and bounded scope. First delivery target is
PowerPoint; native Keynote/Google Slides are subsequent qualifications. Actual
brief, account availability and execution budgets must be frozen before live work.
No live end-to-end run is claimed; Perplexity and presentation handoffs remain open.

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

### P01 — Perplexity account-visible conversations

User-prioritized pilot alongside the existing installation work. The earlier
interactive browser check demonstrated saved Search creation and continuation;
it did not run through an independent Relay browser driver.

Implemented first slice: optional local `task-relay browser` commands, dedicated
profile, exact prompt/URL journal, durable pre-submit intent, duplicate receipt
protection and observation-only reconciliation. Uses the existing state database.
Controlled recovery tests pass. Chat-initiated sign-in now queues a supervised
setup worker from Telegram Providers or `/browser connect` in either channel; it
detects completion and routes status back without terminal input. The user signs
in on the Relay computer, not in chat. No automatic replay, general browser tool access,
file upload, Computer workflow or subscription change is included.

Next gate: qualify the standalone authenticated driver against one new Search
conversation and one follow-up, including interrupted submission recovery. Then
connect the qualified driver to managed task queues and Telegram reply routing.
Keep authentication/account limits explicit; do not infer this capability from a
worker having shell access. See [browser pilot](docs/perplexity-browser.md).

### P02 — general website execution

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
