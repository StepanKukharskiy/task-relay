# Artifact roles at the worker boundary

A worker assignment and a native operation have different file contracts. A
worker can inspect an earlier document while its builder consumes only prepared
content and selected assets. The compiler must preserve that distinction.

## Shared implementation

`artifact_roles` is compiler-owned metadata on registered in-assignment work.
Each assigned input has an exact provenance binding and inheritance origin, an
inspection route, and an explicit list of operations that consume it. Output
ports have separate result bindings. This does not grant access to unassigned
files, new tools, network access, custom code or additional capacity.

The existing handoff closure records which upstream artifact caused inheritance.
Registered adapters may expose an exact inspection representation for already
assigned evidence. The PowerPoint render adapter binds a PDF or source deck to
its matching page-image archive using the completed native receipt, candidate
identity and exact hashes. The same hook supports committed render receipts from
inside a worker assignment. It never guesses by filename or imports a sibling
outside the assigned scope. The freeze boundary and file tools recheck identity.

Text goes through the granted reader. PNG/JPEG pixels and image archives go
through granted visual inspection. JPEG decoding is bounded local code. A PDF
with no exact registered page representation still fails with a specific remedy;
this change is not a general PDF reader. Required assigned evidence is not
silently downgraded to provenance-only metadata to make admission pass.

Native input projection and prepared-content asset binding use the same consumed
file list. An inherited old PDF, deck or preview archive stays inspectable without
becoming a build asset. Historical provenance remains in the existing artifact
and receipt graph; preserving that relationship does not confer operation input
compatibility. A product-image archive can remain an actual build input.

## Failure ownership

Compatibility diagnostics identify the artifact/path/type, its role, selected or
inherited origin, failed check and remedy. A wrong explicitly selected operation
input remains model-correctable through existing proposal recovery. Missing
inspection support introduced by code-owned inheritance creates a durable runtime
compatibility hold; it does not repeatedly ask the owner to remove evidence.
Worker selection still tries the authorized compatible worker profiles.

These are extensions to existing compiler, adapter, file and recovery boundaries;
there is no new job controller. Historical executed assignments and grants are
not rewritten. The owner still has to make useful decisions: deterministic
compatibility checks do not establish efficient live delegation or sound research.

## Qualification

See `outputs/artifact-roles/CHECKS.md` for commands, results and limitations. The
saved-job replay retains mixed evidence and launches actual worker processes with
scripted provider responses. Native build/render operations create real files;
restart reuses committed results, and independent review names the corrected
version. A separate four-stage controlled flow preserves inventory, product
records, source evidence, linked image bytes and the resulting editable deck.
These tests do not establish live semantic quality, provider efficiency, installed
package identity or final client acceptance.

## Owner decision brief

New delegation-v4 jobs capture `decision_brief_version: 1`; existing saved grants
remain unchanged. The current durable state projects exact authorized input
references, current worker outputs, carried findings linked to the original
review's available evidence, failures, remaining capacity and a next-action hint.
The exact request remains in the initial message. Full source bodies and finding
evidence are not loaded into this brief; they remain in worker inputs and saved
journals. Long finding messages are explicitly marked truncated, never accepted.

Registered work routes are derived from requested output formats, existing
preparation defaults, granted inspection companions and authorized producer/reviewer
profiles. They expose a minimal `work` selector, not the worker's content schema.
Source compatibility and current remaining capacity are still validated at
admission. Missing support is disclosed rather than advertised as executable.
Rejection and uncertain-effect handling take precedence over new-work hints.
No furniture task sequence, new controller or model-generated summary is added.

The brief is advisory coordination metadata, not semantic evidence or a stronger
execution grant. Controlled first-response delegation proves that the interface
can be used without prerequisite file/catalog reads; it does not prove that a
live provider will choose to do so or reduce billed tokens. Qualification and
installation are recorded under `private qualification records`.
