# Shared capabilities and dispatch

The registry in `capabilities.py` describes existing execution paths. It does not
give a language model new powers or grant native tool permissions.

## Execution paths

O03 adds `plan_production` (template, project, reference pack, explicit research IDs,
planning-only intent, optional prior plan ID) and `authorize_production_plan`
(saved plan ID). The first saves a bounded planning operation; the second presents
an existing plan for approval. Neither starts workers directly. A delivered,
version-bound Start card registers one producer/reviewer stage in the existing
runtime. See [new workflow planning](new-pipeline-planning.md) for limits and evidence.

| Path | Capabilities | Execution evidence |
| --- | --- | --- |
| Direct orchestrator file calls | List, search and read known project text files | Private request/response/read journal; existing file policy |
| Direct orchestrator web tools | Google-backed search with configured Gemini; public HTTPS page text | Grounding metadata, cited URLs, timestamped page hashes and source report |
| Existing Codex desktop task | File inspection/editing and shell; additional plugins/web are not assumed | `task_routes`, then native task progress/result |
| Existing Claude task | Read, Glob, Grep, Edit, Write, Bash, WebSearch, WebFetch | `backend_jobs`, native permission requests and result |
| Existing Gemini/OpenAI/Qwen/DeepSeek/OpenRouter text task | Three read-only file tools | `backend_jobs`, native provider/tool receipts |
| Relay actions | Existing image, reference, research-folder and production/workflow controls | Existing adapter receipts and user gates |
| Registered production worker | Files/shell within its frozen assignment | Runtime attempts, artifacts, independent review and user selection |

Every ordinary orchestrator request receives a current capability catalog. Targets
include their project, provider, declared capabilities, availability/blocker and
configuration fingerprint. Busy, uncertain and workflow-owned destinations are
unavailable; independent tasks in the same project remain usable. Provider setup
is checked locally. Authentication and remote model tool support are only verified
when execution occurs. No API keys or configuration contents enter the catalog.
The managed-provider catalog lists at most 50 recent tasks and reports truncation.

## How dispatch works

The model can return a typed `delegate_task` action containing an existing task ID,
its provider, and required capabilities. Relay validates that choice, then checks
the destination again before queueing. It sends the original user message verbatim.
Provider choice and project relevance are part of the model's routing instructions;
deterministic checks enforce the declared provider/capability match, current task
identity and availability. They do not independently interpret all natural-language
intent. Ambiguous destinations should produce a question.

Direct file calls and immediate actions use the shared dispatcher. Card-gated
controls retain their existing approval path. A `capability_dispatches` receipt
links each immediate action to its native queue/control record. Queue insertion,
receipt and acknowledgement commit together; repeated dispatch returns the saved
receipt, and a changed action for the same request is rejected. The native worker
owns execution, interruption recovery and results. An uncertain submission is never
automatically replayed or switched to another provider.

Acknowledgements for delegated work are replyable task messages. Queueing is not
completion; recent capability receipts read status from their underlying queues.
Production replies continue through their registered stage controls and do not
expose general worker targets as an escape from frozen scope.

## Examples

- “Use Claude in my existing Agent research task to search online and cite sources.”
- “Use Codex in Fix incomplete floor layout solver to inspect the failing tests.”
- “Read the roadmap and explain the next step.” (Direct file tools can suffice.)

If no suitable connected task exists, the orchestrator explains the missing path.
Task creation remains available through `/new`; arbitrary new task/graph creation
from the delegation action is not implemented. [Direct web research](orchestrator-web.md)
is available. New media adapters remain separate work; the bounded planner now
supports the registered mixed text graph nodes below.
The O06 [mixed graph adapters](mixed-execution.md) now expose `graph_operations`
alongside this direct-dispatch catalog. Registered `text.bundle` and `gemini.text`
steps share the production runtime's artifacts and receipts with Codex assignments.

## Research handoffs and remembered content guides

Codex route/choice/delegation actions can carry `research_ids` from the registered
research-document catalog. Sources are copied and hashed before choosing a task;
the selected task receives complete readable file paths, purposes and hashes.
Copies are checked again immediately before submission. The user's exact request
is preserved. A legacy request explicitly asking for the only two registered
research documents can resolve that unique pair; other missing/ambiguous source
selections block instead of sending an instruction without its documents.

LinkedIn requests discover a unique applicable content guide folder in the
destination project. Its location and purpose persist in `project_guide_profiles`.
The profile remembers a location, not a prose summary: each new handoff reads the
current required guides, available voice examples and parent instructions, then
freezes their bytes for that request. Guide updates affect later requests without
changing already queued work. Missing or unsafe remembered paths produce a blocker.
The current implementation supports LinkedIn guide discovery, with bounded depth,
entry, example and total-byte limits; it is not a general-purpose memory system.

Previously registered video workers already carried copied content guides. Guide
presence does not establish that an editor followed the desired voice or that a
draft is acceptable. Creative review and the user's corrections remain necessary.
