# Reusable procedures from completed workflows

Development source adds a first O08 implementation: extract a completed Relay
workflow, review its project variables, and prepare a fresh run of that exact
procedure version. This is not included in the published 0.13.0 beta download.

Use `/opportunities` to find candidates across recorded requests and workflows.
See [automation opportunities](automation-opportunities.md) for matching rules,
supporting evidence, measurements and promotion into a reviewed procedure.

## Use in Telegram or Messages

1. Finish a saved workflow, including its required selections. Ask Relay:
   “Save workflow WORKFLOW_ID as a reusable procedure. Make the location and
   brief path variables.” If the workflow is older than the current examples,
   use `/procedures source WORKFLOW_ID` to inspect its original request and stages.
2. Relay proposes a template with `{{location}}`, `{{brief}}`, or other named
   variables. Inspect the complete request, stage instructions, outputs and
   retained constants. Literal substitutions are case-sensitive. Saving a draft
   starts no work. Unknown, duplicate or unused examples are rejected. A location
   may also appear within a separately parameterized path; the full path wins there.
3. Send `/procedures approve PROCEDURE_ID` to approve that exact immutable version.
   `/procedures` lists versions; `/procedures PROCEDURE_ID` displays one in full.
4. Ask “Run PROCEDURE_ID with location Iowa and brief briefs/iowa.txt.” Supply
   every variable explicitly. Examples never become defaults. The configured
   orchestrator interprets saving/running; listing and approval need no model.
5. Review the expanded workflow and bound request, then choose **Resume workflow**.
   Relay uses the ordinary pipeline scheduler. It continues after completed
   stages and explicit selections. Native code still requires its exact **Start**.

Each run has a new workflow ID and normal workflow folder. Its `manifest.json`
records the procedure version, SHA-256, parameter values and bound brief alongside
the exact new user request. Later stages receive the exact outputs of this run.
New research, model scripts, renderings and documents are produced within that
run's scope. Prior output identities cannot remain implicit template inputs.

## What is learned

Extraction retains the completed workflow's ordered stages, routes, operation
IDs, declared deliverables and choice/selection gates. It substitutes only exact
literal examples in the request, title, stage instructions and deliverable
descriptions. It does not ask a model to invent replacement execution code.

Original requests, source specification, completion/decision receipt fingerprint,
procedure drafts and approval requests remain recorded. Changed source receipts
invalidate draft approval. Editing variables or extracting again creates a new
content-addressed version; existing approvals and runs remain unchanged. Completed
reuse runs are counted separately from the original example. A completed run is a
workflow receipt, not evidence that the design generalizes to every new project.

Past artifact selections, rendered output, scripts, host approvals and recovery
attempts are not transferred as execution authority. The existing planner checks
current operations and tool availability. Failure recovery uses the normal saved
workflow rules; it cannot silently revise a procedure or replay uncertain work.
Versions are scoped to their original channel. Queue, run binding and receipts are
committed together before any worker dispatch.

This first version does not record desktop demonstrations, infer arbitrary GUI
actions, optimize procedures against a reusable-script baseline, or certify
cross-project creative quality. Those remain O08 follow-up work.

## Website workflow audit

The five website starters exist in `task_relay/workflow_library.py`. They describe
useful stage sequences; the pipeline scheduler and registered operations provide
execution. A starter does not install tools or establish account access.

| Website workflow | Implemented building blocks | What Relay can automate | Remaining dependency or boundary |
| --- | --- | --- | --- |
| Research → evidence → report | Managed Perplexity search, read-only web research, file workers | Research, source ledger, reviewed report and stage handoff | Report export such as DOCX/PDF needs a worker with the relevant libraries; source quality needs review |
| Architecture → model → visualization → presentation | Request-derived pipelines, Blender/Rhino host operations, reference-image generation, `pptx.create` | Research/concept preparation, model-code preparation and review, native execution, visualization and editable deck | Concept/output selections and exact native-code Start remain; licensed apps and configured providers required; AI visualization fidelity needs review |
| Native model → revision → checked candidate | Registered inspect and Python execution operations for Blender/Rhino | Inspect exact source, prepare/review an edit, execute approved code, reopen/check candidate | Requires exact input model, installed application and host-code Start; original model is preserved |
| Approved carousel → reel → review | File/media workers and adaptation starter; separate video-generation adapters | Adaptation brief, asset correspondence, composition/render work through a qualified media worker | No dedicated carousel-to-reel executor; a video model alone does not assemble a faithful editable reel. Renderer/audio tooling must be available |
| Data → analysis → charts → presentation | File/code workers and editable PPTX text, tables and charts | Reproducible calculations, chart preparation, reviewed slide specification and deck creation | Analysis is worker-authored, with relevant data libraries; there is no universal spreadsheet-analysis operation |

The architecture starter now includes optional visualization, with the exact
selected viewport as its input. Raw `.3dm`/`.blend` files do not become image or
PPTX inputs. Single-stage starter requests keep their existing scope. Full-workflow
requests use `plan_pipeline`, which advances after agreed work and decisions;
they no longer inherit the old blanket instruction to request every stage again.

Website source copy distinguishes these requirements. This audit does not claim
deployment, a new installer, live provider execution, or successful creative
qualification of all five workflows.

## Controlled validation

`python3 -B -m unittest tests.test_procedures tests.test_workflow_library tests.test_pipelines tests.test_messages_orchestrator tests.test_workflow_files tests.test_mixed_planning tests.test_channel_policy`

All 98 tests passed locally on macOS. Small text fixtures exercise extraction,
exact approval, fresh-project continuation and choices, one-pass parameters,
old-output exclusion, immutable versions, missing inputs, current operation
validation, atomic rollback, duplicate requests, channel isolation and file-manifest
provenance. Existing pipeline tests cover native approval and recovery contracts.
Website HTML parsed and the whitespace check passed. No live models, CAD apps,
rendering, messenger delivery, website deployment or app installation was tested.
