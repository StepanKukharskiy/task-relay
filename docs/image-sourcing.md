# Sourced images in presentations

`images.collect` searches Wikimedia Commons for a plan's named subjects. It is a
registered operation, separate from image generation and independent of model
credentials. The subject list is supplied by the planner from the user's request
and research; the adapter has no plant-specific pipeline.

Each subject has an `id`, display `label`, and literal `query`. A revision may
provide `exclude_titles` containing exact previously rejected Commons file titles.
There are at most 40 subjects, five metadata candidates per search, and one image
download per subject. Requests are public read-only HTTPS GETs to fixed Wikimedia
hosts, with checked/pinned public addresses, time and byte limits, and saved
request/response receipts. There is no automatic retry or paid image call.

The output ZIP contains `manifest.json` and `images/<id>.jpg|png`. Every subject has
a found or missing result. Found candidates retain title, source page, author,
file licence, download URL, retrieval time, dimensions and byte hash. Supported
licences are public domain, CC0 and CC BY/BY-SA. A metadata match is not visual or
scientific verification. Independent review must check coverage, identity and
suitability; missing matches and uncertain cultivars must not be concealed.

Pass the exact reviewed bundle to `pptx.create` as `application/zip`, alongside
one slide JSON specification and any ordinary image/text inputs. The image path
in the specification is `<staged-bundle.zip>/images/<id>.jpg|png`. The creator reads
only declared members in memory, checks hashes and image bytes, embeds the exact
photos without cropping, and adds full credits to the notes of the slides using
them. Include short visible subject labels and credits in the slide design too.
Untrusted, linked, oversized, duplicate or undeclared archive members are rejected.
The original artifacts and failed/rejected candidate bundles remain unchanged.

For local diagnostics, the package commands are:

```sh
python -m orchestrator.image_sources subjects.json --output-dir new-image-results
python -m task_relay.presentations create slides.json \
  --image-bundle new-image-results/images.zip --output-dir new-deck
```

The desktop planner exposes these operations without requiring users to run the
commands. In-app planning and candidate review remain subject to the usual saved
workflow boundaries. Download and PPTX package checks do not prove rendered layout;
native import and visual review are separate checks.

Provider references: [MediaWiki Imageinfo API](https://www.mediawiki.org/wiki/API:Imageinfo/en)
and [Commons reuse information](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia/en).

## Location-map captures

When the request includes a screenshot of Google Maps (or another named map
service), the planner adds a browser worker with `browser.use` and `browser.capture`
to the same photo/presentation graph. It uses the user's location and named service,
keeps attribution visible, and saves the viewport PNG plus `.png.json` provenance.
The specification author receives the image and provenance; `pptx.create` receives
the exact PNG and source-image ZIP, but only the one slide-specification JSON.
Screenshot JSON must not be misclassified as a second slide specification.

New mixed scopes permit up to twelve tasks so capture and source reviews fit with
document preparation/creation/review. Existing saved scopes without this field
retain their original six-task bound. Browser roles receive compatible context;
implicit Python validators or unrelated binary files do not force a code worker.
Explicit inputs and requested provider choices are preserved.

An eligible configured browser executor is still required. Current screenshot
workers report metadata and DOM observations, not visual understanding of map
tiles; retain user visual review and report consent/verification/loading blockers.

Photo collection uses the exact subject queries in its parameters and supports
`inputs: []`. Research, prior slides and conversation histories belong to the
author/reviewer steps, not the download operation. Explicit inputs remain subject
to the operation byte limit; known oversized selections fail during planning.
