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
| O03 | Request-derived workflows and bounded production, with bundled starter catalog | Model-generated ordered workflows retain the full request and automatically advance through completed/selected stages. Exact host-code Start remains separate; live extraction/rollout qualification is pending. |
| O05 | Decisions and continuation | Exact file/set selection, pause/resume/cancel, status and bounded successor stages; saved workflows resume after selection without another prompt. Standalone stages retain existing controls. |
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
| — | O08 — reusable procedures | Parked | Resume when a repeated operation demonstrates a measurable benefit over a simple reusable-script baseline. |

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
- O12 stays after macOS onboarding; O08 remains parked until repeated work shows
  a measurable advantage over a reusable script. The architecture pipeline is
  a proposed subsequent integration benchmark, not an O13 release prerequisite.

## Current build: O13

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
version-change review precede the detailed programs/formats catalogue.
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
