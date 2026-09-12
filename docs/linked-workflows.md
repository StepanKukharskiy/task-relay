# Linked roadmap workflows

Task Relay owns the workflow state and advances planning → execution → independent review in its background service. Codex tasks provide the reasoning and project work. No coordinating Codex conversation or scheduled LLM heartbeat is required. The Mac, Codex desktop, and relay service must be available.

The displayed executor-turn counter measures dispatched execution turns, including turns blocked before launch. Numerical attempts are counted separately by the project's durable attempt registry. One-shot plans should check environment capabilities and obtain required tool permissions before entering the runner. A sandbox denial is an infrastructure blocker, not evidence that a solver ran or a competing workload exists. Existing terminal records and claimed attempts remain immutable; these instructions do not authorize restarting a blocked run.

## Telegram controls

Use `/orchestrator` to enter conversation mode, then send ordinary messages such as
“Why is Example Project blocked?”, “Plan a recovery for Example Project without launching solvers”,
or “Run one roadmap item for second-project”. You can also send the question on the same
line as `/orchestrator`. Replies to newly delivered workflow notices and orchestrator
answers use this interface even with conversation mode off. Replies to task cards still
go to their agent; request-bound approval answers take priority.

The interface reads saved linked-workflow state, approval receipts, current-run dispatch receipts, and the last six answered conversation
exchanges. `plan_ready` means the request was approved and queued; `submitted` means its instruction was sent to the target task, not that its work is complete. A later pause does not undo that dispatch.

For conversational plan/run actions, the relay retains and forwards the original user message verbatim alongside the model’s summary. Questions and constraints must survive summarization; a proposed cause remains a hypothesis to investigate. The original message remains available during execution and review without expanding the frozen assignment. Direct messages added to an already dispatched desktop task still pause automatic workflow advancement for review. It uses an already-connected text API provider (Gemini first by default),
which receives those excerpts. It does not read project files or run shell commands.
Every model request also receives a fresh host-clock reading with UTC, fixed CET/CEST,
Central Europe's current civil time (including daylight saving), and host local time.
It can answer time/date questions from this context without an internet request.
Choose another connected provider with `/orchestrator provider openai` (also gemini,
qwen, deepseek, or openrouter). The provider's configured default text model is used.

A proposed action shows the workflow name, exact direction and accepted-item budget.
Tap its action button to apply it, or Dismiss. No action executes from model output alone.
Cards expire after 30 minutes and are rejected if the workflow revision has changed.
The existing workflow guards still reject blocked resumes and conflicting runs. A
planning action authorizes read-only planning only. Pause/stop prevent future handoffs;
they do not terminate current agent work. Direct `/workflow` commands remain available.

`/orchestrator off` restores ordinary selected-task routing; `/use TASK_ID` and creation
of a new provider task also leave conversation mode. Attachments can be sent as replies
to task cards; registered-production replies also accept guides for bounded revisions.
Conversation requests run in a separate worker with a five-message queue;
an interrupted provider request is reported without automatic replay. The `/workflow`
controls below target linked desktop workflows. The conversational interface also
supports registered CLI production starts/revisions and reference collection; see
[worker runtime](worker-runtime.md). It cannot yet create a new production plan from chat.

```text
/workflow
/workflow status example-project
/workflow run example-project 1 Recover the missing inputs within current gates
/workflow plan example-project Review the blocker and propose a bounded recovery only
/workflow pause example-project
/workflow resume example-project
/workflow stop example-project
```

`run NAME N [direction]` explicitly authorizes a new run of 1–10 accepted roadmap items. The planner freezes one item at a time. Each item allows one initial execution and two reviewer-requested revisions, then pauses. Only a complete reviewer verdict addressing every frozen criterion counts as acceptance. A completed model turn alone does not count. New items cannot silently repeat an already accepted step ID within a run.

`plan` authorizes planning only: the service returns the proposal and pauses before execution. `pause` prevents further handoffs; `resume` continues a manually paused run. A blocked, uncertain or planning-only run cannot be resumed as if it were an approved execution: use `plan` or explicitly authorize `run` with the intended direction. `stop` prevents further handoffs without interrupting already-started work. If an in-flight turn remains unreconciled, resolve that run before beginning another one. Direct instructions to a linked task pause its automatic handoffs.

To link another pair of existing local Codex tasks in the same project:

```text
/workflow link project-name STRATEGY_TASK_ID EXECUTION_TASK_ID
```

Linking starts no work. Strategy and execution tasks must be different. Cross-project dependency graphs and creating new Codex tasks are not implemented by this worker.

## Handoffs and evidence

The worker sends the planner a schema for one bounded assignment, including scope, exclusions, deliverables, runtime/search limits and acceptance criteria. It sends that frozen assignment to the executor, then sends the result to the reviewer. The reviewer must inspect actual evidence and address each criterion in order. Revisions retain the original scope. The service validates the handoff format and counters; domain correctness still depends on the checks and reviewer, not a claim of success in the response.

Routine machine handoffs are retained in SQLite and omitted from Telegram completion notifications. Telegram receives accepted-item summaries, blockers and required decisions; ordinary agent approvals and questions retain their existing request-bound Telegram controls. Runtime/search limits are part of the agent assignment, not a process-killing timer or a token/cost cap.

State lives in owner-only `private/state.sqlite`:

- `workflows`: project links, current run, phase, frozen assignment, limits and counts.
- `workflow_events`: migration records, state transitions, full results and source turn IDs.
- `workflow_dispatches`: exact prompts, unique markers and delivery status.

The worker uses existing desktop IPC to start turns and reads exact completed turns from Codex rollouts. It does not mutate Codex's database. It waits for busy project tasks and active managed-provider jobs. A changed task/folder, extra user turn, malformed result or uncertain dispatch pauses the workflow. Dispatch is claimed durably before sending; restart or timeout never causes automatic resubmission. Human desktop activity cannot be locked by the relay, so changes observed during a run require reconciliation.
