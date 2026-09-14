# Request-derived workflows

Relay distinguishes a whole user outcome from an individual bounded production
stage. The orchestrator can extract an ordered workflow from the initial request
with `plan_pipeline`. The model supplies stage instructions, routes, requested
outputs, capabilities and decision boundaries; no architecture, research, image
or presentation sequence is built into the scheduler. Single operations keep their
existing direct routes.

A workflow stores the exact original request, model/provider identity, immutable
proposed stage specification, current stage, executed requests, downstream receipts,
source versions and events. Each stage's source context includes prior results and
exact artifact IDs, hashes and file copies. Completed research contributes its actual
answer and conversation URL. A selected image contributes only that selected version.
Files needed by an active workflow survive the recent-artifact catalog window.

## Execution and decisions

The initial request authorizes the extracted workflow scope. A planning-only request
saves the stages without running them. Otherwise the existing orchestrator service
queues the first stage and advances in order after its recorded prerequisites:

- Conversation steps may read a brief and propose choices. Their exact result and
  chosen option are saved. A status message or ambiguous answer is not a choice.
- Research and image routes use existing managed queues and their actual completion
  receipts. Images requested for selection wait for the delivered candidate/card.
- Production steps use the existing bounded planner, producer, independent reviewer
  and artifact store. Ordinary stages can start automatically after their complete
  plan is delivered, within the workflow's declared capability and attempt bounds.
- Unknown host code is never covered by that automatic grant. Script preparation
  retains the existing reviewed-set selection. Relay then automatically prepares the
  pending execution plan; its exact-code **Start** remains a separate approval.
  Related selected host operations can move together into that phase when at least
  one needs prepared registered inputs. Each remains explicitly deferred with its
  reason; API/media operations cannot be hidden in a host-preparation deferral.
- A stage's declared output selection groups related deliverables. After selection,
  the next saved stage is queued automatically; another continuation prompt is not
  needed. Worker completion or procedural review does not imply user acceptance.

The generic routes are conversation, production, managed browser research and managed
image. Registered image providers can also be represented by production operations.
These are execution adapters, not business workflow templates. Stages are ordered,
not a general parallel branching graph; choices inform subsequent interpretation.
A stage can internally prepare/review/execute a supported native operation.

## Recovery and boundaries

Queue identity and stage transition commit atomically. Provider/browser/native work
is dispatched by the existing workers after commit. Duplicate ticks and process
restarts observe the original receipts instead of submitting again. Failed,
interrupted, uncertain, missing-source or changed-source work blocks the workflow;
it never consumes another attempt automatically or switches providers.

Pause prevents further workflow dispatch; work already running may finish within its
existing grant. Resume applies to deliberately paused/planning-only workflows.
Blocked work requires explicit recovery; it is not silently converted into a retry.
For an unexecuted blocked production plan, Recover saved plan revalidates retained
responses and source hashes. A currently valid response becomes a new ready plan
with a durable reference to its original call; the failed plan and all call receipts
remain unchanged. No provider call is repeated. If no saved response validates,
recovery stops and a new explicit planning request is required.
Cancellation stops future stages. A clarification about an addressed waiting stage
retains the original request and the previous interpretation receipt.

There is no retroactive adoption of old unrelated jobs, implicit acceptance of old
artifacts, or automatic rewriting of executed stage plans. Existing standalone
productions preserve their manual continuation behavior. Changes to workflow scope
require a new reviewed instruction/plan rather than editing stored history.

## Validation

`tests/test_pipelines.py` uses small text and PNG fixtures and mocked providers. It
exercises natural-request action dispatch, choice gates, automatic bounded production
start, selected-byte handoff, actual browser/media receipt adapters, restart and
duplicate delivery, pause/cancel, clarification, source drift and native-code approval
boundaries. The production planning, stage continuation and image adapter integration
suites cover the reused paths. These checks do not establish live model extraction
quality, installed-app rollout, or a completed real multi-provider workflow.

## Task deadlines

Each task has its own `limits.seconds`, starting when its worker starts. Producer,
reviewer and host execution do not share a single stage timer. New planning may
propose up to 1,800 seconds per worker task; `task_seconds` can specify a lower
ceiling or explicitly change the ceiling of a newly proposed revision. The planner
chooses actual durations separately for each task. Registered operations retain
their own operation-specific limits. Tool, output and attempt limits still apply.

New workflows freeze a 30-minute automatic task ceiling in their creation receipt.
Older receipts retain the former 600-second ceiling. A proposed task beyond that
legacy automatic grant waits for its exact Start approval; it is not treated as a
failed task. Existing executed assignments and timeout receipts never change.
Longer deadlines alone do not approve partial outputs or restart stopped workers.
The planner and worker instructions reserve time for saving, validation and the
final completion response; deadline management by the model remains to be
qualified through live work.

## Preparation continuation ownership

An explicit registered preparation continuation remains part of its saved workflow.
The scheduler records a `continuation_attached` event and follows the child run;
the original failed plan, attempt and continuation request are retained. Reconciliation
also handles children created by older builds. It requires the creation receipt,
matching channel and unchanged pending deliverables, and does not resume a paused
or cancelled workflow.

For a confirmed failed host Python operation, a registered corrected script can
be proposed with `production_planning.prepare_host_repair`. This internal planning
entry point requires an explicit recovery request and never launches work. It
retains the original plan and receipts, reuses completed dependencies, preserves
unfinished review, and delivers the exact corrected script for a fresh Start.
Start rechecks the stopped parent's state, control epoch and artifact versions.
Uncertain execution cannot use this repair path. A repair is not accepted geometry.
The same saved workflow owns the repair plan and retains its complete output
selection set for downstream stages.

`runtime_repair=True` permits the same Rhino script only when the current failed
execution receipt records an older implementation hash. A new exact Start approves
the updated runtime assignment; an unchanged implementation is not grounds for an
automatic retry. Earlier recovery requests retain distinct historical paths while
the current request remains at `recovery/REQUEST.txt`.

After review and exact selection, the scheduler either advances an ordinary file
stage or queues the deferred execution plan once. Original planning context is
resolved through registered ancestry, while current selections and continuation
requests come from the actual child. Native execution still requires exact-code
Start. No initial request, research stage or failed submission is replayed.

### Inspection evidence before review

A planned fixed inspection can consume an unaccepted producer output when the
producer's independent reviewer explicitly depends on and consumes that inspection.
This is registered capability behavior, not an inference from a task's name, role
or prompt. Rhino and Blender inspections currently support it. Other downstream
operations still wait for completed review and any producer selection gate. Plan
validation includes those completion gates when detecting dependency cycles.

`production_control.resume_review_evidence` recovers a recorded scheduler deadlock
only under the same started plan, assignments, intact successfully delivered
candidate and unchanged controls. It records the exact recovery request and enables
remaining work after commit; it never resets or reruns the producer. An inspection
of an old candidate cannot silently be reused after a revision.

### Recovery of parent workflow state

A blocked production stage retains its workflow owner. If the linked production
subsequently completes with its required review and output selections, the workflow
scheduler validates and freezes those exact sources and clears the earlier production
blocker atomically. It then queues the next stage from the saved original plan once.
It does not rerun production, infer a selection, substitute files or resume a workflow
that the user paused or cancelled. Stage status messages retain this ownership even
while the parent is blocked.

### Context versus operation arguments

Required stage artifacts preserve the user's selected versions and remain available
to authors and reviewers. Each registered operation receives compatible implicit
context sources according to its declared input types. An upstream native model can
remain in the workflow without becoming an argument to a later presentation or text
operation. Explicit incompatible operation inputs are rejected, and sources are not
converted or substituted silently.

### Declared input paths

An explicit artifact input binds both its immutable identity and its task-local
path. Context injection must preserve that path so specifications can reference
images and other assets consistently. Canonical implicit context that collides
with a declared path moves under an artifact-specific context directory; two
conflicting explicit bindings remain an error.

Confirmed failed local procedures with no external requests can receive an explicit
input-path repair proposal. Completed preparation/review outputs become exact
registered inputs, failure history stays intact, and only unfinished tasks are
proposed. PPTX image references are validated before this recovery is queued.
Uncertain operations cannot be recovered through this path.
# Workflow file folders

Each saved workflow has a stable folder at
`<configured generated-files root>/workflows/<workflow-id>/`. Relay includes the
absolute path in workflow and production messages and in workflow status context.
The path is local to the computer running Relay.

Open `README.md` for the current index. `files/` contains exact registered file
copies with distinct artifact identities, including unselected and earlier
versions. `stages/` contains research, program and other stage results; `records/`
contains production attempts, review receipts and decisions. Versioned manifests
record file hashes, source identities, status and unavailable files. Original
requests are retained in `request.txt`. The view refreshes as outputs are recorded,
including while a stage is blocked or awaiting selection.

Explicitly linked follow-up runs share this inspection view. Their folder path
does not make them part of the original stage's execution authorization, and
their results remain subject to their own recorded review and selection state.

These are inspection copies. Editing them does not change Relay's recorded
inputs, select a candidate or launch a worker. Existing copies and user-edited
indexes are preserved; follow-up changes still need an explicit workflow request.
Unregistered files in an active worker's temporary workspace are not presented as
finished workflow artifacts. Export is local and does not call a provider.


## Activity and usage

Production status identifies what Relay is doing and the exact model fixed for
that task, or the registered native operation when no AI model executes it.
Elapsed time and the approved task limit distinguish work duration from its
maximum allowance. Tool count, latest reported action and event age appear
when the worker provides them. A stale heartbeat does not prove active work.

Input/output token counts come from provider reports. Cache and reasoning
counts are separate reported fields, not additional token totals. Providers
that only report usage after a response show “not reported yet” while waiting.
Finished tasks use final receipts; missing counts are not displayed as zero.
No price or remaining token budget is inferred from these counts.

Relay sends one activity notice when a task starts, including when an independent
reviewer starts. Check status retrieves newer elapsed/activity/usage details.
Progress files contain event categories and usage counters, not prompt text,
command contents or hidden model reasoning. They do not affect task limits,
acceptance or retry decisions.

## Automatic script repair

New workflows record a repair policy in their creation receipt: at most one
repair cycle per logical stage, with one preparation attempt and one independent
review. Each uses the original execution model, at most 600 seconds and 24 tools,
and no more than the original review allowance (time/output bounds also respect
the failed operation). The workflow notice states this allowance. Old workflows
without that receipt do not acquire permission for extra provider work on upgrade.

For a confirmed stopped `rhino.run_python` or `blender.run_python` script failure,
Relay preserves the failed attempt and registers a separate preparation run.
Both workers receive the immutable failure receipt, original script/checks,
operation support, failed assignment and exact workflow request. They prepare
and review a corrected script plus a structured diagnosis; they have no host
execution assignment. Checks, native source files, output scope and task limits
stay unchanged. A repair requiring different checks, permissions, installed
runtime changes or broader scope reports the necessary action instead.

Only a completed review of the current candidate can produce a new execution
plan. Its card includes the diagnosis and change explanation, and attaches the
diagnosis, independent review, script and checks. Start checks delivery, exact
artifact hashes, current review identity and the unchanged failed baseline before
registering a new native attempt. Completed original tasks are reused. Normal
output-review and selection boundaries still apply; the saved workflow carries
the exact selected files into later stages.

The unique workflow-stage repair record survives restarts and prevents duplicate
work or recursive repair chains. Queueing, plan creation and lineage updates are
atomic; workers dispatch after commit. Pause/cancel and pending human feedback
stop additional automatic dispatch. Startup failures, timeouts, absent/tampered
receipts, uncertain submissions, unsuccessful repair review or an exhausted
repair allowance require further action. This implementation does not automatically
retry browser submissions, media API calls or arbitrary local procedure failures.

Repair candidates, diagnoses, reviews and receipts remain inspectable in the
original workflow folder alongside the original attempts. Review is not user
acceptance and does not authorize host execution.

## Planning rate-limit recovery

When Gemini rejects planning with HTTP 429 and returns no proposal, use **Retry planning** or send `/workflow retry-plan WORKFLOW_ID` in the original Telegram channel. This explicitly queues a new bounded planning request with the same model and frozen inputs. The original call stays blocked in history. The workflow resumes at that planning stage, without repeating research, choices, or preparation. The current card can be used only for its exact failed plan. Repeated rejection needs another deliberate retry after checking the provider quota; there is no automatic retry or provider fallback. Native execution still waits for exact Start. Uncertain submissions, failed workers and other errors are not eligible. Saved-proposal recovery remains separate and makes no provider call.
