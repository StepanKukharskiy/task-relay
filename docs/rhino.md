# Direct Rhino integration

Relay registers `rhino.startup`, `rhino.inspect`, `rhino.run_python` and `rhino.render` through the
existing production planner, exact artifact selection, review and delivery paths.
Grasshopper definitions, scripts, component execution and graph authoring are
paused. They have no registered operation.

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

Rhino 7 may block a second instance with a modal warning. Save and quit an existing
Rhino 7 session before automated host work. Relay does not close that session or
send modeling commands to it. A blocked startup times out and records failure.

The host adapter launches the Rhino executable directly with its documented
`-runscript` option with `_-RunPythonScript` on 7 or `_-ScriptEditor _Run` on 8. Each phase receives a fresh process
and a PID/token handshake. A command received by a different process is rejected
before modeling or process exit. No persistent listener or plugin is installed.
The process remains in Relay's supervised process group for cancellation.
After the ownership check, Rhino 7 and 8 exit through a macOS adapter using native
process exit, only after closing artifact files and the result receipt. This
avoids Mono/C++ finalizer crashes and Rhino's save-changes dialogs. Both a successful
worker receipt and a clean exit code are required; failed operations remain failed.

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
