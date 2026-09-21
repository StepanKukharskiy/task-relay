# Rhino files and native Rhino integration

## Full standalone library API

`rhino3dm.run_python` runs the exact reviewed Python script against the full
installed `rhino3dm` Python API. Relay does not whitelist geometry classes or
modeling methods. Scripts can create or edit NURBS curves/surfaces, BReps,
extrusions, meshes, annotations, blocks, document tables and any other feature
exposed by the pinned library. This is library access, not every command or plugin
available inside the Rhino application.

The script receives `rhino3dm`, `model` (a new `File3dm` or the selected primary
source file), `input_paths` (declared relative paths mapped to staged absolute
paths), and `workspace`. Modify `model` or replace it with another `File3dm`.
Relay saves it after the script returns. For example:

```python
r = rhino3dm
model.Settings.ModelUnitSystem = r.UnitSystem.Meters
attributes = r.ObjectAttributes()
attributes.Name = "Sphere"
model.Objects.Add(r.Sphere(r.Point3d(0, 0, 0), 2).ToBrep(), attributes)
model.Strings["purpose"] = "Standalone library model"
```

Its selected checks can request Rhino 7 format:

```json
{
  "version": 1,
  "mode": "create",
  "file_version": 7,
  "expected_units": "Meters",
  "expected_object_count": 1,
  "required_objects": ["Sphere"],
  "preserve_objects": [],
  "expected_dimensions": {"Sphere": [4, 4, 4]}
}
```

`file_version: 7` writes a Rhino 7 archive; `8` writes a Rhino 8 archive. Supported
explicit targets are 2 through 8, as provided by this library. The installed
library version (`8.35.0`) is distinct from the target file version. Rhino 7-format
writing does not require Rhino 7 to be installed and does not run its IronPython
interpreter. McNeel documents [target file versions](https://mcneel.github.io/rhino3dm/python/api/File3dmWriteOptions.html)
and the [standalone library API](https://developer.rhino3d.com/guides/opennurbs/what-is-rhino3dmio/).
Objects/features that change when saved to an earlier version are not silently
accepted: object serialization differences require explicit user review, while
missing/invalid geometry or failed declared preservation blocks the result.

Preparation copies the catalog contract and a dependency-free syntax/schema
validator under `operation-support/rhino3dm.run_python/`. Independently review and
select `model.py` and input checks together; a separate Start approves those exact
registered versions, optional primary source `.3dm`, all other inputs, runtime
identity and limits. Unknown future scripts cannot be executed under a preparation
approval. Additional binary assets or models use `application/octet-stream`;
the single `application/vnd.rhino` input identifies the primary edit source.
Source-derived work retains the existing source-fidelity review policy.

Approved Python has normal host filesystem/network permissions, not an OS sandbox.
The runner does not launch Rhino; script authors/reviewers must preserve the approved
scope. External services, native app actions and paid work require their own scope.
The Python executable, library version/package bytes and Relay implementation are
bound to approval, and fresh phase workers recheck that runtime identity.

Relay uses separate processes for source inventory, script execution and candidate
reopening. Verification checks geometry/attributes, archive version, declared
object counts/names, preserved source UUIDs, units/tolerance and document strings.
Geometry/attribute serialization differences and dimension deviations are quality
findings requiring user review. Other document tables, opaque plugin data and
external dependencies need task-specific review; a valid file does not prove
semantic or visual equivalence. Library checks never claim native Rhino verification.

Outputs are `delivery/candidate.3dm`, `delivery/model.py`, `delivery/checks.json`
and `delivery/execution.json`. Receipts record `execution_mode: standalone_library`,
`native_application_execution: false`, `native_rhino_verified: false`, the file
version and runtime identity. `host_execution: true` describes the script's normal
host permissions, not a Rhino application launch. Failures retain exact scripts,
inputs and diagnostic artifacts; confirmed failures can propose reviewed repairs,
with a new exact-code Start. Timeouts/missing execution receipts require
reconciliation and never authorize automatic replay.

Controlled fixtures have written and reopened Rhino 7/8 archives using the library.
Opening those fixtures in the native Rhino 7/8 applications is not claimed.

## Standalone convenience builder

`rhino3dm.create` is a separate local procedure that creates a new `.3dm` using
McNeel's `rhino3dm` library, without opening or connecting to Rhino. Use it for
points, polylines and triangle/quad meshes (including terrain), with named objects,
layers, RGB layer colors, units and document tolerance. It accepts bounded geometry
JSON, never arbitrary Python or an existing model. NURBS construction, Rhino
commands, booleans, plugins, previews and renders remain outside this operation.
Use `rhino3dm.run_python` for the full library API, including NURBS and edits.
Do not substitute a mesh when the request specifically requires NURBS.

The worker requires `rhino3dm==8.35.0`. Source installations can install
`task-relay[rhino3dm]`; the desktop runtime dependency manifest includes the pinned
wheel for future builds. Missing or mismatched dependencies block this operation
without launching Rhino or installing packages from a worker task.

Select `rhino3dm.create` in the planning scope. The planner receives the catalog's
`geometry_schema` and copied dependency-free validation files under
`operation-support/rhino3dm.create/`. Prepare and independently review geometry
JSON before the procedure runs. The actual model and its receipts also need an
independent review and explicit user selection. A format-only `.3dm` request can
use this route if its supported geometry meets the request. Explicit native Rhino
execution or verification retains the native route. Changing an existing approved
`rhino.*` stage requires a new reviewed plan and Start; there is no fallback.

For example, a tiny terrain specification is:

```json
{
  "version": 1,
  "units": "Meters",
  "tolerance": 0.001,
  "layers": [{"name": "Terrain", "color": [70, 120, 65]}],
  "objects": [{
    "type": "mesh", "name": "Ground", "layer": "Terrain",
    "vertices": [[0, 0, 0], [10, 0, 1], [10, 10, 2], [0, 10, 0]],
    "faces": [[0, 1, 2], [0, 2, 3]]
  }]
}
```

Declared outputs are `delivery/candidate.3dm`, `delivery/checks.json` and
`delivery/execution.json`. The saved version-8 model is reopened with `rhino3dm`;
the verifier compares every point/vertex, face index, object name/layer, layer
color, unit and tolerance to the input data, and checks geometry validity. Meshes
use double-precision vertices. Coordinate comparison allows only numerical
round-off (`1e-12` relative, `1e-9` absolute), independently of document tolerance.
Receipts preserve input hashes, library version, implementation hashes, candidate
hash and `execution_mode: standalone_library`, with `native_rhino_verified: false`.

These checks establish library generation and reopening only. They do not establish
survey fidelity, design quality, visual acceptance or a successful Rhino session.
Add explicitly approved `rhino.inspect` or native modeling/rendering stages when
needed. Failure keeps diagnostic files and receipts, never accepts a partial
candidate, overwrites an earlier attempt or automatically retries.

## Native Rhino execution

Relay registers `rhino.startup`, `rhino.inspect`, `rhino.run_python` and `rhino.render` through the
existing production planner, exact artifact selection, review and delivery paths.
Grasshopper definitions, scripts, component execution and graph authoring are
paused. They have no registered operation.

## Verification failures and correction

A model can be saved successfully and still have quality concerns. Bounding-box
differences complete model/preview generation, then enter the shared **user review**
gate. Relay shows expected/measured XYZ, tolerance and units, and waits for explicit
acceptance of those exact outputs or correction feedback. A clean independent AI
review cannot waive that gate. The same policy applies to visual/design concerns
and independently measured source-geometry discrepancies. Invalid geometry,
missing required objects, incorrect units, preservation violations and missing or
invalid verification evidence remain failures. Execution errors do not become
quality warnings. See [shared result policy](result-policy.md).

The saved output `checks.json` is a measurement report, not the selected input
checks. A missing preview after failed execution does not mean modeling never ran.

For an old dimension-only failure, **Continue** can propose unchanged inputs with
the updated runtime and a fresh execution Start. The original failure stays saved.

For other confirmed terminal failures, **Plan correction** or **Continue** proposes
bounded preparation using exact source files, input checks, script and failure
outputs. This works before an independent native review has run. The proposal
cannot execute Rhino. Start preparation approves diagnosis and independent review;
selection and a separate exact-code Start approve execution of revised files.
Original artifacts and attempts remain unchanged. Uncertain submissions must be
reconciled first and never enter this path.

A correction may propose evidence-backed changes to mistaken input expectations,
but must not relax checks merely to accept a defective model. The original geometry
basis and source-fidelity metrics remain part of the review contract. A failed
candidate is diagnostic evidence, not a replacement survey or design source.

## Host setup

The macOS adapter selects Rhino 7 (IronPython 2.7) or Rhino 8 (CPython 3), with a
usable license and desktop session. Set `TASK_RELAY_RHINO_VERSION=7` to select
Rhino 7 explicitly. Without a selector, discovery prefers installed Rhino 8,
then Rhino 7. `TASK_RELAY_RHINO` can select an exact executable absolute path.
Discovery reads the application bundle version without launching it. An invalid
selector, override or mismatched version does not fall back. Other major versions,
Windows and Linux remain unavailable through this adapter.

After installing integration changes, restart the Relay service when no work is
executing. A long-running service retains its imported operation registry even
when the checkout has newer code. The `health:orchestrator-chat` heartbeat records
`process_id` and `registered_graph_operations`; verify a fresh heartbeat from the
new process containing all four `rhino.*` operations. These IDs establish that
the worker loaded the integration; host discovery separately checks installation
availability. A standalone catalog check does not establish what the running
service loaded. Existing responses retain their original capability snapshots.

When Rhino 8.11+ is open, Relay uses its bundled `rhinocode` connection and
runs modeling/inspection in separate headless documents. The script server must be
active (`StartScriptServer` in Rhino); if unavailable, Start explains the missing
connection without spending an execution attempt. It selects the exact application's
PID, never an arbitrary Rhino. Rhino 7 retains the exclusive-process path and must
be closed before Relay starts it. Windows coexistence is not qualified.

Shared-session previews/rendering open only task workspace copies, close only those
owned windows, and restore the Python document context. Your existing documents
stay open. Rhino's interface can be busy during execution; this is document separation,
not a separate process or a security sandbox. Approved scripts must use assigned
`doc`/`scriptcontext.doc`, not global documents or application exit commands.

RhinoCode returns its submission acknowledgement before the script finishes. Relay
waits for a matching PID/token/phase result. Shared operations are serialized, and
an unresolved submission prevents another dispatch. Cancellation/timeouts stop only
the command-line client, never the existing Rhino; the script may still be running.
An identity-bound terminal receipt is required to release an uncertain session.
No resubmission, application shutdown, or automatic acceptance occurs.

When Rhino is closed, the adapter launches its executable with `-runscript`:
`_-RunPythonScript` on 7 or `_-ScriptEditor _Run` on 8. Each phase gets an owned
process and PID/token handshake. A forwarded command cannot model or exit another
process. Only these owned workers exit via the macOS native-exit adapter after
closing their artifacts and receipt. No additional plugin is installed.

The connection uses McNeel's [RhinoCode CLI](https://developer.rhino3d.com/guides/scripting/advanced-cli/)
and [headless documents](https://developer.rhino3d.com/api/rhinocommon/rhino.rhinodoc/createheadless).

These operations use normal host permissions. Native file dependencies/plugins
may access the host when a file opens. Approved Python has filesystem and network
access; input/output limits are not a sandbox. Use assigned `doc` and
`scriptcontext.doc`, not an unrelated open document. Scripts must not prompt for
interactive input. Uncertain or interrupted assignments are never replayed.

## Operations

Plans scoped to `rhino.run_python` or `rhino.render` attach frozen support files
under `operation-support/<operation>/` to agent preparation and review assignments:
`contract.json`, `rhino_contract.py`, and `validate.py`. Run
`python3 operation-support/rhino.run_python/validate.py delivery/checks.json delivery/model.py`
for modeling checks, or use the render support directory for its manifest.
These copied validators require only the Python standard library. They validate
JSON structure and script byte bounds; actual geometry still requires host execution and
independent reopen checks. Both workers receive the same exact contract version.
Existing blocked assignments keep their original inputs and attempt limits; a
new bounded stage is needed to repair a draft produced without the contract.

Script preparation declares `selection_outputs` on the producer, listing the
related script/checks paths (and render-manifest draft, if present). Each member
must be independently reviewed. The user sees one explicit **Select set** choice;
every member must finish delivery before the choice records all artifact versions
in one transaction. The next stage carries the complete selected set, while host
code still requires its own exact approval. Historical drafts with identical
bytes remain context; executable inputs bind the selected artifact IDs.

Prepared host scripts must be at most 100,000 UTF-8 bytes. Collection rejects an
oversized selected script before independent review can release it. The same
bound is enforced again on the actual registered code before host authorization.
Rejected drafts and prior receipts are retained; correction creates a new version.
Status cards name pending deliverables and label the stage as preparation.
After selecting the reviewed set, **Plan execution** queues the remaining declared
operations with those exact inputs and the original request. Repeated clicks reuse
the saved plan. Its **Start** approval remains separate from file selection.

For a rendered model, save a named camera view in the modeling script and declare
it with optional `expected_named_views: ["Overview"]` in checks. Independent reopen
verification rejects a missing required view. The render manifest must reference
that existing view; viewport previews alone do not establish render readiness.

| Operation | Inputs | Outputs | Bounds |
| --- | --- | --- | --- |
| `rhino.startup` | Exact request/context text | `execution.json`, including actual startup success/failure | 120 seconds; 2 MB inputs; 200 KB outputs |
| `rhino.inspect` | One selected `.3dm` plus text context | `inspection.json`, `execution.json` | 120 seconds; 100 MB inputs; 5,000 objects; 2 MB outputs |
| `rhino.render` | One selected `.3dm` and exact render manifest JSON | `render.png`, `checks.json`, `execution.json` | 600 seconds; 100 MB inputs; 10 MB outputs; 64–1024 pixels per axis |
| `rhino.run_python` | Reviewed Python and checks JSON; optional selected `.3dm` | `candidate.3dm`, `preview.png`, `model.py`, `checks.json`, `execution.json` | 600 seconds total; 100 MB inputs/outputs; 100 KB script; one attempt |

All outputs live under the reserved `delivery/` directory. Native model media type
is `application/vnd.rhino`; script and checks input types are `text/x-python` and
`application/json`. Additional context inputs are text.

A failed startup can still complete a diagnostic report, but its receipt explicitly
records `passed=false`. A failed modeling/inspection operation is blocked and
retains evidence and partial files without accepting them.

## Modeling and editing

First prepare and independently review Python source and a checks contract. Then
propose a separate stage selecting those exact registered artifacts. Its parameters
bind `script_sha256`, `checks_sha256`, `scene_sha256` and
`permissions="unrestricted_host"`. A new model has no native input and
`scene_sha256=null`; an edit requires exactly one selected model and its hash.
Unknown future scripts cannot be approved by this operation. Rhino 7 scripts must
use Python 2.7 syntax and installed IronPython modules; Rhino 8 scripts use Python
3. The baseline phase compiles the script in the selected Rhino interpreter before
modeling. The application version is bound to approval and dispatch. Native output
is saved in the selected major version format.

The complete script and checks must be delivered before Start. Approval and run
registration commit atomically; host dispatch follows commit. Changed application,
code, inputs, contract or limits invalidate the approval. Native outputs require
independent review and a user selection gate. Saving does not select a candidate.

Example new-model checks:

```json
{
  "mode": "create",
  "units": "Meters",
  "changed_objects": [],
  "allow_additions": true,
  "expected_object_count": 1,
  "expected_dimensions": {"Tower": [2, 3, 4]},
  "preview": {"resolution": [512, 512]}
}
```

Example source compatible with both interpreters (the worker supplies `Rhino` and `doc`):

```python
box = Rhino.Geometry.BoundingBox(
    Rhino.Geometry.Point3d(0, 0, 0), Rhino.Geometry.Point3d(2, 3, 4))
attributes = Rhino.DocObjects.ObjectAttributes()
attributes.Name = "Tower"
doc.Objects.AddBrep(Rhino.Geometry.Brep.CreateFromBox(box), attributes)
```

For edits, use `mode="edit"`, preserve the original units, and list canonical UUIDs
of existing objects allowed to change or be deleted in `changed_objects`.
Unlisted objects must retain geometry and attributes. New objects require
`allow_additions=true`; the reopened model must have the exact expected count and
declared dimensions for uniquely named objects. Units, tolerance, layers, materials
and the documented named-view snapshot are preserved on edits. Materials compare
native colors, reflectivity, transparency, shine, refraction/glossiness, lighting
flags, name and user strings. They do not compare transient RDK archive bytes or
claim equivalence for arbitrary plugin material graphs.

The worker records a baseline, runs the approved script in another Rhino process,
saves a new file, and reopens it in another process for verification and preview.
Original registered files and attempt input copies are hash checked. The delivered
preview is a shaded viewport capture of the saved candidate, not a production
render. Resolution is bounded to 64–1024 pixels per axis.

For a flat drawing, save a Top orthographic named view and set
`preview: {"resolution": [1024, 832], "named_view": "FacadeSheet"}` in checks.
The reopened file must contain that view; capture restores its camera without
replacing it with the default angled view or reframing it. Omitting `named_view`
retains the existing shaded parallel-perspective preview for 3D work.
Size drawing annotations for the declared preview resolution and inspect the captured
PNG during independent review. Text that exists in the native file can still be
unreadable in a small preview; geometry checks alone do not establish legibility.

Model scripts receive a headless document, so `doc.Views.ActiveView` is unavailable.
The frozen contract includes `named_view_example`: create a standalone
`Rhino.Display.RhinoViewport`, set its projection, size and bounding box, wrap it
in `Rhino.DocObjects.ViewInfo`, and add that record to `doc.NamedViews`. A saved
camera does not require a live modeling viewport.

Blocks/references, external textures and detected custom object user data stop
modeling. Inspection can report them, but it does not package dependencies. The
preservation checks cover geometry/attributes and selected document settings;
they do not establish full equivalence for every Rhino plugin, render setting,
layout, annotation or metadata field.

## Native rendering

`rhino.render` opens one exact selected model and renders an existing named view
through built-in Rhino Render. The manifest must already be registered; its
SHA-256 is the `manifest_sha256` parameter. The complete manifest is delivered
before Start, and the resulting image requires independent review and selection.

```json
{"version":1,"engine":"rhino_render","named_view":"Overview","resolution":[320,240]}
```

Materials, lighting and render quality come from the selected model. Third-party
renderers and dependency packaging are outside this operation. The worker verifies
the saved PNG dimensions/hash and unchanged source; it never falls back to a shaded
capture when rendering fails. It does not save changes to the model. Partial images
and receipts are retained after failure, with no automatic replay.

## Qualification

Run `python3 scripts/qualify_rhino.py` for controlled operation, approval, recovery
and affected Blender integration checks. Add `--host` to exercise fixed startup,
native creation, inspection and a height revision in real Rhino processes. These
small fixtures use no model provider and send no channel messages. Results and
commands are retained under the ignored `outputs/` directory. `--startup-only`
restricts host work to the probe; `--skip-controlled` avoids repeating already
recorded controlled checks while diagnosing a host issue.

Use `--host --rhino-version 7 --continuous` (or `8`) for a single project chain:
create four objects with a material/layer and two named cameras, render, make three
geometry revisions, reject an undeclared object edit, recover from the last good
version, repeatedly inspect and render the final two views. Relay reopens the same
project database between stages and checks all retained version hashes. These are
explicit test-fixture selections, not user acceptance. Each host phase still uses a
fresh owned Rhino process; this is saved-project continuity, not a persistent
interactive Rhino session or a long-duration soak test.

This does not reload an installed service, qualify live planner judgment or prove
Telegram/Messages transport. Those are separate deployed checks.

The stage-handoff harness additionally runs a blocked draft, explicit recovery,
selection of the complete prepared set, modeling, render review and preview/original
delivery through controlled planner/reviewer/channel adapters:

```sh
python3 scripts/qualify_rhino_handoffs.py --host --rhino-version 7 --output outputs/rhino-handoffs-7
```

Use `--rhino-version 8` for the current interpreter. An explicitly reviewed
`--prepared-dir` containing `model.py`, `checks.json` and `render.json` can replace
the fixed fixture; this executes that exact host script. Results retain native
outputs and the controlled stage database. This chain passed with Rhino 7.32 and
8.35; the Rhino 8 trial produced the repaired twisting tower. Missing object
metadata support was correctly rejected on an earlier tower draft. No live
planner/reviewer provider or Telegram delivery is claimed by this harness.

Rhino 8.35 passed the September 12 continuous fixture in about 162 seconds:
13 stages including startup, four native versions, three revisions, four
inspections, three actual renders and one expected preservation rejection. The
rejected edit left the run blocked; the next explicit fixture stage selected the
last good version. All prior native hashes remained unchanged across Relay
restarts. The initial/final rendered images were visually inspected. This exposed
and fixed named-view capture and unstable material-archive comparison behavior.

The controlled suite covers exact-code and render-manifest delivery before atomic
Start, frozen version/implementation changes, incorrect PNG dimensions, timeouts,
process ownership, immutable native review/delivery and no automatic replay.
Channel transport and model planning are simulated in controlled tests.

Rhino 7.32 subsequently passed the same 13-stage continuous fixture in about
328 seconds, using IronPython 2.7.12. All four retained native files had V7 format
headers and unchanged recorded hashes. The final two camera renders were visually
inspected; PNG dimensions, source preservation, process identity and exit status
also passed a separate file/receipt audit. The expected undeclared edit failed,
and the next explicit stage recovered from the last good version.

This qualification exposed a Mono finalizer crash during managed process exit and
an interactive save prompt during Rhino's normal quit. The macOS process-exit
adapter resolves both after closing artifacts and the result receipt. The final
38 focused Rhino operation/planning checks passed. Earlier failed runs and the
successful run remain recorded separately; failed attempts were not relabeled.

These results qualify the tested builds on macOS: Rhino 7.32 and Rhino 8.35.
They do not establish compatibility with every service release, third-party
plugin or large production model. Detailed commands, failures, owned process IDs,
runtime versions and receipts remain under ignored local qualification outputs.

API references: [Rhino 7 macOS startup options](https://docs.mcneel.com/rhino/7mac/help/en-us/information/startingrhino.htm),
[ScriptEditor macros](https://developer.rhino3d.com/en/guides/scripting/advanced-scripteditor-macros/),
[RhinoDoc API](https://developer.rhino3d.com/api/rhinocommon/rhino.rhinodoc).
