# Blender pipeline qualification

Run from the source checkout:

```sh
python3 scripts/qualify_blender.py --host
```

This runs the controlled regression suite and real local Blender/ffmpeg workers.
It does not use provider credentials, start paid model calls, contact a messaging
service, or change existing productions. The reviewed Python executed by the host
phase is the fixed synthetic edit in `tests/test_blender_pipeline_live.py`.
Run in the normal registered host environment: an agent sandbox is not equivalent
and can prevent Blender startup or supervisor process inspection.

Without `--host`, only controlled checks run. For a focused rerun after a failure,
use `--host --only host` or `--only controlled`. `--output PATH` chooses a **new**
evidence directory; an existing directory is rejected. Failed attempts are never
reused or overwritten.

`--host --only host --case test_08_chat_plan_start_review_resume_and_delivery`
runs the self-contained channel scenario alone. Other host cases may require
earlier fixture outputs; a missing dependency is reported as an incomplete run.

## Coverage

| Operation or path | Real host qualification | Controlled failure/recovery coverage |
| --- | --- | --- |
| `blender.startup` | Startup marker and exit status through the registered supervisor | Crash, timeout, no replay |
| `blender.scene` | Cube and cylinder; transforms, material color, camera, render settings; save/reopen/render; revised height rendered separately | Invalid/missing fields, version, vectors, count, camera and numeric bounds; frozen runtime drift |
| `blender.mesh_scene` | Explicit mesh vertices/faces, save/reopen/topology checks/render | Invalid/degenerate geometry, index/type/finite checks and aggregate budgets |
| `blender.inspect` | Exact generated scene, inventory and unchanged source | Missing/changed inputs, interrupted execution and bounded inventory |
| `blender.run_python` | Exact approved script doubles one object; other objects/camera/materials preserved; before/after previews and independent reopen | No approval, changed script/assignment, cancellation, uncertainty, crash/timeout and preservation failures |
| `blender.import_asset` | Append named mesh into collection; bind PNG and JPEG to existing image nodes; pack, relocate and reopen bundle | Wrong hashes/types, missing files, unsupported links, path traversal/collisions, source mutation and extraction checks |
| `blender.animate` | Preview with location/rotation/scale tracks; encoded frames/FPS; final mode with existing animation; confirmed checkpoint reused without rendering frames again | Numeric/quality/track limits, partial checkpoint continuation, unresolved frame intent, tampering and no replay |
| Connected runtime | Data producer → reviewer → host render → reviewer → selection → inspection; immutable baseline and second render; controller restart and repeated ticks | Missing baseline/schema, type/dependency compilation, attempts and source-version checks |
| Chat to delivery | Relay chat handler → saved planner response → Start → data review/selection → automatic scheduler resume → real render/review → native file and image outbox delivery → reply context | Duplicate/foreign clicks, delivery-before-selection, lifecycle/status controls and exact artifact routing |

The data producers, reviewers, planner responses and Telegram transport are
**deterministic fixtures**. Host operations, supervisor processes, SQLite state,
planning validation, callbacks, scheduler and delivery handlers are real. The
suite does not qualify live model judgment, Telegram network delivery or Messages
on this run. It cannot establish that every natural-language request will be
interpreted correctly.

Every registered Blender capability and its current version/parameter names must
have a coverage entry; the controlled suite fails when that catalog changes.
Small native scenes and three-frame clips keep this practical to run repeatedly.
Upper/lower numeric bounds are validated without rendering maximum-size jobs.
This is supported-mode and boundary coverage, not an exhaustive cross-product or
maximum-load benchmark. Interactive UI, simulations and unsupported import
formats are outside the implemented registry.

## Evidence and release use

Each run retains `report.md`, `report.json`, per-phase test logs, source hashes,
the operation registry, isolated databases, frozen assignments, process receipts
and native outputs under `outputs/blender-qualification/`. Host failure skips are
reported as incomplete and return nonzero, rather than making a dependency failure
look like a successful qualification. A channel receipt identifies the simulated
transport explicitly. No synthetic result counts as user acceptance of a real job.

Run this check before qualifying changes to Blender contracts, planning handoff,
execution, review/resume or delivery. Inspect the failing phase/test and its saved
`delivery/execution.json` or worker receipt before retrying. Fix the cause and run
a new qualification; do not clear evidence or reset a user's attempt budget.
Results apply to the recorded OS and Blender version only.

Image-generation reuse of a finished preview is covered separately by
`python3 -m unittest tests.test_orchestrator_images`: it verifies the exact binary
reference in the Gemini request without paying for a generated image.
