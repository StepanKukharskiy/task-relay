# Shared operation review and handoff evidence

The registered operation lifecycle supplies one code-owned provenance envelope to
standalone consumers and reviewers, and to in-worker `work_evidence`. Models do
not manufacture receipt identities or declare their own inspection requirements.
Prospective owner grants enable this interface with `execution_review_version:1`.

The envelope includes:

- Producer attempt and committed selection/admission identity.
- Exact registered execution and frozen assignment digest.
- Original input identities and complete output identities.
- Hashed dispatch, terminal and materialization receipts.
- Registered adapter evidence, verified by its adapter and sealed by the common
  materialization receipt.
- Explicit separation between completion evidence and independent acceptance.

The producer determines capsule identity. Consumer paths, aliases, repeated
handoffs and selected output subsets do not create another version. A consumer
inherits a byte-identical capsule once. A conflicting capsule terminates admission
with an explicit binding fault; it is not a model-correctable writing problem.
The capsule is read-only inspection context, never a native operation input or a
requested final deliverable. Original journals remain available for audit.

Text/JSON uses literal readers. Pixels are required only for images or registered
visual representations. Browser observation IDs remain citations into the bound
original journal, not synthetic `evidence_read` handles. Adapter/build metadata
and confirmed execution observations describe different facts. Neither a capture
nor an execution receipt establishes semantic quality or user acceptance.

Owners can use `job_stop` for a blocker without a permitted repair. Code records a
terminal outcome and the existing settlement controller collects already-dispatched
workers. It does not launch recovery work. Repeated failed completion is counted
across owner invocations. An unchanged failed review snapshot cannot commission
another assessment without a changed candidate or evidence. Corrected/new evidence
remains eligible; final delivery still requires exact completed producers and
independent reviews resolving the applicable findings.

This is a shared operation-review interface over the existing assignment,
artifact, report and recovery contracts. It is not a claim that every external
tool accepts one universal content payload. Each registered adapter still declares
its compatible content formats and capabilities. No provider, website or geometry
application exception belongs in the handoff controller.

Qualification records: `private qualification records` and the
separate live focused runs in `private qualification records`. Controlled
coverage, observed live coverage and unexercised terminal branches are recorded
separately. Original failed attempts are not rewritten as passes.
