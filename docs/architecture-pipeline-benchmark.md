# Architecture competition pipeline benchmark

Status: proposed live integration benchmark; no provider calls, account submissions,
modeling or presentation generation launched by this specification.

## Purpose

Qualify Relay against a complete architectural deliverable, including an explicit
design revision and reuse of the latest model/render. Passing isolated tools or
replaying fixed model responses does not qualify this benchmark.

Initial fixture: a fictional waterfront exhibition pavilion with a 600 m² enclosed
program, a courtyard, an accessible circulation route and three fixed presentation
cameras. The actual benchmark input must freeze dimensions, site boundaries,
program areas/tolerances and a small set of design constraints before execution.
A supplied real competition brief can replace this fixture before approval.

## Stages and evidence

| Stage | Work | Required output and pass condition |
| --- | --- | --- |
| 1. Brief | Extract requirements and unresolved questions | Exact brief and source manifest; measurable constraints; ambiguity surfaced before modeling |
| 2. Research | Submit the approved question in the user's Perplexity account | Account-visible conversation URL, saved transcript, source URLs and dates; citations checked against sources; no silent provider substitution |
| 3. Synthesis and concepts | Summarize research and propose two concepts | Research-to-design rationale and two concept descriptions; distinguish sourced facts from design choices; record the selected concept |
| 4. Model v1 | Build the selected concept through an agent and registered Blender host execution | Editable native scene, generation script, three camera previews, geometry/program checks and independent reopen receipt |
| 5. Model revision | Apply one bounded change to that exact scene | Candidate v2, matching before/after views and machine-readable differences; preserve the original, site footprint, courtyard and cameras; use only the declared change |
| 6. Final imagery | Produce final views from v2; optionally enhance one through image generation | Native render plus separately labeled AI visualization; image worker receives exact v2 preview bytes; neither AI imagery nor visual plausibility substitutes for geometry checks |
| 7. Presentation | Assemble an editable eight-slide PowerPoint deck | Brief, research, concepts/selection, geometry, revision comparison, final views and sources; render every slide for inspection; verify images and labels use v2 |
| 8. Delivery | Deliver files and status through the chosen channel | Native v2 scene, final images, editable deck, slide previews and manifest with descriptive versioned names; delivery receipts and correctly routed replies |

Suggested controlled revision: raise the courtyard-facing roof edge by 1 m while
preserving the footprint, courtyard opening, other roof-edge heights and cameras.
The selected modeling approach must make these properties explicitly checkable.

## Bounded execution contract

Before a live run, freeze the actual brief, provider/account routes, input versions,
model profiles, numerical checks, output names, time/tool/token or cost budgets and
the approval needed for any prepared host Python. Defaults for plan preparation:
two concepts, one selected model, one revision, three fixed cameras, at most one
AI visualization and one eight-slide deck. No open-ended improvement loop.

The plan must expose concept selection and final review. Exact script preparation
may require a separate approved host-execution stage under the existing contract.
Do not claim those future script bytes are approved by approving a research plan.

Use an isolated benchmark project. Keep all real workers, requests, intermediate
versions and receipts observable from Relay status. A missing capability, account
login, quota or dependency produces a specific blocker. Uncertain website/model
submissions are observed before any retry. No automatic backend substitution or
retry-budget expansion.

## Integration failures to detect

- Research transcript or cited source never reaches the concept worker.
- Design requirements disappear between concept and geometry assignments.
- Revision receives a conversation summary instead of the selected native model.
- Final image or deck uses v1 after v2 was selected.
- Review accepts geometry from an attractive AI visualization alone.
- A downstream stage runs before its required selection or remains disabled afterward.
- Service restart duplicates a website submission or worker attempt.
- An expired login, timeout or provider failure is described as completed work.
- Attachments are absent, generically named, mislabeled or bound to the wrong reply target.

Keep deterministic negative/recovery tests alongside the live benchmark. Induce
failures in controlled transports; do not intentionally create uncertain paid
submissions merely to exercise recovery.

## Current gaps and completion gate

Registered Blender operations and exact production-preview reuse have controlled
coverage; Blender operations have real-host qualification. Perplexity's dedicated
account driver has not been qualified as this pipeline's live research stage.
General browser workers are a separate scoped execution route, not proof that the
Perplexity account flow works. Presentation authoring can be performed by a suitable
agent, but a frozen authoring/render/check contract and native file delivery still
need integration qualification. PowerPoint is the initial deliverable; native
Keynote and Google Slides are additional adapter/account qualifications.

Completion requires one recorded live run from brief to delivered presentation,
with the bounded revision incorporated and independent checks passed. Report
provider usage, wall time, human interventions and failed/recovered stages. A
passing run establishes that exact route and scope, not general design quality or
support for arbitrary architectural competitions.
