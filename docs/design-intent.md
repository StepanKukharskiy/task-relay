# Design intent during modeling

Task Relay can maintain a versioned design brief during a conceptual modeling
workflow. The conversational router proposes this mode for design exploration and
revisions. A request such as “Design this in Rhino; show one representative unit
before developing the complete model” should produce a prototype stage followed
by development. The router still interprets natural language; this is not a
keyword-triggered operation.

The plan card shows the proposed construction approach and active intent entries.
The full plan retains every entry, exact supporting user quotation, proposed
checks, superseded entries and the prior version hashes. User requirements and
rejections are separate from agent proposals and unresolved questions. An inferred
dimension or geometric implementation is not an approved requirement.

Unresolved form starts with a representative geometric prototype. Workers should
demonstrate it in plan, section and perspective against the supplied references.
Script preparation and source review retain their existing execution boundaries;
selecting code is not selecting the resulting geometry. Development requires
recorded selection of a prototype model and preview from the same production task,
or a cited explicit user instruction to bypass prototyping. A standalone library
operation that supplies no preview cannot alone establish this visual checkpoint.
Use a native modeling operation with preview support for the first experiment.

Every independent review must cover each active entry with evidence tied to the
exact intent hash. Preparation evidence concerns construction/code; output evidence
concerns inspected artifacts. Generic “valid model” acceptance is insufficient.
Reported concerns and unverified design judgments trigger the existing human
quality gate. Required missing files or tools still block execution/review.

Corrections preserve the earlier version. Ordinary user revisions immediately
retain verbatim feedback in both producer and reviewer assignments. The next
planning stage can atomize that feedback and explicitly supersede affected entries.
Unrelated entries remain active. Review-model suggestions cannot acquire user
authority. Follow-up stages inherit only their selected lineage, including explicit
workflow artifact handoffs; unrelated jobs do not share a mutable project head.
Competing design branches require an explicit source choice.

## Implementation and limits

The existing production plan/assignment JSON stores the state; no new database
schema or separate extraction-model call is required. New routing actions and
production workflow stages can declare `design_intent: true`. Ready planner
responses then supply a bounded design proposal. Earlier frozen plans remain
compatible and are not retroactively changed.

This is an experimental production feature, extending the principles of the local
[continuity experiment](continuity-experiment.md). Evidence quotation, identity,
scope and coverage are checked procedurally. Meaning, relevance of a quotation,
reference interpretation and geometric fidelity still require model/human judgment.
For example, a quoted sentence may be real while its proposed interpretation is
wrong. A prototype selection identifies an exact model/preview pair; it does not
prove every requested camera or design property was demonstrated.

This version does not learn a personal style, merge unrelated projects, extract
manual Rhino edits, certify aesthetic similarity or add tool capabilities. A
linked image must still be collected as an actual source through the existing
workflow. It does not import private modeling histories into product defaults.

Controlled tests use small text placeholders for model/preview identities and
scripted provider responses. They establish state propagation, scoped overrides,
review coverage and decision boundaries. They do not establish improved design
quality, successful live model interpretation or reduced human review time.
The next user design session is the first production evaluation: record repeated
corrections, review effort, unnecessary rebuilds and final quality.
