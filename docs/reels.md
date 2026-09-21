# Provider-independent local reels

Any supported text provider can author a full HyperFrames HTML/CSS/JavaScript
project. `hyperframes.preview` and `hyperframes.render` execute that project through
a shared local host adapter. The model does not need shell access or a special
video provider. Existing storyboard, editorial and reel guides remain author inputs.

## Asking for a reel

Say “make me a reel” when the subject is clear from the conversation, or “make a
reel from this storyboard.” Relay resolves the matching selected content and guides,
chooses the local authoring/preview/render operations and proposes the missing work.
Users do not need operation names, internal run IDs or a technical prompt. If no
subject is available or several versions fit, Relay asks about that specific gap.
A request for a finished reel retains the MP4 as an outcome through preview review;
a storyboard or preview is not reported as the finished reel. Explicit tool/provider
choices, planning-only instructions and normal Start/selection controls still apply.

## Author, inspect, revise, render

1. A text worker authors `project.json` containing actual source files and exact
   local asset bindings. An independent worker reviews that source against the
   supplied storyboard and guides.
2. `hyperframes.preview` stages those exact files, runs HyperFrames checks and
   captures the declared full-resolution samples. It delivers `project.json`,
   `project.zip`, `frames.zip`, `contact-sheet.png`, and `verification.json` under
   `delivery/`. The ZIP preserves editable source and copied assets.
3. Independent preview review can request source corrections. If the plan includes
   the bounded local correction allowance, confirmed check failures or review
   findings return to the author, then pass through source review and a new preview
   attempt. Previous source, attempts and failure receipts remain intact.
4. The user selects the complete preview set. If encoding was also requested,
   planning records `hyperframes.render` as pending until those exact inputs exist.
   The completed preparation stage exposes **Plan execution**.
5. A separately approved render assignment binds the registered project ZIP and
   passed preview receipt by `project_sha256` and `preview_sha256`. It checks the
   same source again, renders H.264 and verifies dimensions, FPS, frame count,
   duration and audio presence. It does not redesign the source.
6. Render deliveries are `reel.mp4`, the unchanged `project.zip`,
   `contact-sheet.png` and `verification.json`. Independent review and human visual
   selection remain required.

A code profile from the author's provider can inspect ZIPs, media metadata and
receipts. Binary access does not establish visual judgment. Pixel inspection needs
an image-capable worker or human review; technical success is never acceptance.
An explicitly locked executor remains locked. Missing review capabilities must be
reported rather than silently changing the model provider.

## Project transport

The frozen catalog supplies `project_schema`. Planning captures that contract and
an asset index under `operation-support/hyperframes.preview/`. This JSON is a source
transport, not a layout or scene template:

```json
{
  "version": 1, "width": 1080, "height": 1920, "fps": 30,
  "duration": 14, "audio": false, "samples": [0.8, 3, 7, 13.8],
  "files": {
    "index.html": "<!doctype html>...full authored composition...",
    "styles.css": "...authored styles...",
    "motion.js": "...authored seekable animation..."
  },
  "assets": {"assets/photo.png": "exact/declared/input.png"}
}
```

The entrypoint is `index.html`; its composition root must declare matching width,
height and duration. Authors control typography, independent layers, transitions,
SVG/canvas/WebGL, local libraries and media timing. Initialize DOM-dependent code
when the DOM is ready. Use a paused registered timeline or paused browser-native
animations with `data-no-timeline`. Stage libraries such as GSAP as declared assets;
do not assume a CDN or package installation. A local font is supplied as
`assets/relay-font.ttf`. Sample scene interiors and transition boundaries.

Bounds are 30 source files / 2 MB source, 50 assets, even dimensions between 320 and
1920 with at most 2,073,600 pixels, 15/24/30 FPS, 0.5–120 frame-aligned seconds, and
1–20 sample times. Input and delivery bounds are 50 MB per operation. The authoring
path does not impose the legacy renderer's fonts, scene layouts or entrance effects.
Editorial claims and reading/narration pace are reviewed against the user's guides;
no generic schema can establish their correctness. `audio` declares expected encoded
audio presence. These operations do not synthesize voices or generate footage.

## Local runtime and qualification

The initial adapter supports macOS with installed Node, HyperFrames **0.8.46**,
Chromium/Chrome, FFmpeg, ffprobe, Pillow and a local TTF font. Other hosts or CLI
versions need their own qualification. The operation downloads or installs nothing.

Save private absolute paths for `node`, `hyperframes` (the package's
`bin/hyperframes.mjs`), `browser`, `ffmpeg`, `ffprobe`, and `font`, then run:

```sh
python3 scripts/qualify_hyperframes.py --paths private/media-paths.json --output outputs/hyperframes-qualification-01
```

Use a fresh directory. This creates a controlled three-layer authored fixture,
checks it, captures preview frames, restores the exact ZIP, renders it and verifies
encoded properties. Success records runtime and implementation hashes in private
`media-runtime.json`; changes invalidate qualification. It makes no provider calls
and does not approve user content.

The adapter constructs fixed argument arrays with a clean environment. Front-end
JavaScript executes in Chromium; arbitrary Node/server/shell programs and project
runtime configuration are not accepted. A disposable runtime copy adds a resource
policy while delivered source stays unchanged. macOS Seatbelt restricts file data
access to installed runtimes/system resources, staged work/output and Chromium's
OS temporary socket namespace. External network is denied; loopback and local Unix
sockets remain available. Each command has a temporary browser profile and an
owner guardian covering cancellation, deadlines, log/working-file limits and
owned descendants. These constraints are execution boundaries, not proof of
creative quality or a general-purpose untrusted-code sandbox.

Failures preserve partial output and receipts. Only a confirmed local preview
failure can use its already approved correction allowance. An intent without a
conclusive receipt remains uncertain; it is not automatically replayed.

## Existing template plans

`media.compose` remains available for saved plans and explicitly suitable simple
slideshows. It accepts bounded scene data and uses Relay's fixed template, with
PNG/JPEG, simple entrances and optional supplied WAV/MP3. It cannot express custom
multi-layer design. Its qualification command remains:

```sh
python3 scripts/qualify_media.py --paths private/media-paths.json --output outputs/media-qualification-01
```

If qualifying both paths, run template qualification first, then full-project
qualification. The legacy fixed-template operation retains its existing host file
permissions; authored project operations use the additional scoped file policy.
