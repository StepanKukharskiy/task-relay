# Typed artifact, workflow and report builders

New generation interfaces expose semantic slots. Relay owns field names, fixed
metadata and serialization. Domain validation and authorization still run on the
compiled result; correct structure does not establish correct content or acceptance.
These are versioned additions, not migrations of historical receipts.

## Artifact references inside a production plan

New generic planning schemas advertise `input_bindings` instead of `inputs`,
`dependencies` and `selection_outputs`. For example:

```json
{"input_bindings": [
  {"source": "captured-artifact-id"},
  {"producer": "prepare", "output": "delivery/model.py"}
]}
```

`artifact_bindings.build` resolves source paths, purposes and authority from the
captured catalog, records exact source hashes, copies declared producer output
types, and builds stable upstream workspace aliases and dependency edges. Optional
`after` expresses ordering without a data dependency. Only rhino3dm additional
inputs may use `role: "asset"`; this preserves the primary script/checks/scene roles.
Registered-operation argument typing still passes the owning domain validator.

A reviewer names `review_of`; Relay binds every output of that producer. A producer
with a user gate selects all its declared companions (a single output uses the
existing single-file gate). Unknown references, duplicates, cycles, reserved-path
collisions and mixed compact/handwritten binding fields fail validation. No implicit
conversion, replacement source, acceptance or permission grant is generated.

The original provider text remains in `production_plan_calls.response`. Compact
proposals compile to canonical `production_plans.result` for existing recovery;
`plan.origin.artifact_bindings` preserves selections and resolved bindings/versions.
Old frozen requests retain their schema. The local validator explicitly accepts
all-legacy task drafts for existing integrations; new advertised schemas expose
only compact bindings. Typed operation builders keep their own stricter interface.

## Workflow stages

New `plan_pipeline` actions use `stage_details`, whose exact schema is supplied in
`snapshot.workflow_builder_schema`. Stage IDs, instructions, route, gate and chosen
capabilities are semantic decisions. Outputs and uses describe intent:

```json
{
  "id": "brief", "instruction": "Write the requested brief from selected facts.",
  "route": "production", "gate": "selection", "capabilities": [],
  "outputs": {"brief": {"description": "Requested brief", "format": "markdown"}},
  "uses": [{"stage": "research", "output": "facts", "consumer": "context"}]
}
```

`workflow_builder` supplies contract version, deliverable descriptors, MIME types
and handoff edges. Formats come from a fixed catalog. For a registered output,
select `operation` plus its exact captured `port` instead of `format`. The special
`result` port applies only to operations with one `output_type`. Registry output
changes reject the proposal. Format selection does not establish installed tooling.

Optional `max_bytes` and `slides` retain requested bounds and quantities without
clamping them to capability limits. Outputs sharing an explicit `together` group
get symmetric companion declarations. Consumers must select those companions;
missing selections are rejected rather than silently added. Earlier-stage outputs
and compatible consumers are required; no conversion stage is inferred.

Canonical stages still pass the existing workflow validator, source bindings,
capacity checks, user gates and scheduling boundaries. The canonical spec is saved
atomically with a `workflow_compiled` event containing the exact typed request,
compiled digest and operation digests. No stage is dispatched by the builder.
Legacy stage contracts remain supported; no existing workflow is rewritten.

## Worker and review reports

New non-operation assignments freeze `report_contract` v1 with a role-specific
schema. Codex final-response schemas and shared Gemini/OpenAI/Qwen agent finish
tools expose the same form. A report supplies judgments in named criterion slots:

```json
{
  "summary": "Independently inspected the candidate.", "decision": "accept",
  "instruction": "", "findings": [],
  "checks": {"c1": {"passed": true, "evidence": "Actual observation and method."}}
}
```

Relay binds the active assignment ID and criterion indices. Every frozen slot is
present; only a blocked report may use null for unchecked slots. Missing/unknown
slots, identity injection into this form, failed criteria with acceptance, and
wrong-role decisions fail. Legacy canonical reports retain their existing identity
validation for compatibility. No worker or host operation is replayed to repair form.

Source-fidelity slots additionally accept typed evidence: observations keyed by
`s1`, `s2`, etc., each with `observed_sha256` and `observation`; measurements keyed
by the frozen metric names with numeric `error` and textual `evidence`. Relay
binds source identities and serializes the existing canonical evidence. Workers
must independently inspect/hash the actual sources. Missing measurements, changed
hashes, negative/nonfinite errors and unsupported evidence never become zero or a
pass. Exceeded tolerances retain the measurement and the existing user-review finding.

API finish tool receipts retain exact arguments; typed `.relay/result.json` and
runtime `first_response` retain the raw form. The runtime records the validated
canonical report separately. Markdown rendering uses that validated judgment.
Structured source evidence is an additional interface; old evidence strings remain
readable. Independent observations and human decisions are never supplied by builders.

## Remaining scope

Other registered-operation builders, the router's entire action envelope, native
script/check authoring and field-scoped structural correction remain in the
[boundary tracker](contract-boundary-tracker.md). These extensions do not remove
those remaining model-authored boundaries or claim live provider qualification.
