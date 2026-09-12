# Blender animation and repeatable rendering — B04 v1

`blender.animate` adds numeric transform/camera tracks to a selected scene or renders
its existing animation. The operation runs fixed Blender and ffmpeg code on the host.
Embedded scripts are disabled; this is normal host execution, not a filesystem sandbox.

A registered manifest fixes `version:1`, `scene_sha256`, `mode` (preview/final),
`frame_start`, `frame_end`, `fps`, `camera`, `resolution`, `samples` and `tracks`.
Each track names `object`, `property` (location/rotation_euler/scale) and `keys` of
`{frame,value:[x,y,z]}`. Keys include both endpoints, with linear interpolation.
Up to 20 tracks and 20 keys per track are supported. Target objects must have no
parent, children, constraints or prior animation. Rotation tracks require an Euler
rotation mode. Empty tracks render the selected existing animation.

Example manifest (replace the hash with the selected scene's exact SHA-256):

```json
{
  "version": 1,
  "scene_sha256": "EXACT_SCENE_SHA256",
  "mode": "preview",
  "frame_start": 1,
  "frame_end": 24,
  "fps": 12,
  "camera": "Camera",
  "resolution": [512, 512],
  "samples": 4,
  "tracks": [{
    "object": "Tower",
    "property": "rotation_euler",
    "keys": [
      {"frame": 1, "value": [0, 0, 0]},
      {"frame": 24, "value": [0, 0, 1.5707963268]}
    ]
  }]
}
```

The planner selects already registered scene/manifest artifacts and sets
`execution.parameters.manifest_sha256`. Prepare a missing manifest in a separate
agent stage. The complete manifest is delivered before Start, and inputs are
rechecked before claim. Conversational plans require independent output review and
a user selection gate. Preview/final quality have different exact manifests and
approval scopes; a preview approval never authorizes a larger final render.

Outputs under `delivery/`:

- `candidate.blend`: new editable scene, independently reopened.
- `animation.mp4`: H.264/YUV420p video with checked frame count, dimensions and FPS.
- `preview.png`: first rendered frame.
- `checkpoint.zip`: candidate, verification record and completed frame data.
- `frames.json`: manifest hash, candidate hash, implementation/executable identity,
  per-frame state, originating render attempt and completed-frame hashes.
- `execution.json`: commands, bounded log tails, checks and outcome; candidate unselected.

The media queue adds an MP4 preview plus independent original-file delivery. Existing
video metadata checks and document fallback apply. Live Telegram delivery is unverified.

Rendering is bounded to 1–120 contiguous frames at integer 1–60 FPS and 600 seconds.
Preview allows even 64–512px dimensions and 1–4 CPU samples; final allows 64–1024px
and 1–16 samples. Declared outputs total at most 100 MB; checkpoint payloads use at
most half that budget. Workspace/source/control copies also occupy disk and are
retained for recovery; 100 MB is not a total process disk quota. Failed render files
remain with their original attempt. This operation adds no automatic cleanup.

Blender, ffmpeg and ffprobe must be installed already. `TASK_RELAY_FFMPEG` and
`TASK_RELAY_FFPROBE` select explicit executable paths; otherwise PATH is used. Invalid
explicit paths do not fall back. Host discovery launches nothing. Only macOS has
native qualification; Windows/Linux qualification remains O12.

Only single-scene, self-contained inputs are supported. Drivers, simulations,
Geometry Nodes, OSL, external caches and linked/unpacked dependencies are excluded.
Opening a native scene still uses normal host permissions. Verification checks the
scoped scene snapshot and declared transforms; it is not general Blender semantic
equivalence, visual quality approval or proof of a physically valid animation.

## Explicit continuation

Each frame has a saved intent before launch and a hash after a confirmed successful
render. An atomic checkpoint is updated before and after each frame. A deadline
between frames leaves later frames pending. Process timeout or interruption during
a frame retains an unresolved intent; it is never silently reclassified as missing.

A new, explicitly authorized stage may select a registered `checkpoint.zip` from a
confirmed stopped B04 attempt with the same manifest. Preflight rejects uncertain
parents, different contracts and unresolved frame intents before consuming a new
attempt. Execution checks candidate/frame hashes and implementation/executable
identities, independently reopens the candidate, then renders only pending frames.
Completed frames are reused; encoding is a new local action within that stage.
Executable identity uses the existing path/stat signature, not a cryptographic binary
hash. Implementation drift blocks checkpoint reuse rather than silently mixing versions.

No folder scan searches for convenient partial renders. Existing attempts, budgets,
receipts and user selections remain unchanged. Resume does not expand frame range,
resolution, sample count or source versions. Final-quality work uses a separately
approved manifest and does not reuse lower-quality frames.
