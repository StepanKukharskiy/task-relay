# Partial delivery after an execution stop

A job can stop scheduling while retaining useful work. For a settled owner job,
`Runtime.status` keeps its historical execution status and provides a separate
`delivery` projection when byte-verified collected candidates exist. The delivery
status is `partial`; `complete` and `user_acceptance` are false.

The shared projection selects current collected producer outputs in the requested
formats. It verifies registered paths, lengths and hashes and binds review labels
to the exact candidate artifact and producer attempt. Candidates are reviewed,
require attention, or are unreviewed. Negative judgments and stop reasons remain
visible; a file's format alone never fills a final deliverable role.

Status cards, the existing terminal handoff and exported files show available work
and unresolved issues. They do not discard files merely because proposal recovery
was exhausted. No new retry, authorization, selection or dispatch occurs. Missing
or changed files are not advertised. Active or draining runs do not become
terminal partial deliveries. A stopped uncertain run with no ongoing independent
work can report verified outputs from completed producers. Outputs of uncertain
producers are excluded. Exact recorded uncertain review judgments remain visible
as requiring attention, including an acceptance accompanied by unresolved
findings; a missing review never becomes approval. Unknown effects and their
original receipts remain unresolved, with no replay or new dispatch. The separate
partial projection does not change the historical uncertain execution status.
Jobs with no available candidate remain stops
without a delivery. Successful completion still uses the existing final-review gate.

This is a reporting boundary, not a change to recorded worker verdicts or the
scheduler state machine. Existing channel controls and notification deduplication
apply. Controlled text qualification covers actual owner proposal rejection,
restart, review rejection, stale reviews, file tampering, uncertainty and export.
