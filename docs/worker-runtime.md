# Local worker factory and workflow scheduler

Reel rendering can use the shared [provider-independent `media.compose` operation](reels.md).
The selected model authors scene data; the local renderer owns HyperFrames and
FFmpeg execution. Text and isolated Python workers do not need shell access to
participate. Same-provider code review can inspect delivery bytes and receipts;
human visual selection remains separate.

API text workers receive a source pack containing up to 96,000 bytes of exact
hash-verified input text, with the candidate and current request prioritized.
Omitted portions carry character offsets for the existing file-read tool; all
original source files and grants remain available. The pack is recorded with the
worker receipts. Complete candidate text must have been supplied before a review
can accept or request revisions. Placeholder-only outputs cannot substantiate a
successful delivery, and a placeholder-only candidate cannot be accepted. These
are procedural checks; source exposure does not prove sound editorial judgment.

Long text can be written in substantive sections: `file_write` creates the first,
then `file_append` requires the byte count from the latest confirmed write receipt.
A stale count fails without appending. Confirmed truncated or malformed generations
can recover once per failure kind within existing request/tool/time limits for
local text and code workers. Every call in the incomplete response is discarded;
recovery starts from the last confirmed tool results. Transport uncertainty and
safety stops do not qualify for this recovery.

An explicit continuation after a definitively finished, exhausted API text review
failure can create one new producer/reviewer stage under the original scope and
provider. It retains the failed review receipt and all parent attempts. It does
not reinterpret an invalid review report, reset attempts, or replay uncertain
requests. Existing recovery for a completed review of an older candidate remains
separate.

Task Relay can now create execution workers, give each an isolated workspace, register their delivered files, and advance a bounded dependency graph. Start with `python3 -m orchestrator --help` from the project folder. The main runtime shares `private/state.sqlite` with the relay, using namespaced production tables. Artifact files and worker workspaces remain under `private/orchestrator/`. It does not alter or activate existing Telegram `/workflow` links. See [shared storage](shared-storage.md).

The implementation carries forward the durable dispatch and bounded revision approach in [linked workflows](linked-workflows.md). The `orchestrator/` package owns worker creation instead of requiring two pre-existing desktop tasks. The agent adapter is the installed Codex CLI with file and shell capabilities. [Registered text procedure/API steps](mixed-execution.md) can now share its graph and recovery records. Text-only API connections remain distinct from agent execution with tools.

## Assignment-specific report forms

New agent assignments freeze a `report_contract`: workers fill named criterion
slots, decisions and evidence; Relay supplies assignment identity and criterion
numbers. Source-fidelity evidence can be a typed object with observed hashes and
measurements. Raw responses and canonical reports remain separate, and acceptance
still requires domain validation and any human selection. Codex and shared API
agents use the same form. See [typed contract builders](typed-contract-builders.md).

## Result disposition

All workers share the [result policy](result-policy.md). Usable outputs with typed
quality findings pause for explicit user acceptance or correction feedback. An AI
review cannot substitute for that decision. Technical failures and uncertainty
keep their existing recovery boundaries; quality does not override procedural
file validation or native authorization.

## First verified loop

This demonstrates a local execution loop. It does not establish reduced total user effort or that a model reviewer can judge listening preference.

## Telegram stage control

After a plan and its files are registered, ask `/orchestrator Start NAME`. The model proposes a stage action card containing the frozen brief, task objectives, attempt limits and per-attempt time/tool budgets. Registration and the proposal launch nothing. An authenticated tap on the fully delivered current card enables the production scheduler; duplicate, stale and expired taps cannot dispatch a second run. Plans changed after approval stop scheduling. Automatic reviewer revisions remain within the approved contract.

The service creates the execution workers, hands outputs to the reviewer, and stops at the registered user gate, exhaustion, cancellation or uncertain outcome. It sends one terminal notice and the latest registered output files as replyable Telegram documents. It resumes monitoring in-flight workers after a service restart, including when scheduling is paused or cancelled. Telegram production cards offer exact selection, pause/resume, cancel, status and inspection; linked `/workflow` controls do not operate these runs. See [production decisions and next stages](production-selections.md) for semantics and limits.

You can ask in Telegram: “Create a folder for this video's research.” The orchestrator's `create_production_folder` action creates `~/Documents/Task Relay Productions/<run>/research/` and a README, links it to the registered production, and returns the actual path. It is a reversible filesystem action and runs directly from the request, without a worker attempt or extra action card. Repeated requests reuse the linked folder; unlinked existing folders and symbolic links are rejected. The model cannot choose an arbitrary path.

Place notes, saved pages, PDFs, screenshots or other research files there. Ask “Import the research from my folder” to snapshot new/changed files into production input staging. A preparation revision imports the linked folder before its card too. Local originals remain editable; workers receive copied bytes. Imports retain filenames, relative source paths and hashes, deduplicate unchanged files, and share the existing ten-file / 50 MB pending-input limit (20 MB per file). Saving files does not trigger a watcher, research or execution. Importing remains available after an attempt budget is exhausted; running another stage still needs its own setup.

Production replies use a dedicated review conversation with history scoped to that production. Ordinary feedback such as “we need current market analysis” requests a revision without requiring command language. The conversational interface cannot verify current market facts itself; a stage limited to registered sources must identify the need for fresh sources or a separate research stage.

Reply to a production notice or any of its documents with corrections to get a **Revise preparation** action card. The current implementation supports one unambiguous producer awaiting user review and its paired reviewer, with unused attempts remaining for both. The card queues the exact Telegram text; it does not use the conversational model’s summary as the worker instruction. Prior registered inputs and outputs remain available, and the original scope, criteria, budgets and user gate remain in force. Rendering a preparation-only stage or exhausting its budget requires separate stage setup.

New guides can be uploaded as replies to production documents. Uploads preserve filenames and captions, download independently (20 MB each, ten new files / 50 MB per revision), and never start work. Wait for “Guide attached” for every file, then send the revision instructions. The confirmed card freezes the ready guide list and hashes. Both producer and reviewer receive immutable registered copies plus the verbatim feedback file. A failed upload must be resent with the same filename; a changed guide or stage invalidates the card. Runtime revision receipts prevent a restart between databases from applying the same revision twice. Each finished attempt set gets its own terminal notice; document captions identify filename, stage and attempt.

**Planning boundary:** chat can discover and collect a previous production's references and propose a new bounded producer/reviewer stage through the [O03 planner](new-pipeline-planning.md). Its exact-plan approval registers and enables that stage. General multi-stage planning and the complete decision loop remain separate work.

## Local commands

Import only selected files. An import creates an immutable registered copy and returns its artifact ID:

```sh
python3 -m orchestrator import-file /absolute/path/approved-cards.md --purpose 'Approved card text'
```

Write an inputs JSON file using the returned ID and a workspace-relative destination:

```json
[
  {
    "artifact": "ACTUAL_ARTIFACT_ID",
    "path": "references/approved-cards.md",
    "purpose": "Exact card titles and order",
    "authority": "Selected card text for this job; no authority for new image geometry"
  }
]
```

Generate a reviewable stage plan, register it, then start the scheduler:

```sh
python3 -m orchestrator template carousel --id carousel-stage --inputs inputs.json --model gpt-6-astra --reasoning high > plan.json
python3 -m orchestrator create plan.json
python3 -m orchestrator run carousel-stage
python3 -m orchestrator status carousel-stage
python3 -m orchestrator events carousel-stage
```

`create` does not dispatch. `run` monitors and dispatches within the saved plan; `tick` performs one scheduler pass. The scheduler window defaults to 30 minutes, independently of each worker's wall-clock bound. Stopping the scheduler leaves its already-started workers supervised. Run the same command to recover their receipts and continue; it does not start another copy of an in-flight assignment. Process inspection and normal Codex authentication must be available to the host process.

The three small templates are `competition` (program/constraint extraction), `carousel` (storyboard and correspondence), and `office-anime` (episode production handoff). Each uses a producer, a separate reviewer and a purpose-specific user gate. These are stage templates, not complete media or design factories. Their graph mechanics have been tested with a deterministic backend; the live execution test used the custom Episode 02 audio plan.

Inspect the exact registered outputs with an export to a **new** directory:

```sh
python3 -m orchestrator export carousel-stage produce /absolute/path/new-delivery-folder
```

Exports copy registered output bytes, not whatever is currently in a worker's workspace. `RELAY-DELIVERY.json` identifies the attempt, hashes, state and any recorded selections. Original input artifacts remain in the runtime archive; an output export is not a standalone reproduction environment.

After an actual user selection, record its exact artifact ID and the plan's decision purpose:

```sh
python3 -m orchestrator select carousel-stage produce ACTUAL_ARTIFACT_ID --purpose 'storyboard selection' --note 'Verbatim user choice and its context'
```

A selection concerns that artifact and purpose. It does not grant unrelated dimensional, visual, voice or general-policy authority. An old version cannot satisfy the current version's gate. Do not call this command to manufacture user approval from a model verdict.

A bounded correction preserves the previous files and creates a fresh assignment and worker:

```sh
python3 -m orchestrator revise carousel-stage produce --instruction 'Concrete correction within the existing scope'
python3 -m orchestrator run carousel-stage
```

Model-requested revisions use the same path automatically. The original scope, criteria, inputs and execution budget remain inspectable; prior outputs are supplied under `previous/`. A producer allows at most three attempts, with two by default. Exhaustion blocks further work. Downstream work that has already started prevents silently revising its source task.

`replace-future RUN assignment.json` versions a never-dispatched assignment. `add-future RUN assignment.json` adds a validated future step. Neither edits running assignments. Dependencies, output references, cycles, review coverage and bounds are validated before saving. Review gates must exist before their producer starts.

```sh
python3 -m orchestrator cancel carousel-stage
python3 -m orchestrator tick carousel-stage
```

Cancellation stops future dispatch and requests termination from each worker's process owner. `cancelled` for a worker is recorded only after its receipt confirms termination. If the owner is missing, the result stays uncertain; the runtime does not pretend cancellation succeeded or replay the assignment. Inspect `workers/ATTEMPT/` receipts and logs before explicitly planning replacement work.

## Assignment and execution records

A plan specifies a fixed backend/model/reasoning effort, brief, concurrency (1–4) and up to 30 tasks. Each task declares objective, role, instruction, exact input artifacts with purposes and authority, output paths/purposes, criteria, dependencies, tool profile and execution limits. A `resource` name serializes tasks claiming the same composition across workflows in the same runtime database. All workspaces are separate copies; there are no shared editable composition directories.

Before launching, SQLite records the frozen resolved assignment, artifact IDs and hashes, worker identity and dispatch intent. Assignments are append-only versions. The supervisor source is copied per new worker; source hashes are included in new dispatches. The worker receives `.relay/ASSIGNMENT.json` and a structured final-response schema. The supervisor records the actual CLI session ID, raw event stream, usage, tool count, exit status, limit/cancellation reason and timestamps.

Events include assignment creation, dispatch, worker start/finish, registered output delivery, procedural checks, model self-reports, independent model review, revisions and user selection. They link attempts and artifact versions. Execution state comes from service operations and process receipts, not inference over conversation text.

The service checks declared files, path safety, input-copy integrity, output size and report identity/criterion coverage. Model self-reports and independent review judgments are separately labeled. A model verdict can release the next technical stage, but cannot satisfy a user gate. `completed` without a user gate means the declared execution/review contract finished; it is not a universal claim of user acceptance.

Blocked reports may contain partial checks when execution stops early, but supplied
indices, boolean verdicts, evidence and instruction text are validated before
formatting. Malformed blocked reports retain their raw response and drafts, settle
blocked and do not release dependencies. O03 tests these orchestration boundaries
with text artifacts; media rendering and browser checks are job-specific.

## Limits and remaining work

- Workspaces use the Codex `workspace-write` sandbox and isolated copied inputs. Temporary directories are also writable; reads are not confined to a confidential-data container. The file/shell tool profile and restrictions on outside reads, messaging and additional agents are assignment policy, not a complete tool-authorization firewall.
- The supervisor enforces elapsed-time limits and stops after the observed tool-start count exceeds the bound. Already-started tools may run before cancellation is processed. There is no hard token, dollar, memory, disk or network quota.
- Uncertain launch or process-inspection results retain their identity and resource lock. No automatic retry or inferred recovery from a model's “done” message occurs. An intact completion receipt can later reconcile the same attempt.
- Plans can be authored through JSON/templates or proposed by the bounded planner. Telegram supports exact-plan approval, registered-stage starts, bounded revisions, reference collection, output delivery, [selection, pause/resume/cancel and next-stage planning](production-selections.md). Next-stage planning carries exact selections and prior instructions into another bounded producer/reviewer pair. Arbitrary multi-stage graphs, branching successors and additional execution backends remain separate work. Selection/cancellation and explicit future-assignment changes also exist in the local CLI.
- The current replay tests routing and receipts. Human listening acceptance, additional real carousel/competition stages, model-requested revision on actual production, and measured coordination burden remain to validate.


## Unassigned Telegram albums

An upload sent to the orchestrator without a production target is saved locally.
Album members share one folder with upload-ID-prefixed filenames, so four Telegram
photos named photo.jpg remain four distinct files. The receiving notice is grouped;
a final receipt lists the saved folder and actual names. Legacy upload locations
remain readable and are not moved.

After all received members finish downloading and three seconds pass without a
new member, one nonempty caption is queued verbatim as an orchestrator request,
with the exact upload IDs. Captionless groups only receive a save receipt; different
captions or failed members do not dispatch partial instructions. A late member is
saved and reported but never added silently to a request already queued. A new
instruction can select it. This is a bounded quiet-window heuristic: Telegram
provides individual album updates without a final-member marker.

Groups allow ten files and 50 MB, with 20 MB per file and a 50 MB pending-download
reservation limit. Previously saved groups do not exhaust the next group's quota.
The caption follows normal routing and approval checks; it is not approval of host
scripts or production candidates. Uploads replying to production documents remain
guides and retain the separate revision flow above.


### Shared native recovery policy

`orchestrator/recovery.py` decides from trusted adapter evidence, not an LLM's
interpretation of error wording. `orchestrator/native_recovery.py` translates
registered native phase receipts. Recovery never itself authorizes dispatch.

| Evidence | Next action |
| --- | --- |
| Confirmed stopped before the selected script ran | Check host readiness and propose unchanged inputs/limits with a fresh Start |
| Confirmed terminal script or verification failure | Prepare a scoped correction under the existing allowance, review it, then request exact-code Start |
| Completed work | Retain the result; do not execute it again |
| Unknown, contradictory or potentially live execution | Inspect and reconcile before considering a retry |
| Known failure without a supported repair | Resolve the environment or request the missing input |

The production integration verifies the latest assignment, artifact identity and
receipt hash, preserves old attempts, and commits a successor plan before external
dispatch. Completed dependencies are reused as exact artifact references. This
iteration wires Rhino and Blender native scripts; other recovery paths retain
their existing policies. A new adapter needs reliable execution/effect evidence
and bounded recovery integration, not a list of error-message strings.
