# Relay Desktop UI controls

Relay Desktop is the reference interface for the shared runtime. This document is
the inventory for its task workspace and menu-bar entry. The implemented styles live in
[`companion.css`](../task_relay/assets/companion.css); use those classes and native
elements before adding a new control. This does not define `.relay` job data or
require another client to use the same visual design.

## Canvas navigation

Jobs opens the shared collapsible sidebar on both the canvas and app pages.
Its job list scrolls independently; Telegram and Settings stay at the bottom.
Telegram opens the existing messenger/service controls. Settings owns app-wide
preferences and saved connections; history diagnostics are secondary settings.
The canvas + Step is the only node-library entry. Provider/model/input setup
remains in the selected node inspector. Non-canvas pages reserve a normal header
for Jobs and the page label; no floating app dropdown covers status messages.
Navigation alone never starts a service or executes a node.

The canvas has a subtle dot grid anchored to the node camera. Spacing is 24px at
100% zoom; pan and zoom move the grid with the graph. At low zoom, fewer dots are
drawn to prevent clutter. This is decorative only: no snapping or new hit targets.

New task uses automatic recommendations without a research dropdown. Ordinary
questions and outcomes use the shared conversational orchestrator, and messenger
conversations project the same committed answer here. Continue messenger choices
in their original channel. Independent reruns may vary with context and model
generation; one saved response remains identical wherever it is inspected.

A Desktop recommendation containing only public search/page reads starts bounded
research on click under its original conversation, using the configured provider
and existing two-search/six-page budget. Other options prepare attached plans;
execution retains Start review. Runtime receipts bind the exact selected option,
question, project and frozen attachments and prevent duplicate uncertain clicks.
Conversation workflows open on Results, showing the latest stage and observed
search/page coverage. Results, Workflow and History controls sit below the job
heading. The full dependency graph is confined to Workflow; conversation steps
open their saved answer in Results without planned-file placeholders. History
retains the original conversation, earlier answers and linked failed preparation.
The latter is excluded from the active graph; its attempts and unexecuted proposal
remain collapsed. All of these are views of unchanged committed records. Merely inspecting an option starts
no work. Free-form Continue still uses the existing New task entry.

Revise plan and Plan next step continue to use the bounded stage planner, preserving
their existing review, Start and ownership contracts. The request receipt freezes
which entry path was used. A lost reply permits only an unchanged receipt retry.
Source links in conversation details are rechecked against successful, hash-checked
read receipts; search references remain labeled separately from page reads.

Conversation bodies render local marked/DOMPurify Markdown with literal code
preserved. Exact saved replies remain available separately. A small source line
shows observed read status; Source details holds advice and retrieval records.
Claim references distinguish pages from search references and unresolved links,
without treating retrieval as factual verification. Display metadata must match
both saved response hashes. Legacy footers are separated only by exact identity.
Unobserved URLs are plain text; observed links use the native receipt gate.
Receipt-bound clicks stop propagation and the generic setup link handler respects
handled clicks. A source-opening failure stays in its answer with brief recovery
text. The setup opener retains its existing restricted scope.

Completed standalone Desktop conversation details place Delete conversation
at the bottom history section. A read-only exact preview precedes in-window confirmation.
Active or uncertain delivery and cross-job ownership block deletion. Linked
follow-up stages also block standalone history deletion; whole-graph deletion
is not part of this control. Local text
and private traces are removed; frozen attachments and submission/delivery
identities remain. Cleanup occurs after database commit and interrupted cleanup
has a visible recovery action in Jobs. Other job/task details lead with their
existing Manage / delete saved-record controls.

## Elements and variants

| Need | Element / class | Appearance and use |
| --- | --- | --- |
| Job views | `.conversation-tabs` | Results, Workflow and History buttons below a conversation job heading; Results is the default. |
| Main action | `button.primary` | Solid blue. One leading action per form or decision group. |
| Ordinary action | `button` | White, bordered, full-size text. Refresh, retry, open and secondary choices. |
| Low-emphasis action | `button.quiet` | Borderless, muted text at the shared action size. Auxiliary actions that do not change or remove data. |
| Destructive action | `button.danger` | White with red text and border; pale red hover. Delete and Forget controls, including Saved work. Never use `quiet` for destruction. |
| Destructive review | `dialog#destructive-confirm` | In-window modal with an ordinary Cancel and a red final action. Show exact records, retained data and irreversible effect after a fresh preview. Escape and Cancel close it without mutation. |
| Full-width choice | `button.row-link` | A full-width, left-aligned button for a selectable row. Combine with an action variant only when the visual hierarchy remains clear. |
| Toggle | `button[role=switch]` | Pill with `aria-checked`; blue when on. Use for on/off settings, not one-time actions. |
| Text or number entry | `input`, `textarea` | Full-width bordered fields with a visible `label`. Use a concise hint for constraints. |
| Closed choice | `select` | Same border, radius and type scale as other fields. Use for a short, stable set of choices such as Saved work category. |
| Disclosure | `details > summary` | Section header with chevron. Use for optional settings and expandable review information. |
| Review or saved item | `.review-card` | Bordered card for one decision, result or saved record. Put its actions and feedback inside the same card. |
| Integration item | `.channel-card` | Divided row for a provider or channel and its related settings. |
| Feedback | `.feedback`, `.feedback.error` | Blue informational or warm error panel. Use `role="alert"` for an actionable error; place it beside the control that caused it. |
| Supporting text | `.hint`, `.muted`, `.path`, `.check` | Secondary text, path, or check result. Do not encode an error only as muted text. |

All action variants, including auxiliary actions, use 14 px text and a minimum
36 px height. The workspace uses a 14 px base font, 8 px action radius,
8 px field radius, 10 px card radius and 8 px action gap. The main window starts
at 1040 × 760 px with a 184 px sidebar; its minimum size is 780 × 560 px. Narrow
previews use the same destinations in a top navigation row.
Action groups use `.actions`, including generated model settings, native session
controls and app updates. A leading save, allow, accept or select action uses
`primary`; destructive cache cleanup uses `danger`, like saved-work deletion.
Keyboard focus is a visible 3 px outline. Disabled controls remain visible when their role is useful
for understanding the state; otherwise hide an unavailable action and explain why
in nearby text. Avoid adding a second button for the same operation in another
section merely to improve discoverability.

## Interaction rules

1. Give an action a verb label. Use an ellipsis when another step, such as review
   or confirmation, follows. A destructive button previews current ownership and
   blockers, then opens the shared in-window dialog before committing a fresh
   digest. Do not use `window.confirm` in the Tauri companion.
2. Show errors beside the originating control and keep the item on screen. A
   global status message may supplement the local message after completion.
3. Disable a control while its request is pending; restore it on cancellation or
   failure. A cancelled confirmation makes no mutation.
4. Use the same button sizes, field borders, card spacing and focus behavior in
   new sections. Add a new variant only when an existing one cannot express its
   role, then update this inventory and the shared CSS together.
5. Keep data and recovery rules in the runtime and bridge. The UI styles and
   confirmation copy are a presentation of those rules, not their authority.

## Current scope

This inventory covers the Tauri workspace in `companion.html`, `companion.js`
and `companion-workspace.js`. Older setup pages and external native applications have their own
UI. A future consolidation can move common tokens into a shared asset after those
surfaces are reviewed; it should not silently restyle them.

## Workspace navigation and authority

Jobs is the default destination. The four sidebar destinations use one consistent
navigation control. Saved records and Safari sessions open focused views under
Jobs; agent permission requests and revision candidates open under Review. Every
focused view has a back action. Disclosures are reserved for settings and details
inside a destination, including plan documents, output identities and receipts.

New task presents a request, explicit attachment choices and optional project and
constraints. Attachments are frozen before provider planning, with up to ten files,
20 MB per file and 50 MB total. Outputs use Relay's managed workflow folders.
Opening a composer or a folder picker makes no provider request. Preview plan
records one durable planning identity; Review for Start freezes the execution
review and Start requires the current plan/document digest. Original requests,
constraints and attachment versions remain saved. Unconfirmed submissions retain
an identity through reload, and an unchanged retry inspects the committed receipt.

Job detail displays committed steps, messages, current and historical artifacts,
independent review concerns and action receipts. Finder actions recheck a registered
file's hash and size through the host adapter. A local selection records the exact
complete output set and the user's note; it never implies acceptance from viewing.
Pause, Resume and Cancel preserve the approved scope and uncertain attempts.
For a completed local stage, Plan next step carries selected artifact versions into
a separate bounded plan; its Start remains explicit. Recovery of blocked or
uncertain stages still uses the development CLI.

The task composer offers suggested research, ideas from existing knowledge/files,
and a source-backed answer. Changing a choice on an unconfirmed submission cannot
reuse or duplicate that request. Sources and research is visible in plan and job
detail. Proposed research is distinct from executed research; only saved tool/host
receipts supply consulted-page links. Search results without a page read have a
separate label, and files supplied to workers do not imply every passage was read.
No recorded retrieval is shown explicitly. Missing/changed or capped receipts mark
the list incomplete. Shell/network activity outside the instrumented routes is
not covered. Opening a source rechecks its exact job receipt through the native
host adapter and opens the current URL. A source-backed-plan button opens a new
draft with the original request, leaving the current job and its decisions saved.

With the default choice, a new Desktop plan shows the orchestrator's saved
recommendation, its reason and concrete source-check questions. Optional research
offers the other approach as a separate draft; unnecessary research is not pushed
as a generic button, and required source checks do not offer a quick-answer shortcut.
Explicit composer choices still take precedence. Advice is returned by the same
planning call and does not imply research ran or authorize Start. Historical jobs
with no advice retain their recorded state and legacy draft choice.

Direct orchestrator conversations can answer without creating a production job.
Their saved text includes relevant request-specific recommendations and source
links from actual read receipts, or explicitly states no successful web lookup.
Search-only references remain labeled separately from fetched pages. These replies
use the conversation provider and its existing tool budget, not the stage planner.
Old replies do not receive invented retrospective recommendations or sources.

Production job detail leads with a short title, one status and the next action.
Results and their Review result disclosure appear together above the workflow.
A note and fresh explicit confirmation are still required to select the exact
complete output set. A selected current artifact is identified by ID and hash;
otherwise the most downstream available non-review result is shown, with other
current files under More files. This presentation does not infer acceptance or
change the pending decision. Previous non-current files stay under Details.

The compact workflow shows human step names and statuses. It draws recorded
prerequisite connections; sequential jobs use one column and dependency layers
place parallel work beside each other. Larger active jobs collapse their completed
prefix. Missing or cyclic history has an explicit warning. The step inspector
starts closed and opens only when a step is selected or Inspect step is clicked.
It shows files and a concise status; tools, model, exact instruction, attempts,
review target, input/output records and saved identities are inside its Details.
Closing the inspector restores focus to the selected step and remains closed on
refresh. This view does not combine separate stages into an invented execution
graph. Exact file links continue to verify the registered version before Finder.

Job Details retains the full request/brief, identities, file records, earlier
results, activity and action receipts. Job options contains Pause work, Cancel job
and saved-history management. Resume work is the leading action when eligible;
blocked/uncertain work has Inspect step and any eligible Resume remains available
in Job options. Standalone messenger jobs can be decided here with exact-version receipts;
results retain their original delivery channel. Blocked jobs show their failure
before Inspect step, Plan a new attempt and Cancel. A new attempt opens a separate
planning draft, with the original request and failure visible; old outputs are not
silently selected or reused. Uncertain work requires reconciliation.

Job rows retain their DOM and keyboard focus when only timestamps change.
Duplicate shortened titles have distinct accessibility names using the saved job
identity; the full request title remains available as a tooltip.

New task remains one entry point. Project folder is visible beside the request and
attachments, with optional Constraints folded. The composer states that Relay
proposes a workflow and that selecting a folder does not create a Codex conversation.
The plan's existing exact document review and Start gates remain unchanged.

File versions shows pairs established by recorded revision intent or explicit
replacement selections. File revised links open the version comparison. Check
source files inspects the saved original locations of desktop attachments, on
request, against their frozen hashes. Source updated outside Relay records an
observation at the displayed check time; it does not import the edit. A step
receiving an earlier version is marked Earlier source version. This includes
transitive recorded input dependencies, not proof that a worker used the content.
The explicitly revised candidate stops propagation of the earlier version.

Comparisons revalidate both versions before showing bounded UTF-8 text changes;
binary and larger files show hashes and sizes. Registered files above 20 MB show
recorded metadata without rehashing their contents. Original checks cover at most
ten files, 20 MB each and 50 MB total; partial or unavailable checks are explicit.
A moved, linked or subsequently changed original cannot produce a stale comparison.
Viewing changes preserves saved copies, decisions and execution authorization.

Desktop-started stages keep desktop delivery ownership. Messenger-started jobs
appear in the shared list and can be reviewed here while retaining their delivery channel. Desktop intake has
its own worker and can operate without Telegram polling. First-time local setup
connects AI and starts Relay; Telegram and Messages are separate optional
connections. The menu-bar entry opens the same main workspace or New task.

Job details link to the matching saved record for history management. Deletion
retains its explicit review and confirmation, and blocks active, uncertain or
unproven shared ownership. A stage inside one saved workflow reviews deletion of
the entire owning workflow. Cancelling the dialog preserves that history.

Settings / Apps and tools groups Browser use with Computer use — Safari. Native
setup checks inspect helper identity and window-observation grants; Automation
remains a task-start check. Permission requests and macOS settings links require
an explicit click. The service dot is green only for verified healthy state,
amber while checking or when status needs attention, and grey when stopped.

Saved messenger plans expose the same document review and Start gate as local
plans. Renew plan review replaces an expired approval without dispatching workers.
Workflow ownership still governs stage Start; paused/cancelled owners show an
explicit blocker. Expired or unreadable unexecuted plans can still be discarded.
Ready decisions and Needs attention form separate groups in Review.

Remove job is a confirmed removal from the main list, with all exact records and
files retained. Show removed jobs makes the record accessible with Restore to Jobs.
Cancellation must finish and uncertain attempts must be reconciled before removal.
Permanent deletion remains a separate ownership-checked action in Saved records.

Plan actions stay above the compact summary; full scope, tools and limits remain
available in a disclosure and exact documents still gate Start. Review rows use
saved identities to distinguish repeated titles. A workflow-owned run can be
cancelled as this stage and later removed from the list; that action does not
approve continuation, transfer ownership or remove the owning workflow records.

## Canvas panel spacing

Chat (workflow authoring and result discussion), Inspector, History, Jobs and the
node library share the panel tokens in companion.css: 20 px inset (16 px on
narrow windows), 12 px control gaps, 20 px corners, the same border and shadow.
Panel headings use 17 px semibold type and a 32 px close target in the header
row, so long headings wrap without colliding with the close button. Form fields
use 13 px text and 10 px inset; supporting text uses 12 px.

Put chat controls and messages inside `.job-chat-messages`; workflow authoring
also uses `.workflow-chat-body` for consistent vertical gaps. Keep the header
outside the scrolling body. Do not attach textareas or actions directly to the
panel shell. Empty status/proposal containers can hide; empty text inputs cannot.
Inputs/Results, canvas-view and conversation tabs share the same segmented
control styles and visible selected state. These styles change no runtime data
or execution controls.

### Workflow Chat model choice

Workflow Chat uses the same text-provider/model and saved-connection snapshot as
node setup. New requests require an explicit provider and model; suggested IDs
are selectable and custom IDs disable autocorrection. Chat choice controls the
proposal node and supplies the default for new AI nodes with no explicit model.
Existing and explicitly proposed node choices remain intact; fixed-provider tools
keep their own setup.

Send prepares an ordinary model-node draft and uses existing Run preview/start.
Paid proposals require an inline confirmation; cancelling never starts the node.
The exact model and request are retained, and an uncertain start is checked using
the same submission identity. Applying a validated proposal remains separate from
running the authored workflow. Historical Codex requests retain their saved choice.

### Conversation and proposal correction

Workflow Chat displays a conversation, with a fixed composer and compact model
selector. User text appears immediately; progress/errors belong to the assistant
reply. Completed messages and model choice follow a saved canvas. Pending requests
restore their exact submission; status recovery does not create a replacement run.

The registered workflow.proposal content contract uses the existing operation_submit
loop. Replies may answer or clarify without a graph. Proposed graphs follow an
operation-aware authoring schema: only model nodes declare custom input/output
interfaces. Registered nodes inherit ports. Invalid graphs return tool feedback
before the worker finishes, within its existing limits. Code validates bindings
and exports the reply. A valid reply updates the unchanged canvas directly, without
an approval step. A changed base is preserved with an explanation instead. Running
the graph remains a separate action. Historical failed proposal bytes stay unchanged.

### Keep execution on the authored canvas

Run updates the mounted editor through the existing status/advance route. Toolbar
labels, chat visibility, selected inspector and camera stay in place. Exact saved
outputs use the shared Results renderer in the inspector; a status refresh never
replaces the entire page with History. Canonical saved canvases reopen in the same
editor; older records without an authored graph retain their read-only projection.

### Progressive Chat composition

Chat publishes complete validated graphs from the existing attempt-bound typed
record store while its worker is active. The worker submits an initial graph,
then amends that record as more nodes and resolved connections become ready.
Every revision uses the same registered graph validation and original limits.
Status reads do not export, collect or execute proposed nodes. Token fragments
and unresolved wires are never projected onto the canvas.

The editor retains the exact submitted request separately from its last applied
preview. Reload observes that request without resubmitting it. New revisions
replace only the last applied preview; concurrent user edits prevent overwrite.
Chat shows Building workflow until completion. A stopped request leaves its last
preview visible as a draft; this is not completed execution or acceptance.

### Saved conversation continuation

The saved-job Chat panel keeps a pinned message composer for Telegram and desktop
conversations, including failed or uncertain outcomes. It displays the shared
Settings conversation provider/model. Send creates a new, explicitly requested
turn through the existing desktop admission and conversation worker; previous turns
remain unchanged. A lost admission response offers Check status with the same
identity, never an automatic resend. Pending work disables another send. Turns
remain in the original Jobs entry, with original context plus a bounded recent
history. A conversation without authored nodes does not invent a workflow graph.

## Portable workflow files

The canvas Export action saves a `.relay.zip` containing `workflow.json` in the
existing workflow schema and a bounded file manifest. “Include input files” is
optional. Prompts, named bindings and model choices travel with the graph; saved
connections, API keys, run history and previous outputs do not. Users should review
prompt text and any included input data before sharing.

Jobs → Import workflow opens the package as a new ordinary draft. Included input
bytes are checksum-verified and registered under new local artifact IDs. If files
were omitted, the file picker requests the exact originals before creating the
draft. Ask when run fields remain unbound. Import never starts a workflow or
reuses the sender’s execution authority. Unsupported operations, invalid ports,
cycles, modified files or unexpected archive entries stop import. Existing jobs
are not overwritten. A historical run is exportable only when it retained an
actual authored workflow; the UI does not fabricate a graph from its history.

Status polling does not rebuild a canvas solely because its observation timestamp
changed. Inspector reading position is retained when an actual data update does
require rebuilding it. Embedded previews remain mounted for unchanged results.

### Full-width reading and automatic names

Chat and the selected-node inspector share an expand/restore control in their
header. Expanded panels span the window below the canvas toolbar, reserving the
bottom status area. Expansion is view state and survives refreshes, without
navigating away, changing tabs or running work. Unnamed canvases receive a short
name from the first Chat request or, at Save, the first node prompt/objective.
This is deterministic, uses no extra provider call, and never overrides a supplied
name. Prior jobs are not bulk-renamed.

### Canvas connection indicators and return navigation

The titlebar shows Telegram and Messages logos with accessible status dots and
tooltips. Only paired, enabled, healthy services with current policy acknowledgment
show connected. Connected logos and dots use the shared action-blue color; all
other states are grey, with the specific status in the tooltip and accessible label.
The existing status refresh updates the badges
in place. Clicking opens Connections, never starts a service or sends a message.
Settings and Connections provide Back to canvas and retain the mounted editor,
selected result, panel state and local inputs while those pages are open.

Node results show a selectable folder path next to Show in Finder. The existing
artifact lookup has a read-only location mode: it checks exact original bytes and
existing folder mappings without exporting or repairing copies. A missing export
is labeled “not exported yet”; the explicit Finder action can publish its existing
exact display copy and then refresh the path. User edits are never overwritten by
reading a location.

### Shared Chat model and compact composer

Canvas Chat inherits the saved Conversation model used by Telegram and Messages.
The chip icon opens that exact Settings section; its adjacent compact model label
opens a per-chat override using existing connections. An explicit override is saved
with that chat and can be reset with Use shared model. Historical responses never
select a new model implicitly, and pending requests keep their frozen choice.
Shared settings are re-read before a new preview; unavailable choices do not fall
back to another provider. Paid confirmation remains in place. The composer uses
a two-row prompt and small Send button, leaving more space for conversation.
