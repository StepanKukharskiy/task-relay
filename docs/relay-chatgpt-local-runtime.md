# Legacy local work-state plugin (0.2.1)

This retained guide describes the earlier database-backed development integration.
The web V1 now follows [the portable Skills/work guide](relay-chatgpt-plugin.md).
Existing local state and runtime contracts remain available independently.

# Task Relay for ChatGPT — development integration

**Keep the work, not just the conversation.**

Task Relay maintains the state of work between AI interactions. ChatGPT is one
interface into that work-state system; the MCP plugin is its integration mechanism.

Connect the material relevant to a piece of work. Task Relay retains an inspectable
state containing its objective, conclusions, decisions, evidence, artifact
versions, unresolved questions and possible next actions.

**Connect → Understand → Continue → Capture**

1. **Connect** selected conversation excerpts, Codex project evidence, files or
   other explicitly supplied material through the available adapters.
2. **Understand** what the work is about, what has been decided, which artifacts
   are current and what remains unresolved. ChatGPT interprets the connected
   evidence; Task Relay turns that interpretation into durable, source-linked
   work state and retains its limitations.
3. **Continue** from a question or suggested action with the relevant current
   state supplied to ChatGPT.
4. **Capture** explicit result notes and questions against that continuation.
   Proposed decisions and artifact references can be retained too; accepting a
   decision or selecting an artifact requires its own review.

ChatGPT supplies intelligence; Task Relay maintains the persistent work state
between AI interactions. Task Relay separates AI-derived understanding from
reviewed project state.
Suggestions, conclusions and artifact candidates do not silently become accepted
decisions or current deliverables.

The graph is one way to inspect these relationships. **Persistent, resumable
work is the product.** Task Relay helps work remain coherent through explicit
identities, evidence, selected versions, unresolved questions and receipts.

## The project experience

Open Task Relay → Competition → understand where the work stands → choose one of
2–4 grounded next actions → continue in ChatGPT → retain the result → return
to changed work.

The sidebar starts with **Work**. A project opens on **Current state**, with its
objective and current conclusions, decisions, selected artifacts, open questions
and suggested next steps. **Current | Sources | History | Graph** keeps source
inspection, reviewed history and relationships within reach. Sources has a
searchable index of connected titles and click-through provenance; being in that
index does not mean a source informed the saved state. Candidates stay separate
from selected artifacts, and proposed decisions stay separate from reviewed ones.

The primary next-action list shows up to four source-linked suggestions. Selecting
one prepares its exact current context; sending it to ChatGPT revalidates that
context. Retaining a result changes work and marks the saved overview as needing
an update. The user can update the state from the connected sources when returning.
No example objective or recommendation is substituted for Competition's actual
saved state.

**Task Relay understanding** groups the proposed objective, conclusions, questions
and actions. **Reviewed state** groups explicitly reviewed decisions, selected
artifacts and resolved issues. Artifact candidates remain outside reviewed state.
The overview displays its actual save time, considered source/record counts and a
prominent changed-work marker. Counts describe saved records, not uncaptured file
edits or verified factual truth.

Sources distinguishes connected source records, sources considered in the frozen
input, sources cited by the saved understanding, and sources added after it was
saved. Request records, evidence excerpts and artifact references count as sources;
decisions and other work records have their own input count. Opening a source does
not establish that it informed the understanding. Inspection-only use is not
persistently tracked or estimated. Each proposed statement opens its exact quotes
and supporting record identities for inspection.

The component uses the existing Task Relay desktop logo and imports the desktop
control styles from `companion.css`: system fonts, blue primary actions, shared
field/card radii, 36 px minimum action height and visible keyboard focus. The
184 px work sidebar follows the desktop shell. Graph relationships use smooth
cubic Bézier curves; proposed relationships retain their dashed style and basis.

The product benchmark is: **Can you leave complicated work for a week, return,
understand it in 30 seconds, and continue without reconstructing its history?**
This remains an acceptance exercise for the connected experience, not a claim
established by protocol or interface tests.

## Development build and current limits

The current 0.2.1 source build implements the work-state backend, thirteen MCP
tools, an MCP Apps interface and a local plugin package for much of this loop.
It can inspect decisions, supersession history, evidence, issues and artifact
versions; prepare and validate continuation context; save source-linked ChatGPT
understanding; and retain explicit continuation results. One bounded worker
publishes exact reviewed text as a new, unselected artifact version. ChatGPT
supplies intelligence; Task Relay preserves state and does not call a model directly.

The complete connected ChatGPT experience is not yet qualified. Source discovery,
automatic collection and deployed ChatGPT integration remain incomplete.

The [connection runbook](relay-chatgpt-connection.md) prepares a project-scoped
Secure MCP Tunnel launcher for a real private ChatGPT test, followed by a separate
remote HTTPS package/ZIP for public submission. Reopened components fetch current
server state; optional ChatGPT widget persistence retains navigation and the
capture identity without caching work data or review controls. These capabilities
still require an actual connected-host check.

This is a developer build, not a published or installed ChatGPT plugin. The
installed local Task Relay Desktop baseline is 0.13.153, including the work-state
and completion bridge runtime; connected ChatGPT deployment remains separate. The accepted broader product
direction is in [project context](project-context.md#relay-for-chatgpt--accepted-product-direction).

## What is still missing from the requested experience

Opening `task_relay/assets/relay-work.html` directly is not running the plugin.
It is the component source; the server bundles its CSS/JavaScript and a compatible
MCP Apps host supplies initialization, tool results and the conversation bridge.
The existing backend, tools and package are a development foundation, not a
qualified end-to-end installation.

The next product proof is the Competition loop above, using deliberately selected
sources with visible coverage and grounded suggestions in a connected interface. The current Codex collector supports one exact
project root and user/final-assistant text; whole-library discovery, incremental
refresh and a general ChatGPT ingestion adapter are not implemented.
The host-model analysis/report handoff and result capture are
implemented in local source, but have not run in installed ChatGPT. Saved analysis
imported into the work store does not prove this connected experience.

Do not promise full ChatGPT history access merely because the desktop app or
plugin is installed. Current [OpenAI plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines#tool-data-handling)
restrict an MCP server to explicitly supplied snippets/resources and prohibit
pulling or reconstructing the full client chat log. Collection from user-chosen
local evidence belongs behind a separate host adapter, with coverage limitations
reported. A ChatGPT export/explicit sharing adapter is a candidate to qualify;
local app cache completeness and published-plugin eligibility are unproven.
Expose task-relevant saved work through the plugin, rather than treating plugin
installation as a history permission. Suggestions remain proposals; they do not
establish acceptance or authorize execution.

## Local setup

Use Python 3.11 or newer with the current source runtime and the pinned plugin
extra. Keep work data and local profiles in private storage.

```sh
python3 -m venv /absolute/relay-plugin-env
/absolute/relay-plugin-env/bin/python -m pip install '/absolute/task-relay[plugin]'
/absolute/relay-plugin-env/bin/python -m task_relay.chatgpt_plugin --db /absolute/private/state.sqlite
```

The default database is Task Relay's configured shared `state.sqlite`. The plugin's
`work_*` tables are authoritative for its explicit work records and coexist with
production records; they do not overwrite production history or approval state.
Work selections determine context, not production acceptance. `.relay/job.sqlite`
and imported analysis stay read-only evidence/projections, with their original
authority retained. The current build does not automatically synchronize all
production jobs into work projects.

Add repeated `--project EXACT_WORK_ID` to restrict a server connection. In stdio,
the local process's OS user and launch configuration are the access boundary.
Model parameters cannot grant a folder or choose an arbitrary database. New work
created through MCP has no filesystem grant. Local administration alone grants a
project root. The no-follow host filesystem adapter enforces reads/writes within
that root. Other OS hosts without that adapter are unqualified.

## Import and inspect work

Save the exact request in a private text file. Create one project and retain its
returned ID:

```sh
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite create --title 'My project' --request-file /private/request.txt --root /absolute/project
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite import-context --project WORK_ID --context-db /absolute/private/context.sqlite --run CONTEXT_RUN_ID --request-file /private/request.txt
python3 -m task_relay.work_state_cli --db /absolute/private/state.sqlite inspect --project WORK_ID
```

`import-context` consumes an already validated Task Relay project-context run without
another provider call. It rechecks the capture hash and coverage, retains source
identities through deterministic mappings, and connects saved topics, claims,
artifact inventory and held citations. An inventory snapshot is logical version
1 of that captured file; it is not an accepted or verified native output. These
inventory entries have no content hash, so continuation reports them as unverified.
Source capture and execution receipts remain in their original database.

Alternatively, `import --file /private/work.json` accepts this bounded format:

```json
{
  "schema": "task-relay.work-state",
  "records": [
    {"id": "source-1", "kind": "evidence", "title": "Brief",
     "data": {"text": "Make a guide.", "refs": [], "topics": ["Guide"]}},
    {"id": "draft-1", "kind": "artifact", "title": "Guide draft",
     "data": {"path": "guide.md", "family": "guide", "version": 1,
              "sha256": null, "refs": ["source-1"], "topics": ["Guide"]}}
  ]
}
```

Imports are frozen, idempotent for identical content/request, and cannot overwrite
record identities. All imported decisions and execution claims remain proposals.
This format and saved Task Relay context are the current ingestion adapters; arbitrary
ChatGPT JSON exports and automatic whole-account history ingestion are not added.
Supported credential patterns are redacted in model/UI views; original requests
and structured imports remain in private storage. This is not a complete secret
detector.

## Connect, understand, continue, capture

The target experience is to open a piece of work, understand its current objective,
conclusions, reviewed decisions, artifact versions and unresolved questions, choose
one useful next action, and retain the resulting work. Universal ingestion is not
required for this proof. The graph inspects the records; persistent resumable work
is the product.

The UI's **Connect explicitly supplied material** form records only the named
snippet/brief the user chooses to send, with its exact connection request. The
existing local selected-project adapter and structured import remain available;
the form does not fetch a chat transcript or browse the account.

**Understand this work with ChatGPT** (or **Update current state with ChatGPT**) calls `relay_prepare_understanding`.
Task Relay freezes the current record revision, global constraints, selected artifact
checks, candidate versions and a bounded source catalog. It includes deliberately
supplied notes, reported continuation results and existing checked excerpts, with
explicit coverage. Unselected archive text is not silently included. The model
can inspect a referenced source with `relay_provenance`; explicit `record_ids`
can expose additional connected records. Budget overflow blocks preparation.

The UI asks the host model to analyze this input through `ui/message`. ChatGPT
then calls `relay_save_understanding` with an objective, conclusions, decision
proposals, open questions, workstreams, next actions and limitations. Each statement
requires literal quote citations to identities in that frozen input. Groups and
action topics are checked against its source scope. These checks prove citation
identity, not semantic truth. The original report, exact request, input hash and
receipt are durable; replaying an identical saved report returns its receipt.
Partial saves roll back. Changed work/files block stale analysis publication.

The Current state view shows the proposed objective, conclusions/questions and
source-linked actions separately from reviewed decisions and selected artifacts.
Derived workstreams overlap without moving or rewriting source records. A change
to work marks the analysis stale. Selecting **Continue…** freezes the exact fresh
action request and its evidence alongside global decisions/issues and relevant
selected versions. Task Relay rechecks the analysis's selected files. Action-only
sources use disclosed exact cited excerpts; evidence for global constraints stays
intact. Full connected records remain inspectable. The UI still validates the
packet before sending it to ChatGPT.

`relay_capture_result` retains explicitly exposed result notes and new questions
against that immutable continuation. It does not ask for the client conversation
log. Late reports disclose that work has moved on; capture never replays execution,
accepts a decision or selects a version. The exact notes and packet hash remain
stored, and identical retries return the same capture receipt. Future analysis
includes these notes and questions. Artifact references use `relay_import_work`;
the bounded reviewed text worker registers its own outputs and receipts. A local
administration bridge can now project production/provider completions and
submitted candidate/continuation sets into a [common execution envelope](execution-results.md).
Owned text/plugin results capture automatically; other outcomes use explicit
host source/project/packet links. Existing scoped tools expose observations,
pending capture state and continuation context. Blanket production synchronization
and model-facing arbitrary worker/source grants remain pending.

The optional result form provides an explicit fallback. Host-model tool calls
can complete the same flow without UI. Successful `ui/message` delivery proves a
request was accepted by the host, not that ChatGPT completed analysis or saved a
report; only the committed report/capture receipts establish those state changes.

## UI and tools

`relay_open_work` returns the work picker or exact project state and declares
global/sidebar and conversation entrypoints. The UI defaults to Current state, with Current, Sources, History and Graph
tabs, overlapping workstream views and click-through provenance. The source index
uses the existing connected-record graph metadata; source details stay behind
`relay_provenance`. No new collection adapter or backend state type is introduced.
Decisions are global constraints even in a topic view. Graph edges name their
basis; imported associations are distinct from reviewed dependencies. Large graph
views display an explicit count and up to 100 nodes, without trimming backend data.

`relay_prepare_change` freezes an exact decision, selection, issue resolution,
dependency or text output for review at an expected revision. Its confirmation
control is component-only `_meta`, absent from model-visible results.
`relay_commit_change` has app-only visibility and requires that exact control and
an explicit confirmation. Cancel leaves the review unapplied. Changed work blocks
stale confirmation; an identical committed retry returns its saved receipt.

The model may propose organization through `relay_import_work`; the runtime builds
the saved graph and state. A reviewed supersession keeps its prior decision and
marks outputs with reviewed dependencies as potentially affected. Unknown links
remain unknown; no section-level staleness is inferred. Artifact selection stays
explicit even when a newer candidate exists or versions conflict.

**Continue this work** calls `relay_prepare_continuation` with an exact request,
expected revision and optional topic. It captures current decisions, selected
artifacts, file checks, cited evidence and all open issues. It preserves global
constraints across topic views and fails rather than silently exceeding its
budget. Packet identity/hash and exact request are saved. Before sending a
`ui/message` to the conversation, the UI calls `relay_validate_continuation`;
changed state or selected files block stale use. Validation does not execute work.
This build sends context to the current conversation; new-conversation launching
is not implemented.

Tools also include `relay_list_work`, `relay_provenance` and `relay_work_graph`.
Server-side project checks apply to every project-scoped operation. UI resources
are self-contained and use no external network/assets. Tools work without the UI.

## Bounded text execution and recovery

A `write_text` review uses this change payload:

```json
{"action": "write_text", "packet_id": "PACKET_ID", "family": "guide",
 "filename": "guide.md", "content": "# Revised guide\n"}
```

Confirmation commits the exact request, packet reference, execution assignment
and ownership before publication. The worker creates a new file under the granted
project's `.relay/outputs/` with exclusive no-follow writes and exact read-back.
It neither overwrites a previous version nor runs supplied scripts. The output
is registered as a new candidate version with its hash and receipt. A separate
selection is required to use it as selected work context.

State or input changes after Start leave the assignment queued. Interrupted
publication stays inspectable; normal calls never replay it. Explicit local
`recover-text --project WORK_ID --run RUN_ID` can register a byte-identical file
already published. A missing or edited file blocks recovery without another
write. History shows the saved run status and can prepare an explicit recovery
review for that same publication; confirmation registers matching existing bytes
without writing again. Other native formats, arbitrary worker dispatch, production plan review,
delivery and paid provider work remain under their existing runtime contracts and
are not exposed by this build.

## Local profile and ChatGPT connection boundary

`plugins/relay` contains the portable manifest and stdio configuration. Build a
private source profile with the exact Python environment/database/project grant:

```sh
python3 scripts/build_relay_plugin.py --out /absolute/private/relay-plugin --python /absolute/relay-plugin-env/bin/python --db /absolute/private/state.sqlite --project WORK_ID
```

It produces portable and compatibility profiles plus file hashes. It does not
install, register or publish the plugin. The developer profile references this
source checkout; it is not a portable public release archive. Install a local
profile through a supported local marketplace/client and qualify the host there.
Both profiles use **Task Relay** as their display name and include the existing
desktop logo as their logo/composer icon, using package-relative asset paths from
the [official packaging format](https://developers.openai.com/plugins/build/plugins).
The tool names, resource identity and package identifier remain stable.

For private protocol testing, `--transport http --port 8766` binds only to loopback
and requires a token of at least 32 characters in `RELAY_PLUGIN_TOKEN`. Tokens are
not stored in the package or printed. HTTP is single-operator bearer-authenticated,
not a hosted multi-user OAuth service. Public ChatGPT connection requires a
supported reachable transport, authentication/authorization integration and
registration; the loopback test endpoint alone does not meet those requirements.

The source also supports a configured external OAuth authorization server:

```sh
python3 -m task_relay.chatgpt_plugin --transport http --host 0.0.0.0 --db /absolute/private/state.sqlite --project WORK_ID --issuer https://issuer.example/ --jwks https://issuer.example/jwks --resource https://relay.example/mcp --subject EXACT_OWNER_SUBJECT
```

Provide HTTPS ingress at that resource URL and configure the issuer's client
registration/consent for ChatGPT. Task Relay publishes RFC 9728 resource discovery and
authentication challenges, verifies RS256 signatures, exact issuer/audience,
expiry and owner subject, and enforces `relay:read`/`relay:write` per tool. OAuth
mode requires an explicit project allowlist. Non-loopback binding is rejected
without configured OAuth. Task Relay does not run its own login/authorization server
or infer identity from ChatGPT session hints. The configured issuer owns login,
client registration and refresh tokens. This verification adapter passed
controlled signed-token checks; no external issuer or public endpoint was used.

Official contracts reviewed for this build:
[UI and bridge](https://developers.openai.com/plugins/build/chatgpt-ui),
[entrypoints](https://developers.openai.com/plugins/build/extensions),
[packaging](https://developers.openai.com/plugins/build/plugins), and
[connection/qualification](https://developers.openai.com/plugins/deploy/connect-chatgpt),
and [authentication](https://developers.openai.com/plugins/build/auth).

## Qualification

Controlled small-text checks cover assistant acceptance claims, explicit
selection versus newer candidates, retained supersession and reviewed impact,
cross-project isolation, stale controls/context, rollback, private originals and
redacted views, symlink/traversal rejection, committed execution and interrupted
publication recovery. SDK checks exercise actual stdio protocol/tool/resource
round trips, authenticated HTTP initialization and OAuth signature/owner/scope
rejection with discovery and challenges. Controlled DOM checks exercise
safe rendering, Cancel, exact confirmation, provenance, stale-packet blocking and
host context messaging. These are not deployed ChatGPT checks. A local Codex-host exercise uses the
existing MCP tools to save a source-linked overview and four next-action proposals
from connected Competition evidence, verifies exact save retry, and prepares and
validates one action packet. A read-only browser preview checks the Current state
layout, source title search, provenance and secondary graph. It supplies no
ChatGPT conversation bridge and does not execute or capture a continued task.

Commands and results belong in ignored `outputs/`. Installation, real ChatGPT UI,
public endpoint/OAuth, native file quality and external delivery need their own
evidence before claims of operation.
