# Confirmed search failure and bounded evidence retention

A provider adapter must correlate the exact submitted request, terminal identity,
structured error and tool activity before calling a failure confirmed. A status
code in prose, a transport exit, missing terminal, pending hosted read or mismatched
receipt remains uncertain. Original journals remain unchanged; usage is unknown
when the provider did not report it.

The Codex adapter recognizes the structured `responseTooManyFailedAttempts`
terminal as well as the legacy JSON rejection. Retry notifications must precede
one non-retrying error and its matching failed terminal. This does not authorize
another search after the provider has exhausted retries. Existing pre-search
service-overload continuation remains limited to one same-thread continuation
within the original deadline; it never replays a started hosted tool.

The provider-neutral search outcome boundary consumes confirmed rejection status.
For rate limiting or service unavailability it stops the remaining batch, preserves
all earlier pages and grounding, records the failed query as unavailable, and marks
later queries not submitted. The pack is evidence of partial work, not proof of
coverage or accepted facts. Other rejection categories still fail; uncertain
submissions still hold the operation. Reviewers and owners receive the exact pack
and decide whether existing evidence and separately granted alternatives suffice,
within unchanged task/owner limits. The outcome grants neither replay nor capacity.

Confirmed Codex rejection receipts bind the query's original submission ID and
hashed journals. A restart restores the same rejection without dispatch. Missing,
changed or mismatched saved receipts stop as uncertain rather than becoming a
query-level missing result that would let the batch continue.

Controlled qualification is recorded in `private qualification records`:
original AO journal interpretation without mutation; synthetic protocol peers;
provider-neutral partial collection; saved receipt corruption; actual registered
source operation, scheduler restart and independent review consuming the partial
pack; affected shared review, fallback and terminal draining checks. These are
not live model decisions or evidence that the full artifact pipeline passes.
