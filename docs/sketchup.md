# SketchUp native operations

SketchUp shares the native application profile in `orchestrator/native_apps.py`
with Rhino and Blender: discovery, native/script media types, checks validation,
exact-code authorization and registered dispatch. Geometry checks and desktop
process handling remain application-specific. Adding another app still requires
its own adapter and qualification; an unknown capability never falls back to Blender.

## Implemented scope

The first adapter targets desktop SketchUp 2025/2026 on macOS, using its embedded
Ruby API. It discovers installed bundles or the absolute executable specified by
`TASK_RELAY_SKETCHUP`; a bad explicit path never falls back. Settings → Apps and
tools controls new dispatch. Discovery proves presence, not license readiness.

| Operation | Inputs | Result |
| --- | --- | --- |
| `sketchup.startup` | Diagnostic request | Owned-process startup receipt |
| `sketchup.inspect` | One exact registered `.skp` | Bounded geometry/document inventory and unchanged input hash |
| `sketchup.run_ruby` | Exact registered `model.rb`, checks JSON, and `.skp` for edits | New `.skp`, PNG viewport preview, Ruby source, checks report and execution receipt |

Preparation and independent review produce `model.rb` and checks JSON together.
Both must be selected before a separate execution plan can reference them.
Start authorizes the complete attached source/checks, input versions, application,
implementation and limits atomically. Dispatch follows that commit. Changed code,
inputs, application or implementation requires fresh approval.

Ruby executes with normal host permissions, including filesystem/network access.
The script has a `model` variable referring to the active model. Relay handles
native save, independent reopen and viewport capture. The operation has separate
baseline, modeling and verification processes. It retains partial results after
failure, does not automatically replay uncertain work and never selects a candidate
on the user's behalf. Final output review and explicit selection remain required.

## Checks contract

Use the catalog's `checks_schema` and the frozen preparation validator. Example:

```json
{
  "version": 1,
  "mode": "create",
  "changed_entities": [],
  "allow_additions": true,
  "expected_entity_count": 1,
  "expected_dimensions_mm": {"Box": [100, 200, 300]},
  "preview": {"resolution": [640, 480]}
}
```

Edits declare top-level persistent IDs permitted to change. Unchanged entities
are compared recursively. Dimension checks target uniquely named top-level groups
or components and use millimeters; SketchUp's internal lengths are inches.
The snapshot records geometry, transforms, visibility, assignments, attributes,
simple material/tag properties, options, active camera and scene cameras/attributes.
This is not full document equivalence: styles, all scene settings and extension
semantics are not comprehensively verified.

The initial scope permits plain edges, faces, groups and components, at most 5,000
total entities and 100,000 recorded geometry points. Textures, images, external
component definitions and unsupported entity types fail explicitly. Preview
dimensions are 64–1024 pixels; modeling has a 600-second ceiling and 100 MB input
and declared output bounds. The PNG is a viewport preview, not a production render.

## Desktop readiness and qualification

Activate SketchUp interactively, then save and quit that version before Relay runs
it. The adapter refuses to attach to an existing process. It establishes ownership
with PID/token receipts and stops only its launched process on timeout. A missing
modeling receipt or interrupted execution intent remains uncertain for recovery.
Installed extensions still load under normal desktop permissions; this adapter
does not isolate or audit them.

For an explicit local check, use a new output directory:

```sh
python3 scripts/qualify_sketchup.py --host --case startup --output outputs/sketchup-startup-check
python3 scripts/qualify_sketchup.py --host --case roundtrip --output outputs/sketchup-roundtrip-check
```

The roundtrip uses a tiny untextured box: create, save/reopen, inspect, then edit
its height and verify a new candidate. It uses controlled orchestration with the
real native executor; it sends no provider requests or messages. Reports distinguish
these checks from installed-service or production delivery qualification.

Current status: source implementation and controlled integration checks pass.
The local SketchUp 2026 startup check reached the sign-in/subscription screen and
timed out before Ruby acknowledged startup. Native create/edit/reopen and preview
remain unqualified until activation and a successful roundtrip. This change has
not been installed or used to reload services.
