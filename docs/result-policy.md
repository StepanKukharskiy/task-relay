# Shared result policy

Execution success and user satisfaction are separate decisions. Workers report
typed findings with a category, stable code, explanation and concrete evidence.
The scheduler owns the disposition; providers do not choose whether to bypass it.

| Finding | Relay behavior |
| --- | --- |
| Quality: usable output differs from the requested design, appearance, optional content or measured geometry | Preserve files and previews; ask for user feedback or acceptance of these exact outputs; hold dependent production work |
| Execution: code/tool failed | Block; retain the failure receipt and partial files for diagnosis |
| Integrity: missing/corrupt files, invalid measurements or mismatched source identity | Block; do not offer quality acceptance as a substitute |
| Authorization: action exceeded or lacks permission | Block until properly scoped and approved |
| Uncertainty: submission outcome cannot be established | Reconcile before further execution; never automatically replay |
| No findings and valid procedural checks | Continue under the approved plan and any existing user decision gates |

Examples: a terrain's measured size differing from its design target, a cropped
slide image, or a missing optional plant photo can be quality concerns. A Python
exception, corrupt 3DM, unmeasurable required source comparison, unauthorized edit
of preserved geometry, or unknown external submission cannot be accepted through
that gate. Missing required deliverables remain blocking; optional omissions must
be declared honestly. Source requirements are retained even if a user accepts a
measured discrepancy.

The core validates files, hashes, host execution and required evidence before it
considers worker findings. A reviewer can add concerns but cannot erase previously
recorded concerns by returning a clean acceptance. Native adapters report size
measurements; the shared scheduler applies the user gate. Independent read-only
inspection may run to supply review evidence, while consuming production steps
wait for acceptance.

The acceptance card binds the current attempt, all its declared outputs, their
hashes and findings. Delivery, a status request, or AI acceptance is not user
acceptance. Old cards cannot accept a revised attempt. The acceptance receipt
retains the concerns and never changes a measured failure into a conformity claim.

Correction feedback follows the existing revision contract and attempt limits.
For Rhino/Blender quality feedback, Relay prepares a scoped correction proposal
from the exact sources and review evidence. Preparation and independent review
come before a fresh exact-code execution Start. No native script is replayed by
accepting feedback. Other capabilities retain their existing revision/recovery
paths; this policy is not a claim that every failed tool can repair itself.

Legacy saved reports without findings remain readable. Legacy failures are not
rewritten or automatically accepted. Controlled tests cover scheduler decisions,
artifact identity, feedback proposals and receipt display; they do not certify
every provider's ability to judge visual quality or a live CAD execution.
