# Task Relay roadmap

Updated 2026-10-03. This is the current plan. [Roadmap history](ROADMAP-HISTORY.md)
retains earlier milestone scope, tests, installation evidence and decisions;
[CHANGELOG.md](CHANGELOG.md) records version changes. Historical entries are not
current priorities unless repeated here.

Universal orchestration adjustment (2026-10-03): implemented in source. A bounded,
provider-neutral request intake freezes outcomes, counts, formats and validation
before drafting/routing. General production plans support shared preparation,
parallel producers and independent reviews within their existing task/budget
limits; there is no article keyword shortcut or forced task per article. Stage
contracts retain original outcomes and typed file checks. Inline replies cannot
fulfill frozen work requests, and missing outputs block completion while retaining
completed artifacts. Separate response-envelope/answer budgets and read-only
saved-response recovery remain available. All 206 focused controlled tests pass. Verification and limitations
are recorded in `outputs/universal-orchestration-implementation-report.txt`.
The signed local 0.13.154 installation is now verified; live model behavior remains unqualified.

Codex project creation adjustment (2026-10-03): implemented and included in the
verified local 0.13.154 update. Saved local projects are available for explicit new-task
requests independently of existing-task routing. A create-and-work request carries
the exact original message, frozen outcomes and saved context into one new Codex
task; creation-only stays idle. App access, unchanged folder identity and uncertain
submission recovery remain enforced. All 124 focused controlled tests pass; checks and limitations are recorded
in `outputs/codex-project-creation-implementation-report.txt`.

Local update completion (2026-10-03): signed 0.13.154 installed successfully.
The maintenance installer preserved the app root and data/service bindings and
saved app/database recovery copies. Strict signing, all 314 packaged release-file
hashes, the request-contract database migration, fresh owned-service health and
app restart were independently verified. Bundled Python checks and 15 controlled
installer tests pass. This establishes local runtime readiness; no new model task
or messenger test was dispatched. Verification remains in ignored local records.

PR validation repairs (2026-10-03): source fixes remove optional YAML from core
startup, retain Codex attachment album ownership and allow only inert initialized
provider defaults during offline consolidation. Nondefault provider state still
requires review, and backups retain exact source records. Controlled fixtures use
isolated project catalogs and current intake/file contracts; original proposal
scope and no-replay checks remain enforced. Validation logs are local in
`outputs/pr12-*.log`. These source fixes have not been installed in the local app.

Desktop release preparation (2026-10-03): 0.13.155 packages the merged source
and validation repairs in an isolated checkout, retaining the existing local
signing identity. Installer, updater and source assets are prepared for a beta
release; public download status requires remote publication verification.
The running local 0.13.154 app and ongoing Chrome edits are preserved. Release
checks and receipts are recorded under ignored `outputs/release-0.13.155/`.

## Product direction

Task Relay aims to be a reliable job runtime that any authorized agent,
including ChatGPT, can use to produce native, reviewable outputs. Models may
propose bounded workflows; Relay retains exact requests,
artifact versions, decisions and execution receipts in its shared database. The
installed 0.13.154 app leads job inspection with status, results and review, with conversation Workflow and History available as separate views and exports a queryable
job-local process record from committed
state and previews and deletes proven saved pipeline and standalone-result graphs.
Exclusive media agent tasks require a separate single-owner proof. Shared channel
conversation and sent delivery history remain outside job Delete. A separate
Telegram history action covers newly deleted standalone jobs; Messages and older
receipts remain open. Bounded evidence-linked revision and selected-state
continuation have been demonstrated with the real plant deck in an isolated job;
wider native/runtime qualification remains open as specified below.
Agent comparisons are optional evaluations, not a pricing objective or product
boundary.

**ChatGPT Web plugin direction (user decision, 2026-10-02):** turn useful
current discussion into separately reviewed standard Agent Skills and portable
work snapshots. Make this reusable → Review → Save/export → Select in a new chat
→ Continue. Update saved work and Improve Skill remain independent proposals.
Web V1 is a skills-only plugin using native ChatGPT review and file capabilities.
It needs no Relay server, tunnel, Desktop, local `.relay` database, execution
engine, complete chat history, cloud synchronization or separate Relay account.
It uses current context and explicitly selected files. This supersedes the earlier database-backed
web integration; local runtime state and historical proof remain preserved.
See the [web guide](docs/relay-chatgpt-plugin.md).

**Chrome extension direction (user decisions, 2026-10-02/03):** portable capture,
review, export and reuse are the browser product. Keep a page/chat → exact preview
→ keep evidence or analyze in the current AI chat → import response → independently
review/export reusable Skills and Work. Lead with useful actions and explicit
privacy: Relay doesn't watch browsing; users choose what to keep. No account,
cloud, Desktop or separate provider is required. An MV3 side panel uses temporary
tab access and thin parsers; native messaging is optional, requested only from
Connect Relay Desktop. That advanced mode adds persistence in the existing shared
work-state database and optional existing-provider analysis. The earlier private
ChatGPT Skill package remains separate. Source 0.1.10 leads with New → selected excerpt → Turn into Skill → user Send →
Download SKILL.md. Turn into Relay job is secondary and exports a portable brief.
The Relay job choice is a full-width outlined button below Turn into Skill on
the New screen; conversion choices are not shown on the result screen. The
updated installed panel was reopened and the outlined action visually verified.
The main panel has no duplicate branding or setup; source preview and recovery
are under ⋯. Skill/job capture requires a selection. One Download click retrieves,
validates and exports the requested single result. Explicit New can replace only
an unchanged owned Relay draft; unrelated drafts and attachments are preserved.
Capture, preparation and ChatGPT draft insertion remain one conversion action. Results have direct
Skill/Work downloads and Edit/Done controls; source details, recovery and optional
Desktop controls sit under Options. The view dropdown and main-screen instructions
are removed. A repeated primary click preserves an uncertain handoff. ChatGPT
draft insertion and matching-response retrieval retain the manual route. This is
the user-authorized narrow page interaction exception (2026-10-03) to the earlier
no-browser-automation boundary: no Send, page observers or general automation.
Exact handoff tickets survive panel reopening; existing drafts, uncertain edits,
response identity and tab/conversation changes have controlled recovery checks.
Read-only inspection of the signed-in Chrome page identified the current Work
composer and virtualized role boundaries; 0.1.3 supports those alongside legacy
markup, including collapsed-request deduplication and rendered CodeContent blocks.
The installed Chrome test exposed a declarative panel-open path without a tab
grant. Version 0.1.4 replaces it with an explicit toolbar action, retaining the
same permission set and no capture on panel opening; affected controlled checks
pass. The installed extension was reloaded to 0.1.4; selection capture and draft
insertion succeeded in signed-in Chrome. The user subsequently sent the request.
Version 0.1.5 preserves displayed inline URLs and display-contents message
containers, and returns recovery errors explicitly instead of misreporting a tab
change. Reloading clears Chrome session storage; explicit recovery reads the
latest loaded Relay request and matching reply in the current chat. Installed
recovery opened one Skill and one Work proposal using the original excerpt and
capture time. No new message or save was performed. Reviewed export and fresh-chat
reuse remain separate checks; recovery of requests with selected bases uses the
original files and manual import.
Installed 0.1.6 inspection confirms the minimal opening and recovered result cards
with direct download controls and Edit/Done. Original proposal fields remain
unchanged; no new request, save or download was executed. The combined primary
action has controlled coverage; a new live action and fresh-chat reuse remain open.
Version 0.1.7 fixes selected rendered citations and empty markup causing capture
rejection, returns explicit extraction errors and hides stale previews on New
text while preserving review on failure. Affected controlled checks pass.
Installed 0.1.7 captured the previously failing selection and inserted its draft
through Make reusable; the draft was left unsent. Fresh-chat reuse remains open.
Version 0.1.8 adds visible Restore request and permits unfinished New text with
Back; replacement captures retain prior exact state and receipts in session.
Affected controlled checks pass. The updated installed panel was reopened while
preserving the pending session; original draft restoration, New text and Back
were checked without Send. Full manifest reload and live replacement capture
remain unqualified for this update.
Version 0.1.9 controlled checks pass for selection-only capture, independent
Skill/job requests, direct export, wrong-category rejection and draft recovery.
The existing unpacked extension was reloaded. Its live panel shows the simplified
actions with one panel logo; a missing selection produces a clear prompt without
changing the original unsent ChatGPT draft. Live typed conversion, Send/export and
fresh-chat reuse remain separate qualification.
Version 0.1.10 accepts artifact references to the exact captured source URL,
including when the selected excerpt does not repeat that URL. Other uncaptured
links and unsafe references remain rejected in browser and optional Desktop
validation. Controlled checks and replay of the original failing response pass;
the original request and source remain intact. The installed panel was reopened
without a full manifest reload; the original response downloaded successfully
and the downloaded file passed portable validation. No new AI run was needed.
Portable evidence association and opt-in bridge permission/recovery remain.
Controlled checks pass; user Send is still required, continuation uses copied
context, and other AI sites retain manual handoff. Public V1 acceptance is not
inferred. Broader live site qualification,
Desktop-installer integration and store publication remain open. See the
[Chrome guide](docs/chrome-extension.md).

**Product boundary:** Relay Desktop is the reference product and primary inspection
surface. The runtime and `.relay` schemas must be usable without it: no Tauri or
desktop IPC dependency in job recording, export, validation or recovery. A CLI or
another host UI can inspect the same versioned files; desktop actions call the
same runtime contract. Native file editing and OS permissions remain behind host
adapters.

**Desktop direction (user decision, 2026-09-30):** tasks can start in Relay as
well as in a messenger. The main app is a workspace with Jobs, Review, Connections
and Settings; the menu-bar entry remains a quick way to open it. Both entry points
use the shared runtime and preserve exact job history. Desktop-started stages stay
in Relay for plan review, Start, output selection and follow-up planning. Existing
messenger jobs stay visible; local 0.13.142 adds desktop decisions for exact shared
plans and standalone runs while retaining their original delivery destination and
workflow ownership. This supersedes
the older minimal messenger-companion direction retained in roadmap history.

This is a goal, not a description of all installed behavior. A supplied file is
currently a **potential dependency**. Relay cannot yet prove that a particular
source statement supports one fact, spreadsheet cell or slide, or that another
location is unaffected without explicit reviewed links. Local 0.13.110
supports those links for three bounded pilots; it does not automatically reconcile
edits made outside Relay or selectively regenerate arbitrary deliverables.

## Common execution result — local 0.13.153 (2026-10-02)

The shared-result boundary is now connected to existing completion and capture
paths in the installed local 0.13.153 runtime. One versioned observation envelope adapts production attempts,
direct provider jobs, external native/spreadsheet candidate submissions, revision
bundles and continuation sets, plugin reports and reviewed text runs. Exact
original rows, assignments, inputs, artifacts, bindings,
checks, issues and receipts retain their owning authority. Completion, saved
uncertainty, validation, selection and delivery remain separate facts.

Local administration can inspect a source, capture its exact hash into one saved
work continuation and export the frozen redacted result with read-back recovery.
Atomic capture advances work state and invalidates earlier understanding without
selecting an output or dispatching. Existing scoped MCP inspection, provenance,
understanding and continuation consume captured observations. Changed sources,
conflicting retries, wrong identities and edited exports are refused; late results
disclose changed work and changed selected inputs. Existing completion/admission
transactions retain observation intents and frozen envelopes. Owned text/plugin
results capture automatically; production and other external outcomes capture
only into explicitly linked work projects. Pending projection/delivery state is
visible within project scope. Capture errors preserve worker outcomes and recover
from frozen observations without execution replay. Local binding, backfill and
bounded recovery commands retain exact requests and retry receipts.

The initial 35-check source pilot covered five representative job shapes. The
completion bridge now passes 86 focused text-record, runtime, work-state,
admission-hook, direct-provider and SDK checks. Eight saved cases on isolated
database copies verify three plant revision/continuation sets and five research
outcomes, retaining parent/set decisions, artifacts, checks and original receipts.
Forced capture interruption, recovery, export and return preserve retry identity;
original and copied owning tables remain unchanged. No native files are rebuilt
or providers called. See the [contract and local CLI](docs/execution-results.md).
The already demonstrated plant continuation loop is reused as compatibility
evidence. The signed local 0.13.153 installation retains verified app/database
recovery copies and the installed app root identity. All 302 packaged runtime
files match source; 13 controlled completion/recovery tests pass with bundled
Python. Installed imports and strict signatures pass; both owned services have
fresh restart health and the app reopened. No live provider action or new test
message was requested. Live executor swaps, generic external MCP executors,
universal ownership discovery, deployed ChatGPT qualification and a Desktop
source-linking interface remain open. Existing milestone
order and integration support policy are unchanged.

## Connector and provider documentation — 2026-10-02

The [capability inventory](docs/capability-registry.md) now indexes the current
seven text/agent connections, three additional media providers, 19 production
executor profiles and all 35 registered operations, plus browser/account routes,
ChatGPT/MCP, local context, documents, channels and host infrastructure. Provider
and capability guides reflect current profile families, frozen request budgets,
configuration-bound metadata verification and capability resolution. README
version references are aligned with source 0.13.152 and plugin 0.2.1.

The plant-deck selected-set follow-on is retained as bounded continuation evidence;
the pending Competition/ChatGPT substantive-action check does not negate it or
become a new prerequisite. Source, recorded installation and live qualification
remain distinct. `.relay` exports remain projections; generic external MCP/HTTP
executor consumption and automatic production/work-state synchronization remain
pending. This is documentation upkeep, with no runtime behavior, milestone order,
integration-freeze policy, provider dispatch or installation change.

Static source/documentation checks verify coverage of 35 operations, 19 profiles,
seven worker capabilities and the seven-plus-three provider connections, and all
125 local links in the affected documentation scope resolve. Scoped `git diff
--check` passes. Commands and results are retained under ignored
the ignored connector-documentation check records; no runtime suites or deployed checks were run.

## Current baseline and release boundary

| Layer | Recorded status | Boundary |
| --- | --- | --- |
| Public Mac beta | 0.13.89, per [release notes](docs/release-notes.md) | Public package contents and live qualification differ from later local work. |
| Local Mac app | 0.13.153 installed locally | Jobs, Review, Connections and Settings form the main workspace. Tasks can start here with frozen attachments and explicit plan review/Start; shared messenger jobs retain their delivery channel and can be decided locally with exact receipts. Conversation details render sanitized Markdown, keep source records collapsed and start explicitly selected bounded public research in the original conversation workflow. Other outcomes prepare attached plans with Start review. Completed standalone Desktop conversations have a bottom history Delete control with exact review with retained replay identities and recoverable trace cleanup. The signed bundle contains 302 source-matching runtime files, including the work-state/context runtime and completion envelope bridge. Its job detail leads with one status and next action, keeps results beside their review, and draws compact step names/statuses. The inspector opens on request; technical records and activity remain under Details. Exact saved filenames still open Finder. New task stays one entry with visible project folder; unchanged list refreshes retain focus and repeated titles have distinct accessibility identities. Recorded revisions and replacements have version comparisons; an explicit check detects edits at saved desktop attachment locations and marks steps supplied an earlier version. Inspection preserves frozen copies, decisions and execution scope. Its 0.13.153 installer receipt records app/database recovery copies and fresh owned-service health. Exact shared plans can be reviewed/started here, with expired approval renewal, original delivery routing and committed Start identities. Ready decisions and attention jobs are separated; cancelled owning workflows show their Start blocker. Cancelled jobs and discarded plans can be removed from the list and restored without deleting exact history or files; unresolved workers block removal. Workflow-stage cancellation keeps continuation under the original workflow authority. Saved work Delete and shared-history actions pass the packaged Tauri action allowlist; 0.13.114 replaces the blocked browser confirmation with an in-window dialog. The 0.13.113 native click unexpectedly deleted the named pavilion task because an asynchronous confirmation result was treated as truthy; its complete receipt is preserved. The 0.13.114 dialog was opened for a different eligible task and Cancel preserved that task with no receipt. Earlier isolated-copy deletion, live standalone job deletion, and quality boundaries below still apply. The Yamaha historical candidate remains blocked by active or uncertain work. No revision was accepted/selected or installed-app Grasshopper graph executed. Installed-app real-deck revision and batch-scale translation remain unqualified; the bounded isolated plant-deck selected-set continuation is recorded below. |
| Job control | Ordered request-derived workflows, exact artifact versions and decisions, conservative artifact-level impact, bounded continuations | Availability, user selection, approvals and uncertain-submission rules still govern execution. |
| Native files | Editable outputs through supported workers and operations; `pptx.edit` changes exact text runs and pictures | There is no general control of open Excel/PowerPoint/Rhino/Blender sessions or universal format fidelity. See the [capability index](docs/capability-registry.md). |
| Job view | Read-only `.relay/snapshots/<snapshot>/job-state.json` and `.relay/job.sqlite` in a Relay workflow folder | Installed 0.13.110 projects exact process rows, media-stage task links, standalone ownership, attributable delivery state and coverage gaps alongside artifacts and revision evidence. It is not authoritative or a portable job without referenced files. See [handoffs](docs/workflow-handoffs.md). |
| External evidence planning | Guard and typed `web.sources` planning installed locally in 0.13.94; 0.13.95 requires downstream file producers to receive the source review report; 0.13.96 requires a complete browser scope in planner responses; 0.13.97 deduplicates byte-identical implicit browser inputs; 0.13.98 rejects empty browser text outputs; 0.13.99 recognizes explicit catalog research followed by a native deliverable; 0.13.100 permits a bounded sequential chain of independently reviewed file stages | The completed 10-part pilot records seven exact-article-supported English-to-Russian names (Yamaha 2/5, Harley-Davidson 5/5), three blank Yamaha names, and a reviewed distinction between an original part and its named replacement. The user selected the outputs after the search-quality warning. The inherited source search used altered query variants, including a different Yamaha prefix and `1000cc`; accepting these outputs does not qualify literal-query fidelity or complete catalog coverage. `web.sources` gathers candidates and gaps, not verified OEM facts. |

## ChatGPT Web V1 — reusable Skills and portable work

**Current source: skills-only 0.4.2; native capture and fresh-chat reuse verified.**
The user selected native ChatGPT skills/file capabilities over a hosted custom
panel. The canonical `relay-work` package contains the existing Task Relay logo,
one make-reusable Skill and a work-format reference. It has no MCP configuration,
app binding, server, tunnel, separate account or Desktop requirement. Default
packaging produces this skills-only archive and keeps receipts outside it.

Make this reusable separates general method from instance progress and requires
independent review/save. Continue saved work uses explicitly selected files and
the new request without reconstructing the original conversation. Update saved
work and Improve Skill remain separate. Native file creation/selection must be
available in the host; unavailable capabilities must be reported without invented
files. No persistent Relay catalog, history ingestion, automatic latest-file
search, cloud synchronization, local execution or Skill installation is implied.

Seven focused packaging checks pass, including exclusion of historical server
configuration and account bindings, exact workflow content and preserved old
profiles. Skill metadata validates. The private native package is saved in the
user's account with its scope, identity and 0.4.2 root/compatibility metadata
verified. The old app-backed prototype rejected the native source package name;
it and its recovery records remain separate. Live ChatGPT capture separates the
method and fictional work, keeps unaccepted criteria proposed and waits for
review. Independent native exports were downloaded through Zen: the Skill ZIP
has its standard named folder and valid frontmatter, and the work retains the
seven sections and proposed criteria. The first export exposed an initial-parent
compatibility error; 0.4.2 explicitly uses YAML null and preserves request text
through serialization. A new chat with only those selected files restores the
objective and missing inputs without the original chat. One supplied-evidence
eligibility action distinguishes a supported candidate from an unknown one and
proposes a separately reviewed work revision linked to the exact base SHA-256,
while leaving the Skill unchanged. The downloaded revision validates against the
portable reader and the original-byte parent hash. A separate corrected initial
export validates with YAML null and retains the multiline capture request and
proposed title. Improve Skill proposes only a generic table addition for separate
review, without exporting it or changing the work. These synthetic checks do not
establish public publication or an automatic file/history catalog.

Publisher, free availability, support contact, all supported countries and policy
text are confirmed. The four publisher pages are deployed on the existing static
website and their contents/access are verified. A final skills-only ZIP passes
local listing/icon/inventory checks. The signed-in public portal in Zen blocks
upload until individual publisher identity verification is completed. The user
reports that Persona says the application is misconfigured. Reopening the existing
desktop inquiry displays a fresh mobile QR code, but the handoff still reports
the configuration error and verification is not completed.
Attestations, scans, review and actual publication remain pending.

The custom-panel 0.3.2 implementation is preserved under `plugins/relay/hosted/`
and its historical guides. Explicit Python/endpoint builds retain that profile;
it does not enter the default upload. Its transport/validation evidence remains
historical. The temporary custom-panel deployment was stopped after the native
choice; Railway reports it REMOVED. No local project state or Desktop records
were changed.

## Project context organization — legacy local source pilot

The source runtime now has a bounded, Relay-owned `project-context` operation:
read-only collection of one selected local Codex project's canonical messages and
Markdown knowledge, model-derived topics, complete source coverage, claim quote
and role checks, artifact inventory links and topic context exports. A durable
internal job retains the exact request, original capture, redacted model input,
budgets, response and usage. Invalid individual claims stay quarantined as review
gaps; invalid coverage or inventory blocks export. Uncertain submissions cannot
be replayed. Export intent and read-back receipts support recovery without
overwriting edited files.

Twelve controlled synthetic text cases cover atomic queue ownership, idempotent
dispatch, budget rejection, source authority, credentials, interrupted submissions,
committed response recovery, failed-claim quarantine, partial exports and exact
project collection. The local selected-project provider run and its limitations
are recorded separately in ignored private outputs. See
[project context operation](docs/project-context.md).

This CLI pilot is packaged in the installed local 0.13.153 Desktop runtime; it
does not add a Desktop context interface. No
ChatGPT history API, sidebar mutation, automatic context router or source-file
rewrite is qualified. Native geometry/media are not revalidated. Further UI and
host integrations remain follow-on work, not prerequisites for this pilot.

**Plugin status: product direction accepted; local development build implemented.** The
2026-10-01 user decision expands the earlier Context Explorer into a work-state
system: inspect current work, provenance, versions and unresolved issues, then
continue with a bounded context packet. Chats are evidence; topics are overlapping
views. Relay owns ingestion, graph construction, state resolution and continuation
through its runtime. The source pilot already projects topics, captured files and
checked/held citations without another model call; it does not resolve accepted
versions, decision supersession or downstream freshness automatically.

The source now includes authoritative `work_*` records in a selected Relay
database, explicit reviewed decisions/selections, supersession and potential
impact through reviewed dependencies, bounded continuation packets, scoped MCP
tools and a self-contained MCP Apps UI. The UI declares sidebar/conversation
entrypoints, renders provenance and graph views, and revalidates context before
messaging the current conversation. One exact-text worker commits its assignment
before exclusive publication and recovers only matching already-published bytes.
Outputs remain unselected candidates. Work context selection does not replace
production acceptance. See the [development operation guide](docs/relay-chatgpt-plugin.md).

Twenty-eight focused Python cases and a controlled DOM suite pass for work-state
failure/recovery, actual SDK stdio/HTTP protocol, OAuth owner/scope enforcement
and the affected project-context integration. A private developer profile also
passes an actual SDK round trip on imported saved project evidence, including
graph integrity and continuation validation, without a new model call or execution.
These are local checks; they do not qualify an installed ChatGPT interface.

This plugin sequence does not make deferred runtime milestones prerequisites or
authorize external dispatch beyond an exact reviewed text assignment.
V1 evidence is limited to Relay-involved context explicitly supplied to its tools,
authorized imports, connected files and Relay execution records. Reviewed public
APIs do not establish full ChatGPT history enumeration or native chat-list
mutation. Local stdio uses host user identity; project allowlists and private
single-operator bearer HTTP are implemented. An external OAuth resource adapter
adds discovery, signed-token issuer/audience/expiry/owner checks and per-tool
read/write scopes with an explicit project allowlist. Portable and compatibility
developer profiles are built without installation or publication. External issuer
setup/public deployment, tenancy,
arbitrary native worker integrations, automatic production-job synchronization
and live installed ChatGPT qualification remain pending. The installed Desktop
baseline remains 0.13.152.

**Next plugin product proof (2026-10-01 clarification):** Connect → Understand →
Continue → Capture the result. Define the current-state experience first and connect
only the sources needed for it. ChatGPT supplies intelligence; Relay retains the
persistent state. Universal capture is not a prerequisite. The graph is an
inspection view; persistent resumable work is the product.

**Product hierarchy (2026-10-01 refinement):** implemented in local source.
The guide leads with the persistent work promise and the product loop, followed
by development inventory and limits. The sidebar is Work; a project opens on
Current state with Current, Sources, History and Graph tabs. Up to four grounded
next steps appear first, selected artifacts stay separate from candidates, and
failed citation checks stay in source review rather than project questions.
The source index reuses existing record metadata and provenance; no new backend
concept or collection adapter is added. The next acceptance exercise is one
connected Competition loop: return after a week, understand the state in 30
seconds, continue an action, retain a result and return to changed work.
A local Codex-host analysis through the existing Relay MCP tools now saves a
cited Competition overview and four next-action proposals, using 52 connected
records. Exact save retry returns the same receipt; reviewed decisions and
artifact selections remain empty. One exact-action continuation passes preparation
and validation without being sent or executed. The full connected product proof
remains pending.

**Task Relay branding and trust cues (2026-10-01):** implemented in local source.
The plugin display name and component use Task Relay, the existing desktop logo,
desktop control styles and smooth cubic Bézier graph edges. Current state visibly
separates proposed Task Relay understanding from reviewed decisions, selected
artifacts and resolved issues. Save time, changed-work status, connected/considered/
cited/added source counts and exact per-statement citations use existing records;
inspection-only source use is not invented. No new MCP tool, state table or
provider integration is added. The connected ChatGPT Continue → Capture product
proof remains the next integration priority.
Twenty-three affected Python cases, controlled UI and syntax checks pass. The
read-only browser preview verifies desktop branding, source metrics, exact quote
inspection and Bézier paths. A fresh private profile validates its packaged logo,
manifest/runtime hashes and exact-action context via the actual MCP SDK; no work
was dispatched and no client was installed for this styling change.

**Development integration framing (2026-10-01):** complete in documentation.
The package README leads with “Keep the work, not just the conversation” and
defines Task Relay as maintaining the state of work between AI interactions.
ChatGPT is one interface into that system; MCP is the integration mechanism.
The product loop, durable source-linked state and understanding/review distinction
precede package inventory, installation and qualification limits. The operation
guide shares this framing. Final wording describes persistent work state without
claiming sole authority over external files/tools, explains capture as the next
interaction starting from new state, and keeps visual implementation details in
the guide. Positioning refinement is complete. Runtime behavior is unchanged;
the next experiential check is whether returning to Competition through its saved
state is easier than reconstructing the original chats. The connected ChatGPT
Substantive suggested-action execution remains pending; the connected capture
and fresh-chat return are verified below.

**Connected ChatGPT interface (0.2.1, 2026-10-01):** local connection preparation
implemented. A project-scoped stdio launcher and guided Secure MCP Tunnel setup
serve the existing runtime from any working directory, without storing credentials
or registering a connection. A separate remote package builder emits an HTTPS
MCP ZIP without local data/paths/credentials and preserves prior package versions.
The UI fetches fresh authorized state on reopen, opens a single connected project
and optionally retains navigation/capture identities in ChatGPT widget state.
No new work table or MCP tool is added. The connection runbook covers the actual
Competition loop and public distribution path. The installed ChatGPT loop,
stable hosted endpoint, real OAuth/account
isolation, publisher policies and public review remain pending. Local preparation
and controlled checks do not establish a connected or published plugin.
Nine focused Python cases and controlled UI/syntax checks pass. A prepared
Competition-only launcher passes actual SDK discovery, fresh-state and UI-resource
checks from another working directory without mutating work. The official Mac
tunnel client is downloaded privately with a matching release checksum. Initial
controlled checks covered help and synthetic local profile initialization.
Live Zen inspection reaches the MCP app form through Add plugin → Create MCP
App (or Create app → Create MCP App in the earlier interface). The initially
empty Tunnel list required Platform setup. The user selected the organization and approved
creation of a private development tunnel associated with the ChatGPT workspace;
the Platform success receipt and exact identity are retained privately. After
separate user approval, a one-day runtime key was created with only Tunnels Read
+ Use; its secret is excluded from logs/files and the user has the exact launcher
command for local entry.
The first user-run startup exposed a relative client path failure before profile
creation. The generator and prepared launcher now resolve the executable before
changing working directories; the previous launcher and repair hashes are kept
privately. Five focused packaging/launcher cases pass, including this failure
regression and restart identity checks. The user's live retry starts the MCP
process and fetches tunnel metadata; the local admin UI reports Health: live and
Ready: ready. The private ChatGPT app is registered and connected. Registration
initially left its app disconnected; Manage → Connect completes activation.
An unintended duplicate registration is retained with both identities recorded
privately; no duplicate is deleted or used. The connected read-only Competition
test discovers work, opens revision 379 and renders the actual Current, Sources
and Graph views through the tunnel. No result capture or reviewed change is made.
An explicit desktop canvas fixes low contrast under ChatGPT's transparent frame;
the fix is visibly verified in a new tool opening after development tool refresh.
Four focused MCP cases and controlled UI checks pass. The user refreshes the
understanding in ChatGPT, explicitly captures the pass and reopens Competition
in a fresh chat at revision 388. A read-only database check verifies the exact
saved notes, three question records and immutable packet hash/link. The overview
at revision 384 is stale after the four new capture records. Reviewed decisions
and selected artifacts remain empty. This proves durable capture and return;
the captured work is an understanding refresh, not a completed suggested design
or modeling action. Substantive continuation and public distribution remain
pending; improved resumption experience has not been inferred.

Local 0.2.0 plugin source now freezes bounded connected evidence, stores cited
host-model understanding proposals, derives overlapping workstreams and next
actions, prepares fresh exact-action context and captures explicit result notes
and new questions against immutable continuations. Current-work UI presents the
objective, conclusions, questions and suggestions separately from reviewed work
authority. Quote identity, source scope, stale state/files, rollback and stable
retries are checked. Late result capture discloses changed work without executing
again. Whole-library discovery, incremental refresh, general ChatGPT ingestion,
native-worker synchronization and installed ChatGPT qualification remain pending;
the saved-analysis import and controlled protocol checks do not establish a live
Competition loop.
Twenty-four focused Python cases and controlled UI checks pass for the affected
work-state, understanding, MCP and OAuth contracts. A new developer profile passes
manifest schemas, runtime/profile hash checks and actual SDK preparation over
saved selected-project evidence. No fresh model analysis or real worker was
dispatched for that profile qualification. Private evidence preserves the user's
exact product-loop request and earlier build receipts.
Directly opening the component HTML does not run its backend or MCP host.
Qualify collection coverage and a runnable interface before calling the feature
complete. Current OpenAI plugin guidelines restrict MCP access to explicitly
shared snippets/resources, so plugin installation cannot be presented as full
ChatGPT-history permission. Separate local collection and task-relevant plugin
retrieval need their own access and distribution qualification.

## Conversation inspection hierarchy — 0.13.152

The latest result opens first. Results, Workflow and History are distinct views
beneath the conversation job heading. Full dependency inspection is secondary;
recorded search/page coverage appears above the research answer. Linked historical
failed preparation stays in History with collapsed unchanged attempts and
unexecuted proposal, rather than looking like blocked current work. Conversation
step inspection opens its saved answer without planned-file placeholders.

Receipt-bound source clicks bypass the generic restricted setup opener. Inert
links stay inert and setup permissions remain unchanged. Source-opening failures
are local, concise messages. These presentation changes do not retry research,
accept plans, rewrite saved replies or alter deletion ownership.

Four affected DOM checks and 39 in-app-browser synthetic text checks passed.
The signed 0.13.152 installation completed with app/database recovery copies,
seven fresh owned-service health records and all 289 runtime source files matching
source. Computer Use inspected the user's actual job before and after installation:
Results opens on its research answer, Workflow has the conversation, two recorded
searches and answer, and History retains the earlier blocked preparation with
collapsed attempts. Saved answers, read journals, lineage, plan/call, artifact and
decision digests are unchanged. No research rerun, execution approval, source URL
opening or live message was performed by this inspection. Source-click routing
was verified in a controlled fixture, not by opening the live redirect URLs.

## Conversation workflows and selected public research — 0.13.151

The user authorized bounded public research on selection. A Desktop recommendation
containing only public search/page reads queues that exact outcome atomically in
its original conversation, with frozen input versions and durable retry identity.
It uses the configured provider and existing two-search/six-page read budget.
Other selected outcomes queue attached planning stages; execution retains Start.

One Jobs entry projects the saved conversation, observed read sequence, answers
and attached plan/run dependencies. A rejected proposal is labeled unexecuted;
retrieval records do not certify claims. Historical attachment requires exact
matching inputs and an explicit relationship; it neither retries nor accepts the
old plan. Nested recommendations retain the same root. The main view shows status,
results and actions; planner attempts and raw rejected data stay collapsed.
`web.sources` has typed query/domain parameters even when offered optionally, and
validation errors identify missing fields for the existing correction attempt.

Conversation Delete is at the bottom history section. Linked stages still block
standalone history deletion; deleting a whole conversation workflow is not qualified.
Free-form continuation still uses the existing New task entry. New requests preserve exact offered tool IDs outside trimmed overviews. Historical
selection uses only explicitly captured availability; model-suggested unknown tools
cannot become available through fallback. UUID ownership protects follow-up history.

103 distinct affected Python cases, two DOM checks and 27 real-browser synthetic
fixture checks passed. 59 controlled cases passed against bundle modules. The final
ownership guard updated one Python runtime resource in the built native candidate;
no additional native compile was required. Private recovery receipts preserve the
initial cache-related installation failure and subsequent controlled correction.
The exact reported failed preparation is linked to its original conversation as
display history only: one job entry, six recorded/proposed nodes, two retained
planner calls and no executing run. Original request/response, plan/call, artifact
and decision digests remain unchanged. The final signed installation completed with verified app/database recovery
copies, seven fresh owned-service health records and a reopened app. All 289
installed runtime files match source. Read-only installed bridge checks preserve
this history and show the joined workflow; standalone deletion is blocked by its
linked ownership. No provider rerun, execution approval or message dispatch was
performed. Exact commands, controlled failures and receipts stay in ignored local
outputs.

## Readable conversations and local history controls — 0.13.150

Answer-first Desktop conversation views render bundled, sanitized Markdown and
show concrete outcome buttons that prepare reviewed plans. Routing and source
records stay under collapsed details; the source status reflects observed reads,
not a factual correctness verdict. Runtime-owned claim/source fields accept data
only, with no model contract or state definitions. Display projections bind to
exact committed replies; historical footer separation requires full identity.

Completed standalone Desktop conversations have a visible Delete conversation
control above the answer. Fresh exact review and in-window confirmation precede
atomic local-text deletion. Retained submission/delivery identities prevent replay;
frozen attachments and other jobs remain. Private trace cleanup follows commit,
with recoverable receipts and changed/linked-file protection. Existing job/task
history controls are visible near the start of their details.

133 distinct affected Python cases, two DOM checks and 17 browser fixture checks
passed. The browser uses synthetic text and native routes; no real conversation
was deleted, provider rerun or message sent. 35 bundled controlled cases passed. Signed installation completed with verified
app/database recovery copies, seven fresh owned health records and a reopened app.
All 288 installed runtime files match source. The installed bridge passes the
reported conversation's read-only deletion preview, while original conversation,
plan, artifact and decision digests remain unchanged. Exact commands, controlled
failures and limitations remain under ignored local outputs.

## Runtime-owned response schemas and automatic recommendations — 0.13.149

New Desktop requests use automatic orchestrator recommendations; no research
selector is required. Explicit recommendation choices and pending request receipts
retain their saved scope. Relay compiles the final response schema, enums, limits
and available tool IDs procedurally. The model supplies data through the same
non-executing final function on all five transports, with no extra provider turn.
Action data still passes the existing runtime-owned validators and authority
checks before committed dispatch. A model cannot supply or amend the contract.

Malformed advisory metadata in a non-executing direct answer no longer discards
valid answer data. Preserve the exact raw response and recovery notes without
inventing a mode or replaying the provider. Explicit source choices and actions
remain strict. The reported failed reply passes offline validation with both next
options; its original saved failure remains unchanged. Controlled checks cover
transport data, read-budget termination, strict action failures, shared channels,
saved conversation projection and UI receipt recovery. Signed installation completed with verified app/database recovery copies, seven
fresh owned health records and a reopened app. All 287 installed runtime files
match source. Qualification passed 93 distinct Python cases, two UI checks and
21 bundled controlled cases; installed read-only checks preserve original
conversation, plan, artifact and decision digests. Exact commands and limitations
are recorded under ignored local outputs. No live provider rerun or messenger
delivery is claimed.

## Shared orchestrator entry and proactive options — 0.13.148

Installed local 0.13.148 routes new Desktop requests through the same
conversational worker and captured capabilities as Telegram. Explicit plan
revisions and stage follow-ups keep their saved scope. Desktop projects the exact
saved messenger answer and receipt-bound source links. Request identities, frozen
attachments and entry modes remain atomic; inspection and suggested options create
no execution authorization.

The response contract offers up to three concrete next outcomes from available
tools, rather than only generic advice or a research toggle. Desktop choices open
editable drafts with saved input versions. Explicit source checks use primary-page
reads; search-only responses claiming verification fail without replay. Controlled
entry, provider, channel, source-recovery and UI checks pass: 147 distinct Python
cases, three DOM checks and 15 packaged cases. Signed installation preserved
verified app/SQLite recovery copies, seven fresh owned health records and a reopened
app. All 287 runtime files match source. Read-only installed inspection proves
the reported Telegram answers are projected exactly; original conversation,
plan, artifact and decision digests are unchanged. No live provider rerun or message
delivery is claimed; semantic option quality and factual correctness remain to be
assessed on an authorized rerun.

## Job-local SQLite decision

**Current authority:** Relay, its channels, production runtime and durable outboxes
share one `private/state.sqlite`. Job folders hold native files and read-only
exports. This keeps job decisions, worker claims and delivery intents within the
existing transaction and recovery rules. See [shared storage](docs/shared-storage.md).

**Installed local source:** O14 adds a **read-only `.relay/job.sqlite` for saved
workflow and production-result jobs** as a queryable projection of committed
records. It includes exact reviewed links, output coverage and saved candidate
impact for three bounded adapters.
It is published after the shared database commits, with a schema version, snapshot
identity, source hashes and explicit incomplete-coverage markers. Treat files in a
user-accessible folder as data, never as authority or executable instructions.
Keep it in Relay's job folder by default; placing it inside another project needs
an explicit destination and access review. A SQLite file alone is not a complete
portable job unless its referenced artifacts are included and hashes verify.

The installed projection indexes exact requests, stage plans, assignments,
attempts, checks, decisions, exceptions and recovery receipts reachable from the
registered pipeline and plan/run ancestry. It records missing referenced rows and
pending receipts explicitly. Shared channel conversation and delivery history is
still outside the job-local scope; ordinary watched agent chats do not yet get a
`.relay` job folder. Installed deletion covers saved pipelines whose
plans, runs, attempts, evidence, decisions and delivery receipts have proven
ownership. It blocks active, uncertain, missing and shared downstream work. The
shared conversation remains outside this Delete action. Since local 0.13.107,
one completed Gemini image task may be deleted with its pipeline only when exact
stage, dispatch, backend job, provider, artifact and delivery ownership is proven;
reused, active, uncertain or incomplete tasks block. Ordinary watched agent tasks
remain outside pipeline Delete. Local 0.13.109 records selected standalone results
against an exact root plan and gives historical selected results a verified,
explicit backfill before Delete preview. It retains shared conversation and sent
delivery records and blocks pending or cross-job work. The separate lifecycle of
shared channel history remains open.

**Later decision:** moving authority into each job database requires a separate
migration design and recovery proof. The scheduler/index, channel outbox, job facts
and dispatch intent must have one unambiguous owner; cross-job references, moves,
backups and upgrades need defined behavior. Simply writing both the shared and
per-job databases would create two sources of truth. SQLite WAL transactions across
attached databases are not crash-atomic as a set ([SQLite documentation](https://sqlite.org/lang_attach.html)).
A per-job database becomes authoritative only after the same transaction and
no-duplicate-dispatch guarantees have been demonstrated. This is not a prerequisite
for the O14 evidence pilot.

## Active and ordered work

**Requested Telegram/direct-conversation follow-up — installed local 0.13.147:**
The conversational orchestrator can answer without creating a production plan;
the previous Desktop stage repair did not cover that path. The live conversation
generator now requires request-specific research advice in its existing response,
while historical answer parsing stays compatible. Relevant recommendations,
source-check questions and actual tool-read links appear in the saved reply.
Exploratory replies stay concise and reject recognized unsolicited blueprint
wording. Fetched pages and search references are distinct; no successful lookup,
changed receipts and capped disclosure are stated honestly. Missing advice saves
the exact provider reply and stops without replay or dispatch. Conversational
stage actions can carry the same explicit research modes and frozen source/review
contract as Desktop. 109 distinct affected checks pass; four workflow checks use
the packaged Python's presentation dependency without generating presentations.
Packaged Python passed nine focused cases. Signed installation completed with
verified app/SQLite recovery copies, seven fresh owned health records, reopened
app and 287 matching runtime files. Read-only record comparisons preserve the
reported direct reply and both earlier exploration jobs. No live provider rerun,
public-source request or Telegram send was submitted by this repair. Model
recommendation quality and semantic correctness remain outside the structural
proof. Private receipts remain under `outputs/telegram-research-147/`.

**Requested contextual recommendation follow-up — installed local 0.13.146:** New
default Desktop plans return a saved orchestrator recommendation within the same
planning response: quick/source-backed approach, unnecessary/optional/required
research, a request-specific reason and concrete source-check questions. The
proposed graph must implement that advice; source-backed recommendations retain
shared evidence, independent research review and frozen routes/models. Supplied
documents can satisfy the requirement without new web research. Explicit choices
retain authority. Contextual alternatives open new exact-request drafts without
submitting or starting work, creative cases omit the generic research push and
required checks omit a quick-answer shortcut. Historical plans receive no inferred
advice. 114 distinct affected Python cases and controlled UI checks pass; packaged
Python passed 17 focused cases. Signed installation completed with verified app
and SQLite recovery copies, fresh owned-service health, reopened app and 286
matching runtime files. Installed read-only bridge checks and exact-record digest
comparisons preserve both historical exploration jobs. No live provider rerun was
submitted; recommendation quality remains a model judgment to assess on new
requests. Private receipts remain under `outputs/research-advice-146/`.

**Requested source visibility follow-up — installed local 0.13.145:** Desktop
offers an optional research choice, committed and frozen with the unchanged exact
request. A source-backed text plan requires shared independent evidence; it cannot
fall back to blanket disclaimers. Supplied documentation does not force a new
browser step. Sources and research distinguishes proposed work, observed pages,
search-only results, supplied files and missing/changed receipts. Consulted links
come from job-bound saved host/tool receipts, not draft prose. A separate new-plan
draft can request research while preserving the old job. This is a narrow UI and
planning repair; generic fact-state propagation, uninstrumented shell coverage,
semantic truth and physical testing remain outside its proof.
109 distinct affected Python checks and controlled UI checks pass; the bundled
Python passed 12 focused checks. Signed installation has recovery backups, fresh
owned-service health and 286 matching runtime files. Installed read-only bridge
inspection confirms no recorded research for the two historical exploration jobs
and unchanged exact requests, plans, contexts, artifacts and decisions. No new
provider job was submitted. Private receipts remain under `outputs/research-choice-145/`.

**Requested quality repair — installed local 0.13.144, 2026-09-30:** new text planning
preserves recognized exploratory requests and rejects unsolicited implementation
blueprints. Recognized factual/technical verification criteria bind both agents to
independent source inputs and require structured candidate/source citations for
acceptance. Circular evidence, invented quotes/hashes, altered inputs and uncertain
claims cannot pass that contract. 126 affected-suite checks and one focused
research-graph check pass, and an offline
copy of the historical deficient proposal fails both scope and evidence guards.
Receipts are retained privately under `outputs/text-source-verification/`. Existing
jobs/decisions are unchanged. Signed installation has app/database recovery backups,
fresh owned-service health and 285 matching runtime files. Seventeen focused checks
pass in the bundled Python; installed read-only replay rejects the copied deficient
proposal and the workspace read route passes. The original plan hash is unchanged.
A fresh live provider request remains user work; narrow wording recognition and
source-bound model judgments do not certify exhaustive
claim coverage, semantic truth, compilation or electrical/physical testing. This
repair is not a new prerequisite for the ordered milestones below.

| Track | Milestone | Status and completion gate |
| --- | --- | --- |
| User-requested native capability | **Grasshopper definition authoring** | Installed in local 0.13.108 as `rhino.grasshopper` for Rhino 7/8 on macOS. Exact approved Python authors a new graph, saves native `.gh`/`.ghx` through installed official APIs, and independently reopens/solves both. A fixed slider/embedded-template/GhPython/panel graph passed on Rhino 7.32 and Rhino 8.35 from development source; Rhino 7 includes UTF-8/Unicode authoring and hash-checked cached assemblies. 85 focused checks passed, and the installed bundle registers the operation and detects Rhino 8.35. Rhino 7 uses owned processes and must be closed before execution. No installed-app graph execution, provider/channel run or user acceptance is claimed. Existing-definition editing, visual/geometric fidelity and other hosts remain outside this scope. |
| Active native capability build | **O15 — native Computer Use** | Background Safari navigation/scrolling, worker ownership, raw-capture handoff and user-selected single-profile delivery have run through the installed app. Locked-session native/scripted qualifications are recorded separately; the selected model-driven run does not establish lock state. Its review missed excess posts and overstated observations. Version 0.13.123 adds frozen post caps and complete claim audits, with 113 controlled affected tests passing. Live qualification of the stricter contract remains open before multi-prospect expansion. See the [feature plan](docs/computer-use.md) and detailed receipts below. |
| Next product build | **Shared-history lifecycle** | Local 0.13.112 includes a separate, confirmed Telegram history action after deletion of a standalone job with a versioned receipt of exact request and sent-event IDs. It removes local request rows and sent notice text atomically while retaining acknowledgement and deduplication identities, reply routes, external Telegram messages, native files and frozen copies. Focused tests and a synthetic job on a consistent real-database copy passed. The only previously deleted live job has an older receipt and correctly blocks; no live history was removed. Messages delivery text, older receipts, and shared history outside proven standalone ownership remain open. |
| Next runtime proof | **O14 — evidence-linked revision pilot** | Three bounded candidate adapters use reviewed links and conservative impact. A copied 45-slide plant job now has two successive user-selected PPTX/JSON/photo-manifest sets with exact preserved versions and review receipts. A fresh blind synthetic XLSX case froze the request and impact before an independent agent returned a candidate; Relay admitted it after exact affected, preserved and unknown-location checks. Technical review passed, with user selection pending. The agent dispatch remains outside Relay's runtime and is marked as such. Real-source blind qualification, Relay-owned dispatch receipts and XLSX selection/continuation remain. Rose identity, site suitability and license details remain unverified. The original live pipeline and installed app are untouched. |
| Active release work | **O13 — installation and onboarding** | In progress. Local 0.13.142/143 adds shared-plan review/renewal/Start and standalone messenger controls, visible failure reasons, separate ready/attention groups, and reversible removal from Jobs with retained exact history. Thirty-five distinct focused runtime checks across the affected planner, workspace, file-version and original-channel guards pass; 24 final planner/workspace checks pass after the stage-control adjustment. Controlled UI checks confirm the document gate, compact leading actions and stage cancellation at 360 px. Signed 0.13.143 installation completed with recovery backups, 283 matching runtime files and fresh owned-service health. Native exact Safari-plan inspection confirms leading Start/Discard with unopened-document gating; no user job action was executed. Private evidence is under ignored `outputs/desktop-review-actions-142/` and `outputs/desktop-review-actions-143/`. Clean Mac install, provider/channel/project setup, interrupted-setup recovery, safe app update/rollback and explicit migration; public signing/notarization and live end-to-end acceptance remain open. Local 0.13.140/141 simplify job inspection around status, results/review and compact workflows, with on-demand step inspection, folded technical history and one New task composer. Nineteen focused Python integrations, workflow/result projection cases, a focused-row polling regression and controlled browser checks pass. Signed 0.13.141 installation completed with recovery backups, 283 matching runtime files and fresh owned-service health. Native Jobs/composer and a retained cancelled job were inspected; its step inspector starts closed. The 0.13.140 native repeated-title click failure is preserved and resolved by distinct saved identities plus stable rows. Local 0.13.139 adds recorded revision/replacement pairs, explicit original desktop attachment checks, earlier-version dependency badges and bounded exact-version comparisons; 34 focused Python checks, workflow projection checks and controlled UI checks pass. Signed installation completed with recovery backups, 283 matching runtime files and fresh owned-service health. Native visual inspection remained blocked by the locked Mac. Local 0.13.138 adds compact read-only stage workflows, explicit attention/review panels and clickable exact-version Finder links; 16 focused Python checks, graph projection checks and controlled branching/sequence/correction/narrow-layout checks pass. Signed installation completed with recovery backups, 282 matching runtime files and fresh owned-service health. Native visual inspection was blocked by the locked Mac. Local 0.13.137 adds direct saved-record management from job details, a Safari Computer Use setup section and truthful service-dot colors; 31 focused checks and controlled UI verification pass. Signed installation has recovery backups, 281 matching runtime files and fresh owned-service health; native inspection confirms the green dot and read-only Safari setup check. Local 0.13.136 adds the main task workspace, frozen attachment intake, exact plan review/Start, shared job inspection and local output/control receipts; focused runtime/browser verification and installed native Jobs, composer and shared-job detail inspection are recorded. Signed installation completed with recovery backups, 281 matching runtime files and fresh owned-service health. Completed local stages can propose a separate plan from selected versions; blocked or uncertain recovery still uses the development CLI. Local 0.13.135 applied the [Desktop UI control system](docs/desktop-ui-system.md) across existing actions: shared sizing and states, grouped controls, leading save/review actions, destructive styling and common review cards. Four companion tests, nine setup/update tests and the native-session DOM fixture pass; local browser checks at 480/380 px and installed native home/model-settings inspection confirm the styles. Signed installation completed with recovery backups, 279 matching runtime files and fresh owned-service health. Workflow authority is unchanged. Browser action/page receipts also need a declared handoff to independent reviewers so a completed search can be audited without another search. O14 is not a release prerequisite. |
| Platform follow-up | **O12 — native Windows/Linux qualification** | Foundation in source; native host execution, access enforcement, service recovery and authorized provider-to-Telegram path still need qualification on each host. Do not infer Windows execution from imports or controlled macOS/Linux fixtures. |
| Separate reuse work | **O08 — reusable procedures** | Extraction and history discovery exist in development source. Cross-project quality and benefit over a reusable-script baseline remain unqualified. Procedure work does not certify fact-level provenance. |
| Conditional follow-up | **Job-owned authority** | Decide after O14 whether the read-only per-job database solves the portability/inspection need. Migrate authority only with a tested single-owner transaction and recovery contract. |

### O15 — native Computer Use

**Status: O15.3 installed single-profile checks verified; fresh batched discovery read five X searches successfully, but independent review exhausted its allowance on malformed provider function calls. The 20-person benchmark remains incomplete.** Build a native Relay capability for a user-selected,
already signed-in Safari window on macOS. Use public Accessibility and window
capture APIs behind a host adapter, with Relay-owned permissions, assignments,
evidence and recovery. No dependency on Codex's private controller or a second
job database. See the [feature plan](docs/computer-use.md) for contracts and gates.

**Next outcome: one complete prospect dossier through Safari/X and corroborating
sources.** Candidate discovery belongs to the research job; a user-supplied profile
URL is optional. Use Relay's native helper in the selected signed-in Safari session
to read a discovered relevant profile/post and a bounded sample of replies, then
establish actual workflow, tools, remaining manual work and contactability.
Return cited notes and a KEEP/REJECT/HOLD decision before expanding the candidate pool.
The first native live trial now reads a profile, scrolls and navigates to replies.
The changed-text blocker now returns a fresh observation without performing the
queued action. The existing worker loop is connected and a visible ownership panel
passes native local refresh/navigation and Take over checks with a scripted model.
Next qualify one bounded configured-model X case and exact post/link discovery. The saved-text reviewer is supporting infrastructure,
not completion of the research feature. A bounded development trial can precede
installed packaging; installed qualification remains required for shipped support.
The final prospect job requires 20 evidence-backed qualified people, retained
rejections/holds, candidate notes and source evidence, prospect/rejection workbooks,
and individualized unsent outreach drafts. Cross-source corroboration and reviewed
qualification are part of completion; reliable X access alone is not completion.

Authorized implementation order:

1. **O15.1 — observe, native fixture passes:** development CLI, portable contract and
   ad-hoc-signed macOS helper, with exact current-window/URL checks and bounded
   text/PNG output. Eleven controlled Python tests and native compilation/signature
   checks pass. User-granted Accessibility enabled a local Safari fixture: five
   exact text lines, selected-window PNG and wrong-URL rejection. Focused-window
   selection, Safari web-area URL lookup and AppKit initialization were corrected
   during native testing; failed receipts remain preserved. Installed permission
   identity, upgrade behavior, adversarial native target changes and continuous
   tab binding remain unqualified. No model is needed.
2. **O15.2 — finite native sessions implemented:** exact allowed URLs and bounded
   document scrolling, one host-user lease, persistent selected-tab binding,
   shared-database intent/result records, CLI pause/cancel and explicit no-replay
   recovery. A local native sequence navigated and scrolled with three text/PNG
   receipts; a tab-switch test blocked the queued action. Controlled tests cover
   interruption, stale replies, budgets, pipe transport and job ownership.
   Native redirect/permission-loss cases and installed qualification remain open.
   No arbitrary clicking, typing, social actions or credential entry.
3. **O15.3 — research and review, in progress:** development Desktop lists existing
   sessions and shows their frozen scope, action receipts and recent decisions.
   Pause/Cancel atomically compare the inspected state and preserve in-flight or
   uncertain outcomes. Controlled Python and isolated UI-controller fixtures pass.
   A separate native development preview saved Pause/Cancel decisions for two
   synthetic sessions with zero native actions; installed UI remains unqualified.
   CLI evidence export now freezes verified saved text/PNG bytes and provenance
   into a registered, unreviewed ZIP artifact for declared inputs. Offline
   verification, interrupted-publication recovery and optional post-commit `.relay`
   export pass controlled checks; three saved native observations exported without
   new browser calls. Explicit worker-target setup, configured-provider profiles and the shared bounded
   worker loop are implemented. Resume remains explicit recovery. A separate saved-text reviewer freezes the pack, claims, Gemini model and one-call budget, validates literal citations and registers its report without inferring acceptance. Scripted tests pass. The first live response had correct synthetic verdicts but invalid limitations formatting and remains preserved without replay. The explicit schema initially produced HTTP 400. After authorized reconciliation, a new request with simpler schema constraints passed live review and report registration on the same synthetic pack; 26 focused checks pass. Earlier attempts remain preserved, and bounded redacted provider diagnostics now survive rejection. The separate native X trial now reads a real profile, scrolls and opens replies; a fresh observation captures reply text. Post-action geometry settling was corrected, with 23 observation/session tests passing. Pre-action refresh now returns a no-effect receipt and a fresh token; the worker makes the next decision. A native ownership panel shows the task/state with Pause, Stop and Take over. Real local Safari tests with a scripted provider pass dynamic refresh, navigation, output completion and takeover before a queued action. There are 49 passing focused tests and 61 passing affected integration checks; a broader capability run retains one pre-existing clarification/catalog mismatch. Local 0.13.115 now contains these routes; installation preserved the app identity and data, and both existing services restarted with fresh health. Installed signature, packaged runtime, worker imports, helper receipt compatibility and the read-only desktop session route pass. That 0.13.115 deployment used an external development helper without a production target; the bundled automatic route below supersedes that setup. No paid X worker ran. Exact post/link discovery, complete prospect evidence and installed native permission/control qualification remain open. This addresses the
   same evidence handoff need tracked in O13 without silently changing old reviews.
Automatic worker startup now freezes exact URLs, journals a single launch, opens
   and foregrounds a dedicated default-profile Safari window, and binds it before
   any model call. No selected target is required when the bundled launcher is
   available. Packaging includes the helper with its final signed binary receipt.
   Native synthetic startup/scroll/navigation passed from Safari in the background;
   ownership release and uncertain launch stop without reopening or reclaiming focus.
Router-inferred Safari profiles no longer lock every role to computer use when
   the user did not name a provider/executor. New proposals can include a text-only
   reviewer; explicit locks and saved executable scopes remain fixed. Forty focused
   checks pass, and the actual corrected failed proposal validates offline with
   the proposed catalog. Failed live records remain unchanged; no paid replay ran.
Approved standalone plans now bind sessions to their existing result/export job
   identity in the assignment transaction. This records ownership without creating
   a pipeline or accepting results. Fifty-six focused session, worker, launch and
   ownership/deletion checks pass, including rollback and conflicting-owner cases.
Local 0.13.117 contains both corrections with fresh service health, verified
   packaged runtime/helper and 274 matching release-source files. Its validator
   accepts the saved corrected proposal under the proposed catalog; the live
   failed plan is unchanged. Paid model-driven X execution remains unqualified.
4. **O15.4 — qualify installed behavior, partial:** local 0.13.116 now bundles
   the signed helper. Installed runtime/helper startup, new-window binding,
   scrolling/navigation, receipt verification and provider-profile availability
   pass without a manually selected target. Existing macOS grants report ready;
   both services restart with fresh health. Development native tests additionally
   verify bringing background Safari forward. Installed native tests began with
   Safari foreground despite the focus-test setup, so they do not add a separate
   background-transition qualification. A controlled takeover event cancels a real
   native session before its queued action; the new installed ownership buttons
   were not clicked through the UI tool. Fully quit Safari startup and a paid
   profile/post/reply case remain unqualified. Record exact source coverage,
   usage, review and gaps. No login retry campaign or outreach.

One-app background research feasibility: a development Safari Apple Event probe
   created a dedicated local window, read dynamically updated text and HTML links,
   and navigated between two synthetic pages while the session remained locked
   before and after every command. Both fixture windows were finally confirmed closed after unlocking and UI
   inspection; initial scripting window lists retained a stale fixture entry.
   Original windows remained. No extension, screenshots, provider calls or lock
   setting changes were needed. At that prototype checkpoint, JavaScript scrolling
   was denied by Safari's setting. The subsequent bundled adapter integration and
   qualification are recorded below; the visual worker still requires an unlocked
   session. An earlier Apple Event timeout remains unexplained.

Background adapter implementation (0.13.118): newly planned default Safari scopes
   now use bundled Apple Events, preserving explicit visual targets and refusing
   transport changes after approval. Loaded text, exact navigation, optional fixed
   scrolling and bounded link extraction use the existing native action/evidence
   journal and ownership controls. Scrolling is removed from the tool surface when
   Safari denies JavaScript. Forty-eight focused checks and a native scripted-worker
   local test pass. A zero-provider X trial captured profile and loaded post text;
   dynamic post links require JavaScript. An installed app-associated background job completed the scripted local worker
   flow. A fresh native X trial with JavaScript enabled read loaded posts and exact
   post links and executed one scroll; no provider ran. Version 0.13.119 adds the
   missing packaged-service app association, bounded dynamic settling and retained
   native failure codes. Thirty-six service/installer/handoff/diagnostic checks pass.
   Version 0.13.119 is installed: 274 source-matching runtime files, verified
   signatures, app-associated Aqua service, fresh service health and an available
   background Safari worker. The installed app-associated worker completed local
   navigation and file delivery with scripted replies while locked. A separate
   installed-native X trial read loaded posts and exact links and executed one
   scroll, also beginning and ending locked. No paid provider ran. This qualifies
   the bounded background transport, not a complete model-driven prospect job;
   old blocked jobs are not replayed by this change.

Live model-driven qualification: the configured Gemini computer worker completed
   a bounded profile/five-loaded-post summary and structured evidence output, and a
   separate Gemini reviewer completed its review. Artifact and native receipt hashes
   were verified read-only. Two quality gaps remain: a queued scroll returned fresh
   evidence with `action_executed=false`, after which the worker finished without
   executing a scroll; and the reviewer received producer-authored evidence rather
   than the immutable native captures. An ACCEPT report is therefore not proof of
   independent raw-source verification. Prioritize raw-capture handoff and explicit
   accounting for unmet action requirements. This run does not establish lock state,
   complete prospect research, or user acceptance of the artifacts.

Follow-through (0.13.120): new reviewer claims bind a hash-verified raw capture pack
   from the exact computer producer attempt. The reviewer receives all saved text,
   coverage and action outcomes and must read the complete pack. Missing/changed
   evidence blocks before dispatch. Known no-action refreshes remain incomplete
   until an explicit matching action executes; otherwise a blocked report is required.
   The supervisor also checks completed native work. Controlled tests pass (28
   focused, 87 affected integrations); no new live/provider qualification is inferred.
   Earlier results remain unchanged and do not acquire retroactive verification.
   Installed 0.13.120 passes bundle verification (275 source-matching files), fresh
   service health and ten controlled installed-module cases. The next live research
   job still needs its own output/evidence review; no paid rerun was dispatched.

Output-generation follow-through (0.13.121): a later live job confirmed its scroll
   but hit a received provider output limit while writing evidence. The computer
   adapter had excluded generation recovery despite remaining requests. New scopes
   permit bounded local-write/report recovery after confirmed complete native work;
   the incomplete candidate is discarded and native tools stay disabled throughout
   recovery. Sectioned file writes/appends preserve confirmed bytes. Original budgets,
   ownership, cancellation and no-uncertain-replay rules remain. Seventy-eight
   controlled affected tests pass; the old blocked attempt is not resumed or rewritten.
   Version 0.13.121 is installed and verified (275 runtime files, fresh service
   health, ten installed-module fixture cases). A new live provider qualification
   remains separate; the existing blocked job records are hash-confirmed unchanged.

Research routing follow-through (0.13.122): missing file-source choices are now
   corrected with a source-only patch merged onto the exact saved proposal. This
   avoids regenerating research descriptions while excluding unrelated uploads.
   Normal source and scope validation still applies; original/correction/merged
   receipts remain separate. Seventy-four controlled routing/planning tests pass.
   Version 0.13.122 is installed with 275 matching runtime files, fresh service
   health and five installed-module regression cases passing. The earlier failed
   request and blocked production remain unchanged.
   No paid rerun or acceptance is inferred from this fix.

Research quality follow-through (0.13.123): a selected single-profile run completed
   background navigation, an executed scroll, raw-capture handoff and delivery,
   but its review missed excess post records and overstated observations. New
   research plans now enforce recognized post caps and require a bound audit of
   every labeled summary claim, with exact citations and candidate/source hashes.
   113 controlled affected tests pass. Semantic entailment still requires model
   judgment; a live qualification of the stricter contract remains separate.
   Installed 0.13.123 has 276 verified source-matching runtime files, fresh service
   health and 14 installed-module quality cases passing. Completed production
   metadata remains unchanged.
   Multiple-prospect expansion remains deferred until that qualification.

Citation follow-through (0.13.124): a live attempt stayed within five posts and
   executed its scroll, but four excerpts flattened captured line breaks. Strict
   preflight correctly blocked review before dispatch. The same raw-capture check
   now runs at producer finish and in the supervisor, with exact-slice diagnostics
   for unambiguous whitespace-only corrections inside the existing budget. Matching
   remains strict, sources remain unchanged and no native action is replayed.
   Installed 0.13.124 passes 276-file bundle verification, fresh service health
   and eight installed-module citation cases; 90 affected source tests pass.
   A new live qualification remains separate; the blocked attempt is preserved.

Subsequent live check on 0.13.124: a single-profile run completed with exactly five
   selected posts, literal citations that pass raw-capture validation, one executed
   scroll, no unexecuted actions and a complete 14-claim audit. Read-only verification
   of the saved candidate/review passed; no correction-tool errors were recorded.
   This qualifies the bounded execution and validation path, not blanket semantic
   accuracy. The reviewer still endorsed a speculative inventory-automation benefit
   without specific evidence. Expressed AI interest was absent in the sampled posts;
   hypothetical tooling benefit must not become a positive prospect signal.
   Prospect-qualification rules remain to be settled before broader research.

Twenty-person benchmark follow-through on 0.13.124: the user authorized discovering
20 people using the original criteria. The Desktop-started discovery attempt
blocked before native/provider execution because its plan remained Desktop-owned
while progress switched to Telegram. A fresh discovery plan through the existing
Telegram route reached three of six X search pages. Four consecutive navigation
requests refreshed without executing because captured text contained a changing
countdown. The next provider response reached its generation output limit; pending
navigation correctly prevented file-only recovery. No research artifacts were
delivered and the reviewer did not dispatch. Eleven native receipt file sets passed
read-only size/hash checks; raw-text diffs isolate the countdown changes. Private
receipts retain both failed attempts. Fix the channel ownership handoff and
navigation freshness, then resume bounded discovery and person-by-person review;
the complete 20-person benchmark remains unfinished. No app behavior changed in
this qualification run.

Follow-through in 0.13.125: background exact-URL navigation validates ownership,
source URL and challenges without requiring identical incidental page text.
Desktop Start transfers unexecuted plan ancestry to Telegram in the same commit,
with a receipt preserving original channel/request identities. The orchestrator
now receives explicit guidance to own research batching in one saved workflow,
preserve the requested total, hand off reviewed sources and budget setup/refresh/
writing calls. No fixed prospect template, attempt reset or user acceptance is
introduced. Controlled, native and installed qualification receipts are recorded
separately; the full 20-person outcome still requires live completion.

The installed 0.13.125 helper passed a local countdown-navigation fixture, stale
token rejection and changed-source-URL rejection. Its 276 bundled sources matched;
five installed ownership cases and 31 focused source checks passed. Two unrelated
PowerPoint cases in a broader 93-test run were blocked by unavailable rendering
capability; the other 91 passed. Relay then independently created one eight-stage
prospect workflow with research batches, but proposed five discovery URLs with the
default eight-request allowance. The workflow was paused before research dispatch.
Version 0.13.126 adds a versioned multi-page budget floor and uses the existing
bounded planner correction when a worker cannot cover its declared grant. Batching
remains the orchestrator's responsibility; no queries or partitions are scripted
into the benchmark submission. Installed 0.13.126 passed 27 affected source tests,
13 installed checks, signature/runtime verification and fresh service health.
The unexecuted predecessor was cancelled with its records preserved. A fresh
whole-goal request reached the configured orchestrator, which returned HTTP 402
with a depleted-prepayment-credit diagnostic before creating a replacement
workflow. No research workers ran in that retry. Live batching and the full
20-person outcome remain unqualified pending provider availability.

A later user-submitted whole-goal request successfully created a Relay-planned
six-stage workflow and a discovery worker with 24 requests/8,192 response tokens.
Its first background Safari launch/read became uncertain before any research
provider request. The transport raised a native error which the worker's error
path failed to preserve; the saved record cannot establish its precise cause.
Version 0.13.127 retains bounded native codes, operation and failure phase through
the journal and supervisor without clearing uncertainty or replaying actions.
62 affected checks pass, including a private-pipe integration. The original
attempt and pending later stages remain intact; full batching remains unqualified.
The diagnostic update is installed with 276 matching runtime sources, fresh
service health and 20 passing installed checks. With explicit user authorization,
the failed native session was reconciled as stopped while preserving its unknown
outcome and original receipts; normal production cancellation released its scheduler
reservation and the old workflow was cancelled to prevent further
dispatch. A fresh original-goal request was submitted to Relay without supplied
searches or batch partitions. An intervening proposal granted only bare X landing
URLs despite requiring targeted searches; it was stopped with no worker attempt.
Relay was given that capability mismatch and chose five concrete search URLs for
its replacement. The producer completed six native observations/actions and 11
provider requests, saving seven post-based leads. All six receipt file sets passed
hash/size verification. The independent reviewer exhausted both planned attempts
on `MALFORMED_FUNCTION_CALL` while generating its JSON audit (two responses per
attempt, zero tools executed). No candidates were accepted, no later research
batch ran and no outreach was sent. Saved evidence can support a future bounded
review recovery without repeating Safari discovery; full qualification stays open.

The visual adapter requires an unlocked interactive Mac session; window changes,
unknown URLs, permission loss and login/challenges block rather than cause a
fallback. Implementation does not authorize installation, paid execution or live
account research. A later five-candidate pilot is a separate job. General
desktop actions, other OS adapters and automatic prospect requalification remain
deferred. O15 does not make unfinished O13/O14 or lifecycle work prerequisites,
nor does it replace their acceptance gates.

### O15 structured research operations — core and campaign installed in 0.13.129

Design recorded in [Shared operation contracts](docs/shared-operation-contracts.md).
Extend the existing assignment, workflow, artifact-binding and handoff compilers
with reusable typed operation-family contracts, not one custom contract per job.
Immediate order: checkpointed typed claim audits and code-generated audit files;
separate candidate discovery from the current profile/post contract; typed
content identities across tool handoffs; then bounded candidate/batch progress.
Qualification criteria and target counts are job data. The model chooses queries
and supplies judgments; Relay owns IDs, source bindings, persistence, serialization,
budgets and transitions. Preserve existing versioned assignments, review gates and
the shared database authority. Qualify the audit change from saved captures before
any new browser discovery; no unrelated contract migration is a prerequisite.
Implemented the provider-agnostic family registry, attempt-bound transactional checkpoints,
typed audit/candidate submissions, exact-source validation, deterministic exports
and supervisor verification. New planning selects discovery/profile explicitly;
candidate identity and each requested field join the audit. Typed JSON handoffs
reject contract mismatches and reuse the existing geometry validator. Frozen
legacy assignments remain unchanged. Prospect and supplier fixtures exercise the
same candidate contract with different parameters. An isolated copy of saved
20-claim evidence assembled seven batches in eight scripted responses; all
verdicts remained uncertain, with no provider/browser call or production mutation.

Installed 0.13.128 has 278 matching runtime sources, verified signatures, fresh
service health and 21 passing installed checks. The original blocked run
retained its task states, attempt counts and frozen assignment hashes.

Research campaign controller implemented: explicit versioned job policies compile
bounded discovery/assessment slots, with independently audited criterion decisions,
cross-batch identity tracking, replenishment, target stop and honest shortfall.
The existing pipeline owns queues and attempts; empty discovery and repeated
identities consume capacity without padding results. Exact raw evidence and
review receipts accompany the final ledger. Paused, cancelled and uncertain work
does not automatically restart. A controlled 20-entity integration passes through
the actual production-completion path; this is not a live research result.
Installed 0.13.129 matches all 279 release sources and passed 22 controlled
installed-runtime checks. Signatures and fresh service health were verified;
the previous blocked research run retained its task states, attempts and frozen
assignment hashes. No live research was launched during this update.

Live campaign follow-up exposed a Safari Apple Event timeout before any worker
provider call, plus an infeasible discovery grant containing only the X home URL.
Discovery preflight now rejects X landing pages/empty searches before dispatch,
and native timeout diagnostics identify the scripting step. The timeout duration
and no-replay rules remain unchanged. Thirty controlled checks pass; a subsequent
read-only Safari readiness check passed. The failed native outcome remains unknown
and requires explicit reconciliation before a fresh run; this is not live campaign
qualification.
Installed 0.13.130 matches 279 sources, passes 30 installed campaign/scripting
checks and has verified signatures/fresh service health. Its new preflight rejects
the exact saved invalid plan. The uncertain run remains unchanged; a fresh request
preserving the original brief is prepared but awaits the user's recovery choice.

Repeated campaign launch failure was reproduced on localhost with the installed
helper, before any provider request. Direct AppleScript succeeded. Source 0.13.131
isolates the single create-document command in a bounded child OSA process, uses
numeric window snapshots and checks the exact URL/tab binding. The repaired
helper passed the app-associated local worker flow with scripted replies and zero
paid requests. The failed campaign remains uncertain; live X qualification of
this repair is still outstanding. Installed 0.13.131 passed signatures, 279
source matches and 23 worker checks, but both installed native fixtures created
windows then failed global process rediscovery. Source 0.13.132 checks the bound
Safari PID/bundle/launch timestamp directly; 24 controlled worker checks pass.
Installed 0.13.132 matches 279 sources, has verified signatures and fresh owned
service health, and passes all 24 installed worker checks. Its app-associated
native localhost worker flow completes creation, exact identity binding, evidence
reading, navigation and delivery with four scripted responses and zero paid
requests. The campaign failure row remains byte-for-byte unchanged; no live X
research or locked-session qualification of this update is claimed.

A subsequent live campaign completed initial X observation and one scroll, then
failed its Russian-language search navigation. A localhost comparison reproduces
Safari acknowledging raw Cyrillic navigation while leaving the old URL unchanged;
the percent-encoded spelling succeeds. Source 0.13.133 freezes encoded new grants
without changing query meaning or old assignments, and separates blank-window
creation/identification from initial URL loading. Forty-six controlled affected
checks pass. The uncertain campaign is preserved and no action is replayed.

Installed 0.13.133 passed package verification and all 46 controlled installed
checks, but its native Unicode fixture hit the process-identity guard before a model
call. Source 0.13.134 binds scripting sessions to kernel PID/start-time/executable
identity after initial Safari discovery, avoiding repeated AppKit metadata lookup.
An owned-process native check verifies stable identity and rejection after process
termination; constructed changed start/path identities do not match. Both signed
candidate and installed 0.13.134 worker/helper flows pass the encoded Cyrillic
localhost fixture with delayed responses: creation, URL binding, evidence reads,
navigation and delivery. Each uses four scripted responses and zero paid requests.
The installed app matches 279 runtime sources, has verified signatures/fresh service
health, and passes all 46 focused installed checks. The failed live campaign attempt
is unchanged; no live X or locked-session verification of these updates is claimed.

Remaining: live provider qualification and dedicated deterministic workbook/draft
renderers. Final output stages currently use existing production workers and
independent review, supplied with the campaign ledger and exact source artifacts.
These changes do not complete the twenty-person research run. See
`outputs/shared-operation-contracts/CHECKS.md` and
`outputs/research-campaign-controller/CHECKS.md` for commands and limitations.

### Next `.relay` build

1. **Implemented and qualified on an isolated real-job copy:**
   preview the saved pipeline's exact plans, runs, attempts, revision evidence,
   decisions and message receipts. Delete only proven owned rows in one transaction
   after a fresh exact-state confirmation. Block active, uncertain, missing or
   shared downstream work. Retry private `.relay` view and Relay metadata cleanup
   from a durable receipt after interruption; retain native deliverable copies and
   files outside Relay's managed folder. Audit the copy for orphaned records and
   confirm the desktop control in the installed app. The controlled companion
   fixture, isolated real-job copy and installed inventory have passed. A live,
   user-approved standalone deletion also completed; the pipeline Delete path
   remains qualified through controlled and installed read-only checks.
2. **Exclusive media-task deletion installed and qualified on an isolated real-job copy:**
   record exact stage request, backend job and watched agent task IDs, and project
   attributable execution and delivery receipts. Keep unrelated turns and shared
   channel messages outside the job view with explicit coverage markers. Prove a
   single completed Gemini task, one backend turn, exact incoming request, provider
   history, artifacts and sent delivery before deleting its Relay-local records.
   Save hashes of private provider traces in the cleanup receipt and retry after
   interruption. Reused tasks block. Pipeline Delete retains shared conversation
   records and user-owned files.
3. **Standalone result ownership installed and live Delete exercised:** record the
   exact root plan, request hash, channel and current selected run before exporting
   a result. Offer explicit verified backfill for older selected results with a
   sent handoff and matching Relay folder marker. Preview the complete plan/run
   graph; preserve shared channel conversation and sent delivery, block pending or
   cross-job work, and retry private-view cleanup from the atomic deletion receipt.
   Controlled tests and an in-memory copy of the real database passed one
   unblocked case and correctly blocked one active case. The installed app then
   deleted the user-approved unblocked Rhino job: 155 owned rows and private
   `.relay` metadata are gone; selected file hashes match before and after,
   shared sent delivery remains, and the recovery receipt is complete.
   Independent shared-history
   deletion and ordinary watched agent chats remain outside this contract.
4. **Installed; qualify further:** define one versioned job-process ledger: exact objective, stage plans and
   assignments, frozen inputs, worker attempts and receipts, checks and exceptions,
   review/selection decisions, output versions, channel delivery state and
   replacement events. Record IDs that join to the existing authoritative rows;
   never reconstruct a decision from prose or a declared dependency.
5. **Installed; qualify further:** project those records into `.relay/job.sqlite` after commit. Mark missing,
   truncated or externally stored evidence explicitly. Keep the versioned JSON
   snapshot for readable handoff, and verify both exports describe the same
   committed snapshot. Test restart and failed export with small fixtures.
6. Revisit job-owned authority only after this projection answers real inspection
   and continuation needs. Use O14 to prove that another agent can consume the
   same frozen plan and return a candidate under Relay's review and recovery rules.

### Shared-history lifecycle gate

Installed local 0.13.110 deletes one idle Relay-managed provider task only
when its completed turns, local reply routes, sent delivery, provider history
and private traces have exact single-task ownership. One direct image/video
request can join that graph when its request, dispatch and single provider turn
match; finished attachment batches and uploads remain tied to a durable
deletion tombstone so late attachments cannot resubmit the original caption.
A fresh digest guards the
atomic database deletion; a receipt retries trace cleanup without replaying it.
External channel messages, external provider conversations, project folders and
native/input files remain. Codex tasks, pipeline-linked media tasks and unknown,
active, pending or shared records are blocked. Saved work hides Delete when the
preview is blocked and shows the reason. An isolated copy of one real completed
image task passed the full delete/recovery path, and four live tasks have
unblocked read-only previews in the installed bridge. In 0.13.113, a native
Delete click on the user's pavilion task exposed an asynchronous confirmation
bug: Tauri denied the dialog command, yet the truthy Promise passed the old
synchronous guard and a complete deletion receipt was written. Version 0.13.114
uses an in-window dialog and its installed Cancel path left a different eligible
task and its history intact. No further live task was deleted.

Local 0.13.112 offers a second confirmation after a newly deleted standalone
Telegram job. Its job-deletion receipt freezes the exact request and sent-event
IDs. The history action requires complete, terminal request and sent-delivery
records, retained deduplication state, no new event or other typed owner, and a
fresh digest. It deletes the retained local request rows and clears sent notice
text in one transaction; sent flags, event IDs, reply routes, incoming-update
deduplication, external Telegram messages, native files and already frozen copies
remain. A controlled synthetic job passed on a consistent copy of the real
database. The earlier live deleted job has no frozen ownership list, so history
deletion remains unavailable for it rather than guessing from event prefixes.
Extend this exact-ownership policy to Messages delivery and other shared channel
records only after their deduplication and callback contracts are proven.

### O14 build order and completion

1. **Freeze a small acceptance case.** A supplier XLSX and catalog XLSX share a
   stable product key. Specify one changed material value, an independent value,
   a conflicting or missing source, and expected affected/unknown locations. Use
   tiny controlled files first; freeze the comparison method before a real trial.
2. **Record reviewed fact links.** In authoritative SQLite, bind a typed product
   fact to exact source artifact/hash and sheet/cell, evidence and review state;
   bind it to exact output artifact/hash and cell plus its check. Record which
   output fields have complete reviewed coverage. A declared input alone never
   creates a fact link. Preserve superseded versions and decisions.
3. **Project the job.** Export the committed job/fact/check records to read-only
   `.relay/job.sqlite` and the existing versioned job view. Verify snapshot
   identity, missing artifacts and incomplete coverage. Export writes must not
   authorize an action or be trusted on import.
4. **Plan impact.** An explicit source-version replacement reports affected
   locations, locations supported as unaffected, and unknowns with reasons.
   Unaffected requires complete reviewed bindings. A changed hash, missing source,
   conflicting manufacturer statement or ambiguous product key blocks a complete
   impact claim. Planning does not approve or start a rebuild.
5. **Revise one format.** Produce a distinct XLSX candidate for reviewed cell
   changes, check supported untouched values/formulas/styles and reject unsupported
   workbook features. Retain the original, independent review, user selection,
   exact authorization and recovery receipts.
6. **Qualify the runtime.** Test change, non-change, ambiguity, stale source,
   unsupported file, restart and failed revision with small fixtures. On an
   authorized real case, freeze the exact change request and impact plan before
   dispatch, give that handoff to an agent through a documented interface, and
   check the returned candidate against affected, unaffected and unknown
   locations. Preserve review, selection and recovery receipts. Comparison with
   another execution method is optional evaluation.

O14 does not require general entity extraction, catalog-scale retrieval, arbitrary
manual-file reconciliation or broader PPTX/CAD editing. After its XLSX proof, test
the same fact/decision/impact contract in one second domain, such as a plant change
in a presentation that leaves independent climate research valid. Expand the model
only if that transfer test succeeds.

The controlled source implementation uses the frozen case in
`tests/fixtures/o14_acceptance.json`. It records only explicit, reviewed XLSX
material-cell bindings and declared output coverage; it does not discover facts
from a workbook. `plan_impact` is read-only, and the candidate writer accepts only
the exact affected direct-value cells in a simple supported XLSX. A registered
candidate is not accepted or selected by this operation. A distinct reviewer can
record accept/revise after revalidating exact candidate bytes, and selection needs
an explicit actor and action receipt. A shared desktop review screen now exposes
these decisions for candidate types that have an adapter. Each action revalidates
the exact candidate and plan. The installed app's review screen displayed the
isolated motorcycle candidate and its evidence; no review or selection action
was exercised.
The ten-part real-case comparison below is complete; its post-control fix means a
real holdout and XLSX selection/continuation qualification remain before O14 is
complete. A separate small blind agent handoff trial is recorded below.

A translation-specific extension has also replayed the user-selected ten-part
motorcycle pilot in an isolated development database. Exact source-row and output
links were recorded from the selected workbook and verification report. Changing
only Harley source `Лист1!B7` from `CLAMP` to `BOLT` in a copy marked part `10014`
for review, preserved six independently supported translations, and kept three
unresolved Yamaha names blank. Its candidate clears the affected Russian name and
name-confirmation link; it retains the saved catalog title as historical evidence
with a review warning. Only six cells in the affected output row changed in the
original candidate. The comparison found that five Harley source locators still
named the old file. A development-source fix rebinds those locators and produced
a separate candidate with 11 logical cell changes across two OOXML package parts.
Both candidates are unselected, and no new Russian name was researched or approved. The
private run receipt is under `outputs/o14-motorcycle-revision/`. This demonstrates
conservative revision for ten explicit links, not automatic fact discovery, batch
translation, live app execution or an advantage over a general agent.

The reusable boundary now includes normalized reviewed links and impact records:
typed source and output locators, evidence, coverage, version hashes and reasons
for affected, supported unchanged and unknown locations. Both adapters save the
same impact shape with a candidate and expose it in the read-only job export and
desktop review. Each adapter still needs a safe source reader, evidence-link rules,
change interpretation and native-file validator. The motorcycle source parser and
workbook writer remain pilot-specific.

**Blind XLSX handoff qualification (2026-09-29):** A fresh four-workbook synthetic
case froze its exact request, registered source versions, reviewed links,
affected/unchanged/unknown impact and evaluator answer before an independent
agent received the handoff. The agent changed only the affected material cell,
preserved one supported independent cell and left a conflicting cell and an
uncovered cell unchanged with reasons. Relay admitted the returned XLSX under
an idempotent external submission key and an independent technical review
accepted its exact bytes. The job's JSON/SQLite views contain the handoff,
submission and review; no user selection was inferred. The process ledger
explicitly marks the external dispatch/attempt outside Relay's runtime. The
qualification report (private evidence) records
hashes, package differences and checks. This qualifies the documented handoff
and candidate gate for explicit cells in a small fixture. A blind real-source
case, Relay-owned dispatch receipt and XLSX selection/continuation are still
needed for the wider O14 completion claim.

The second native format transfer is a controlled three-slide PPTX case. Two
spreadsheet values have explicit links to exact slide text runs; a third run has
incomplete coverage. Changing `North Plant` to `South Plant` yields one affected
run, one supported unchanged climate run and one unknown run. The candidate
changes only slide 1's XML package part, retains other package parts byte-for-byte,
and remains unreviewed and unselected. The installed 0.13.103 review screen showed
the exact evidence and coverage in a disposable job copy; 0.13.104 also refuses
an original source with no reviewed link to the deck. This qualifies the
shared contract for bounded PPTX text runs, not arbitrary slide or chart edits.
The private controlled case is under `outputs/o14-pptx-transfer/`.

**Real plant-deck audit (2026-09-28):** An isolated, read-only audit pinned the
existing 45-slide Bullhead City delivery, slide specification, research export,
photo manifest and delivery receipt by hash. Oleander has four exact PPTX text
runs across the shrub schedule (table shape 6, row 3, column 0) and photo slide,
plus one matching native picture and its attribution. The original pipeline's
source and delivery files lack registered `production_artifacts` versions and
reviewed per-location links. Climate slides 2–7 contain candidates for
preservation; slide 8 contains plant imagery and was misclassified in the
initial frozen list. Whole-slide validity has not been certified.
Development source now inspects native PPTX table cells and guards an edit to
one exact cell when a text run repeats in a shape; this does not register a
reviewed dependency or revise the real deck. A controlled in-memory edit of the
hash-pinned deck changed only the targeted slide-18 XML; all other package
parts, including climate slides and the photo, stayed byte-for-byte unchanged.
This checks the native edit primitive, not the validity of those other slides.
An isolated Relay job registers the five exact baseline file versions and
ten reviewed **structural membership** links from the research row/photo
manifest to table runs, card text, picture and credit. Its read-only
`.relay/job.sqlite` now projects seven artifacts, 18 links and 25 coverage entries.
A pre-agent withdrawal plan derived from those persisted links classifies ten
locations as affected, eight exact climate value runs as independently
supported and unaffected by Oleander withdrawal, and seven broader slide
assessments as unknown. NOAA station normals support the approximate annual
temperature and degree days; a University of Arizona city-level table supports
zone 10a and 30–35 °F, using an older USDA map. These source links do not certify
the exact site, whole slides, botanical claims or photo identity. Whole-slide
completeness is barred by this
adapter. Frozen case and protocol (private evidence).
The two climate PDFs were independently retrieved and reviewed; no persisted
deck changed, agent control ran or live job mutated. This is development source
and a disposable isolated job; the new
behavior has not been installed in the app.

**Model-neutral change-plan handoff (development source):** a separate
authoritative record freezes the exact request, caller key, actor, baseline
artifact and conservative plan before any agent edit. Same-key retries reuse an
unchanged plan after interrupted export; changed evidence requires a new handoff.
The record projects into JSON and SQLite `.relay` views and the process ledger.
The first controlled plant handoff identified 10 affected locations but missed
six Oleander photo-attribution notes. Inspection of the native deck exposed that
gap. An isolated job copy now records those six exact notes runs and has a new,
current 16-location handoff (private evidence): 16
affected, 8 supported climate runs and 7 unknown slide assessments. A
removal-only native candidate (private evidence)
was submitted through the model-neutral contract; exact package admission passed,
with only slides 18 and 39, slide 39 notes and the orphaned Oleander image part
changed. The candidate remains unreviewed and unselected. Its photo slide has
empty space, and the original companion files still name Oleander. The live
pipeline was untouched. The user then supplied a rose image as a replacement.
Its exact bytes are pinned in a typed handoff. A first render exposed two shared
sourcing footers absent from the 16-location plan. Those exact runs were linked
and a new 18-location handoff (private evidence)
and replacement candidate (private evidence)
were created in a copied job. Only slides 18 and 39, slide 39 notes, picture
relationships/types and replaced media changed. That candidate is pending
review and unselected. The user's positive layout review is pinned to this
candidate as scoped feedback (private evidence);
it does not constitute semantic acceptance. A later audit found one misleading
speaker note on slide 18. A 19-location handoff (private evidence)
and PPTX candidate (private evidence)
correct that note. The visible slide package members are byte-identical to the
layout-reviewed version. Exact patches revise the companion `slides.json` and
photo manifest, pinning the rose image and leaving unknown rights fields empty.
A versioned `.relay` bundle ties these files to the PPTX candidate, the exact
request, baseline hashes and 13 declared cross-file checks. All checks pass in
the isolated job copy. The user's exact positive response is recorded as
acceptance of the provisional set. A later exact response attests permission to
use the pinned image; source and license details remain unsupplied. The accepted
set is selected in the isolated copy. Rose identity and site suitability remain
open. Development source now has an atomic set selection
contract that also selects its native candidate and projects all three revised
artifacts together. The live pipeline and installed app were untouched. The
original handoff record (private evidence)
remains an audit of the earlier incomplete scope.

**Second revision from selected state (2026-09-28 to 2026-09-29):** The user's later exact
request froze a continuation plan (private evidence)
before a new candidate was produced. Seven exact PPTX text/notes edits reconcile
selection and image permission wording while retaining the unknown cultivar and
site-suitability caveats. Seven `slides.json` patches and three photo-manifest
patches make the native and companion records agree. The permission value and
image hash are checked against the selected parent's saved decision receipt.
The candidate set (private evidence)
passes 13 cross-file checks and complete package comparison: only slide 18/39
XML and their notes XML changed, with 258 of 262 members reused verbatim. The
rose image bytes and relationships are unchanged. The rendered slides 18 and 39
were inspected. The user's exact positive review was recorded against the
second set digest; the PPTX and both companion files were selected together in
the isolated `.relay` job view. The first rose set and its selection receipt
remain in history. The selection receipt (private evidence)
pins the decision. This proves a bounded repeat revision, not general dependency
discovery or installed-app execution.

**O14 real-case comparison:** The frozen five-file ten-part motorcycle case was
run against a fresh general agent without Relay state or internet. Both methods
correctly flagged one conflicting changed part, preserved six supported names
and three unresolved names, and left the changed Russian name blank. The control
identified five stale source locators in Relay's original candidate. After the
development fix, both changed the same 11 cell locations; the corrected Relay
candidate touched two OOXML package parts and the control export touched nine.
Because the fix followed the control, this is not a blind superiority result.
The setup cost of ten reviewed links and prior research is excluded from the
revision comparison. The private comparison record (private evidence)
contains the hashes, measurements and limits. Neither candidate was reviewed or
selected; the corrected implementation is installed in local 0.13.108.

**Selection continuation in local 0.13.108:** An explicitly accepted and
selected translation candidate carries its exact row links to the selected
workbook version in the selection transaction. The changed name stays unresolved;
supported names retain their exact evidence and source versions. Each child link
records its parent link, selection and candidate hash. A controlled second source
change worked after reopening the database. A forced child-link failure rolled
back the selection; a post-commit job-view export failure was repaired by retrying
the same request without duplicate links. No real candidate was accepted or
selected.

**Frozen Yamaha real-file holdout:** a different supported Yamaha part changed
name and two source rows moved. Relay marked one name for review, preserved six
supported names and three unresolved names, and produced an unselected candidate
with 13 changed cells in two workbook package parts. The protocol expected ten
cells and omitted the source-file locator updates for three unresolved rows; the
strict preregistered assertion failed, while the documented semantic adjudication
passed. An isolated fixture-channel error stopped the first job-view export; the
same committed candidate was exported after correcting that fixture metadata.
See holdout report (private evidence). No independent agent control,
new catalog search, real selection or installed-app action occurred.

**Independent control comparison:** A fresh general agent revised the same five
frozen files without Relay state or internet. Both outputs withdrew the changed
Russian claim, preserved six supported names and three unresolved names, and
correctly moved two source rows. The control passed the original exact ten-cell
rule; Relay changed three more valid source-file locators, so only its documented
semantic adjudication passed. The control kept the new review text in the old
green confirmed style, while Relay used the existing yellow review style. The
comparison (private evidence) separates frozen scores from
post-scoring presentation observations and does not claim a speed or cost win.

Installed 0.13.107 listed the isolated candidate but rejected its newer plan as
stale. Installed 0.13.108 lists and verifies it, with review available in read-only
bridge inspection of a disposable database copy. No candidate was reviewed or
selected. **Next O14 quality steps:** qualify the separate decision controls
with an explicitly authorized case; independently review the plant case's
botanical/photo evidence and remaining climate claims before wider certification;
then use an approved substitute and deck treatment for an exact candidate and
agent continuation through the frozen handoff. The current real-case links certify structural
membership and eight exact climate values only. Discovery of links from unreviewed files remains a separate
measured capability.

## Deferred and operating rules

Keep broad application UI automation, extra hosted adapters, general media work and
unrelated acceptance exercises outside O14 unless a selected case needs them.
O15 is a separate, bounded Safari capability under development; its inclusion
does not authorize broad application editing or change the installed baseline.
Preserve exact requests, versions, decisions, assignments and recovery receipts.
Keep database changes atomic and external dispatch after commit. Never infer
acceptance or replay an uncertain submission. Run focused checks for changed
behavior; distinguish controlled fixtures, installed-runtime checks and live
provider/channel results. See [historical milestones](ROADMAP-HISTORY.md) and
[publication policy](docs/publication.md).
