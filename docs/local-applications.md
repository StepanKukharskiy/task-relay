# Local application execution

Direct Rhino 7/8 support uses the same production/approval paths through
`rhino.startup`, `rhino.inspect`, `rhino.run_python` and `rhino.render`. See
[Rhino setup, modeling and qualification](rhino.md). Grasshopper support is paused.

Run the [Blender pipeline qualification](blender-qualification.md) with
`python3 scripts/qualify_blender.py --host` to check all registered operations and
the planning/review/delivery connections using isolated fixtures.

Blender now has seven registered **host operations**. Six run fixed Relay code;
`blender.run_python` adds separately approved host Python. Blender runs with normal
OS permissions, outside the agent shell sandbox. Agents retain
their existing permissions. The proposed stage explicitly displays host execution;
starting it authorizes only its declared inputs, outputs and limits.

- `blender.startup` runs one fixed startup probe and saves
  `delivery/execution.json` with command, exit status, captured streams, marker,
  elapsed time and host details. A crashed probe is a completed diagnostic report,
  not a successful Blender startup. Maximum 120 seconds, one attempt.
- `blender.inspect` opens one exact registered `application/x-blender` version with
  embedded auto-execution disabled. It inventories objects, mesh counts/transforms,
  materials, cameras, frame/render settings, dependency references and embedded text
  hashes. It saves `delivery/inspection.json` and `delivery/execution.json`, with
  source identity and unchanged-copy verification. Maximum 120 seconds, 100 MB
  inputs, 5,000 objects and 2 MB outputs; no truncated inventory is accepted.
  This uses host permissions: linked libraries may resolve during opening. It does
  not isolate dependency access or create a portable asset bundle.
- `blender.run_python` edits a selected scene using an already registered script
  and verification contract. It returns `candidate.blend`, `before.png`, `after.png`,
  `edit.py`, `checks.json` and `execution.json` under `delivery/`. Each script, scene
  and checks hash is fixed before approval. Maximum 600 seconds, 100 MB inputs and
  100 MB declared outputs; previews use CPU Cycles, 64–1024px and 1–16 samples.
  This is explicitly approved **normal host Python**, with filesystem/network access.
  Time/output limits and embedded-script suppression do not provide OS isolation.
- `blender.import_asset` stages exact selected `.blend`, PNG and JPEG versions in
  the relative layout declared by an asset manifest. It packs file-image dependencies,
  optionally binds a selected image to an existing named material Image Texture node,
  and appends exact named mesh objects from selected libraries. It returns a packed
  `candidate.blend`, `preview.png`, `bundle.zip`, `manifest.json`, `checks.json` and
  `execution.json` under `delivery/`. The source bundle retains paths, hashes and
  supplied provenance/licenses; unknown licenses remain unknown. No download or
  persistent library link occurs. Bounds: 30 files, 30 import instructions, 100 MB
  inputs/outputs, at most 50 MB uncompressed bundle contents, 600 seconds and a
  64–1024px CPU preview. Newly packed file textures are limited to 16 megapixels.
- `blender.scene` consumes exactly one `application/json` primitive scene input,
  builds the scene, saves it, then reopens it in a separate Blender process to check
  object count/transforms and render on CPU. It produces `delivery/scene.blend`,
  `delivery/preview.png`, `delivery/scene-script.py` and `delivery/execution.json`.
  Maximum 600 seconds, 100 MB declared outputs, one attempt.

- `blender.mesh_scene` accepts a version-2 scene with agent-computed triangle/quad
  meshes, optionally mixed with primitives. The agent can write its own geometry
  algorithm inside its sandbox; the reusable host operation converts the numeric
  data to Blender objects. It uses the same four output paths and 600-second/100 MB
  output bounds, with at most 100,000 vertices, 200,000 faces across all meshes and
  20 MB of input. Primitive-only version-1 plans remain unchanged.

All operations accept additional request/context inputs as text. The source
hashes and implementation hashes are retained with the assignment. An exclusive
execution intent prevents replay. Failed scene builds do not trigger rendering,
retry the original task, reset attempt budgets or switch executors. Partial
outputs and failure receipts remain available. Supervisor cancellation terminates
the local process group on the currently supported macOS host.

## Asking Relay

“Animate the selected tower through 90 degrees over 24 frames at 12 FPS and return
an editable scene and video” uses `blender.animate`. An agent prepares the numeric
manifest if needed; the render stage selects that exact manifest and scene. It
returns a native candidate, MP4, PNG preview and resumable frame receipts. See
[animation, rendering and recovery](blender-animation.md) for limits and setup.

“Inspect this selected Blender scene before editing it” should select
`artifact_ids` for the exact registered native artifact and
`step_capabilities:["blender.inspect"]`: host inspection and independent review.
If the version is absent or ambiguous, Relay needs the selected file first.
Inspection does not perform an edit. Agent-authored Python editing, asset imports,
animation and UI control are ordered in [B01–B05](../ROADMAP.md#additional-implemented-capabilities).

“Make Roof 30% taller, preserve cameras/materials/other objects, and save a new version”
uses two stages. First an inspector and agent prepare `edit.py` and `edit-checks.json`
for independent review. Then a separate plan selects those exact artifacts and the
native scene. Relay delivers the complete script/checks, discloses host permissions,
and requires Start on that specific plan. The approval commits atomically with run
registration; host dispatch happens later. Scripts produced by future tasks cannot
be inputs to this host operation. A changed hash, assignment, executable or execution
implementation requires a new approval. The resulting candidate is reviewed and
waits for selection; saving a version never selects it automatically.

The initial editing contract preserves object names, collections and active frame;
permits declared existing objects to change; checks declared final dimensions; and
preserves other objects, cameras and materials within its recorded snapshot scope.
Mesh vertices/topology/UVs, transforms, scalar modifier/constraint/camera settings,
and material/node/socket values are compared. This is not full Blender semantic
equivalence. Self-contained scenes with packed/generated assets are supported;
known unpacked dependencies, linked libraries and populated sequence editors stop
execution. B03 now provides a separate import/packing stage that can produce a
self-contained input for this editing operation. Animation, general object additions/removals,
full Geometry Nodes/simulation verification and interactive UI are not qualified.

“Use these textures and append Chair from this library into my scene” first needs
an exact asset manifest. An agent can prepare/review it using `asset_schema` in the
operation catalog. The execution plan selects the manifest and every source version;
Relay sends the complete manifest before Start can approve the import. The six outputs
go to independent review and a candidate selection gate. No future unselected files
can enter this operation. Candidate creation never changes the selected project scene.

Bundle paths preserve the scene's original relative dependency layout. Unselected
or absolute external references are rejected rather than guessed/remapped. Known
live library links, Geometry Nodes, simulation caches, non-image dependencies and
external shader scripts are outside this version. A local append may leave library
bookkeeping; Relay clears it only after confirming no datablocks reference a library.
This is not a filesystem sandbox or a complete audit of every Blender extension.

“Check Blender startup” should select `plan_production` with
`step_capabilities:["blender.startup"]`: host probe then independent report review.

“Make a twisting tower in Blender and send the model and preview” should select
`step_capabilities:["blender.scene"]`: scene-data producer, its reviewer, then host
scene execution (dependent on that review), optionally followed by a scene-output
reviewer. The user still selects the creative result. Each stage uses the existing
plan approval and durable production status/delivery mechanisms.

For unfamiliar modeling, such as a gyroid, parametric sculpture or custom surface,
use `step_capabilities:["blender.mesh_scene"]`: agent computes geometry and saves
version-2 scene JSON plus its generator/checks; a reviewer checks that data against
the request; the host operation saves/reopens/renders it; the user selects the result.
The host verifies mesh counts, coordinates and face indices after reopening, as well
as object transforms. Model-specific properties (e.g. a printable, closed solid or
wall thickness) belong in the agent/reviewer criteria, not an assumed renderer check.

Version 2 has the same camera, transforms, colors and render settings as version 1.
A `shape:"mesh"` object additionally carries `vertices:[[x,y,z],...]` and
`faces:[[i,j,k],...]` (triangles/quads). Unknown fields, expressions/scripts, nonfinite
coordinates, invalid/repeated indices, zero-area triangles and over-budget geometry
are rejected before Blender starts. Open surfaces are allowed and not called solids.

The original primitive scene format supports 1–500 cubes/cylinders with numeric positions,
sizes, rotations in radians, RGB colors, an orthographic camera, a sun light and
CPU rendering at 64–1600 pixels per dimension and 1–32 samples. Towers can be built
from rotated storey objects. The exact schema is exposed in the operation catalog.

```json
{
  "version": 1,
  "objects": [{"shape":"cube","position":[0,0,1],"size":[1,1,2],
               "rotation":[0,0,0.3],"color":[0.2,0.4,0.8]}],
  "camera": {"position":[6,-8,5],"target":[0,0,1],"scale":5},
  "resolution":[640,640],
  "samples":16
}
```

Arbitrary Python, imported `.blend` files, external assets, addons and expressions
are not inputs to this operation. Unsupported modeling work needs a suitable
existing desktop task with its approval flow. A request for arbitrary script
execution must not silently become primitive modeling. No unrestricted agent
shell mode or application installation is added.

## Discovery, diagnosis and evidence

`host_apps.py` discovers Blender via an explicit absolute `TASK_RELAY_BLENDER`,
PATH, the macOS application bundle or Windows Program Files. A bad explicit
setting does not fall back. Executable presence is not startup qualification.
Windows/Linux discovery is tested with fixtures; native host execution was checked
on macOS. Broader supervisor portability remains separate work.

Execution evidence is now grouped by environment. `agent_shell.historical_failures`
cannot establish `registered_host` failure. Host evidence comes from typed execution
receipts, including explicitly imported controlled checks. A matching receipt binds
the executable's path/stat identity, Blender adapter/script hashes and a 24-hour
freshness window. Missing, stale or changed evidence is `unverified`, not `failed`.
A completed diagnostic with a failed startup marker remains a **failed startup**.
Checks are observations, never a guarantee for a later job or automatic acceptance.
