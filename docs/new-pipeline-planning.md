# O03 — natural request to a new bounded workflow

Status: **bounded implementation complete, extended by O05/O06**. Live end-to-end Telegram interaction is tracked separately from implementation tests and service health. Priority and dependencies are defined in [ROADMAP.md](../ROADMAP.md). Same-scope continuation remains a separate operation. The default is one producer/reviewer stage; explicit mixed text scope supports the registered operations described below.

## Using the implemented planner

Ask the orchestrator for a new bounded workflow and name the work and sources. The LLM chooses `plan_production` when an existing task, direct capability or continuation is insufficient. Existing guide discovery and reference collection provide selected versions. A concrete plan card names inputs, outputs, checks, limits and any user decision; `plan.json` and `sources.json` are attached. **Start this stage** creates and enables that exact stage once. The scheduled notice has **Check status**, and normal production delivery/replies use the existing runtime.

Planning-only requests expose no Start button. A later explicit execution request can present the saved plan for approval. Replies to the plan card or its documents carry the plan identity; clarification retains the original request and creates a successor plan, invalidating the earlier card. Pending replies prevent starting an old plan while interpretation is in flight. Natural-language intent and semantic adequacy remain model judgments.

`production_planning.py` stores requests, frozen instructions, template origin/version/changes, source hashes, raw model responses, usage, validation errors and stage receipts in the existing `private/state.sqlite` (`production_plans` and `production_plan_*` tables). Frozen files live under `private/production-planning/`; artifact bytes use the existing runtime registry. Selected packs reuse registered artifact IDs without making another complete copy during planning. Worker workspaces still copy their inputs.

The default scope is exactly two dependent workers, one attempt each, at most **600 seconds / 60 observed tool calls / 100 MB outputs per worker**. O06 adds explicit `step_capabilities` for [mixed text graphs](mixed-execution.md) of 2–6 steps with smaller registered-operation limits. Complete selected reference bundles travel to all steps; **150 MB total distinct selected inputs** is the overall limit, and each operation enforces its smaller input bound. Oversized bundles stop rather than silently dropping dependencies. Separate selected research, guides, conversation and exact current request are required inputs as well. These bounds do not establish a token or dollar cap for agent execution.

The planner uses the conversation's configured provider/model. The worker backend comes from `production-planner-policy.backend`, or the most recently registered production backend; it is frozen at enqueue and must be `codex-cli`. No worker model is invented when neither exists. Planning permits **two calls maximum**, the second only for structural correction, with 10,000 output tokens per call and a 400,000-character request bound including correction. Existing provider transport timeouts are at most 180 seconds. Provider failures or interrupted submissions are retained without automatic retries.

Generated, known-template and adapted-template plans use the same validator. Template snapshots and actual modifications are retained; reusable templates are unchanged. O05 adds `previous_run` for a completed stage with recorded selections: exact selected versions, prior instructions and original job identity become required inputs to both workers. One successor is retained per stage; clarification uses `parent_id` on its saved proposal. See [stage control and progress](production-selections.md). Telegram transport and approval paths have controlled tests; they do not establish deployed Telegram delivery.

## Verification scope

O03 checks Relay orchestration: preserve the request and sources, validate and
approve one bounded plan, dispatch once, pass the exact output to its reviewer,
deliver the result with the correct identity, and recover after interruption.
Use a small useful text artifact from selected project documents. Browser access,
video rebuilding, pixel/audio comparisons and creative media acceptance are not
O03 completion requirements. Product-specific checks belong to jobs that require them.

## User outcome

The user names real work and supplies/selects its references in the existing Telegram conversation. Task Relay prepares a bounded plan, resolves only consequential missing information, and starts its workers through the existing execution controls. The user does not create plan JSON, task IDs, job registries or handoff files.

The first delivery ends at the next declared decision boundary. It does not require complete autonomous project planning. An explicit production request with sufficiently clear scope should not become a series of unnecessary questions about internal worker roles.

## Reuse and additions

Reuse existing natural-language routing, reference-pack collection, registered artifacts, action-card authorization, `orchestrator/contracts.py`, `orchestrator/templates.py`, the worker factory, scheduler, production notices and revision receipts. Keep linked desktop workflows functional as a separate route; do not replace or migrate their active runs during this milestone.

Add one durable planner operation between a request/reference pack and stage registration. Its saved record needs:

- Original user text and request identity; explicitly chosen project and sources.
- Reference-pack hash, artifact IDs, purposes, unresolved references and relevant exact user selections.
- Supported execution capabilities and configured model/worker limits.
- Model request, first response, usage, validation outcome and any clarification/repair attempt.
- Validated plan version and resulting runtime stage ID, or a specific unresolved question/blocker.
- Plan origin: known template, generated plan or adapted template; source template ID/version where applicable and the modifications made for this request. Retain the original user outcome and link the resulting stage to it, so later continuation can preserve job identity.
- Dispatch/registration receipt so a restart cannot create two stages from the same plan.

The planner receives a capability description, not credentials or arbitrary access. First execution backend: existing `codex-cli`, with its supported files/shell profile. Use the configured planning model; additional model selection is not part of O03.

Prefer a compatible existing template when it fits; adapt or generate only as the request requires. A generated plan and an adapted template pass the same contract checks. Save the resulting plan and origin without modifying the reusable source template. A request already served by a direct capability stays on that route; O03 does not require a graph for every job. The broader [job/pipeline/capability model](../ROADMAP.md#jobs-pipelines-and-capabilities--design-requirements) adds no requirement to rebuild existing queues or implement the complete O05 job view first.

## Planner result

Accept one of three outcomes:

1. **Plan ready:** a stage conforming to the existing plan/assignment contract, with references, outputs, roles, dependencies, criteria, limits and any necessary user gate.
2. **Needs a decision:** the specific missing source/version, creative choice or scope tradeoff that prevents a sound plan. Include relevant options/evidence where available; preserve the original request when the user answers.
3. **Blocked:** a missing capability, unavailable required input or exhausted planning budget. Do not register a superficially runnable substitute.

Role descriptions should be task-specific. A preparation step does not authorize rendering, and a request to render an already selected composition should not automatically add another storyboard-selection gate. Determine the boundary from the request and established decisions, while retaining genuine ambiguity.

Default first planner policy: one planning response and at most one correction for a structurally invalid response, using the same inputs and a recorded validation error. Preserve both responses and usage. Freeze configured input/output/time limits before the test. Exhaustion stops planning; it does not restart the experiment or silently expand scope. Semantic adequacy remains an evaluated model judgment.

## Registration and execution

1. Check the plan with the existing validator and resolve every input to an immutable registered artifact or declared upstream output. Reject unsupported tools/backends, cycles, missing review dependencies and out-of-range budgets.
2. Check the selected references and request revision again before registration/start. Store the exact plan hash with the request and action record.
3. Use the current authorization mechanism. A current accepted action applies once to its exact scope; duplicate/stale cards cannot create or start another stage. Preserve planning-only semantics and existing approvals rather than introducing a confirmation for each node.
4. Hand the stage to the existing runtime. Its supervisor receipts establish worker state; model text saying “started” or “done” does not.
5. Return actual outputs, review status and the next concrete decision. Preserve the first plan and first outputs even when a later revision succeeds.

Changes to future stages and the general post-selection loop belong to O05. New script/API node types belong to O06. Do not make those prerequisites for the first producer/reviewer stage.

## Acceptance cases

| Case | Required result |
| --- | --- |
| Clear request with a ready reference pack | Produces and registers a valid bounded plan; user supplies no machine-authored setup files. |
| Known, generated or adapted plan | Records its origin and exact resulting version; adaptation leaves the source template unchanged, and all origins pass the same validation. |
| Planning-only request | Returns a plan without launching workers. |
| Ambiguous source/version | Asks one relevant selection question, retaining the original request; no guessed authority. |
| Missing required artifact or unsupported capability | Reports the exact gap before dispatch; no placeholder output or invented source. |
| Invalid graph or budget | Rejects it; permits at most the recorded bounded correction; no worker launch from invalid output. |
| Source/user instruction changes before start | Invalidates or versions the affected plan and authorization; no stale dispatch. |
| Duplicate message, action or restart during registration | Reconciles the saved identity without creating duplicate stages or replaying an uncertain operation. |
| Real stage | Creates workers, passes registered outputs to review, delivers a result or a justified blocker, and records all preparation/repair burden. |

Use a small source-grounded text task based on already selected project documents for the next integration check. Do not manufacture user approval or add media/browser checks. Broader workflow and output-quality evaluation belongs to O07.

## Completion record

Record changed modules, targeted checks, live routing/registration/worker evidence, first plan quality, all retries/repairs, usage and unmeasured effort. A test-suite pass alone does not close the real-stage acceptance case. Update O03 to implemented only with remaining live boundaries stated explicitly; do not mark the broader product promise proven.
