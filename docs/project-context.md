# Project context organization pilot

For the accepted product target and implementation sequence, see
[Relay for ChatGPT](#relay-for-chatgpt--accepted-product-direction). The operation
described first is the existing source pilot that contributes to that target.

Relay can collect a selected local Codex project's user messages, assistant final
answers, wiki/export Markdown and file inventory, then submit one durable analysis
job to the explicitly selected Gemini model. Topic names and source membership
come from the model response, not a manual taxonomy. A source may belong to
several topics, and one chat can contribute to several topics.

The portable runtime validates complete source coverage, exact quote matches,
source roles, topic identities and artifact inventory membership. It saves the
exact request, original capture, capture hash, redacted provider input, budgets,
provider response, usage and proposal in SQLite. Original credentials remain in
the private local capture; supported credential patterns are redacted before
dispatch and in exported contexts. This is not a general secret detector.

Claims remain model proposals. Citation validation proves a quotation appears in
the frozen evidence, not that the model's interpretation is correct. An assistant
report cannot serve as a direct user instruction or acceptance receipt. Artifact
inventory membership establishes presence during capture, not current existence,
geometry, visual quality or approval. Context export does not execute next steps.

## Commands

Use `task-relay project-context --help` or the source equivalent
`python3 -m task_relay.project_context --help`. Example paths are placeholders:

```sh
task-relay project-context capture --project /absolute/project --codex-home /absolute/codex --out /private/context/capture.json
task-relay project-context prepare --db /private/context/relay.sqlite --capture /private/context/capture.json --request-file /private/context/request.txt --model EXACT_MODEL_ID
task-relay project-context inspect --db /private/context/relay.sqlite --run RUN_ID
task-relay project-context run --db /private/context/relay.sqlite --run RUN_ID
task-relay project-context export --db /private/context/relay.sqlite --run RUN_ID --out /private/context/organized
task-relay project-context context --db /private/context/relay.sqlite --run RUN_ID --topic EXACT_TOPIC_ID
task-relay project-context graph --db /private/context/relay.sqlite --run RUN_ID --out /private/context/graph.json --request-file /private/context/graph-request.txt
```

Capture accepts repeated `--exclude relative/path` arguments. Exclusions are
recorded. Hidden/cache/private directories and symlinks are excluded by the host
adapter. Text capture covers wiki/export Markdown and root `AGENTS.md`; other
files have metadata only. Exported topic Markdown has source and artifact links;
JSON context packets include the topic's redacted source messages and documents.
Selecting a topic requires an exact ID. Broad ambiguous requests cannot silently
choose a branch or an accepted artifact version.

Prepare queues the job and its owner atomically. The default ceiling is one call,
1,500,000 input characters and 32,768 output tokens; oversized input fails before
queueing, with no silent truncation. API usage may be billed. Repeating the same
capture/request/model/budget returns the existing run. Run dispatches only queued
jobs. Interrupted sending jobs require explicit `recover`; they become uncertain
and are never replayed. A committed completed response can be validated/exported
again without a provider call. Structural, coverage or inventory failures block
the proposal. Individual failed claim citations are quarantined with the original
claim and validation reason; complete topic membership can be exported as
`proposed_with_gaps`. No quotations or claims are repaired, and no additional
provider call is made. Export records intent before file writes, verifies
read-back, recovers matching partial output and refuses to overwrite edited files.

## Boundary

This is a source-runtime CLI pilot. It is not installed Desktop UI, a ChatGPT
plugin, a chat sidebar organizer or an automatic context router. It writes derived
topic contexts at an explicitly selected destination; source chats and documents
are never renamed, moved or rewritten. The local history collector is a POSIX
host adapter for the observed Codex SQLite/canonical event schema. It joins history
projections and current rollouts by message identity and queries an exact project
root; there is no general ChatGPT history API integration. Tools/reasoning/media
payloads are excluded. Concurrent changes, conflicting projections and exceeded
capture budgets fail rather than silently dropping evidence. Windows collection
is unqualified; portable analysis can consume an already frozen capture.

Personal project data and execution records belong in ignored private storage,
not public fixtures. Controlled checks use small synthetic text and scripted
provider responses. A real project run is separate evidence from those tests.

## Relay for ChatGPT — accepted product direction

**Web scope superseded on 2026-10-02:** the current web plugin follows the
[portable Skills and work brief](relay-chatgpt-plugin.md). It reviews/exports
user-owned files and resumes from explicit selection, without Desktop state or
cloud synchronization. The broader local runtime direction below is retained
for context and is not a prerequisite for web V1.

Accepted by the user on 2026-10-01. Product promise:

> Keep the work, not just the conversation.

The user's follow-up defines the loop as **Connect → Understand → Continue →
Capture the result**. Relay turns sources the user deliberately connects or
exposes into persistent useful work state. ChatGPT supplies intelligence and
conversation; Relay supplies the persistent state of the work. Start with the
experience of opening a project, understanding where it stands and continuing
one useful next action, then add only the ingestion needed for that proof.
Universal capture is not a prerequisite. The graph is a way to inspect the
system; persistent, resumable work is the product.

Relay retains and continues work across conversations, files, tools and
executions. The plugin lets users inspect where work stands, understand its
provenance, find the relevant artifact versions and continue with the necessary
context. This supersedes the earlier positioning of Context Explorer as primarily
a chat organizer. The existing source pilot remains a component of this product;
the capabilities below are requirements, not claims of implementation.

### Primary objects and state

The work graph connects projects/work items, exact requests, decisions, source
evidence, artifacts and their versions, validations, open issues and executed
assignments with receipts. Conversations supply evidence to that record. Topics
are overlapping views: a source, decision or artifact can appear in several views
without being duplicated.

Each relationship records its evidence and authority. Model-extracted associations
remain proposals until the applicable runtime contract validates or records them.
An imported assistant statement is not a user decision, acceptance or execution
receipt. Quote matching proves textual presence only. A timestamp or filename
does not prove that an artifact is the current selected version.

Current state must distinguish newest recorded, selected/accepted, superseded,
potentially affected and unknown. Explicit decisions or reviewed relationships
establish supersession and dependencies. A changed upstream decision can flag
dependent artifacts for review; precise section-level staleness requires reviewed
location links. Unlinked or ambiguous impact stays unknown. Earlier versions and
decisions remain inspectable. Conflicts and missing evidence are visible open
issues rather than silently resolved facts.

### Product surfaces

The primary work view answers: where were we, what did we decide, why, which
version should we use, what is unresolved, and how can we continue? It presents
the current brief, decisions, artifacts, evidence gaps, potentially affected
outputs and next actions. Topics and an optional graph help users navigate those
same records. Clicking any claim, decision, version or relationship opens its
provenance.

**Continue this work** selects a work item and assembles a bounded context packet:
the exact continuation request, current constraints and explicit decisions,
selected artifact versions, relevant cited evidence, conflicts/open issues and
available next actions. The packet records the state snapshot, record IDs, hashes,
capture time and coverage limits. Unknown selection or missing files are explicit
gaps. Context budget limits never silently erase a decision or constraint. Changes
after preparation invalidate or refresh the affected packet before execution.

The plugin supplies that packet to ChatGPT through supported context mechanisms.
Inspection and context preparation do not start a worker. A subsequent request
can invoke existing bounded Relay planning/execution contracts with the selected
inputs, authorization and budgets. Commit assignment and ownership before dispatch;
preserve recovery receipts and block uncertain replay. Follow-up outputs return
as new versions tied to their request and execution, without inferred acceptance.

### Architecture and ingestion

| Layer | Responsibility |
| --- | --- |
| ChatGPT plugin | Interface and control: work overview, provenance, versions, issues, topic/graph navigation and continuation. |
| Shared work state / `.relay` | Portable records and versioned views of requests, decisions, evidence, dependencies, artifacts, validations and issues. |
| Relay runtime | Committed state changes, bounded execution, host adapters, delivery identities and recovery. |

The existing `.relay` JSON/SQLite views are projections of committed Relay database
records, not an independently authoritative writable database. Implementation must
reuse that authority or explicitly define a versioned reconciliation contract;
the plugin must not create a second conflicting source of work state. Desktop,
ChatGPT and future clients inspect and change the same work through runtime
contracts, without Tauri dependencies in recording, validation or recovery.

V1 ingests explicitly supplied context from Relay-involved conversations,
authorized history imports, connected documents/files and Relay execution records.
Enabling the plugin or correlating a tool call does not capture a whole transcript.
Imported history preserves original identities, roles, timestamps where available,
versions and capture coverage. Backend permissions govern project/file access;
model-selected IDs and anonymized conversation hints are not authorization.

The plugin owns its work views. Full-account chat ingestion and native ChatGPT
sidebar rearrangement require separately verified supported integrations. Local
execution requires a qualified connection to the user's Relay runtime and host
permissions; it cannot be inferred from a web plugin installation.

### Implementation sequence and completion evidence

1. Add versioned work records and deterministic current-state resolution over
   recorded decisions, artifact selection, reviewed links and runtime receipts.
   Check conflict/unknown states, exact provenance and atomic recovery with small
   text fixtures; reuse existing recording and revision contracts.
2. Add bounded continuation packet preparation and read-back receipts. Check
   multi-topic sources, superseded decisions, selected versus newer versions,
   missing evidence and changes between preparation and use.
3. Expose authenticated MCP work inspection, provenance, graph and continuation
   tools over those contracts. Enforce project access and stable schemas; reads
   must work without UI and must not dispatch execution.
4. Add the plugin work overview and conversation panel. Render committed backend
   results, link provenance and supply selected context through supported bridges.
5. Connect continuation to an existing supported bounded worker, preserving the
   same plan/start authority, version history and interrupted-dispatch behavior.
   Qualify the installed ChatGPT experience and runtime connection separately
   before publication or claims of live operation.

A complete first slice imports a small work record with a revised brief, an
explicit artifact selection and an unresolved issue. Relay identifies the selected
version and why, retains the earlier decision, prepares the continuation packet,
and records any authorized follow-up as a new version. A graph alone does not
complete this slice. Additional native formats and deferred runtime acceptance
exercises are not prerequisites for this bounded plugin proof.

The context source pilot supplies collection, saved analysis, topic contexts and
graph projection. The [plugin development build](relay-chatgpt-plugin.md) now adds
explicit work-state resolution, continuation packets, scoped MCP tools, UI,
developer profiles and bounded text execution. The local 0.2.0 plugin source adds
frozen understanding inputs, host-model report storage with checked citation
identities, proposed workstreams/actions, current-work analysis and exact result
capture. These are controlled local contracts, not a live ChatGPT or real-project
analysis qualification. General production-job
synchronization, external OAuth issuer setup/public deployment and live ChatGPT
qualification remain pending.

### Platform evidence and existing graph backend

Official OpenAI documentation reviewed on 2026-10-01 supports plugin sidebar and
conversation-panel surfaces with model/app context sharing
([extensions](https://developers.openai.com/plugins/build/extensions)). The bridge
reference documents model-visible results and component-authored follow-up
messages; session metadata correlates calls and is not a transcript archive
([reference](https://developers.openai.com/plugins/reference)).
Packaging and installed-client testing have their own contracts
([packaging](https://developers.openai.com/plugins/build/plugins)). Platform support
does not establish availability for every account or qualify Relay's integration.
Starting a new conversation from the UI and local runtime connectivity still need
their exact host contracts checked when implemented.

The earlier Context Explorer requirement is retained as a view over work state:

The requested product feature lives inside Relay's ChatGPT plugin. Users select
an authorized project or import, ask Relay to organize it, and open topic groups
or a graph connecting chats, messages, documents, artifacts and claims. Selecting
a topic retrieves its source-linked context for the current conversation. A chat
can participate in several topics without duplicating or rewriting its messages.

Relay owns collection, analysis, saved memberships, graph construction and context
retrieval. ChatGPT invokes these operations; the plugin UI renders their committed
results. The source `graph` command is the deterministic backend projection:
every edge names its basis. Captured chat ownership and file metadata differ from
model-proposed topic/artifact associations. Quote checks establish textual support,
not factual truth. Failed citations remain explicitly held for review. It does
not infer causal production dependencies, accepted versions or supersession edges.
Graph export preserves the exact request and hashes before writing, verifies
read-back and never calls the analysis provider.

OpenAI's [plugin extensions](https://developers.openai.com/plugins/build/extensions)
support a plugin's own sidebar entry and conversation panel. The
[MCP UI guide](https://developers.openai.com/plugins/build/chatgpt-ui) documents
rendering server-owned results and sending selected context to the model.
[File inputs](https://developers.openai.com/plugins/reference) support authorized
uploads and selections. These APIs make the Context Explorer interface feasible.
The reviewed public plugin APIs did not establish full ChatGPT history enumeration
or reorganization of its native chat list. That is an integration limitation,
not evidence that the graph cannot be built. Initial evidence can come from
explicitly imported chats/documents, context supplied to Relay, or an authenticated
connection to an authorized Relay project. Access must be enforced by the server;
model-supplied project IDs or anonymized conversation hints are not authorization.

The context pilot alone does not publish a plugin. The development build now
implements its own work UI and scoped local MCP service; public distribution and
live ChatGPT behavior remain unqualified. Native ChatGPT sidebar mutation requires
a separately established supported integration.
