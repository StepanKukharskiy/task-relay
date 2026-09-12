# Natural-language task routing

Enable conversation mode with `/orchestrator`, then describe the work and optionally say to use Codex. The relay supplies the conversational provider with current Codex task titles, project folders, short initial-request excerpts and availability. These are metadata for choosing a destination, not proof that project files have been inspected.

An explicit work request with one clear destination queues one Codex turn immediately. Several plausible destinations produce task-name buttons; selecting one sends the saved original request, including wording, newlines and constraints. The model cannot provide a rewritten execution prompt through the routing schema. General questions and hypothetical examples should remain answers rather than dispatches.

The independent routing worker rechecks task identity/history, current idleness and destination ownership before connecting and again before sending. Busy or changed destination tasks, active jobs on that same task, and strategy/execution tasks owned by an active linked workflow do not receive another request. Separate tasks in the same project may receive work independently; a peer being busy or unknown does not reserve the whole project. Routed reservations and duplicate prevention are keyed by task ID, including ordinary Telegram submissions. Uncertain delivery reserves only that destination. Linked roadmap loops retain their separate concurrency policy. Duplicate updates/choices cannot send it twice. Queued choices expire after 30 minutes. An uncertain IPC submission is recorded and never automatically replayed; inspect the task before trying to recover. A submitted receipt means delivery, not goal completion.

Results use the existing Codex watcher and file delivery. Reply to the resulting task card to continue that exact task. Use ordinary orchestrator text to ask about routing status. Existing workflow and production action cards retain their controls. Destination choices use buttons in this first version; free-text resolution of a pending choice is not yet supported.

This first milestone reuses existing desktop tasks only. It inherits their model settings and approval mechanism and adds no desktop task time/token cap. New task creation, automatic file discovery, generated pipeline plans and other providers' execution tool loops are subsequent milestones O02–O05 in ROADMAP.md.

The catalog excludes archived tasks and local worker/subagent records, and is capped at 300 entries. No raw tool output or full conversation history is sent for discovery. Automatic selection uses the configured conversational model; task-name choices handle ambiguity, while deterministic checks enforce known destinations, unchanged history and ownership. Live model classification and controlled dispatch tests are distinct from real phone-to-Codex acceptance.

## Reading project evidence

The conversational orchestrator can now find and read project files itself with `file_list`, `file_search`, and `file_read`. Tools are available for the known catalog/workflow project folders, across Gemini, OpenAI, Qwen, DeepSeek and OpenRouter conversation formats. It can inspect README/roadmap files, find another documented source, and follow local links before answering; the user need not supply each filename. Ambiguous project or source choices remain questions. These are read-only text tools, not shell execution, web browsing or media interpretation.

For an identified project, the current root ROADMAP.md is also captured automatically with its path, read time, modification time and SHA-256. Project scope comes from the current message, reply focus or earlier user messages, not assistant claims. Up to three roadmaps of 64 KB each are supplied whole; missing, oversized or unreadable files are explicit gaps, with file tools available for further discovery. Current canonical documents determine documented priorities; task titles are routing metadata and runtime receipts determine execution status.

Discovery is bounded to 12 calls in six rounds and a 1 MB accumulated request limit. Existing file-tool exclusions, text limits, paging and incomplete-search indicators apply. Private/hidden/credential paths, links and paths outside known projects are excluded. Request/response and read receipts are retained under `private/orchestrator-reads/`; interrupted conversation submissions retain the existing uncertain/no-auto-replay behavior. Reading a file does not register it as a production guide, alter a frozen assignment or authorize a workflow. Use reference collection/import for production inputs.

Verification: 460 tests pass, including provider-format tool continuations and path boundaries. A connected Gemini check read ROADMAP.md and its linked O03 implementation brief, returned the correct next milestone and retry limit, and proposed no action. Other provider formats have mocked integration coverage; their live tool eligibility is not established by this check.

## Images without an existing task

Upload a sketch in orchestrator conversation mode, wait for **Attached**, then say “Can we make a logo based on this drawing?” The orchestrator queues one managed Gemini image job using your exact words and the selected file bytes. It uses the image model configured for Gemini; a separate Codex task or production pipeline is unnecessary. Results arrive on the generated image task. Reply there normally with your changes to edit the image. Image tasks retain their image model and native image history across ordinary replies and restarts. `/gemini` explicitly switches the task to text discussion; `/image` switches back. Relay status commands do not generate another image.

Unaddressed uploads stay separate from production guides. To add guides to a particular production, reply explicitly to one of its notices/documents. Only ready references in the current conversation/production scope may be selected; selected image inputs use Gemini's existing six-reference, 10 MB/file and 11 MB combined limits.

## Production progress evidence

Production snapshots derive status from the same task/dependency rules as the scheduler and include current attempt errors, runnable queues and revision/selection availability. Queued reviewers behind blocked producers are waiting dependencies, not active execution. Review evidence is bound to the exact producer attempt; earlier reviews remain historical and cannot approve new drafts. A blocked attempt may deliver useful files without completing review or user acceptance. Exhausted stages require a separately bounded successor; neither waiting nor importing research resets attempts. Original feedback remains saved even when its requested revision cannot launch.

## Continuing an exhausted preparation stage

An explicit request such as “continue the video script using the provided research” can now create one same-scope successor of a blocked or exhausted preparation stage. This supports a single producer and independent reviewer with an existing user decision gate. It preserves the output declarations, criteria, provider, exact original request and registered sources; carries the prior producer drafts as unaccepted candidates; and imports current linked research. The same research folder remains linked to the successor.

The successor allows one attempt per worker, capped at the existing limits or 600 seconds/60 tool calls, whichever is lower. It stops at the existing user decision boundary; no rendering, publication, changed criteria or later stage is added. A clear request directly authorizes this bounded continuation without another setup card. Planning-only/status questions do not dispatch. Normal in-place revisions remain available when the old stage has budget.

A unique parent/request receipt prevents duplicate successors. Runtime artifact registration, plan creation and lineage commit atomically; the relay recovers a committed receipt after interruption before enabling scheduling. Changed parent contracts, tampered/missing inputs, pending uploads and active/uncertain work stop dispatch. A failed successor never creates another automatically. General new-workflow planning is still O03; this is a constrained continuation of an existing contract.

## Check status button

New production notices and production action cards include **Check status**. It returns a fresh card with runtime stage states, attempt counts, dependency blockers and the review gate, using no conversational model and launching no work. A button on an earlier stage follows its recorded continuation to the current stage. Status cards retain the button and their production reply routing. Each press returns a card; duplicate delivery of the same callback does not create another notice. Existing action buttons remain intact.

Callbacks are bound to a delivered production message and the paired private-chat user. Short hashed callback identifiers fit Telegram's limit even for long production names. A stale/missing scheduler heartbeat is disclosed; recorded running state alone is not presented as proof of current execution. Status reads skip source-file contents, so viewing progress does not require loading production references.

Repeated same-scope continuations keep current feedback at `continuation/REQUEST.txt` and the newest drafts under `previous-stage/`. Colliding inherited versions move to distinct `continuation-history/` paths with their original bytes retained and authority marked historical. Older stage records remain unchanged. This avoids duplicate workspace paths when continuing more than once.

## Optional guide discovery and choice

Codex `route_task`, `choose_task`, and `delegate_task` handoffs now search the selected
project for relevant optional guides across topics. Destination selection happens
first. Matching uses guide/skill/playbook/style naming, task words in paths and titles,
and bounded document content. The scan excludes private, hidden, dependency, output,
and archive folders and symlinks. It supports visible Markdown, text and reStructuredText;
it is not a whole-computer search or semantic guarantee. Incomplete scans are disclosed.

When candidates are found, routing pauses in `guides_pending`. The Telegram card lists
paths and offers one guide, all candidates, continue without optional guides, or cancel.
Nothing starts until the choice. At most six candidates are offered, with a 5,000-entry,
eight-directory-depth and 8 MB text scan budget. The choice expires after 30 minutes.
A failed/incomplete scan also pauses for a decision rather than implying no guide exists.

Research sources remain separately frozen as requested. Guide versions are saved before
the card; only chosen guides enter the handoff manifest. The agent gets the original
guide location for resolving its relative references. Hash checks guard the saved copies;
task identity and availability are rechecked before approval and dispatch. Repeated
callbacks do not repeat submission. An unexpired pending guide choice reserves only its
destination task. Snapshot status distinguishes proposed guides, the user decision,
included inputs and actual submission.

Remembered guide profiles record discoveries, not permission to apply them next time.
AGENTS.md is not an optional candidate: native project instructions apply independently.
This replaces the earlier LinkedIn-only automatic bundle. Direct Claude/API queues and
already registered production/reference-pack contracts retain their existing input rules;
that original routing-only gate is now supplemented by the orchestrator-level gate below.

## Guide-aware orchestrator drafting and managed workers

Guide discovery now begins with the model's explicit `discover_guides` action,
using the original user request or an explicit model-selected topic query. It searches up to 20 known project folders, ranks
matches across projects, and offers up to six candidates. This works without choosing
Codex or creating a worker task. The model decides whether guides are relevant from
the request and context; question words and work verbs do not trigger or suppress it.
File tools remain available for other discovery questions. The scan uses
visible local text guides and the existing directory/read limits; it does not search
all home directories, cloud drives, hidden skills or arbitrary disk paths. Incomplete
scans are disclosed.

The durable `orchestrator_guide_choices` record binds a guide set to one original
request. A paired-user button choice resumes that same request once. Guide files are
frozen before the choice and checked again before use. Selection accepts up to 80 KB
of complete guide text, never silent truncation. Status questions can distinguish
waiting for a guide choice from a queued/running conversation. Declining does not remove
native project instructions, and choosing a guide does not authorize new stages,
publishing or altered budgets.

Selected guide bodies and original source locations are supplied to the orchestrator
regardless of its conversation provider or production focus. It can draft card text,
posts and scripts directly. Relevant companion references can be read through file
tools; unread or missing companions must be disclosed. A direct draft is not rendered
card imagery, publication or a completed production stage.

The same selection is forwarded as text to existing managed Claude/API and image jobs,
as frozen files in Codex handoffs (without a second guide question), and as versioned
feedback inputs to BOTH producer and reviewer for revisions/continuations. Linked
workflow planning/run controls carry the selected guide context with the source request.
A selected new guide cannot silently modify a never-started frozen production contract:
that requires a revised assignment. No arbitrary new production graph creation is added.

## Generated production files in Codex handoffs

The snapshot now lists the 100 most recent generated artifact versions, including
useful reports from blocked attempts. Routing actions (`route_task`, `choose_task`
and Codex `delegate_task`) explicitly select `artifact_ids`; when this catalog is
nonempty, omission blocks dispatch and `[]` means no generated files are needed.
The LLM resolves references using reply/focus, run, purpose and version, or asks
which file when ambiguous. This selection is separate from `research_ids`.

Relay verifies the immutable blob, freezes a readable copy under the request's
`route-inputs` directory, and sends the original filename, local path, SHA-256,
run/task/attempt identity and state at capture. It rechecks the copy before dispatch.
Sharing a blocked report does not accept its run. Destination choices retain the
same selected versions; missing/changed files fail rather than fall back to chat
history. Up to ten artifacts, each at most 100 MB, are supported. The supplied
conversation remains additional context, not a replacement for selected files.
