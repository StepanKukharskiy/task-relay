# Editable PPTX creation

`pptx.create` turns a bounded JSON slide specification and selected PNG/JPEG images
into a new editable PowerPoint file. It runs locally without Google sign-in,
PowerPoint or Keynote. Native text, shapes, tables and charts remain editable.
The generator preserves the supplied chart values in an embedded workbook.

Install the optional dependency into the same Python environment as the worker:

```sh
python3 -m pip install '.[presentations]'
task-relay presentation schema
```

The desktop runtime requirements include the pinned dependency wheels for a
future rebuild. Changing source does not update an already installed app. The
operation catalog reports missing or incompatible dependencies before a claim.

## Local creation

Save this as `slides.json`:

```json
{
  "version": 1,
  "title": "Project overview",
  "slides": [
    {
      "notes": "Draft for review.",
      "elements": [
        {
          "type": "text", "x": 0.7, "y": 0.6, "w": 12, "h": 1,
          "text": "Project overview", "font_size": 40, "bold": true
        },
        {
          "type": "text", "x": 0.7, "y": 2, "w": 11, "h": 3,
          "text": "Editable slides from selected project sources.",
          "font_size": 28
        }
      ]
    }
  ]
}
```

```sh
task-relay presentation create slides.json --output-dir candidate-v1
```

The directory must be new. It contains `presentation.pptx` and `receipt.json`
with source/output hashes and reopen results. Existing candidates are never
overwritten. The equivalent module command is
`python3 -m task_relay.presentations create slides.json --output-dir candidate-v1`.

For images, add `--image assets/view.png` for each selected file. Paths in image
elements must exactly match these declarations, relative to the specification's
directory. Linked files and traversal outside that directory are rejected.
Images fit their boxes without cropping or stretching. No downloads occur.

## Production planning

Select `step_capabilities=["pptx.create"]` in `plan_production`. The planner gets
a frozen schema and creates a bounded graph:

1. An agent writes the slide JSON from selected sources.
2. An independent reviewer checks that specification.
3. `pptx.create` depends on both and generates the deck.
4. An independent reviewer reads the actual PPTX and the same source versions.
5. The user selects the candidate through the existing selection flow.

The operation uses `parameters={}`, no agent tools, one invocation and one
`.pptx` output with MIME type
`application/vnd.openxmlformats-officedocument.presentationml.presentation`.
It accepts exactly one `application/json` specification plus optional typed
images and text context. Images may be upstream artifact outputs. Their names
inside JSON must match their staged input paths in the creation assignment.
An already registered specification can go directly to creation and deck review.

Architecture and data presentation starters now identify this route. Extra
deliverables, including rendered previews, retain their separate requirements.
Original requests, frozen assignments and selected artifact identities use the
existing transaction and recovery machinery. Invalid inputs or implementation
drift stop creation. Interrupted or uncertain attempts never authorize replay.

## Scope and checks

The schema supports custom slide dimensions, background/font choices, presenter
notes, text, rectangles/ellipses, native tables and column/bar/line charts. It caps
slides, element counts, text length, chart/table sizes, input/output bytes and
execution time. Objects must fit within the slide. Unknown fields fail rather
than being silently ignored.

The generator reopens the saved PPTX bytes and compares slide count, dimensions,
title, notes, editable text, tables, chart data and image bytes. The receipt
records a relative tolerance of `1e-14` for numeric chart round trips through
Office serialization. Chart labels beginning with `=` are rejected to prevent
implicit spreadsheet formulas; the original JSON remains the exact source.
The receipt explicitly distinguishes these checks from visual review and native-app import.
It does not detect every text overflow, font substitution or overlapping object.

PDF and image rendering are not part of `pptx.create`. When requested, add a
separate renderer of the actual PPTX and inspect its output. A separately
constructed image is not a preview of the deck. Keynote can open PPTX, but this
implementation does not launch Keynote or claim native import fidelity. Existing
PPTX/template editing, animations and native `.key` creation are outside v1.

Controlled checks:

```sh
python3 -m unittest tests.test_presentations tests.test_mixed_execution tests.test_mixed_planning tests.test_workflow_library -v
```

Tests use small synthetic text/table/chart data and one tiny image fixture. They
cover editability, exact inputs, output preservation, missing dependencies,
failure/restart behavior, a real supervised local worker and planning/review gates.
Agent decisions and channel delivery are fixtures, not live provider qualification.

## Reusable layouts and user branding

New decks can use specification version 2: the author chooses `title`, `section`,
`text`, `two_columns`, `image_text`, `table`, or `chart` and fills named slots.
The deterministic compiler creates native editable objects; a separate reviewer
still checks content, overflow, credits and actual presentation quality.
`python3 -m task_relay.presentations templates` prints the layout catalog.
Version 1 coordinates remain supported for existing decks and unusual slides.

```json
{
  "version": 2,
  "title": "Project overview",
  "brand": {
    "body_font": "Arial",
    "heading_font": "Georgia",
    "background": "FFFFFF",
    "text": "222222",
    "accent": "285A44",
    "logo": {"path": "assets/logo.png", "x": 11.5, "y": 6.95, "w": 1.2, "h": 0.35}
  },
  "slides": [
    {"layout": "title", "content": {"title": "Project overview", "subtitle": "Research and recommendations"}},
    {"layout": "text", "content": {"title": "Findings", "body": "Concise source-grounded findings."}}
  ]
}
```

The logo is an exact declared PNG/JPEG input; pass `--image assets/logo.png` for
local CLI creation. It retains its aspect ratio inside the requested box. A logo
box overlapping content fails validation instead of silently moving either.
Brand settings control heading/body fonts, text colors and slide backgrounds;
charts and table fills retain the generator's default styling. Fonts are named,
not installed or embedded, so recipients need the font for consistent rendering.

For a custom layout, include a `templates` object in the same frozen specification:

```json
{"our_cover": [
  {"slot": "headline", "type": "text", "x": 1, "y": 1, "w": 10, "h": 2, "role": "heading"},
  {"slot": "summary", "type": "text", "x": 1, "y": 3.5, "w": 10, "h": 2}
]}
```

Then use `layout: "our_cover"` and `content: {"headline": "…", "summary": "…"}`.
Slot types are text, image, table and chart. Missing or extra content is rejected.
All layouts use 16:9 dimensions in inches and the usual schema limits.

Users can attach a template JSON, a logo and written brand instructions to their
request. Relay should select these exact references and retain the resolved profile
inside `slides.json`; reusing the profile never changes an earlier deck. Users can
also supply example slides/PDFs as guidance for a proposed profile. Inferring rules
from examples requires their review. Native `.pptx`/`.potx` master import, embedded
fonts and a Settings template library are not implemented in this version; do not
promise pixel-identical reproduction of an uploaded PowerPoint template.

## Result handoff

After exact output selection and completed review, Relay exports files before
queuing a single completion handoff containing absolute selected-file paths and
the containing folder. Saved pipelines keep their numbered stage folders. Standalone
productions and their recorded plan recovery ancestors share a `job-…` results
folder under `generated/workflows`, with selected files, versioned drafts, inputs,
reviews and receipts. This display grouping does not attach work to a pipeline or
change its authorization. Files are identified by artifact ID and verified hash.

Local edits are preserved; Relay exposes the exact registered version alongside
an edited copy. Status cards include verified file paths once export succeeds.
Installing the feature does not send historical completion messages. Earlier
selected results can be exported explicitly without rerunning a model or sending
any messages.


## Image collections and predictable styling

Use `style: "clean_minimal_v1"` for a stable white background, charcoal text and
Arial heading/body typography. Explicit brand overrides still take precedence.
Existing v1 decks and v2 decks without a style keep their prior defaults.

`image_grid` accepts an ordered collection and automatically paginates it:

```json
{
  "version": 2,
  "title": "Plant catalogue",
  "style": "clean_minimal_v1",
  "slides": [{
    "layout": "image_grid",
    "content": {
      "title": "Trees",
      "per_page": 6,
      "items": [
        {"image": "assets/photos.zip/images/tree.jpg", "label": "Common name", "caption": "Botanical name"}
      ]
    }
  }]
}
```

Four items per page use two columns; six use three. Both use two rows. Relay
preserves input order, adds page numbers for a collection spanning pages, and
keeps the same geometry on a partly filled last page. It does not enlarge the last
image, shrink fonts or silently drop items. The model supplies names, exact image
paths and brief captions rather than coordinates and duplicate slide objects.

Bounds: 1–120 items per collection, 70 characters in a title, 60 in a label, 80 in
a caption. Each field accepts one input line. Credits can be supplied per item
(maximum 2000 characters) and remain in notes; `images.collect` bundle attribution
is added automatically to the pages using those images. The expanded deck still
must fit the existing 50-slide/1000-object limits. Longer text needs a detail slide.
Unavailable photos may be omitted from the list only under the user's existing
permission; preserve the subject research and document the omissions.

Image `fit` defaults to `contain`, showing the entire source without distortion.
Explicit `fit: "cover"` fills equal rectangles using native center cropping; this
can hide parts of a plant or other subject, so choose it only when appropriate.
Original embedded image bytes remain intact. Bundle credits disclose cropping.
Logo collision checks apply to every generated grid page. Gallery content is
editable and uses no ornamental panels or shadows.

The eight layouts and this style are reusable program data. Model reasoning still
chooses relevant content and reviews image identity and presentation quality;
template compilation owns spacing, typography and pagination. This reduces the
amount of layout JSON to author; token savings have not been measured in a live
provider run.
