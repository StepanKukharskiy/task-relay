# O03 — natural request to a new bounded workflow

Status: **bounded implementation complete, extended by O05/O06**. Live end-to-end Telegram interaction is tracked separately from implementation tests and service health. Priority and dependencies are defined in [ROADMAP.md](../ROADMAP.md). Same-scope continuation remains a separate operation. The default is one producer/reviewer stage; explicit mixed text scope supports the registered operations described below.

## Typed artifact and workflow details

New planner schemas expose compact artifact selectors and compile input metadata,
reviewer coverage and companion selection. New workflow actions use `stage_details`
to select named outputs, formats and uses; Relay constructs their handoff contracts.
See [typed contract builders](typed-contract-builders.md) for exact forms, receipts,
compatibility and remaining scope.

## Typed standalone execution stage

For a single `rhino3dm.run_python` scope with captured script text and valid checks,
Relay freezes `operation_builder` v1 and a narrower planner response schema. The
planner fills input slots using the listed artifact IDs; it does not author task
objects, operation constants, hashes, permissions, output paths or review edges.
A ready response has this shape (IDs are illustrative):

```json
{
  "decision": "ready",
  "message": "Execute and review the selected pavilion script.",
  "geometry_basis": {"mode": "procedural", "artifacts": [], "checks": []},
  "input_basis": {"mode": "new", "artifacts": []},
  "plan": {
    "operation": "rhino3dm.run_python",
    "inputs": {"script": "selected-script-id", "checks": "selected-checks-id"},
    "review_instruction": "Check member spacing against the requested dimensions."
  }
}
```

Edit checks require the `scene` input; create checks forbid it. Optional `assets`
contains distinct captured IDs with their existing workspace aliases. When outputs
are requested in `options.deliverables`, `plan.deliverables` maps each requested ID
to one of `model`, `script`, `checks`, `receipt`. Relay resolves these semantic ports.
Geometry/source declarations retain their existing validation and fidelity checks.

The builder derives mode from validated frozen checks and execution fields from
registered definitions and exact source hashes. It creates one bounded host step,
an independent binary/code reviewer and a gate selecting all four output companions.
The frozen executor choice still applies; a text-only profile cannot silently gain
code tools or switch providers. No script is run while constructing the proposal.
Changed registered definitions require a new proposal rather than silent rebinding.

Raw typed JSON remains in `production_plan_calls.response`. The canonical proposal
is saved in `production_plans.result` for existing recovery consumers; the resolved
plan also records the typed request, registry digest and input versions in
`origin.operation_builder`. Rejections record code/field/expected details under
`planner-contract-error:<plan-id>:<call-number>` and provide them to the existing
single correction attempt. This does not enable arbitrary field patches or retries.
Trusted recovery validates canonical proposals through the full domain validator;
provider responses cannot opt into that path. A correction-preparation successor
removes the execution builder and restores the generic preparation schema.

Exact scripts/checks must still be delivered before Start; Start verifies the
captured files and records exact-code authorization atomically. Output review and
user selection remain separate. This implementation does not construct scripts or
checks, and does not claim native Rhino verification. Preparation without valid
captured script/checks, mixed-operation graphs and old frozen requests retain their
existing generic contract. Additional builders are tracked in the contract inventory.

## Local geometry sources and fidelity review

`plan_production.project_files` selects up to ten exact, project-relative files
from the selected known project, with a 100 MB total capture limit. Resolve names
through project file tools before selecting them. Capture uses the bounded
workspace reader, rejects links/traversal/excluded paths, and saves immutable
copies with SHA-256 hashes. Author and reviewer receive the same registered
versions. Editing the original afterwards does not change the approved input;
using its new version requires a new proposal. Frozen-copy tampering prevents Start.

New Rhino, Blender and SketchUp script/preparation proposals carry
`geometry_source_policy=1`. A ready planner response must declare `geometry_basis`:

```json
{
  "mode": "source_derived",
  "kind": "terrain",
  "artifacts": ["exact registered DXF artifact ID"],
  "checks": [
    {"metric": "contour_deviation", "tolerance": 0.05, "unit": "m"},
    {"metric": "boundary_deviation", "tolerance": 0.05, "unit": "m"},
    {"metric": "elevation_span_error", "tolerance": 0.05, "unit": "m"},
    {"metric": "missing_source_entities", "tolerance": 0, "unit": "count"}
  ]
}
```

These illustrative tolerances are not defaults. Use the user's tolerances or
propose appropriate ones in the plan card. Other source-derived geometry uses
`kind: general` and task-specific error metrics. Work designed from scratch uses
`{"mode":"procedural","artifacts":[],"checks":[]}`. Selected CAD sources cannot
be relabeled procedural. A conversation, request or contract snapshot cannot
serve as the source file. Missing original bytes require `needs_input`; missing
format tooling requires a blocker. Neither permits synthetic replacement geometry.

The compiler binds originals to source-based agents and adds a service-owned
`source_fidelity` review contract. Preparation review records extracted geometry,
units, transforms, entity identities and how the script consumes it; it does not
certify an unexecuted model. Native output review adds a source-comparison criterion
without altering the registered operation's procedural criteria. Its evidence is
structured JSON containing the exact source IDs/hashes, per-source observations
and every proposed metric's measured error and reproducible measurement evidence.
The runtime rejects acceptance with missing evidence, changed identities, missing
metrics, invalid numbers or errors exceeding the frozen limits. Review can instead
request revision or report missing measurement tooling as blocked.

These checks enforce evidence completeness and declared tolerances, not the truth
of arbitrary model-reported measurements. Classification and measurement methods
still need competent workers. A deterministic DXF-to-native geometry comparator
is not provided by this change. Existing saved plans and completed runs retain
their original contracts; new proposals receive the new policy. No provider,
native application, package installation or workflow replay is invoked by planning.

## Using the implemented planner

Ask the orchestrator for a new bounded workflow and name the work and sources. The LLM chooses `plan_production` when an existing task, direct capability or continuation is insufficient. Existing guide discovery and reference collection provide selected versions. A concrete plan card names inputs, outputs, checks, limits and any user decision; `plan.json` and `sources.json` are attached. **Start this stage** creates and enables that exact stage once. The scheduled notice has **Check status**, and normal production delivery/replies use the existing runtime.

Planning-only requests expose no Start button. A later explicit execution request can present the saved plan for approval. Replies to the plan card or its documents carry the plan identity; clarification retains the original request and creates a successor plan, invalidating the earlier card. Pending replies prevent starting an old plan while interpretation is in flight. Natural-language intent and semantic adequacy remain model judgments.

`production_planning.py` stores requests, frozen instructions, template origin/version/changes, source hashes, raw model responses, usage, validation errors and stage receipts in the existing `private/state.sqlite` (`production_plans` and `production_plan_*` tables). Frozen files live under `private/production-planning/`; artifact bytes use the existing runtime registry. Selected packs reuse registered artifact IDs without making another complete copy during planning. Worker workspaces still copy their inputs.

The default scope is exactly two dependent workers, one attempt each, at most **600 seconds / 60 observed tool calls / 100 MB outputs per worker**. O06 adds explicit `step_capabilities` for [mixed text graphs](mixed-execution.md) of 2–6 steps with smaller registered-operation limits. Complete selected reference bundles travel to all steps; **150 MB total distinct selected inputs** is the overall limit, and each operation enforces its smaller input bound. Oversized bundles stop rather than silently dropping dependencies. Separate selected research, guides, conversation and exact current request are required inputs as well. These bounds do not establish a token or dollar cap for agent execution.

The planner uses the conversation's configured provider/model. Existing stages and
clarifications retain their frozen worker backend; an explicit executor choice takes
precedence and locks the worker catalog. Otherwise the worker backend comes from
`production-planner-policy.backend`, or the most recently registered production
backend. For a fresh installation with neither, Relay selects an available verified
file worker, preferring the conversation provider, then a stable executor-ID order
before Codex. Browser and code profiles remain task-specific choices, not bootstrap
defaults. Models come from verified configuration and are frozen at enqueue; no
model is invented. If no worker is ready, connect a provider and select its text
model, then use **Apps and tools → Code and document tools → Worker provider →
Check worker connection**. Explicit or saved assignments that become unavailable
fail rather than silently switching providers. A proposed plan still requires its
existing execution approval; selecting a planning default does not start a worker.

Planning permits **two calls maximum**, the second only for structural correction,
with 10,000 output tokens per call and a 400,000-character request bound including
correction. Existing provider transport timeouts are at most 180 seconds. Provider
failures or interrupted submissions are retained without automatic retries.

New requests freeze a versioned `response_contract` alongside the source catalog.
`planning_contract.py` defines the proposal's JSON Schema and validates its shape
locally for every provider, before source binding and executable-plan compilation.
Gemini also receives it as native `responseJsonSchema`, following the
[structured-output API](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
Other providers receive the contract in their planning context; their transport
is unchanged. A provider rejection never causes an automatic schema-free retry.
Operation parameters, browser permissions and geometry policies retain their
own domain validators; the response schema does not prove semantic correctness.

The service compiles worker bindings from requirements and the frozen catalog.
With a locked executor, the planner omits executor/model/backend configuration;
the schema excludes both task-level and worker-level executor fields. If a
provider nevertheless repeats the exact locked executor in either location,
the compiler removes that redundant field from a copy and records its path,
value and source under `origin.planner_field_bindings`. The original provider
response and saved result remain intact. Conflicting selectors, injected backend
fields and unlocked task-level selectors are rejected, never guessed or dropped.
Missing worker declarations enter deterministic resolution with text requirements
(plus browser requirements when an explicit browser contract exists). Actual
bound validators and binary/visual inputs still constrain eligible profiles.

Malformed fields report their JSON path, expected type or allowed keys to the
bounded correction call. Text-only profiles assigned operation validator inputs
report the missing `code.execute` capability and available frozen profiles.
Existing frozen requests without this contract keep their original interpretation;
no saved stage, provider selection, approval or execution is migrated or replayed.

Host input `path` is a consumer workspace alias; `output` in an upstream reference
is the producer's exact output path. The compiler relocates input aliases under
`delivery/` to `source-inputs/delivery/` before approval and records each binding
in plan provenance. It does not rewrite scripts, manifests, hashes or producer
outputs. Colliding aliases are rejected, and frozen assignments retain the strict
reserved-directory check. If an unexecuted execution plan was blocked by validation,
click **Plan execution** on its preparation card to revalidate the saved proposal.
A valid recovery presents a new plan for **Start**, without another provider call.

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
