# Shared operation contracts and structured research

Status: implemented and installed locally in Task Relay 0.13.129, including typed
research records, JSON handoffs and the bounded campaign controller. No live
provider qualification is claimed.

## Provider independence

Contract IDs, versions, JSON Schemas, job parameters, domain validation,
checkpoint transactions, completion checks and serialized artifacts are provider
agnostic. The common tool definition exposes ordinary JSON Schema under
`parameters`. Only the provider adapter translates that schema and the request/
response envelope (for example, Gemini uses `parametersJsonSchema`; OpenAI and
compatible endpoints use their own function-tool envelope). Existing backend
bindings still prevent silent provider switching.

A scripted parity test exercises Gemini, OpenAI, Qwen, DeepSeek and OpenRouter:
the same frozen audit data, invalid-source rejection, successful submission,
identical retry receipt and byte-identical assembled audit. This verifies local
adapter/contract parity, not live model availability or response reliability.

## Implemented contract boundary

`orchestrator/operation_contracts.py` is the shared registry and validation boundary.
`operation_records.py` owns attempt-bound checkpoints in the existing shared
SQLite database. The existing planner, worker, supervisor and handoff compilers
use these modules; this is not a separate executor or database.

| Contract | Version | Current adapter |
| --- | --- | --- |
| `research.audit` | 1 | Submit at most three next claim verdicts; code builds the existing audit JSON and worker builds the Markdown review. |
| `research.candidates` | 1 | Submit one entity with its identity references and every job-required field, explicitly labeled observation, inference or unknown. Code builds a candidate ledger. |
| `research.batch` | 1 | Campaign discovery or assessment records, including one decision per frozen criterion. Empty discovery is valid when independently audited coverage supports it. |
| `geometry.specification` | 1 | Typed JSON handoff delegates validation to the existing standalone geometry specification validator. It grants no new geometry or host execution. |

New research plans select `research.mode` explicitly (`profile` or `discovery`).
Discovery parameters are `entity_type`, `required_fields` and `max_records`.
The existing profile/post producer format remains supported. New reviewers use
research-audit assignment version 2, which binds the record operation; historical
version-1 reviewers keep their original file-writing contract.

`operation_submit` takes a request key, current revision and a small typed record
batch. The family schema is selected by the frozen assignment, never by a tool
argument. Claim IDs come from the frozen evidence pack. Relay derives checkpoint
record IDs, source hashes, output paths and serialized files. The prompt includes
current progress and only the next three audit claims. Generic writes/appends
cannot modify a contract-owned output.

Each submission validates the whole batch before an atomic commit. Identical
request-key retries return the saved receipt; conflicting keys, duplicate record
identities, stale revisions, foreign claims and invalid source quotes fail.
Exports happen after commit and can be repaired with `Store.export` without a
provider or browser call. `Store.verify_export` runs again in the supervisor.
This does not automatically restart an interrupted worker or reset its attempts.
Job deletion includes owned checkpoints and submission receipts.

The planner rejects oversized batches and insufficient declared budgets rather
than raising them. A discovery batch can contribute at most 30 identity/field
claims plus ten summary claims; all are independently audited. Discovery needs
one submission per possible candidate plus summary, finish and reserved URL
actions. Review plans reserve 16 requests/tools for up to 40 claims. These are
capacity checks, not a guarantee of yield. Empty results remain blocked; a record
ceiling is not a promised number of qualified entities. Identity deduplication is
by exact URL; aliases and real-world identity conflicts still require review.

Workflow outputs and consumer edges may carry `content_contract: {id, version}`.
Typed consumers require the same identity/version, and delivered files are
validated by that family. A posts-only object cannot cross a candidate-ledger
port. Untyped legacy handoffs retain their existing behavior. Content validation
never promotes an artifact to independently reviewed or user accepted.

Controlled qualification used small prospect/supplier fixtures and the saved
20-claim evidence pack in an isolated database. The latter assembled seven batches
and a review in eight scripted responses, with every verdict deliberately
uncertain. It did not call a provider, read X again, mutate production state or
accept research. See the private check log under `outputs/shared-operation-contracts/`.

## Remaining research lifecycle work

The campaign controller now implements qualification, target/yield tracking and
bounded replenishment; see [Research campaigns](research-campaigns.md).
Dedicated workbook/draft renderers remain separate work; existing final production
stages receive the campaign ledger and exact source artifacts. No twenty-person completion or live Gemini
reliability improvement is inferred from scripted tests. Other operation families
retain their existing validators until a concrete integration needs migration.

## Decision

Extend the existing shared contract/compiler layers with reusable operation-family
contracts. Do not create a new contract for every user request, and do not replace
domain validators with one unrestricted universal JSON object.

The model chooses strategy, selects known inputs, proposes bounded domain data
and makes attributed judgments. Relay constructs executable assignments, binds
versions, validates records, persists progress and renders artifacts. Semantic
truth and suitability still require independent review; structural validation
does not establish them. Native/provider calls can still fail or return malformed
data, so bounded recovery and no-replay rules remain necessary.

## Existing pieces to reuse

| Layer | Source | Existing responsibility and limit |
| --- | --- | --- |
| Planner wire contract | `task_relay/planning_contract.py` | Versioned proposal schema, local validation, provider structured output. Some domain payloads remain opaque to this outer schema. |
| Assignment/runtime contract | `orchestrator/contracts.py`, `orchestrator/runtime.py` | Frozen tasks, declared inputs/outputs, dependencies, worker limits, attempts, review and selection. Does not guarantee the model can construct its output. |
| Workflow compiler | `task_relay/workflow_builder.py` | Compiles semantic outputs and uses into workflow ports; binds registered operation outputs and companion files. Model still designs stages. |
| Artifact binding compiler | `task_relay/artifact_bindings.py` | Model selects captured artifact IDs or producer outputs; Relay constructs paths, authority, dependency edges and reviewer inputs. |
| Cross-tool handoffs | `orchestrator/handoff_contracts.py` | Checks media types, operation versions, capacity, declared producers/consumers and companions. Generic JSON ports do not distinguish a candidate ledger from an audit or geometry specification. |
| Registered operations | `orchestrator/execution.py` | Versioned operation IDs, parameters, inputs, outputs, limits, checks and execution adapters. Includes `web.sources`, `pptx.create/edit`, `rhino3dm.create/run_python`, image collection and media rendering. Registration alone does not establish live qualification. |
| Typed operation builder | `task_relay/operation_builders.py` | Currently scoped to `rhino3dm.run_python`: model selects captured script/check/model IDs; code builds assignments, paths, hashes, criteria, limits, reviewer and selection gate. Best existing pattern for research. |
| Domain validators/writers | Geometry, PPTX, browser/computer and media contract modules | Own actual format, native-action and domain-specific rules. Keep these validators; do not flatten them into a generic schema. |
| Evidence and revisions | `task_relay/reviewed_links.py`, `native_links.py`, `impact_handoff.py`, `revision_review.py` | Normalize explicit evidence/output links, conservative impact and exact-version review/selection across bounded adapters. They do not discover all dependencies or validate arbitrary research claims. |
| Research checks | `orchestrator/research_quality.py`, `computer_review_inputs.py` | Frozen raw captures, post citation checks and complete claim audits. Model still authors audit JSON through generic file tools. |
| Reusable workflows | `task_relay/procedures.py` | Reviewed immutable templates extracted from completed workflows. A saved workflow template is separate from an operation/data contract and does not prove quality on a new job. |

## Shared framework responsibilities

The implemented registry follows these shared rules:

- Contract ID and version, typed input/output ports, record schema and semantic
  validator, fixed construction/serialization code and completion checks.
- Existing job/task/attempt identity and authorization, artifact IDs and hashes,
  declared side effects, time/request/tool/record limits and recovery behavior.
- Bounded record submissions with stable request keys. Identical duplicate
  submission returns its receipt; conflicting reuse fails. Code assigns internal
  IDs and source/candidate hashes rather than asking the model to reproduce them.
- Transactional record persistence in the existing shared `state.sqlite`.
  `.relay` and JSON files remain projections/artifacts, not a second authority.
  External dispatch remains after commit. Export failures can be repaired from
  committed records without another model or browser call.
- Code-generated final JSON/Markdown/native artifacts, bound to exact record
  versions. Existing independent-review and user-selection gates remain separate.

Extend handoff descriptors with an explicit optional content-contract identity
and version. A typed consumer must require the right contract, not merely
`application/json`. Check compatibility at planning and actual record validity at
handoff. Legacy frozen plans keep their historical behavior. Conversions must be
declared operations; no implicit conversion or trust promotion.

Freeze contract versions in new plans. The model cannot invent a runtime schema,
validator or executable operation as a way to gain capabilities. New operation
families require implementation and tests; ordinary jobs configure existing ones.

## Reusable research family

Use related explicit contracts for distinct objects:

1. Source observation: captured URL, retrieval time, snapshot hash and locator.
   The native/public-source adapter creates this record; the model cannot supply
   a replacement capture as authoritative evidence.
2. Entity/candidate: identity and source-linked discovery facts, aliases,
   provenance and unresolved identity conflicts. An observed post is evidence
   associated with a candidate, not a substitute for the candidate record.
3. Claim: entity, predicate/value or concise text, observation/inference/limitation
   label and exact source references. Missing, conflicting and unknown values
   remain explicit. Exact substring presence alone does not prove attribution or
   that the source supports the whole claim.
4. Audit verdict: frozen claim ID, supported/unsupported/uncertain, bounded
   explanation and source references from a separate reviewer assignment.
5. Qualification: explicit criterion decisions bound to a versioned policy,
   evidence and review state. Keep/hold/reject is separate from evidence quality
   and separate from user acceptance.
6. Progress: queued/researched/reviewed/qualified/rejected/held candidates,
   remaining authorized capacity and recorded reasons for a shortfall.

Job-specific data includes target count, geography/industry, criteria, required
fields, source scope, acceptable uncertainty and output columns. It does not
require writing a new validator for each request. A supplier shortlist, product
comparison and prospect study should reuse source/claim/audit primitives while
using appropriate entity types and qualification policies. Do not impose the
prospect schema on every URL-reading task.

The implemented model-facing tool is `operation_submit`, whose record schema is
selected by the frozen family contract. Separate claim authoring and candidate
qualification outside campaign batches remain future integrations. Submit small bounded records;
do not accept a string containing a complete audit document. The handler owns paths, hashes, assembly,
coverage bookkeeping and receipts. The independent reviewer owns its verdict.

The planner still chooses queries and batch strategy. Runtime feasibility checks
must reject unsupported actions, bare search landing pages used as executable
queries, missing producers, oversized batches and incompatible outputs before
Start. A scheduler tracks actual reviewed yield against the requested total and
the declared effort ceiling. Further discovery may occur only within an explicit
bounded batch/iteration grant; existing twelve-stage/task and provider limits
must not be silently expanded. If a fixed plan cannot cover the requested scale,
return it for correction or declare the limitation before paid dispatch.

For the prospect job, compose discovery, candidate enrichment, evidence audit,
qualification and deterministic workbook/draft export. Outreach remains draft
only. Producing twenty rows does not establish twenty qualified people.

## O15 sequence and remaining scope

1. **Typed audit submissions — implemented in source.** Add a versioned research-audit handler to
   the existing worker tool dispatcher. The runtime freezes the next bounded set
   of claim IDs. The model supplies verdicts, reasons and references only. Validate
   and checkpoint each set, track missing/duplicate claims, and assemble the audit
   and Markdown report in code. Disallow generic file writes to contract-owned
   audit outputs for new assignments. Reuse current capture bindings and literal
   quote/claim checks. Use the already-saved evidence for qualification of this
   change; no new Safari searches are required.
2. **Separate discovery and profile contracts — implemented in source.** Replace output-extension-based
   research binding with explicit operation identity. Keep the existing post/
   profile contract for historical assignments; add a candidate ledger contract
   and typed producer operations. Validate candidate/source linkage and unknowns.
3. **Typed cross-tool handoffs — JSON validation implemented; table exporters remain.** Carry candidate/claim/audit contract identity
   through the existing workflow and artifact builders. Generate JSON and output
   tables from records. Reject a posts-only object offered as a candidate ledger.
4. **Bounded batch lifecycle — implemented in the campaign controller.** Track candidate progress and remaining work;
   validate query feasibility and total capacity before dispatch. Implement any
   needed bounded iteration explicitly rather than encoding it in prose. Test
   replenishment and an honest shortfall at the declared ceiling.
5. **Reuse proof — controlled prospect/supplier fixtures pass.** Exercise the same research primitives with two small synthetic
   policies (prospects and suppliers/products). Add another domain family only
   when it has genuinely different invariants. Do not migrate all existing tools
   or rebuild unrelated artifacts as a prerequisite for this research fix.

## Acceptance and recovery checks

Use small captured-text fixtures and scripted provider responses to check:

- Interrupted audit resumes from committed claim records; no producer replay.
- Duplicate, stale, foreign-source and conflicting submissions do not corrupt
  records or advance completion. Identical idempotent replay returns the receipt.
- Oversized or malformed model responses execute no partial operations, preserve
  prior records and remain within original request/time/attempt limits.
- Completion requires every frozen claim to have an independent verdict. The
  model cannot self-approve, supply trusted hashes, overwrite source captures or
  turn unknowns into supported claims by changing the schema.
- Candidate identity, evidence freshness, citation attribution, required-field
  coverage and policy version are distinct from mere JSON validity.
- JSON-kind mismatch fails before downstream use. Missing output/renderer/worker
  capability fails before paid research for an undeliverable workflow.
- Batch exhaustion records a shortfall; it does not pad results, spend beyond the
  approved ceiling or create an endless discovery loop.
- Old frozen assignments/receipts remain readable and unchanged; any recovery
  creates an explicit new version/attempt under the existing authorization rules.

Installed 0.13.128 passed 21 controlled worker/planning checks, including provider
parity. The completed live twenty-person benchmark is not claimed.
