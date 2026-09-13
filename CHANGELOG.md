# Changelog

## 0.12.1 — unreleased

- Companion settings show configured folders with their purpose and a macOS
  permissions shortcut, without implying an enforced folder sandbox. Usage loads
  on expansion; cleanup stays in troubleshooting. Removed unsupported-channel copy.

- Added direct Mac beta DMG packaging with Applications shortcut, installation
  notes and checksums. The website offers the DMG first and guided CLI installation
  as an alternative, with explicit Apple Silicon/macOS 14 and unsigned-beta limits.
- Companion onboarding now presents AI access, Telegram bot, service startup and
  pairing as saved, sequential steps. Failed startup does not advance to pairing;
  saving credentials never starts the next action. The CLI honors a previously
  selected companion data binding without replacing services.

- The companion now has one Channels panel for Telegram and Messages, with
  per-channel switches and Pause all messaging in the menu bar. Saved policy
  gates incoming commands and outgoing text/media; existing work continues,
  queued replies retain their destination, and uncertain sends are not replayed.
  Resume skips old requests and drains undated Telegram button clicks once.
  Release notices have a separate Off/Telegram/Messages destination. The UI
  distinguishes saved policy from current runtime acknowledgement; old services
  need updating/restarting. Future messengers remain unavailable until implemented.
- Licensed Task Relay under Apache-2.0, with the full license in the source
  distribution and Python wheel, and matching Python package metadata.
- Packaged services write launchd logs under Library/Logs so protected Documents
  data locations do not prevent the helper from launching before app permissions
  can be requested. Existing service definitions remain subject to exact handoff.
- Desktop runtime staging now removes retired generated sources before copying
  the reviewed release inventory and refuses a symlinked output directory.
  Removed unused platform icon exports from the macOS pilot source set.
- The companion menu bar uses the same transparent monochrome icon as Messages
  Relay, with native template rendering for light and dark menu bars.
- The packaged desktop now uses a compact menu-bar companion: setup, connection
  status, settings and on-demand exact decisions. It closes to the menu bar,
  prevents duplicate app instances, restores its hidden window when reopened
  from Finder on macOS, and opens the Telegram conversation. Task
  lists/composers, workflow/tool navigation and startup usage/storage scans are
  removed from this UI; saved records and existing backend operations remain.
  The source installer keeps its loopback setup page. Earlier workspace UI
  changes below are superseded as the packaged app's primary interface.
- Bundled the optional Messages transport as a hidden helper under the same
  companion. Existing installations remain untouched until a reviewed service
  handoff. Exact definitions/runtime identities, in-flight checks, unload-before-
  replacement, fresh startup evidence, failed-start restoration and explicit
  interrupted-handoff recovery preserve pairing and uncertain submissions.
  Previously stopped services remain stopped. First-time Messages pairing,
  actual macOS permission transfer and live handoff remain separate qualification.
- Local approval details retain exact request fingerprints and one-shot decisions.
  Service actions now have a lifecycle timeout long enough for startup/restoration;
  timeouts direct users to inspect receipts rather than repeating an uncertain action.

- Desktop navigation now uses Jobs, Workflows, Automations & tools, Usage, Setup
  and System. Project-grouped job history sits beside a focused conversation and
  bottom composer. Usage and storage no longer occupy the job workspace.
- Saved linked workflows, execution runs and plans from all channels are visible
  in a paginated read-only library. Desktop drafts retain their existing separate
  review and Start boundary. The capability catalog lists supported assistant and
  browser actions, providers, and registered host/API/procedure operations with
  availability and limits. Automatic project extraction and recurring scheduling
  remain unimplemented; an editable reels assessment request is available.
- Conversations include saved user inputs and bounded native Codex message
  history. Markdown, tables and fenced-code highlighting render locally using
  bundled libraries, with HTML sanitization and remote image loading disabled.
  Markdown review documents retain an exact-source disclosure. Display excerpts
  do not change stored requests. A cross-job approval inbox exposes existing
  Codex/Claude request-bound review and one-time decision controls.

- The desktop Tasks view now leads with tokens recorded through Task Relay,
  including direct API tasks, planner/chat calls and managed workers; it shows
  the larger indexed machine-wide total separately. A storage disclosure lists
  the folders inside a source checkout and can prepare and apply the existing
  verified-cache cleanup policy. Live data, unique backups and work artifacts
  stay outside that automatic cleanup.
- Pending Codex command, file, permission and connector approvals and Claude
  tool permissions now appear with exact review text beside the selected task.
  Desktop Allow requires opening the review, checks the current request and
  owner again, and claims one decision before dispatch. Changed, expired and
  uncertain requests are not replayed. Supported Codex questions can be
  answered there. The Tasks layout now gives the task list, activity and
  composer a chat-style hierarchy; production output choices still use Telegram.
- The desktop Tasks tab now shows recorded seven-day token totals and the disk
  space used by Relay data, workspaces and generated files. When connected to a
  source checkout, it also shows that whole folder's size, including builds and
  saved data. Missing token counts stay unknown, and an incomplete storage scan
  is labeled as a lower bound.
  New provider tasks and workflow plans start without a folder; Relay creates a
  stable isolated workspace for each folderless provider task. A selected folder
  supplies that task or plan’s working context. A default folder is optional
  during desktop setup.
- Packaged the existing blue-on-white Task Relay artwork as a rounded macOS
  desktop app icon. Its transparent corners leave the blue mark unchanged.
  Local app bundles declare `CFBundleIconFile` and contain the matching `.icns`;
  public signing and notarization remain open.
- Added **Plan a workflow** inside the desktop Tasks tab. A goal, optional
  constraints and selected project create one durable, planning-only request in
  the existing bounded production planner. Drafts, exact proposal text and
  attached review documents stay in the app; revisions retain the original
  request. A separate Review for Start action presents the fixed scope, and
  Start checks the current plan/document digest before scheduling workers and
  explicitly hands progress and later output choices to paired Telegram.
  Generating a draft can use the configured API provider; no provider or live
  delivery was exercised in controlled checks. A current service and configured
  planner executor are required. If local data access times out, the app shows
  that error in Tasks and disables Generate draft.
- The desktop bridge now disables Python bytecode writes into the app bundle.
  This keeps its local ad hoc signature valid after opening the window; an
  app-owned service launch and distribution signing still need separate checks.

- Added version-aware direct Rhino 7/8 macOS launch paths: IronPython 2.7 on 7,
  CPython 3 on 8, matching native save formats, exact version selection with no
  fallback on invalid overrides, and application/version binding at approval,
  dispatch and phase boundaries. Grasshopper remains paused. Rhino 7.32 and
  Rhino 8.35 both passed the local continuous workflow qualification.
- The orchestrator worker heartbeat now records its process ID and loaded graph
  operation IDs, making stale service registrations diagnosable. Reloading the
  local service restored the four Rhino registrations; controlled worker checks
  and the running service heartbeat verified the change. No live planner prompt
  or channel delivery was exercised for this service refresh.
- Fixed missing Rhino preparation inputs: script/checks and render-manifest
  preparation now freeze the operation contract and a standalone JSON validator
  into both producer and reviewer workspaces. Controlled dispatch checks exercise
  those copied files without Rhino and reject the provisional format that blocked
  a tower draft. Old assignments remain unchanged; native execution still requires
  separately approved exact artifacts.
- Added explicit output-set selection for related preparation files. The plan
  names the members; selection waits for every file, records all exact versions
  atomically and carries them to the next stage. Single-file alternatives retain
  their existing behavior. Host inputs bind selected artifact identities, avoiding
  duplicate executable inputs from byte-identical historical drafts.
- Extended frozen contract/validator handoffs to Blender Python, asset-import and
  animation preparation. Rhino checks can require named render views after
  reopening, and rendered-model preparation includes the camera requirement.
- Qualified the recovery-to-render stage chain with real Rhino 7.32 and 8.35.
  Rhino 8 produced and rendered the repaired twisting tower. Controlled checks
  cover missing/tampered set members, restart/rollback, review, preview/original
  delivery and old-attempt preservation. Planner/reviewer responses and channel
  receipts remain controlled fixtures; no live provider judgment or message
  delivery is claimed.
- Fixed Rhino 7 worker shutdown on macOS. A native process-exit adapter runs only
  after process ownership is verified and files/receipts are closed, avoiding
  Mono finalizer crashes and interactive save prompts. Success still requires a
  clean exit code and matching successful worker receipt. Focused regression
  checks cover failed receipts and exit-code preservation.
- Added fixed `rhino.render` with a delivered, hash-bound named-view/resolution
  manifest, built-in Rhino Render, PNG verification, unchanged native source and
  independent review/selection. Timeouts retain evidence without replay or a
  viewport substitute. Existing startup, inspection and exact-script modeling
  retain native candidates and separate reopen checks.
- Added continuous project qualification with four retained native versions,
  three revisions, repeated inspection, three actual renders and a deliberately
  rejected edit followed by recovery. Both Rhino 7 and Rhino 8 host sequences passed across
  Relay restarts. It exposed a named-view API mismatch and transient material
  archive hashes; preserved materials now compare documented native properties.
  Controlled checks cover exact approvals, version/source drift, failed rendering,
  source preservation, process ownership and restart/no-replay behavior. Other
  hosts, long-duration use, live providers and channel delivery remain unqualified.

- Simplified the native desktop window into Tasks, Setup and System tabs. Saved
  task status and latest activity are visible first; older events and exact
  submission receipts are expandable. The Tasks tab can create a managed-provider
  task identity without starting provider work or changing Telegram's selection.
  Duplicate creation requests return their prior result. Busy tasks no longer offer another send,
  and managed-provider stop is shown only for an active uncancelled run. A selected
  small UTF-8 text file is frozen with a SHA-256 digest into the durable instruction;
  a retry of its request identity cannot send changed file bytes. The
  direct-open HTML install guide remains available. The native bridge now stops
  waiting after ten seconds when macOS stalls access to a selected data folder;
  the page shows an access error and a retry control.
  A clean first launch opens Setup with the first unfinished checklist step
  expanded; saved steps advance the checklist, and the final step links to the
  service controls in System.

- Corrected the desktop service status when a healthy source-installed Relay
  service owns the LaunchAgent; the app now identifies that service as external.

- Licensed Task Relay under Apache-2.0, with the full license in the source
  distribution and Python wheel, and matching Python and desktop package metadata.

- Added a macOS Tauri desktop pilot with bundled standalone Python and Relay
  sources. Explicit controls can start/stop an app-owned background service,
  connect to an existing source service's task history without changing it, and
  view/continue saved tasks. Desktop instructions use durable request IDs and
  local receipts; uncertain submissions are never replayed automatically.
  Managed provider tasks expose cancellation. Controlled checks cover ownership,
  failed start, command identity and recovery. Signing, clean-host installation,
  and live provider/Telegram delivery remain open release gates.

- Fixed browser HTTP redirects bypassing the origin check. Navigation now checks
  every redirect hop before following it, with no request retries. A known scope
  block during navigation returns a recoverable error with the target URL;
  redirects after form submissions still preserve uncertainty when their result
  cannot be inspected. Reachable-server tests verify no out-of-scope contact,
  permitted redirect chains and exactly-once POST behavior.

- `/browser TASK` now enters the reviewed browser production queue from Telegram
  or Messages, preserving the original request and requiring `gemini-browser`.
  Existing `connect|status|cancel` controls still handle Perplexity sign-in.
  Stale model metadata is refreshed before planning; execution waits for Start.
- Browser workers reserve their final model requests for writing evidence and
  submitting a report. Late browsing is rejected locally. A live information
  search exposed the previous failure: eight browsing rounds could end without
  a deliverable. Request and tool budgets remain unchanged.
- Browser planning and execution now receive current host date context. Successful
  delivery/review requires a nonempty page observation in that worker's attempt;
  reading only the candidate cannot establish a successful browser review.
  This is an evidence prerequisite, not proof that all model claims are correct.

- Image generation can reuse exact PNG/JPEG/WEBP production artifacts as well as
  chat uploads. Selected versions are hash-checked and copied into the image
  request, with artifact/attempt provenance retained; no download/re-upload is
  needed. `/image` in orchestrator chat or a production reply uses this selection
  path; existing provider-task replies retain their own routing.
- Production downloads and image-reference labels now include the production
  brief, step, output name and exact artifact version. Internal frozen output
  paths and previously delivered files remain unchanged.

- Added `scripts/qualify_blender.py --host`: one qualification command for Blender
  regression checks and isolated real-host pipelines across all seven registered
  operations. It includes planning/Start, review selection, scheduler resume,
  native file/preview delivery through a simulated Telegram transport, revisions,
  controller restart recovery, asset modes, animation and checkpoint reuse. Reports
  retain failures, frozen inputs, receipts and coverage limitations.
- Fixed false material-preservation failures after Blender save/reopen: unused
  materials that Blender does not retain are excluded from the persisted scene
  snapshot. Used and explicitly retained materials remain checked. Real-host
  qualification exposed the issue in both Python editing and animation.

- Added a complete controlled browser pipeline gate with per-test reports,
  command logs and a parser/tool coverage check. It exercises all nine browser
  commands, current operational flags and 12 tools through local Chromium, plus
  the normal producer/reviewer pipeline and recovery. Model transport and account
  pages use isolated fixtures; no live-account qualification is implied.
- Fixed failures exposed by the gate: CLI subcommand failure codes now propagate,
  browser observations include select choices, and full non-secret field hashes
  invalidate stale drafts before submission. Password/OTP values remain excluded;
  browser failures and unconfirmed sign-in produce concise CLI errors.

- Fixed scheduling after an intermediate user review. The unchanged scheduling
  grant is retained during the gate; selecting its output atomically resumes
  remaining authorized work. Completed stages remain stopped. Explicit resume
  and a status-card control can recover older stuck review pauses only against
  unchanged started plans, assignments and recorded decisions. Cancelled/changed
  stages and deliberate control actions are not implicitly resumed.
- Mixed visual-production guidance places the visual decision after a preview,
  rather than on intermediate data unless the user requests that earlier gate.

- Production planners can now select exact prior output versions omitted by chat
  routing. The captured catalog contains metadata only; selected files are verified
  before preview and again at Start, listed in the source manifest, and passed to
  producer/reviewer. With prior candidates available, plans explicitly distinguish
  independent work from modifications with a required baseline. Clarifying a ready
  plan retains its selected source versions. No prior output is implicitly accepted
  or attached merely because it exists.

- Scene/mesh production plans now freeze their operation contract and a standalone
  copy of the actual JSON validator as inputs for workers and reviewers. Data
  assignments explicitly defer Blender startup/rendering to the registered host
  step. General Codex worker instructions now distinguish the assigned step from
  the overall production brief, preventing a JSON producer from being told to run
  the downstream application. Existing failed assignments remain preserved.

- Fixed Blender production planning failures caused by omitted media types and
  agent-style tool budgets on fixed host operations. Before approval, Relay fills
  registered output types, types the unambiguous scene JSON and its producer,
  propagates types along declared edges, and includes those producers as explicit
  dependencies while retaining review gates. Conflicting types and ambiguous scene
  inputs remain errors; frozen plans and blocked attempts are not rewritten.

- Added a local HTML launcher opened by the source installer. It shows the selected
  project, setup progress, installed version, cached update status and detected
  tools; provides a public source ZIP download; and saves project, provider and
  Telegram setup one step at a time. It does not start a task or infer delivery.
  The page now uses the existing blue-on-white Task Relay logo and states which
  required Python packages the installer handles versus host and optional tools.
  Directly opened HTML now gives an install guide instead of permanent checking
  placeholders. The macOS double-click setup script is documented as the primary
  install path and keeps installation errors visible for retry.

- Added a bounded `gemini-browser` execution profile for general website work:
  dedicated profiles, managed tabs, DOM observations, scoped interactions and
  declared UTF-8 transfers. Existing production plans expose the exact scope before
  Start and retain the fixed model, independent review and Gemini usage records.
- Added durable browser action receipts, stale-observation checks, shared profile
  ownership and no replay after uncertain actions. Local `browser general` commands
  prepare plans, support human sign-in and inspect/resolve receipts. Controlled
  worker and local Chromium checks passed; live account/provider qualification and
  general-profile chat sign-in remain open. See `docs/general-browser.md`.

- Added explicit additive-schema migration plans, atomic application receipts and
  guarded reversal during release rollback. Newer data is retained; populated added
  fields/tables, record rewrites and destructive schema changes are refused.
- Recovery preserves the original migration identity across interrupted service
  restoration and checks whether the database transaction actually committed.
- Migration-aware updates use protocol 2; the 0.12.0 controller must be bootstrapped
  before selecting these releases. Separate Messages migration remains outside this
  updater.

## 0.12.0 — installation and release updates

- Added explicit release checks, separate-environment wheel installation, owned
  Telegram service switching, compatible-code rollback and interrupted-activation
  recovery. Candidate workers wait for activation commit. Schema/data changes,
  unfinished work and changed service bindings block switching.
- Added daily stable-release checks and at-most-once Telegram notices with an
  opt-out. Checks send no task content or credentials; installation remains explicit.
- Added a tag-driven draft-release workflow and update/bootstrap instructions.
  Controlled macOS fixture services verified update, rollback and failed-start
  restoration. Native Linux switching and live provider/delivery remain open.

## Earlier public product baseline

- Aligned natural-language routing instructions: requests to proceed should route
  bounded work or ask for a relevant destination, carrying earlier user context.
  A missing attachment/research selection now gets one model correction before
  dispatch instead of exposing internal field names. Unrelated files can be
  explicitly excluded; requested versions still require exact selections. The
  correction preserves the destination and existing choices, records both model
  responses separately, and never replays uncertain submissions.

- Removed the global workflow-context size/count rejection from orchestrator chat.
  Models receive a bounded overview with explicit omission indicators and can read
  exact pages of the captured evidence through `context_read`. Current user text
  stays exact; action validation still uses full state and existing revision gates.
  Conversation snapshots now store overviews instead of repeated full background
  dumps. No saved failed request is automatically retried.

- Added cleanup listing and execution for regenerable Python/Finder caches,
  explicitly selected generated build files and verified duplicate retired
  databases. Each removal checks the listed identity and keeps a receipt; source,
  user artifacts, active databases and unique recovery copies are excluded.
- Large Codex file approvals now send a compact Telegram card plus a complete
  literal text document, instead of rejecting patches at the old escaped-JSON
  length limit. Allow requires delivered, unchanged review material and the same
  pending desktop request. Replies to the document retain approval identity;
  missing/oversized details still require desktop review.

- Consolidated Messages pairing, delivery and direct Gemini history/jobs into the
  main Relay database. Messages uses the shared provider worker and keeps explicit
  channel ownership. Added an offline atomic import with verified backups,
  conflict/uncertainty preservation, usage identity migration and resumable archival
  of retired stores. Startup prevents silently starting from unmigrated databases.

- Added chat-initiated Perplexity browser sign-in: Telegram Providers and
  `/browser connect|status|cancel` in Telegram/Messages queue a supervised login
  window, detect readiness and return status to the originating channel. The user
  enters credentials only on the provider page on the Relay computer. No terminal
  input is required. Controlled setup/recovery/channel tests pass; standalone live
  login and conversation task routing remain separate qualification gates.

- Added an experimental local Perplexity Search browser command with a dedicated
  profile and durable submission/reconciliation journal in the shared database.
  Exact requests and conversation URLs are retained; uncertain submissions are
  never automatically repeated. Browser dependencies are optional. Controlled
  recovery tests pass; the standalone authenticated driver and Telegram integration
  remain unqualified. This does not expose general browser actions to the orchestrator.

- Added a source installer, resumable `task-relay setup` for local API-provider,
  model, Telegram and first-project configuration, and a network-free general
  `task-relay doctor`. Setup preserves saved credentials/pairing and prepares a
  first-task command without dispatching work. The source installer refuses
  unrelated environments and changed-source upgrades. The macOS setup launcher
  uses this flow without requiring Codex desktop. Compatible releases use the
  update controller. Version 0.12.1 adds an explicit additive-schema migration path.
- Published product documentation, portable setup instructions and an explicit
  source/distribution inventory. Personal research, installation records and
  one-time migration/replay programs are kept outside the public repository.
- Added a publication check for excluded files, personal home paths, credential
  signatures, personal runtime identifiers and links into private evidence.
- Messages first setup now requires an explicit task ID; subsequent starts reuse
  the saved task. Diagnostic launchers ask for the current pairing code. Existing
  pairing and execution records remain authoritative.
- Native launch wrappers resolve Python from the user's environment instead of a
  particular local framework installation.

## Packaged runtime — 0.11.0 development series

- Packaged application and orchestration modules, CLI entry points and maintained
  assets. Centralized data/project/output paths with explicit overrides.
- Added host interfaces, private-file/environment/Keychain credential sources,
  declared read/edit grants and frozen worker-support identities.
- Added optional Linux systemd user-service management with activation rollback.
  POSIX cancellation handles an exited parent and resistant descendants.
- Added native Linux text-runtime and Windows installed-boundary CI profiles.
  Windows task execution and native provider/delivery qualification remain open.
- Implemented bounded planning, worker handoffs, output decisions, mixed execution,
  artifact dependency/replacement records and usage reporting.

See [the roadmap](ROADMAP.md) for scope and [native qualification](docs/native-qualification.md)
for platform evidence. Development-series versions do not imply production readiness
or qualification of every provider, channel and application adapter.
