# Mixed graph execution — O06

One production graph can combine Codex assignments with versioned registered
operations. Existing graphs retain their agent behavior. A task with `execution`
uses its registered adapter; a task without it uses the graph's fixed Codex backend.
Both paths share assignments, frozen input copies, artifacts, dependencies, attempt
receipts, cancellation, status and selection records.

## Available operations

| Capability | Inputs and output | Limits |
| --- | --- | --- |
| `text.bundle` v1 | 1–20 UTF-8 text files → one text bundle containing their verbatim content, identities, hashes, purposes and authority | 2 MB input, 2.1 MB output, 30 seconds, one attempt, no external request |
| `gemini.text` v1 | 1–20 UTF-8 text files plus the declared instruction → one text response | 120 KB input, 200 KB output, 1–4096 output tokens, one request, 180 seconds maximum; HTTP timeout at most 120 seconds and response body at most 1 MB |

Input types are `text/plain` or `text/markdown`; registered output type is
`text/plain`. Declare `media_type` on connected inputs and upstream outputs.
The graph validates compatible types; the operation also checks actual UTF-8
decoding, bytes and input hashes. No arbitrary command, endpoint, credentials or
agent tools can be supplied in the execution specification.

For example, a bundle task uses:

```json
"execution": {"capability": "text.bundle", "version": 1, "parameters": {}}
```

A Gemini task supplies an exact model ID and `max_output_tokens` in `parameters`.
The planner uses the frozen configured Gemini text model. Its API call has no
tools, sessions or automatic retry. Credential configuration is read by the trusted
adapter and is not placed in the plan or worker input files. Availability means
configuration is present; authentication is established only when the API is used.

## Planning and approval

For a mixed text workflow, `plan_production.step_capabilities` lists the needed
registered IDs from `snapshot.capabilities.graph_operations`. The bounded planner
can then propose 2–6 steps. Each agent producer retains independent review;
registered operations use fixed mechanical criteria and cannot impersonate an
independent reviewer. Required selected sources must be text for this first mixed
planner scope. They and the exact request are carried to every step.

The existing plan card shows operations, API model/token limit and external source
transfer. Its Start action authorizes the exact graph. Missing configuration,
unrequested capabilities, changed inputs or an invented API model prevent starting.
Selection and later stages continue to use O05's recorded decisions.

A useful shape is **draft → independent review → bundle selected text → API text
operation → user decision**. An API step belongs only where the requested work
needs it. There is no requirement to add an external call to ordinary agent work.

## Receipts and recovery

Registered operations use the existing detached supervisor. A committed attempt
precedes submission, and an exclusive supervisor claim prevents duplicate child
execution. Input/output registration and checks use the same runtime collection.
Unknown, unavailable or incompatible operations cannot become arbitrary commands.

The API child saves `request.json` before transport and the first `response.json`
when received. `operation.json` and the common attempt receipt retain capability
version, upstream response ID, hashes and reported usage. Truncation, filtering,
invalid text and size failures block downstream work while preserving evidence.
Procedure checks establish transformation integrity; API checks establish receipt
of complete text. Neither establishes factual accuracy or user acceptance.

An ambiguous submission or a local timeout after request intent remains uncertain
and is never automatically replayed, including after service restart. Cancellation
stops the local child and future scheduling; it cannot undo an accepted remote
request. Local termination and unknown external outcome remain distinct in the
receipt. Missing usage/cost stays unknown. Inspection includes available operation
and response logs with the existing truncation labels.

## Scope and verification

This first implementation supports registered text operations and the existing
Codex graph executor. Additional APIs, media operations, Blender and hosted workflow
adapters require a concrete workflow need and their own contracts. Existing host
supervision limits remain; this change does not establish Windows support.
