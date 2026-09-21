# Sourced images in presentations

`images.collect` searches Wikimedia Commons for a plan's named subjects. It is a
registered operation, separate from image generation and independent of model
credentials. The subject list is supplied by the planner from the user's request
and research; the adapter has no plant-specific pipeline.

Each subject has an `id`, display `label`, and literal `query`. A revision may
provide `exclude_titles` containing exact previously rejected Commons file titles.
Optional `identity` specifies an exact name from the request or research that must
appear as a phrase in title/description. Prefer concise queries over prose captions.
The collector first searches the exact phrase, then the same literal words in any
order. It never drops words, invents synonyms or changes the requested subject.
Short names (including two-word botanical names) retain phrase matching.
There are at most 40 subjects, two searches with five candidates each, two distinct
candidate download attempts and eight HTTP GETs including redirects per subject.
Only one photo is retained per subject. A failed candidate may be replaced by a
different eligible candidate; the same URL is never retried. Requests are public read-only HTTPS GETs to fixed Wikimedia
hosts, with checked/pinned public addresses, time and byte limits, and saved
request/response receipts. There is no transport retry or paid image call.

The output ZIP contains `manifest.json` and `images/<id>.jpg|png`. Every subject has
a found or missing result, exact search queries/counts and candidate download failures.
No search results, rejected metadata and failed downloads have distinct reasons.
An entirely empty collection is a failed operation with its diagnostic ZIP retained,
so a requested photo stage cannot silently succeed without photos. Partial bundles
remain reviewable, including user-permitted omissions.
Found candidates retain title, source page, author,
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

## Browser discovery without a search API

Users can ask for relevant photos without naming a website. A shared read-only
policy exposes an availability-based default to the orchestrator and stage planner:
use browser discovery when Browser use is enabled, Chrome is available and a
verified browser worker is in the captured catalog; otherwise use Commons.
An explicit Commons-only or documented-reuse requirement takes precedence.
Stage planning only advertises operations in that stage's selected scope, and
explicit worker choices retain their captured catalog.

For browser discovery the planner chooses suitable search sites and includes a
primary and alternate site's exact origins before execution. Instructions direct
the worker to refine queries or try that alternate for empty/irrelevant results
within the same action/request budget, retaining successful exports. An explicit
site requirement does not gain an alternate; challenges are never bypassed.
This is planned browser behavior, not a cross-operation fallback scheduler: failed
or exhausted approved stages retain their receipts and require scoped recovery.
No search API key is needed. Website layout and verification challenges can still
interrupt browsing; verification remains manual and frozen origins remain enforced.

The browser assignment reserves a JSON manifest through
`image_sources: [{path: "delivery/image-sources.json", subjects: [{id, label, query}]}]`.
Visible images have labelled click controls and image refs in `browser_read`.
`browser_image_source` accepts an observed image ref and a frozen subject ID; it
exports actual DOM URLs, publisher page, observation and action identity. Google
result links with explicit original/publisher URLs are decoded. Thumbnail proxies,
embedded data images, local URLs and stale observations are rejected. Source JSON
is a reserved output that the model cannot create with `file_write`.

A separate registered `images.fetch` operation accepts exactly that JSON manifest
and returns `application/zip`, compatible with the existing image bundle/PPTX path.
It downloads up to two candidates per subject, validates JPEG/PNG bytes and records
exact hashes, original page links, download failures and missing subjects. Public
HTTPS requests are pinned to public IPs and limited to the observed image/publisher
hosts; redirects cannot expand that host set. It sends no cookies or credentials.
At most eight GETs per subject (including redirects), 40 subjects, 3 MB per image,
45 MB per bundle. Entirely empty bundles fail with diagnostics; partial results
remain reviewable. Unknown authors and licences are explicitly recorded as unknown,
not inferred from appearance or from discovery through a search engine.

Plan small browser batches with explicit request/action limits. Independently review
the exact downloaded ZIP for subject identity, coverage and suitability before use.
Source-rights review is separate from image-byte integrity. Pass the exact ZIP(s)
to `pptx.create`; full source information is retained in slide notes. No image
creation, paid search, or automatic substitution of screenshots is part of this path.

Live qualification in 0.13.58 covered one Google Images result through Relay's
managed Chrome adapter, followed by the real registered downloader. Bing and
DuckDuckGo use the generic DOM mechanism but have not had live qualification.
