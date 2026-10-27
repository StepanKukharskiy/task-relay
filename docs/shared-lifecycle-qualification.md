# Shared correction and delivery release gate

Use impact-based qualification from `AGENTS.md`. Focused regressions and an
affected composed path are the default for local changes. The full matrix below
is for public release candidates, broad runtime changes or an explicit request
for the full matrix. A local installation alone does not require it. Inspect
documentation-only changes without rerunning execution tests.

Run `python -B scripts/qualify_lifecycle.py --output outputs/lifecycle-check-N`
in a fresh output directory. Install the declared `presentations` and `images`
extras first. The runner is offline; it does not install dependencies. Missing
dependencies, skips, expected failures, empty selections, process timeouts,
failed assertions and source changes during qualification fail the gate.

The release workflow requires this job before creating a draft release. It runs
on changes to the runtime, tests and gate as well as release tags. Local release
preparation uses the same command; `--verify <output>/report.json` rejects stale
source or changed evidence. A local pass does not claim CI ran or repository
branch protection was configured. This gate does not authorize release publication.

## Contract and matrix

The reference lifecycle exercises the real owner tool loop, advertised schema,
compiler, atomic admission, worker file/record tools, collection, carried finding
judgments, exact review binding, registered composition and delivery projection.
Provider replies and worker process observations are controlled fixtures. It does
not set acceptance or edit scheduler state to complete its reference graph.

| Group | Required behavior |
| --- | --- |
| Public read recovery | Actual node loop consumes failed-page recovery state, follows a literal observed alternative and delivers. Existing receipts own six shared method attempts, restart reuse, HTTP-shell to rendered choice, retained failed captures, bounded observed links, global uncertainty and tamper holds. Error headings do not promote error pages into usable captures; partial paywall text remains available for honest semantic assessment. Synthetic transports and scripted decisions do not establish live completion. |
| Operation tools and named node ports | One registered definition supplies direct-tool and scheduled-node inputs/outputs. The UI catalog hides registered historical duplicates by default, preserves exact wire IDs and connector pins across label changes, rejects unsupported/ungranted baseline fields, and reloads the two exact former content definitions only when their unsupported field was not supplied. Graph and lowering validation agree on eligible correction subsets. Actual scheduled page read to model input, retained HTTP/rendered outcomes, shared six-method exhaustion, cross-interface uncertainty, concurrent admission exclusion, rejected proposal correction and unchanged version-one captures. Synthetic transports only. |
| Node specification and desktop admission | The same versioned node document drives model declarations, admission and UI projection. Desktop requests admit once without a legacy intake/planner; exact attachments, unavailable-provider rejection, failed proposal correction, saved-port restart and desktop baseline continuation without re-planning are exercised. Gated executor discovery shares dispatch verification and remains independent of shell CLI discovery; a missing qualified gate cannot fall back to that CLI. Controlled decisions do not prove live quality. |
| One node interface | The real model tool loop binds and completes direct text in one call; connected nodes use the existing compiler/queue, deterministic admission identities and exact named outputs. Failed proposals retain a usable correction surface. Saved outputs survive failed completion/restart, required review and uncertain effects remain blocking, and partials remain unreviewed. Owned temporary browser profiles are removed only after confirmed closure; durable evidence and historical/authenticated profiles remain. |
| One node composed correction | The existing inventory/acquisition/failed-correction fixture executes through version-2 node declarations: typed inventory admission, image acquisition, partitions, retained corrections, controller restart, real local PPTX composition, scripted renderer and independent re-review, then exact mixed partial outputs. Original ceilings and semantic review obligations remain. |
| Inventory/image admission and paired acquisition | Free-form saved plans are rejected before native dispatch; a fresh registered subject producer and its independent review create the sealed projection. Direct HTTP and rendered reads share the original read allowance with per-reader receipts, confirmed outcome reuse and no uncertain replay. Three field schemas traverse acquisition, failed corrections, restart, actual local PPTX, scripted render, rejection/re-review and exact mixed partial export. |
| Image acquisition and saved render continuation | Existing bounded readers follow literal captured product links and reprioritize missing image coverage after each confirmed read; uncertain reads never replay. Saved layout pages seed revision zero with exact retained assets. A blocked but confirmed typed correction can continue in a fresh worker; uncertain producers and pending operation intents cannot. Historical review files remain inspectable without entering the current renderer's single-file input. The full graph runs across three field schemas through acquisition, two catalog corrections, section correction, restart, actual local PPTX construction, scripted rendering, independent re-review and mixed partial export. |
| Discovery and workload continuation | Saved search titles and captured listing entities can enter a provisional visual pool without verified buying facts or an approved catalog. The existing image operation retains exact captured image associations before catalog construction; unknown buying fields cannot be promoted from discovery titles. Fair bounded pools retain omitted leads, ambiguous images remain missing, and altered source hashes cannot rebind photos. A deferred inventory keeps its original semantic ceiling through resolved correction workloads. Across three schemas, actual compiled partitions, two failed amendments, revision-zero continuation, request-23 inspection, restart, retained photos, local PPTX, independent rejection/recomposition/re-review and mixed partial export execute within original grants. Text inventory hashes are not image-reference hashes; visual references retain exact pixel binding. |
| Record transport efficiency | Explicit compatible baselines initialize scoped revision-zero records without model resubmission. Guarded amendments survive restart across three field schemas; independently executed bounded review batches retain every exact-item verdict. Stale members, duplicates, oversized batches and conflicting retries fail atomically. Bounded exact initial text retains omissions and does not imply pixel observation or acceptance. |
| Correction and delivery | Invalid proposal corrected within its original allowance; two substantive corrections and exact re-reviews; inherited evidence retained; actual controller exit-75 restart before receipt collection; text composition and final completion; uncertain peer with draining and mixed partial labels; rejected proposals; uncertain exact reviewer |
| Correction export handoff | New worker amendments export exact retained or appended sources; another worker consumes the export after restart; typed independent re-review, real native admission, slides/document composition, local PPTX photo bytes and exact partial file export. Blocked semantic work does not erase proven capture ancestry; legacy serialization is reconstructed exactly; uncertain/pending/forged exports fail closed |
| Review dependency handoff | Rejected inline candidates retain exact collected inspection evidence through two fresh corrections, restart, independently executed reviews and partial export. Historical inspection reuse binds the producing attempt and committed output hashes, without adding an approval dependency on rejected work. Current candidate waits and explicit dependencies remain; uncertain, pending, missing, altered and ambiguous evidence cannot trigger replay or acceptance |
| Complete correction and coverage | Literal EUR/GBP spans retain currency and exact offsets; ambiguous/range selections fail. Request 23 retains existing export-read authority under the 24-request ceiling. Exact history pages fit remaining context across four transports with verified continuation offsets; a real scripted owner delegates after a constrained page, then corrects/reviews/restarts/exports. Prepared queries visit each subject before deepening; fallback prioritizes zero/low coverage without new queries or capacity. A composed local PPTX chain retains photos through fresh catalog corrections and restart, executes structured independent review, corrects the catalog after rejection, recomposes, actually executes re-review, drains an uncertain peer and exports exact mixed-label partial files |
| Photo and working context | Twice-amended registered records retain uniquely bound page/image receipts through composition and local PPTX export across three schemas; ambiguous, changed and foreign sources fail closed. Oversized read results remain hash-addressable through existing history pages across four transports; owner correction, restart, review and partial export proceed within unchanged limits |
| Visual selection and standalone inspection | Inventory-wide discovery precedes page reads; original search sessions and a bounded candidate pool are retained without extra queries or reads. Explicit visual judgments count distinct suitable designs independently of unknown buying facts. Six synthetic candidates yield three distinct choices, a provisional lead and an exclusion; duplicate seller/variant identities do not increase coverage. Original image observations are required for both selection and independent acceptance. Fresh amendments, restart, retained photos, local PPTX, independent rejection, correction/re-review and exact partial export execute. Completed standalone inspection outputs survive semantic rejection through immutable artifact bindings; pending, uncertain or altered evidence cannot trigger replay |
| Compiler record transfer | Public owner intent crosses automatic partition thresholds with visual and legacy policies. Every declared semantic parameter has an explicit transfer mode; missing mappings or generated consumer mismatches yield an effect-free compiler hold. Eleven-subject graphs across three field schemas execute partition workers/reviews/merge, visual selection, fresh partitioned corrections, request-23 export reads, restart, retained photos, local PPTX, independent rejection/recomposition/re-review and mixed partial export under original limits |
| Failed correction continuation | Two confirmed failed correction workers preserve exact sealed records and source exports. A fresh worker inherits revision-zero records only after frozen-assignment, terminal receipt, procedural collection, report and every projection hash agree. Partition scope survives restart; guarded amendments retain prior corrections. Changed existing-option submissions fail atomically. Three field schemas traverse the public compiler, corrected partition reviews/merge, local PPTX, independent rejection/recomposition/re-review and mixed partial copies. Pending, uncertain, missing or altered checkpoints remain ineligible; no historical acceptance or rescue |
| Registered baselines | Two registered amendments and reviews, explicit target-three gaps, missing format projection; exact source retention; incompatible, uncertain, tampered and equal-byte distinct baselines refused |
| Handoff construction | Lossless raw intent, collision-free paths and reuse of exact inherited inspections; compiler-owned metadata cannot be supplied by a worker |
| Database contention | Real WAL readers/writers and stale snapshots, bounded writer waiting, nested rollback, no transaction-body replay, catalog lookup composed with amendment/review/restart |
| Exact review | Rejected/stale/uncertain snapshots, retained evidence, combined exact candidates; terminal draining never dispatches new work |
| Partial export | Reviewed, requires-attention and unreviewed files retain exact identities; uncertain producers excluded; corrupt/missing bytes withheld; missing formats visible; local handoff deduplicated |
| Process and restart | Actual common launcher/controller/supervisor/text-worker subprocesses; committed restart, no duplicate dispatch, source-only execution with incidental/poisoned caches; missing/foreign receipts never establish completion. Frozen shared source checks before requests and tools stop on drift while retaining received responses. Owned local child/grandchild cleanup is verified; a denied probe requires independent process-table evidence of absence, otherwise cleanup remains uncertain |
| Gate controls | Empty/skipped/expected-failure suites and stale/incomplete receipts fail closed |
| Installation delivery maintenance | Exact pending intents bind preparation; active work or changed intents block. Existing channel controls pause transport before sender shutdown. Verified stopped senders permit an atomic uncertain transition with original rows in the database journal. Interrupted transactions roll back; interrupted installs retain the pause and uncertainty across restart without replay. Healthy installation restores exact channel preferences and intake cursors. Native service/signing/archive calls are controlled adapters in these fixtures, not installed-app evidence. |

The maintained selector matrix lives in the runner. A shared boundary change needs
a meaningful regression and an affected composed path, not just a check of the
newly failing component. Add broadly applicable regressions to the maintained
matrix; run the full matrix when the scope criteria in `AGENTS.md` apply. Boundary probes may inject malformed
receipts or states deliberately; they are distinct from the complete reference
lifecycle. The reference graph also crosses an actual common-launcher controller
restart, retaining controlled worker observations while using the original
database and tool receipts. A separate text test covers real supervisor/worker
subprocesses. Neither proves every failure permutation has been tested.

Failed correction continuation uses the existing baseline and record lifecycle,
not a second recovery controller. A versioned proof binds the producing attempt,
confirmed terminal receipt, collected outputs, source export, parent and original
findings. The owner brief exposes eligible checkpoints; the fresh worker receives
the exact assigned records at revision zero and the unresolved findings. Only
guarded amendments change them. Semantic rejection remains rejection until an
independent review of the new exact candidate. Incomplete or uncertain exports
remain outside this sealed-checkpoint path.

Source checks are fail-closed barriers before requests and tools, including after
a provider response is saved. They do not create an immutable filesystem or reload
an active worker. Process-table absence can resolve a denied probe of a vanished
owned group; denial involving a present group or unavailable observation remains
uncertain. Controlled checks do not resolve historical cleanup incidents.

## Limits and evidence

The new reference lifecycle retains ceilings of concurrency 3, 60 tasks,
24 owner invocations, three attempts, and per-task 1800 seconds, 100 tools,
24 provider exchanges, 16384 response tokens and 100000000 output bytes.
Provider cooldown remains two retries with delays 30/90 and maximum wait 180.
Registered content uses options_per_item 3 and count_policy target. A disclosed
shortfall is not acceptance and does not authorize more work. Focused boundary
probes can use smaller deadlines to exercise exhaustion quickly; these do not
alter production allowances. Scripted model responses are explicitly synthetic.

The newest completed full audit-matrix execution preserves per-test outcomes, original requests, supplied context,
tool declarations, responses, rejection/review receipts and SQLite journals where
the fixture supports retention. The runner hashes all retained evidence and the
runtime/test/gate sources. AUDIT.md indexes those original files; tests.log retains
failures. Unknown provider usage is not inferred as zero. Outbox tests inspect
local rows only; no message is sent to an external service.

For targeted tests, use temporary fixtures and retain compact results on success.
Retain useful failure logs and minimal reproduction inputs; keep large trees only
when diagnosis or an explicit audit requires them. Existing evidence and live runs
are not disposable fixtures. Live journals are outside lifecycle retention.

The full runner automatically keeps the newest completed run's fixture journals
in each output parent. Once another run completes, older runner-owned directories
retain their original report, source fingerprints, per-test outcomes, AUDIT index,
tests.log and process.log; their bulky group/journals trees are retired. This
also applies to old failed runs: useful traceback/result logs remain, while the
newest failed run retains its complete captured fixtures. Active run locks and
unfinished markers protect concurrent and interrupted work. The lock mechanism
uses the existing host adapter. No live workflow, database or backup is targeted.

Lifecycle retention has explicit ownership markers and checks original evidence
hashes before deletion. Modified, linked and unregistered data is skipped.
retired-evidence.json records retirement before removal and supports resuming an
interrupted cleanup. Original pass/fail reports are never rewritten, and --verify
rejects retired receipts rather than presenting compact logs as complete evidence.
cleanup.json records cleanup outcomes separately from qualification results.
Legacy directories without ownership markers are not automatically adopted;
their cleanup still requires an explicit reviewed migration. There is no timer
or background cleaner: retention runs at the end of future full-gate commands.

Network transport is denied in gate test processes. Actual subprocess tests use
small local scripts. No live model, browser, native application or paid API is
part of this gate. Minimal local presentation files test structure only. Research
yield, model judgment, pixel quality and installed native-host behavior remain
separate live/installed qualifications; a pass is not universal semantic approval.

Photo rebinding establishes retained page/image provenance, not product identity,
variant suitability or recommendation approval. Context paging preserves the exact
read receipt and call pairing; the owner must read needed passages through the
existing history tool. Effect receipts and pending correction exchanges are not
paged, and required state that exceeds capacity still stops before another request.

The correction-export graph uses a controlled image download and local PPTX file;
its final native inspection deliberately reports uncertainty, leaving the deck
unreviewed and PDF missing in partial delivery. It does not launch a native renderer
or run the binary reviewer. Typed catalog reviews use scripted independent judgments.
Unchanged source exports retain original bytes. Historical canonical serialization
can be reconstructed exactly from bound parents; arbitrary JSON equivalence is
not evidence identity. Option IDs identify content versions and change on amendment.

The review-dependency lifecycle continues through actual scripted independent
review and partial export after two corrections. Its opaque documents contain
small text and its registered previews are tiny synthetic PNGs; no native app or
visual-quality judgment is implied. The real owner/compiler, worker operation
receipts, pixel transport, review bindings and export code run. This complements
the local-PPTX correction-export test's deliberate final-inspection uncertainty;
that earlier test alone does not qualify dispatch of a corrected binary reviewer.
Historical inspection evidence may be reused after semantic rejection only when
the original completed attempt and exact committed candidate/output bytes verify.
It is not a new accepted baseline, a task-state repair or permission to drop an
explicit dependency. New candidates still wait for their own inspection/review.

The complete-correction fixture composes a real local PPTX, then supplies a valid
blank PDF and tiny synthetic page PNGs through a controlled renderer response.
It executes typed independent rejection and re-review around another fresh
catalog correction and recomposition, followed by exact partial copy export.
These scripted judgments qualify the complete handoff, not content, native
application compatibility or pixel quality. The earlier uncertainty fixture stays
mandatory. Coverage ordering preserves authored queries and existing ceilings;
it cannot guarantee that three distinct suitable products exist or can be verified.
History-page fitting preserves the original journal and verifies its archive hash
before shortening only the returned text and updating its exact continuation offset.
It does not replay the read or page an external-effect receipt.

Visual selection is explicit opt-in catalog state. Legacy catalogs retain their
historical interpretation. Models assess appearance and design equivalence;
code validates observed image hashes, derives counts and projects only the
distinct suitable shortlist. Unknown price, dimensions, stock or delivery remain
separate disclosures. A hash proves observation/provenance, not visual judgment.
Reviewed record-range merges preserve the same visual policy across three field
schemas and reject mixed policies, allowing bounded catalog/photo partitions.
The visual lifecycle uses tiny synthetic reference/product images and scripted
assessments; its pass cannot establish real product suitability or guarantee
three options for every item. Completed standalone inspections bind the exact
frozen execution, original terminal/materialization receipts and collected bytes.
Their rejected semantic status remains unchanged; no accepted baseline is inferred.

Record transfer metadata accounts for the complete registered semantic schema.
Call parameters are projected explicitly and checked against the actual consumer
schema before admission. Artifact-derived policy comes only from exact sealed,
independently reviewed partitions; all partition policies/source versions must
agree. Unknown new semantic fields cannot silently disappear. Compiler defects
produce a typed no-effect hold through existing recovery, without asking the model
to rewrite generated internals or increasing grants. Historical captured connector
contracts are never silently rebound. The 11-subject composed fixture has six
synthetic leads for one subject and honest gaps for ten; it tests orchestration,
not a claim of three real options for every subject. Three content field schemas
share this compiler path. Original sources, policies and review bytes remain bound.

### Exact baseline parameter inheritance

Registered correction preparation resolves the exact eligible baseline before
semantic validation and workload planning. All public semantic schema properties
are copied by code; supplied conflicting values reject without admission. New
content still requires complete choices. The registered-baselines group covers
omission, matching subsets, conflicts, ambiguity and schema evolution. The three
failed-correction compiler paths now omit correction parameters throughout,
including fresh blocked-checkpoint continuation, retained photos, composition,
independent re-review and partial delivery. Synthetic pixels and scripted judgments
do not establish live visual quality or universal input compatibility.


Ordinary owner execution is a required release group. It exercises direct saved
text, exact current-version inspection, inherited output checks, duplicate-save
reuse, confirmed HTTP/rendered fallback and retained reads, uncertain-read holds,
partial delivery, service admission without a plan card, and the existing text
export. These fixtures use scripted provider decisions and transports. They do not
prove article availability, semantic summary quality or installed routing behavior.

Independent plant/component schema paths in the acquisition/render and discovery groups run as separate mandatory processes, like inventory/acquisition. The ordered scenario selectors and assertions are unchanged, and every process retains the 180-second deadline. This partitions the offline harness only; no production grant, retry allowance or scenario is widened or omitted.

The reusable-node-bindings group qualifies typed custom fields and literal defaults,
required run values, unchanged drafts/version 1/version 2 captures, UI bridge
validation, invalid/missing output references, incompatible media, dependency
cycles (including file bundles), foreign/tampered templates, and exact-file
compilation into the existing Runtime. A missing-value rejection is followed by
binding the same template, one registered synthetic page read, dependent model
work, restart observation, idempotent admission and exact unreviewed delivery.
Transport/model replies are scripted offline; app/model execution is separate.

Public-read recovery also requires exact cancellation-receipt checks for browser
request settlement and a captured-product alias through discovery/image download.
A cancelled optional request is tolerated only with the same browser network ID;
unconfirmed errors, main documents and denied requests remain failures. Product
aliases require a shared explicit identifier on the same capture and no conflicting
identifier, variant or URL evidence. Separate local Chromium probes are not part
of the network-denied gate and do not prove public website availability.
