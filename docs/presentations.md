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
