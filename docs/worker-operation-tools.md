# Productive work inside one assignment

Implemented in source on 2026-10-11. Package, installation and live-model
qualification remain separate. Existing installed jobs and grants are unchanged.

The owner can delegate one `work` intent using an operation name, input references
and semantic content choices. Code compiles it to an ordinary declared-file API
worker. The owner supplies no output paths, hashes, runtime commands or schemas.
For example:

```json
{
  "id": "deliver",
  "objective": "Prepare, inspect and correct the requested presentation",
  "inputs": [{"artifact": "an-exact-granted-reference"}],
  "work": {
    "operation": "pptx.create",
    "parameters": {},
    "content_parameters": {"max_records": 8}
  }
}
```

This requires a prospective `worker_tools_version: 1` job grant and both the
producing operation and its registered inspection companion in that grant.
Historical grants do not acquire tools. The selected file-worker profile must
support image inspection when the companion produces visual evidence. Capacity
must already accommodate content, sealing, local work, inspection and correction;
compilation cannot increase requests, tool calls, seconds or output bytes.

## Existing machinery, one productive worker

`owner_intents` compiles the intent through the same atomic owner admission,
producer binding, worker selection and Runtime used by other work. The registered
fragment family owns the content schema and projection. `operation_submit` saves
content; `operation_amend` replaces a guarded fragment while preserving its old
version. The current layout progress exposes the saved fragment hashes needed
for amendments, so the worker need not compute them.

`work_run(build)` calls the registered adapter through the existing fixed
`step_runner.py` and host process adapter. `work_run(inspect)` consumes the exact
current build. Results immediately appear as code-owned declared output aliases,
readable by the same worker. `image_view` sends actual PNGs from the preview ZIP
in the next model request. An amendment makes the old build stale; rebuilding
makes its old preview stale. Delivery requires current results and confirmed
observation of every current rendered page.

Local-call eligibility is explicit adapter metadata. This first scope enables
`text.bundle`, `pptx.create`, and the `pptx.render` inspection companion. It does
not expose arbitrary commands, network operations, host scripting, paid tools,
or an implicit custom-authoring fallback. Other operations continue through
the existing task interface until their in-worker transport is qualified.

The compiler adds one independent final reviewer, with the exact candidate,
matching PDF/previews and supporting input evidence. It does not create separate
layout/build/render tasks for this work intent. Final-quality checks include
registered inspection files. The existing owner completion gate verifies the
exact current candidate, its render receipt and the reviewer's observed pixels;
a different hash or producer attempt cannot inherit that review.

## Persistence and uncertainty

The private assignment control directory retains each native call's intent,
frozen child assignment, adapter outcome and immutable output version. Its intent
precedes external dispatch. A successful outcome is committed before publishing
output aliases. Reusing an identical request key returns its saved result without
execution; changed inputs with that key fail. A failed call consumes its tool
call and any produced output bytes. A new attempt at local work requires a new
key inside the remaining parent allowance.

A work checkpoint retains conversation history, pending provider turn, cumulative
request/tool counts and the original assignment clock. Restoring the same frozen
assignment reuses a received response and confirmed local results; it never sends
that provider request again. Generation-retry counters are reconstructed from
prior recovery receipts. Native versions share the original output-byte ceiling.
An unresolved provider request or native intent holds for reconciliation. The
existing factory also reports unresolved local-work intents as uncertain, so
outer recovery cannot mistake process exit for confirmed execution.

This is persistence inside the existing worker loop, not a new scheduler or an
automatic service-restart policy. The controlled restart tests re-enter the
worker with the same frozen assignment, workspace, journals and record database.
A stopped service still uses its existing recovery/authorization path.

Collection verifies receipts and current output hashes without rebuilding or
republishing anything. It shares the collector's database transaction when
checking record projections; it does not open a competing write transaction.

## Controlled evidence and remaining qualification

`tests/test_worker_tools.py` enters via scripted owner `job_delegate`, normal
compiler/Runtime admission and one file worker. It creates a real PPTX with a
seeded missing image/wrong heading, renders it with the local presentation tools,
supplies actual pixels, amends the registered layout, interrupts after the saved
correction, restores, rebuilds and renders v2. It rejects stale v1 delivery and
unobserved v2 delivery, then performs an independent scripted review and normal
owner completion. The final PPTX contains the corrected text, exact fixture image
and hyperlink, and the PDF contains the corrected heading. Both versions remain
in the native journals.

Additional small text fixtures exercise confirmed-result reuse after interruption
between outcome commit and publication, unknown native/provider holds, cumulative
requests/tools/bytes/deadline and generation retries, denied custom code/tools,
changed-input/output rejection, and invalid-response correction inside the worker.

These tests script model replies and reviewer judgments. The test factory captures
normal task dispatch; native adapters execute in real child processes. The binary
reviewer's Python-runtime discovery is stubbed; review uses the actual image tool,
not Python execution. No real provider is called. Thus these results establish
execution plumbing and identity/capacity boundaries, not autonomous judgment,
client-ready quality, provider efficiency or installed-app qualification.

Commands, results, initial failures and synthetic artifacts are retained under
`outputs/worker-tools/`. The next deployment step is exact-package qualification;
any paid experiment requires its own current authorization and comparable budgets.

## Exact-package deployment

Version 0.13.220 was qualified and installed on 2026-10-11. The combined package
passed 250 affected controlled checks and the exact saved failed-proposal replay.
The complete worker flow generated real PPTX/PDF versions and observed rendered
pixels, using scripted provider/reviewer decisions. Whole signed installed identity,
all 140 runtime overlays, a running app and five fresh core services were verified;
all 237 saved jobs remained unchanged. No paid run was started. See
`private qualification records` for commands and limitations.
