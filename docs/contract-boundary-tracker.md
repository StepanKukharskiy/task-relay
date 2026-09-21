# Procedural contract boundary tracker

Status: tracked implementation and read-only planning-error inventory. Worker
selection/proposal schemas shipped in 0.13.77, standalone execution construction
in 0.13.78, and the [typed artifact/stage/report interfaces](typed-contract-builders.md)
are implemented for 0.13.79. Remaining work is listed below; no audit or builder
expands execution authorization or schedules a monitor.

The target is for the model to choose meaningful content and references, then for
Relay to assemble the contract from registered definitions and frozen state.
Strict validation catches bad output; procedural construction removes the need to
invent or copy those fields in the first place. Neither establishes semantic truth.

## Open boundaries

P1 means an early follow-up because it affects common planning or preserves scope.
P2 means a subsequent focused improvement. “Source evidence” is a confirmed code
path, not proof of a live failure. Saved-error examples are kept separately in
ignored evidence and are not copied into public source.

| ID | Priority/status | What the model still constructs | Existing protection and remaining work |
| --- | --- | --- | --- |
| CB-01 | P1 / open | Router `answer/action` envelope and action-specific field sets. | `orchestrator_chat.generate` requests JSON but no native response schema; `interpret` dispatches to handwritten validators. Define each action once, expose a discriminated schema or typed action tool, and compile common fields. Keep action selection/intent with the model. |
| CB-02 | P1 / partial | Registered operation `version`, parameter keys, configured model, input hashes, fixed outputs, fixed criteria and operation budgets. | `operation_builders` now compiles a single `rhino3dm.run_python` execution/review stage from frozen script/checks/scene/asset slots and semantic review details. Other operations still require model-authored constants checked by `execution.validate`. Accept a capability plus typed semantic parameters and input-slot references; compile registry-owned fields before approval. Do not infer a host permission grant from a generated field. |
| CB-03 | P1 / partial | Artifact IDs, source/output aliases, upstream paths, MIME types and repeated dependency links. | `artifact_bindings` now compiles captured source/producer-output selectors, reviewer coverage, upstream aliases, dependencies and companion gates. New schemas expose compact bindings; existing integrations retain an explicit legacy path. Extend typed source/producer-output selectors to compile identities, hashes, types and paths from the selected versions. Missing/ambiguous sources and actual conversion needs remain blockers. |
| CB-04 | P1 / partial | Pipeline handoff output descriptors, matching consumer types, reviewer edges, deliverable maps, deferrals and companion selection lists. | `workflow_builder` now compiles semantic stage outputs/uses into versioned handoffs with registry-owned types and explicit companion groups; `handoff_contracts.compile_workflow` and pipeline guards still enforce compatibility and scope. Other operation task builders remain. Single unambiguous registered output types are already bound procedurally. Compile dependency/reviewer/companion wiring from explicit port bindings and selected stage policy; keep scope, user decisions and unresolved stages explicit. |
| CB-05 | P2 / open | Native checks/manifest field names, versions, null conventions and create/edit variants. | Workers receive authoritative contracts and standalone validators, but schema examples are often prose `DESCRIPTION` strings. Add typed builders/serializers shared with validators. Model/user still supply design intent, object names, required dimensions and preservation scope; never set expected values from candidate output merely to make checks pass. |
| CB-06 | P2 / partial | Completion `assignment_id`, criterion numbers and the report envelope. | `report_builder` now freezes named criterion slots for Codex and shared API agent reports, supplies assignment identity/indices and preserves raw reports. Canonical legacy reports remain supported; judgments and findings remain worker-authored. Bind assignment identity from the active invocation and expose criterion slots from the frozen assignment. The model must still supply judgment, findings and evidence. Never manufacture acceptance or success. |
| CB-07 | P2 / partial | JSON serialized inside a criterion's string `evidence`, including exact source ID/hash lists and metric labels. | `report_builder` now accepts typed source observations and metric measurements and serializes the existing source-fidelity evidence. Observed hashes must match actual frozen inputs; missing measurements never default to zero. Legacy JSON strings remain readable. Replace this with a typed evidence payload; bind known source identities and metric slots while preserving independent file inspection and measured results. Do not fill missing measurements with zero. |
| CB-08 | P1 / open | A whole replacement proposal during structural correction, including unrelated fields. | `production_planning.Worker` keeps both responses and allows one correction, but does not restrict the changed fields. A correction can remove a previously valid companion selection. Use field-scoped edits against an immutable proposal, permitted by a typed error. Recompile and validate the whole result; scope/permission changes need a fresh proposal. Workflow media-type correction already checks unrelated fields remain unchanged and is a useful precedent. |
| CB-09 | P1 / partial | Worker requirements, tool declarations, limits and attempt counts already constrained by selected adapters and task inputs. | 0.13.77 compiles missing workers, owns locked executor selection and diagnoses validator/code mismatches. `worker_capabilities.matches` already checks bound validators, binary and visual inputs. Derive mechanically required capabilities and default ceilings once; let the model request extra capabilities or lower budgets explicitly. Missing availability must remain a real blocker, not trigger provider fallback or removal of checks. |
| CB-10 | P2 / partial | Contract shapes outside the new planner envelope, plus unstructured validation-error text. | `planning_contract` leaves browser policy, operation parameters, geometry basis and output handoff descriptors opaque for their domain validators. Gemini alone receives the native planner schema; other providers receive it in context and are checked locally. Compose domain schemas from their owners, qualify each provider transport separately and emit stable error code/path/phase receipts instead of deriving telemetry from message text. |

## Code anchors and completion checks

- **CB-01:** [orchestrator_chat.py](../task_relay/orchestrator_chat.py), `generate`,
  `response_json`, `interpret`; action modules including `pipelines.validate` and
  `production_planning.validate_action`. Done when an unsupported field cannot
  enter dispatch and the same action definition drives generation and validation.
  Test explicit user-selected provider/source, missing required fields and no-action
  answers across supported providers without live requests.
- **CB-02:** [operation_builders.py](../task_relay/operation_builders.py), frozen typed inputs and pure builder; [execution.py](../orchestrator/execution.py), `REGISTRY`, `validate`;
  [production_planning.py](../task_relay/production_planning.py), `validate_result`.
  Done when a minimal operation selection compiles exactly the same reviewed
  assignment, altered constants cannot override it, and approved historical
  operation versions are never silently refreshed.
- **CB-03 / CB-04:** [handoff_contracts.py](../orchestrator/handoff_contracts.py),
  [workflow_correction.py](../task_relay/workflow_correction.py),
  [pipelines.py](../task_relay/pipelines.py), planner wiring/binding functions.
  Test exact selected versions, multi-output ambiguity, alias collisions,
  unsupported format conversions, reviewer coverage and script/checks selection.
  Completion must preserve original output identities and human decision boundaries.
- **CB-05:** native contract modules such as
  [rhino3dm_script_contract.py](../orchestrator/rhino3dm_script_contract.py).
  Test round-trip construction/validation for create and edit, explicit format
  versions, nulls, missing semantic values and immutable preservation requirements.
  Small text manifests suffice; no model rendering is required for this boundary.
- **CB-06 / CB-07:** [contracts.py](../orchestrator/contracts.py), `REPORT_SCHEMA`,
  `report`; [gemini_worker.py](../orchestrator/gemini_worker.py), `definitions`,
  `save_review_report`; [workers.py](../orchestrator/workers.py);
  [source_fidelity.py](../orchestrator/source_fidelity.py).
  Test wrong invocation identity, missing/duplicate criteria, partial blocked
  reports, missing measurements and evidence tied to a different source version.
- **CB-08:** planner `Worker.tick` and
  [workflow_correction.py](../task_relay/workflow_correction.py), `verify`.
  Regression: repair one field while retaining exact instructions, inputs, budgets,
  gates, selection lists and deliverable coverage. Reject unrelated changes and
  preserve both raw responses plus the applied patch. Uncertain submissions are
  never replayed to obtain a better format.
- **CB-09:** [worker_capabilities.py](../orchestrator/worker_capabilities.py),
  `matches`, `resolve`; [planning_contract.py](../task_relay/planning_contract.py).
  Test derived validation requirements with a locked text-only profile, conflicting
  tool claims, explicit lower user budgets and unchanged bindings at Start.
- **CB-10:** `planning_contract.contract`, planner/router/worker receipt writers.
  Done when one boundary's typed error can be followed through original rejection,
  bounded correction, final disposition and deployed contract version. Provider
  errors, authorization errors, missing tools and content-quality findings remain
  separate from structural errors. Do not retrofit inferred codes onto old records.

Suggested first implementation order: CB-08, CB-02, CB-03, CB-09. This addresses
unrelated correction drift and repeated service-owned metadata before expanding
schema support into every domain. Each change retains its own focused regression
and deployment evidence rather than requiring a cross-product live exercise.

## Repeatable tracking now

Run the read-only inventory against the selected instance's database:

```sh
python3 scripts/audit_planner_contracts.py --db /path/to/state.sqlite
python3 scripts/audit_planner_contracts.py --db /path/to/state.sqlite --since 2026-09-18
```

The second form uses an inclusive UTC date, not a software-version filter. Use
`--details` only with output saved under ignored `outputs/` or private storage: it
includes exact saved error text and plan IDs. The default contains category counts,
current plan status counts, date bounds and hashes for unclassified signatures;
it does not expose prompts, responses or artifact contents.

The report counts **failed calls** and **distinct plans** separately. One plan can
have multiple failed calls or categories. Old errors remain counted even when a
later call succeeded; `started` is not proof of accepted output or task completion.
Known error-message signatures are triage hints, not a causal determination that
the model invented a contract. Provider and capability failures are separate, and
unknown messages remain visible instead of being forced into a guessed category.

Current automated coverage is only `production_plan_calls`. Router failures live
in different receipts/answers, worker failures in attempts/reports, and analysis
jobs have another store; those need typed adapters under CB-10. This audit does
not parse free-text answers as facts, scrape full user prompts, migrate data,
invoke providers, dispatch workers or schedule a background monitor.

For each future fix record: boundary ID, error code/path, schema version, original
receipt reference, bounded correction disposition, focused regression and deployed
version. Keep instance-specific receipts and research in ignored storage; keep
only generic contract definitions and tests in public source.
