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
| O10 | Python packaging | Runtime packages, CLI, tests and maintained assets have explicit distribution boundaries. |
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

**Next planned implementation within O13: desktop launcher.** Provide a separate
visual entry point for installation and setup, installed version/update status,
provider/channel/project configuration, and connected tool/application availability.
Reuse the CLI/host services and report missing capabilities explicitly. Completion
requires working setup/status controls and interrupted-setup recovery; a catalog or
mockup alone is insufficient. Provider calls, application probes and message sends
remain explicit actions. The launcher is planned, not implemented.

Native Linux service switching, separate Messages deployment updates, fresh-install
provider execution and Telegram delivery remain open qualification or adapter work.
Controlled migration checks do not establish those gates. O13 remains incomplete.

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
