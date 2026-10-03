# O15 — native Computer Use, starting with Safari research

Status: **O15.3 worker integration, visible ownership and dynamic refresh implemented; background Safari adapter, raw-source review and bounded writing recovery installed in 0.13.121**.
New automatic scopes use the [background Safari route](#background-safari-scripting).
The foreground visual route and its earlier qualification are described below.
The planner can compose a configured `*-computer` worker in a saved pipeline using
`computer.use`, alongside existing file/Python workers and independent reviewers.
It uses the shared API loop and supervisor; it does not require a separate agent
implementation for each research job. Local 0.13.116 adds automatic window startup
and a bundled helper; installed/native qualification is tracked in ROADMAP.md.

The first live X development trial read a profile, scrolled and opened replies,
then blocked when the page text changed before another scroll. The new worker path
returns a fresh observation and token with `action_executed=false` in that case.
The worker must inspect it and choose its next action; Relay never replays the old
action automatically. Bounded observation-only settling preserves strict window,
process, tab, URL and foreground checks.

A real local Safari qualification now passes: initial observation, a synthetic
page update that suppresses the queued scroll, a new decision to navigate, and a
saved output/report. A second native check verifies the visible **Take over**
button: its durable receipt cancels the session before the pending action. Both
used a scripted provider with zero paid calls. The ownership panel shows the
worker/task, current action or waiting state, and Pause / Stop / Take over. It is a
non-activating helper panel without a second Dock icon. Pause ends this attempt;
continuation requires explicit reconciliation, not a silent resume. An already
in-flight provider request can return and be saved, but no further action follows.

Local 0.13.116 packages the native helper and supports automatic startup. The
current change passed 74 focused checks and 44 affected executor/planning checks;
a subsequent nine-check startup run includes permission failure before dispatch.
The installed interpreter/worker/helper completed synthetic launch, scroll and
navigation with verified receipts. The configured Gemini computer profile is
available without a manually selected target. Background-to-foreground activation
passed in the development native run; the installed runs began with Safari already
foreground. A real native session stopped before its queued action after a
controlled takeover event. The UI tool could not identify the accessory helper
reliably, so this does not qualify an installed button click. No paid X worker or
complete prospect-research job ran. Scope/order: [ROADMAP.md](../ROADMAP.md#o15--native-computer-use).

### Visual worker windows (earlier foreground transport)

For an explicit visual scope, the planning payload uses a `new-window`
launcher. A task declares `computer: {selection, url, allowed_urls, max_seconds}`;
the planner resolves the exact URLs and helper identity into the approval preview.
No user window IDs or manual target-selection commands are needed. Before the
first provider request, the worker checks native permissions, commits a launch
intent, opens Safari if needed, activates it once, creates a new normal window in
Safari's default profile, opens the approved initial URL and binds that window/tab.
This uses the default profile's existing sign-in; it does not copy cookies or
choose a different profile automatically. A login challenge remains a blocker.

The ownership panel is visible during startup. After initial activation, focus
loss or ownership release blocks further actions; Relay never steals focus back.
Only the new window's address field is used. Startup enables its tab bar if needed
for continuous tab identity. Existing windows/tabs are left intact, and completed
or interrupted task windows remain open for inspection. Unknown startup outcomes
must be explicitly reconciled/stopped, never replayed. A fresh approved attempt
creates a new window. The manual session runner cannot launch managed windows.

The helper is compiled during packaging, signed with the app identity, and its
receipt is finalized after signing. Runtime discovery never compiles, opens Safari,
or prompts for permissions. macOS Accessibility/Screen Recording grants and an
unlocked session are required; the worker reports a missing grant before launch.

### Selecting an existing worker target (optional)

Build a new helper, inspect `computer-use windows`, and use
`computer-use worker-target --helper /absolute/Relay.app --spec-file /absolute/spec.json`.
The spec uses the existing session shape: exact process/launch/window identity,
initial URL, 1–10 exact allowed URLs across at most three origins, `actions: []`,
`capture: false`, `local_fixture: false`, and `max_seconds` at most 300.
Selection validates the current document, freezes the helper identity and writes
the private host target. It does not start a model or research job. The planner
receives the selection ID and resolves `computer: {selection: "…"}` against that
frozen target. Model output cannot substitute another window/helper/URL grant.

A normal approved pipeline stage creates and supervises the worker automatically.
Its tools are `computer_observe`, `computer_navigate` and `computer_scroll`, plus
declared text-file tools. A binding observation and the ownership panel precede
the first model request. Text is sent to the chosen provider; screenshots are not
part of this profile. Configured credentials/model and source identities stay
fixed. Changing the selected target requires a new scope. Calls, provider requests,
output bytes, evidence bytes and the five-minute session deadline remain bounded.
There is one native host lease and one attempt; lost outcomes require recovery.
Saved native evidence stays in the existing pipeline job's authoritative database.
Approved standalone production graphs register the native session under their
existing result/export job identity; no shadow job/database is created.

For explicit selection, use a dedicated Safari task window in the already signed-in
profile. Relay binds that selected window. Automatic startup instead creates a new
window as described above; neither route launches an isolated Safari profile or
moves focus back after user takeover. Equal window bounds are disambiguated by an exact,
unique title match; identical titles/bounds still block. Later navigation retains
the exact AX window object and selected tab. No typing, social buttons, login,
credential access, arbitrary clicks or background-control claim is added.

Remaining qualification: a bounded configured-model X case, exact post/link
discovery beyond the approved URL list, complete evidence review/dossier, and
installed permission/upgrade/controls behavior. Dynamic updates that never produce
a stable observation remain a truthful blocker.

## Immediate research milestone

The user-facing goal is X research in an already signed-in Safari session through
Relay's own Computer Use implementation. Synthetic navigation and saved-text
review establish components, not completion of that goal.

Candidate discovery belongs to Relay; the user need not supply a profile URL.
The next checkpoint is one complete candidate dossier. Discover a relevant
operator, then use their real X profile or post to read visible text,
inspect a bounded sample of posts/replies with native navigation and scrolling,
and save source URLs, observations and explicit coverage gaps. Corroborate relevant
claims through public professional sources, and return a KEEP/REJECT/HOLD decision
with evidence about workflow, existing automation and the remaining manual work.
Use the live case to
identify any missing X-specific text/link discovery or interaction support, then
qualify the connected research worker on the real site. A development trial need not wait for full
installed packaging; it does not establish installed support.

The eventual prospect job needs evidence-backed candidate notes about concrete
work, current tools/automation, remaining manual tasks and public responsiveness,
with qualify/reject/hold decisions and outreach drafts for human review. Completion
means the requested 20-person shortlist (or an honest shortfall at an agreed limit),
prospect and rejection workbooks, source evidence, dossiers and unsent drafts.
X is one source; revenue claims and indexed summaries alone cannot qualify anyone.
An isolated
schema test or a generic profile summary is not that deliverable. The exact
personal research brief and trial records belong in ignored local storage.

## Development interface now available

`python3 -m task_relay computer-use` provides `build`, `status`, `windows`, `worker-target`,
`request-permissions` and `observe`. The Swift source is a package asset; a
development build requires Xcode command-line tools. A release must later package
a prebuilt signed helper rather than compile during user setup.

```sh
python3 -m task_relay computer-use build --out /absolute/path/RelayComputerObserver.app
python3 -m task_relay computer-use status --helper /absolute/path/RelayComputerObserver.app
```

Builds target macOS 14+ and use bundle ID `org.taskrelay.computer-observer` with
ad-hoc development signing. The adjacent `.build.json` pins source and executable
hashes; calls check both and verify the signature. Changed source needs a new
explicit build. Existing bundles are never overwritten. The helper accepts fixed
JSON operations through one-shot child-process stdin/stdout pipes, with no listening
endpoint, arbitrary code or output-path access.
One-shot launches initialize AppKit as an accessory before ScreenCaptureKit uses
the display connection; the helper does not activate itself.

`status` neither prompts nor reads pages. `request-permissions` explicitly requests
Accessibility and Screen Recording access, which the user must grant in macOS.
Prompting does not imply a grant. Permission attribution to the helper versus its
launching app and retention across upgrades remain unqualified; ad-hoc signing
does not establish Developer ID/notarization or installed permission behavior.

After unlocking the Mac and granting access, `windows` lists Safari process/window
IDs, launch identities and a `focused` indicator without titles or URLs. The
indicator requires Safari to be foreground and its focused AX window to match
exactly one capture window by bounds. Identical window bounds are ambiguous;
resize the selected window before retrying. Select that exact focused window and
its currently displayed URL. The numbers below are placeholders:

```sh
python3 -m task_relay computer-use windows --helper /absolute/path/RelayComputerObserver.app
python3 -m task_relay computer-use observe \
  --helper /absolute/path/RelayComputerObserver.app \
  --pid 123 --launch-id 1234567890.000000 --window-id 456 \
  --url https://example.com/profile --request 'Read this selected page only.' \
  --out /absolute/path/new-observation --capture
```

Safari must already be foreground with that window focused when the observation
runs. The one-shot observation command never activates or navigates it. Use a controlled local page
before account-site qualification; `--local-fixture` allows loopback HTTP only.
Other URLs require HTTPS without credentials or fragments.

The helper requires one matching AX window and one active web area with an exact
Safari `AXURL`, then checks focus/process/document/text before and after the
observation. Safari's window-level `AXDocument` is unavailable in the native fixture
test, so it is not used as the loaded-page identity. There is no persistent tab
identity across CLI calls: each command
authorizes a fresh observation of the current exact window/URL. Within a call the
live AX document identity must remain stable; assignment continuity is O15.2.
Text is limited to 24,000 UTF-8 bytes of visible static text; editable controls and
nested documents are excluded. Optional selected-window PNGs include browser chrome
and are limited to 4096 pixels per side, eight million pixels and 10 MB. Known
visible editable controls, nested documents or truncated inspection block capture.
These conservative checks are not a universal secret/login detector and need native
qualification. Incomplete text coverage is explicit, never presented as a full page.

A new output folder saves exact `intent.json` before invoking the helper, then
`page.txt`, optional `viewport.png`, hashed `evidence.json` and `completed.json`.
Failure retains an incomplete/uncertain receipt; a crash may leave only the intent.
Existing destinations cannot be overwritten or replayed to repair missing output.
These are **unreviewed local diagnostic receipts**, not registered jobs. A host lock
serializes this route across data bindings. The separate O15.2 session route below supplies shared-database action records
and the native host lease. Desktop session setup and model-driven research remain
O15.3; no auxiliary database is introduced.

Checks run: `python3 -m unittest tests.test_computer_use` (11 controlled tests,
including native-abort recovery), CLI help, native Swift build/signature checks,
permission request/status and a loopback-only Safari fixture. The fixture proved
five exact visible text lines, a 575 × 838 selected-window PNG and wrong-URL
rejection. Its completed receipt and file hashes were verified; failed attempts
remain preserved. Earlier runs exposed foreground/identical-window ambiguity,
the unavailable window `AXDocument`, and an AppKit initialization crash, which the
successful fresh build addressed. A nonforeground target and an invalid window
were rejected. These are bounded development checks, not installed or account-site
qualification. Codex Computer Use prepared the fixture window; Relay's standalone
helper performed the successful text and pixel observation. Private build/check
records are under `outputs/computer-use-o151/native-fixture-20260928/`.

## Bounded development sessions (O15.2)

A finite manual plan can now be approved for an existing saved pipeline job.
`session-approve` records the exact request, target, exact allowed URLs, complete
ordered actions, helper build identity, output root and limits in the existing
shared SQLite database. It does not dispatch. This is a development CLI surface;
Desktop session setup, planner registration and provider execution are still open.

Example `session.json` (replace the target values using `windows`):

```json
{
  "target": {"pid": 123, "launch_id": "1234567890.000000", "window_id": 456},
  "url": "https://example.com/one",
  "allowed_urls": ["https://example.com/one", "https://example.com/two"],
  "actions": [
    {"operation": "navigate", "url": "https://example.com/two"},
    {"operation": "scroll", "direction": "down"}
  ],
  "capture": false,
  "local_fixture": false,
  "max_seconds": 300
}
```

```sh
python3 -m task_relay computer-use session-approve \
  --database /absolute/path/state.sqlite --job SAVED_JOB_ID \
  --request-key unique-request --request-file request.txt --spec-file session.json \
  --helper /absolute/path/RelayComputerObserver.app --out /absolute/path/evidence \
  --actor 'local user'
python3 -m task_relay computer-use session-run \
  --database /absolute/path/state.sqlite --id RETURNED_ASSIGNMENT_ID \
  --helper /absolute/path/RelayComputerObserver.app
```

Before Run, put the exact selected Safari window in front with its tab bar visible.
The first observation binds the current tab matching the approved window and URL.
The helper retains that native tab control for the life of its private pipe
session. It checks the tab, window, process, actual URL and observation text before
acting. Safari replaces page accessibility objects during address editing, so
retaining a page object across navigation is not a reliable tab identity. Missing
or changed tab controls block the session; hidden tab bars must be shown manually.
The one-shot `observe` diagnostic continues to work without a visible tab bar.

Navigation uses only the identified Safari address field: focus it, set the exact
allowed URL and invoke its advertised confirmation action. It checks the actual
loaded page afterward. Scrolling uses an advertised page-scroll action when
available, or Safari's settable vertical document scrollbar. The latter derives
an offset of at most 90% of a viewport from the document and viewport geometry.
There is no keyboard, arbitrary click, text-entry, clipboard or JavaScript tool
surface. Unsupported native controls/geometry block rather than switch mechanisms
outside this contract. Dynamic pages may need explicit recovery when text changes.

A host-user-wide lease serializes native diagnostics and sessions across Relay
data bindings. Its location is under the host user's `.task-relay/computer-use`;
it does not control human input or other applications. The helper never activates
Safari. An approval dialog may bring another app forward: return to Safari before
running. Readiness itself is not permission to choose another window.

Limits: up to ten exact URLs across three origins, 20 calls including initial and
recovery observations, five captures, 200,000 saved text bytes, 10 MB saved image
bytes and at most 300 seconds from the first Run. Requested plans with capture
have at most four subsequent actions. Recovery does not reset any budget. Native
pipe reads and writes have a timeout; lost replies are never resent.

Every action has a committed intent before the helper call. Receipts bind the
exact request and helper to hashed text, optional PNG and evidence JSON. Completed
duplicates verify saved bytes and return without starting a helper. Missing or
changed evidence blocks; it cannot be repaired by recapture. Native failures,
process death or publication failure retain unknown outcomes and block dispatch.
Consumed plan positions never run again, including after recovery.

Controls use the same `--database` and `--id`:

- `session-inspect` reads the saved assignment, actions and decisions.
- `session-pause --actor ... --note ...` or `session-cancel ...` stops future claims.
  An already claimed action may finish; these controls do not undo it.
- `session-resume --url EXACT_CURRENT_ALLOWED_URL --actor ... --note ...` requires
  the host lease to be free. The explicit decision skips any uncertain action,
  keeps its original unknown outcome, and starts with a fresh binding observation.
- `session-stop --url ... --actor ... --note ...` reconciles and ends a stopped
  session without dispatch. Use it for an expired or abandoned session. A fresh
  request key for the same job cannot bypass unresolved work.

The new assignment, action and decision tables are job-owned. Existing job-process
exports include their committed rows when synchronized. Job deletion blocks active
or unresolved sessions, includes settled owned rows, and preserves native evidence
files and the user's Safari data. The evidence route below supplies registered
downstream artifacts and explicit post-commit `.relay` synchronization.

Qualification: a native local fixture completed binding, navigation and scrolling,
with three verified text/PNG receipts. A second native fixture switched tabs after
binding and blocked the queued scroll. Controlled tests cover commit-before-call,
crashes after claim, lost replies, stale tokens/URLs, changed helper/evidence,
pause/cancel, explicit no-replay recovery, retained budgets and job ledger/deletion
integration. The private pipe transport also passed a small subprocess fixture.
Logs are under `outputs/computer-use-o152/`. Earlier failed native attempts were
preserved and explicitly stopped before new tests. Installed permission attribution,
redirect/permission-loss native qualification, other Safari versions and real-site
coverage remain open. No installed app, live job, provider or account-site research
was run or accepted.

## Desktop session inspection (O15.3, development)

The companion shows **Safari sessions…** when the connected data location has
saved native assignments, including during unfinished messenger onboarding.
This panel lists sessions in pages of 20 and shows the
exact approved request, frozen target/URL/action scope, helper build identity,
action receipts and recent decisions. Decision notes are clearly labeled excerpts;
the exact records remain in the database and CLI inspection. The view reads saved
receipt hashes only, without reading Safari or claiming the evidence files were
reverified or independently reviewed.

Pause and Cancel require a decision note. Each control atomically compares the
displayed assignment, action records and decision revision with current database
state. A changed receipt invalidates the old decision; refresh and inspect before
trying again. An already claimed action may finish. Cancel never resolves an
unknown outcome, restores an earlier page or authorizes another run. Lost control
replies require inspection instead of automatic retry.

This source panel operates on existing sessions only. Creation, Run, resume and
reconciliation remain explicit CLI steps. It neither requests OS permissions nor
starts native or provider work. Database reads do not create or migrate history.
Nineteen focused Python tests cover this integration and existing session recovery;
an isolated DOM/controller fixture covers escaped content, stale UI responses,
explicit notes and lost replies. A separate native development preview also showed
the panel during onboarding, required decision notes and saved Pause/Cancel for two
synthetic sessions. Its database recorded zero native actions. The panel layout was
inspected there; installed app execution remains unqualified. Records are under
`outputs/computer-use-o153/`.

Configured-provider X qualification remains open; the worker integration and
local scripted-provider qualification are described at the top of this document.
The separate frozen text-review route below has its own provider adapter.

## Saved evidence handoff (O15.3, development)

`evidence-export` freezes an exact handoff request and the settled session snapshot,
then creates a ZIP containing `pack.json`, `README.md` and numbered observation
folders. Each folder contains the original request, evidence receipt, text and
optional screenshot. The manifest includes source URLs, observation timestamps,
coverage limits, helper identity and the original action/recovery records. Original
local paths are included for audit, so treat this as a private research artifact.

```sh
python3 -m task_relay computer-use evidence-export \
  --database /absolute/path/state.sqlite --id ASSIGNMENT_ID \
  --request-key review-pack-v1 --request-file handoff-request.txt \
  --actor 'local user' --out /absolute/path/new-evidence.zip --sync-job
python3 -m task_relay computer-use evidence-inspect \
  --database /absolute/path/state.sqlite --id PACK_ID
python3 -m task_relay computer-use evidence-verify \
  --file /absolute/path/new-evidence.zip --sha256 REGISTERED_SHA256
```

Export requires a completed or cancelled session with no unresolved actions and at
least one completed observation. Reconciled unknown actions remain explicit gaps.
Every source file is read once, hash-checked and checked against its committed
action, approved scope and helper identity before those exact bytes are packaged.
The ZIP is limited to 16 MB. No native helper, browser or provider runs.

The committed export intent pins the manifest, destination and ZIP hash before
publication. Repeating the same request key cannot change the request or target.
A completed duplicate verifies its registered artifact without rereading original
observations. An interrupted export can finish from its exact saved ZIP or rebuild
the same ZIP from unchanged frozen source bytes. Existing damaged output is never
overwritten; missing or changed registered evidence blocks rather than recaptures.
Artifact registration and the ready-pack record commit together. A crash may leave
an unreferenced file; it does not authorize replay or create accepted evidence.

The result includes an artifact ID, SHA-256 and an `input` descriptor suitable for
an explicitly authorized downstream task. This does not dispatch a reviewer or
change any existing plan. `--sync-job` publishes committed records into the job's
`.relay` view. A view failure is reported separately; repeat `evidence-inspect
--sync-job` to retry publication without recreating the pack. Pack registration is
job-owned, and downstream references prevent deleting the source job's history.

Offline verification checks the bytes against a separately supplied trusted hash;
it makes no claim about source truth, full-page coverage or user acceptance. Packs
remain **unreviewed**. Reviewers must treat page content as untrusted data and keep
claims within the recorded visible coverage. The text reviewer below produces its
own version-bound review artifact without changing the original pack.

Controlled checks cover publication/registration interruption, corrupted sources
and artifacts, duplicate requests, explicit uncertainty, job ownership and `.relay`
export. A copied native fixture also exported all three previously saved text/PNG
observations and passed offline verification without opening Safari. Private check
records are under `outputs/computer-evidence-o153/`.

## Independent saved-text review (O15.3, development)

`review-prepare` freezes the exact review request, explicit claims, pack artifact
and hash, Gemini model and output budget. It prepares no more than 240 KB of saved
visible text, URLs, timestamps and coverage metadata for one fresh tool-free call.
It excludes screenshots, original local file paths and producer conversation.
No previous review conclusions enter this context. Preparation is local and free.

Each claim has an `id`, literal `text` and `scope` of `visible_text` or
`beyond_pack`. Use the latter for image-dependent or broader claims that the
captured text cannot establish. The reviewer returns supported, contradicted or
insufficient for every claim, exact text citations, explanations and limitations.
The runtime rejects missing/duplicate findings, invented quotes, image citations
and resolved beyond-pack claims. Exact quotations prove citation integrity, not
that the model's interpretation is correct. Support is limited to the saved text.

```sh
python3 -m task_relay computer-use review-prepare \
  --database /absolute/path/state.sqlite --id PACK_ID \
  --request-key review-v1 --request-file review-request.txt --claims-file claims.json \
  --actor 'local user' --model EXACT_CONFIGURED_GEMINI_MODEL --max-output-tokens 2048
python3 -m task_relay computer-use review-inspect \
  --database /absolute/path/state.sqlite --id REVIEW_ID
python3 -m task_relay computer-use review-run \
  --database /absolute/path/state.sqlite --id REVIEW_ID --allow-provider-call
```

`review-run --allow-provider-call` explicitly authorizes one billable Gemini request
with that frozen text context. No tools, browsing, screenshot transmission,
conversation history or provider fallback are available. Limits are one call,
256–4096 output tokens, a 120-second request timeout and a 200 KB saved response.
Native usage is retained; these limits do not promise a particular dollar cost.
New requests freeze a JSON response schema alongside their instructions and send
it through Gemini's structured-output configuration. Previously prepared requests
keep their original format contract. Literal citations and claim scope still
require local validation; a schema alone does not establish correctness.
The provider schema uses types, required fields and verdict enums. Array bounds
and extra-field rejection are enforced locally rather than in the provider schema.

The submitted intent commits before the call. Unknown outcomes are never resent,
including through an already prepared alternate review. `review-stop --actor ...
--note ...` acquires the dispatch lease, cancels a prepared review or explicitly
reconciles an unknown result without changing its original unknown status. A new
review requires a fresh request key. Lost results do not become acceptance.

A saved response is validated before its JSON report becomes a registered artifact.
Invalid responses remain inspectable and cannot automatically trigger another call.
`review-finish` retries local publication from saved response bytes after a crash;
it needs no provider credentials. Completed duplicate runs verify the existing
artifact. Pack corruption or a changed review blob blocks use. The result declares
both the evidence pack and review artifact as downstream inputs. Review rows,
responses, usage, reconciliation decisions and artifacts remain job-owned and
appear in the process ledger. Optional `--sync-job` exports after commit.

Controlled scripted tests cover exact citations, broader-scope rejection,
no-replay recovery, version changes, artifact publication and downstream ownership.
Scripted reports are labeled `scripted_fixture`; they are not semantic model reviews.
Live reports use `provider` execution mode. Neither mode accepts the research on
behalf of the user. The first authorized provider trial returned the expected
three synthetic-text verdicts, but failed publication because `limitations` was a
string instead of a list. Its original response and usage remain saved as invalid;
no retry of that request was dispatched. A separately authorized second request
with the corrected schema returned HTTP 400 (invalid argument), without a model
report or usage receipt. The provider did not identify the rejected argument.
Relay conservatively recorded the call exception as `uncertain` and blocked
replay; the CLI receipt retains the HTTP error. Under a subsequent explicit
repair authorization, that attempt was reconciled without changing its original
status, and a new request with simpler schema constraints completed successfully.
The three expected verdicts, literal citations and limitations passed local
validation, and the report was registered. Only one new provider call was needed.
The successful trial used the same model, claims and 2,048-output-token budget;
it supports a schema-compatibility diagnosis but does not isolate a single
rejected constraint. Earlier responses and recovery receipts remain preserved.
Provider errors now retain bounded, redacted field violations when supplied,
with status and uncertainty diagnostics saved in the review record. Twenty-six
focused controlled checks pass; the live result qualifies only saved synthetic
text, not real-site research or installed operation. Private check records are under
`outputs/computer-review-o153/`; no installed UI is enabled.

## Outcome and first supported scope

Let a Relay job inspect and navigate a user-selected, already signed-in Safari
window on macOS, then return a reviewable evidence pack. The first live target is
one profile, one relevant post and the replies visible within a bounded sample.
Report gaps rather than claiming a complete timeline or reliable access to X.

Computer Use combines observation, model-selected actions, native execution and
fresh observation. A standalone local helper will provide Accessibility text and
window screenshots through public macOS APIs. Relay will supply the worker loop,
frozen scope, provider integration, decisions, artifact handoff and recovery.
The feature must work without Codex, a Codex subscription or its private controller
package. A compatible configured model is required only for the agent-driven stage;
observation and controlled native tests do not need a model or paid work.

The first version supports an unlocked interactive Mac session and a visible,
selected Safari window. Foreground focus may be required for actions. It does not
promise background operation while the user works in the same app. A user takeover,
window/tab change or unexpected dialog pauses execution until the target is checked
again. The helper never closes Safari, signs the user out or copies session cookies.

The work is a separate native capability alongside managed Chromium research and
[delegated desktop browser tasks](desktop-browser.md). It does not replace those
routes or silently switch a frozen assignment between them.

## Architecture and ownership

| Layer | Proposed responsibility |
| --- | --- |
| Portable runtime contract | Versioned observations/actions, target identity, grants, limits, cancellation, action journal and evidence validation. No AppKit, Accessibility, ScreenCaptureKit or Tauri imports in shared core. |
| macOS host helper | A packaged, signed helper using Accessibility APIs and ScreenCaptureKit. Enumerate minimal selectable-window metadata; inspect/capture only the bound window; perform only registered native operations. Authenticate local IPC peers and bind requests to one assignment lease; an open local port is not authority. |
| Safari adapter | Resolve selected window/tab and actual URL, validate origin and document state, navigate through the address bar, and scroll the selected document. If URL or target cannot be established, block rather than infer from page text. |
| Worker | Use the existing configured provider and bounded tool loop; require verified text/tool capability, plus image input when screenshots support visual claims. Freeze model, adapter versions and limits. No provider fallback or arbitrary native code execution. |
| Relay Desktop | Explain required OS access, allow target selection, preview scope, show running/paused/blocked state and expose Pause/Stop. The shared runtime enforces these decisions; the UI is not their authority. |
| Evidence and review | Register immutable observations and files; pass the exact evidence pack to an independent reviewer and then to file producers. Project committed process records into the existing read-only `.relay` view. |

The helper's public API and version handshake must be stable across the CLI and
desktop UI. Helper executable identity, signing, minimum macOS version and OS
permission attribution must be established in O15.1 before claiming availability.
Missing native dependencies or permissions report an unavailable capability before
provider dispatch. Windows/Linux adapters remain deferred; they must fail as
unsupported, not import or emulate macOS mechanisms. Locked-session work uses
the separate background Safari transport described below, never the visual adapter.

## Proposed assignment and tool contract

Freeze the exact user request and input versions with: host/session identity,
application bundle ID, process identity including start identity, selected window
and tab identity, allowed origins, permitted operations, output paths, capture/text
limits, provider/model, and action/time/usage ceilings. Ephemeral element references
belong to an observation and cannot survive a changed document or restart.

Initial proposed operations (names are design labels, not registered capabilities):

| Operation | Boundary |
| --- | --- |
| `observe` | Return bounded visible document text, relevant accessible controls, URL, target identity, capture time and explicit truncation/unavailable fields. Do not enumerate unrelated tab content or read password/OTP fields. |
| `capture` | Save an explicitly granted selected-window image and provenance; check the binding before and after capture. No full-desktop capture or incidental notification content as a fallback. |
| `navigate` | Navigate the selected tab to an exact allowed HTTP(S) URL; production grants require HTTPS. Address-bar input is implemented inside the adapter, not exposed as arbitrary keyboard input to the model. |
| `scroll` | Bounded movement of the observed document, followed by a new observation. No key presses that could submit a form or operate a focused composer. |
| `stop` | Cancel further dispatch and release the owned lease after reconciliation; retain files and receipts, and leave the user's application open. |

The one-shot diagnostic exposes observation/capture only. O15.2 adds finite
manual navigation/scrolling sessions with the targeting checks described above. Arbitrary click, typing, keyboard shortcuts, downloads,
uploads, arbitrary JavaScript/shell, and site-specific message controls are outside
this first contract. Opening reply threads must use an evidenced allowed URL;
inaccessible threads remain explicit gaps rather than permission to click freely.

An origin grant checks the top-level page and what reaches the model; it is not a
network firewall for Safari scripts, redirects or subresources. Recheck the actual
URL before exporting text/pixels to a provider. A redirect outside scope, login
screen, challenge or unverifiable URL blocks further work. Website instructions
cannot expand grants, authorize new actions or supply recovery decisions.

“Research only” means a restricted tool surface, not a promise that navigation or
scrolling has no website-side effects. Automated engagement, likes, follows, posts,
DMs, contact forms, purchases, credential entry, password changes and challenge
solving are excluded. Manual sign-in remains the user's action; it does not grant
new website access or authorize replay of an uncertain action.

## Consent, targeting and operating limits

Separate OS permissions, the selected application/window, website scope and actual
job approval. Accessibility and screen-recording permission can be broader than
the job; the helper must enforce the narrower job binding on every request. Show
which page text/images will be sent to the selected provider. A grant to inspect
Safari is not a grant to unrelated sites, private messages or every open window.
Use existing [companion controls](../task_relay/assets/companion.html) and explicit boolean decision
results for review actions; a pending promise is never approval.

Use a single-owner Safari lease initially, covering window selection, capture and
navigation across all Relay jobs. Desktop-wide input, if needed, also needs one
exclusive host input lease. Internal leases do not prevent a person or another
application from changing the UI; validate fresh target/focus/document identity
immediately before actions and compare afterward. Unknown identity, closed windows,
revoked permission or a locked screen pauses/blocks; do not choose a similar window.

Proposed pilot limits per research worker: one selected window/tab, at most three
exact origins, 20 total observation/action calls, five minutes, five viewport
captures, 200,000 text-output bytes and 10 MB image output. The planner must validate
these against the selected worker and freeze explicit provider request/token limits
and any supported spend ceiling. A reviewer has its own disclosed budget. These are
planning defaults, not current implementation limits or approved spending. Missing
pricing stays unknown; unsupported budget enforcement must be disclosed before Start.

## Durable actions and evidence

1. Atomically record the approved assignment, request/grant digest and dispatch
   intent in authoritative shared SQLite. Commit before invoking the helper.
2. Claim each action by a unique assignment/action identity and exact arguments.
   Bind it to the current observation and target. Reject stale or conflicting reuse.
3. Save bounded evidence files to owned output paths; record hashes, lengths and
   completed outcome after verifying them. A completed duplicate returns its saved
   receipt without repeating the action.
4. A crash after claim with no proven result remains uncertain, including navigation
   and scrolling. Never replay automatically or generate a new ID to evade it.
   Missing output bytes cannot be repaired by repeating a capture silently. A
   deliberate fresh observation can aid reconciliation but cannot prove that an
   earlier action did not occur or clear its receipt automatically.
5. Reconcile uncertainty with an explicit recorded decision. Resume with a fresh
   target/observation and remaining approved scope; a changed target, grant or model
   needs a new assignment decision. Cancellation stops future dispatch but cannot
   undo a completed website action.
6. Publish `.relay` projections after committed state. Retry failed exports from
   saved records without executing desktop actions. Keep shared SQLite authoritative.

The evidence pack contains a versioned manifest and declared text/PNG files. Each
observation has assignment/action/observation IDs, source URL, UTC capture time,
helper/adapter version, selected target identity, content hashes, byte lengths,
visible excerpt/locator, source date when actually observed, and truncation or
access gaps. OCR/model interpretations remain derived claims, separate from original
AX text and pixels. A page observation is not proof that its statements are true.

A reviewer receives these exact registered files as declared inputs and checks
claim-to-observation support without repeating the search. This introduces an
explicit frozen-evidence review mode for O15; it must not silently relax the current
browser review contract that requires live inspection. Missing or stale evidence
causes a gap or a separately scoped fresh observation. A source pack is not a
prospect fact-revision adapter. Initial downstream workbooks can use a versioned
candidate ledger; automatic requalification remains separate.

Record actions, observations, gaps, provider usage and review decisions as job-owned
process records. Define their ownership/export/delete relationships before durable
integration; no unowned auxiliary database or second authority. Native inputs and
user browser data stay outside job deletion. Keep personal evidence and installed
permission/qualification receipts in ignored private storage.

## Build order and acceptance gates

| Step | Deliverable and completion gate |
| --- | --- |
| **O15.1 — observation foundation** | Development CLI/contract and ad-hoc-signed helper built; 11 controlled Python failure/recovery tests pass. After user-granted Accessibility, a native local Safari fixture proves exact text, selected-window pixels and wrong-URL rejection. Still open: installed permission attribution, upgrade retention and adversarial native target/permission-loss behavior. No model needed. |
| **O15.2 — bounded navigation and recovery** | Development CLI and shared-database action journal implemented. Local native navigation/scrolling and tab-switch rejection pass; controlled recovery, budget, pipe and ownership tests pass. Native redirects/permission loss, installed behavior and broader Safari qualification remain open. |
| **O15.3 — research worker and evidence handoff** | Planner/catalog integration, frozen configured provider, image-capability checks, bounded worker loop, independent frozen-evidence review, native file-producer inputs and `.relay` export. Scripted model fixtures verify no scope expansion, output linkage and export recovery. Review failures remain failures; produced evidence is not user acceptance. |
| **O15.4 — installed Safari qualification** | Package the signed helper, verify permissions and action controls in the installed app, then run one explicitly authorized real profile/post/reply sample through the selected provider. Compare captured evidence with the visible source and measure usage/coverage. Completion needs actual receipts, independent review and truthful gaps. No outreach or bulk campaign. |

O15.1/O15.2 development implementations are available with the qualification limits above. O15.1–O15.3 controlled checks precede
O15.4 live work; publishing code or passing tests does not authorize installation,
provider calls, account actions or a campaign. A five-candidate research pilot is
a later separately scoped job after the single-case route works.

Run only checks relevant to the step being changed. Prefer tiny synthetic text/HTML
pages and scripted provider responses for state, identity, recovery and evidence
tests. Native browser tests are appropriate here because browser interaction is the
capability under test, but unrelated media/modeling suites are not prerequisites.
Log exact commands, scope, results and limitations under `outputs/`; distinguish
controlled tests, native helper checks, installed checks and live-site results.

## Roadmap relationships and deferred work

O15 is the next newly planned user-requested native capability. Existing lifecycle
follow-ups, O13 installation work and O14 evidence quality work remain independent;
this feature does not redefine their completion gates. The O15 evidence pack shares
the O13 browser-receipt handoff need, but extending all existing browser workers is
not required for the first Safari observation proof. Job-owned database authority,
automatic prospect requalification, reusable procedure extraction, general desktop
editing, unattended multi-app workflows, Windows/Linux support and a 20-person
prospect campaign are not prerequisites or implicit scope.

Open implementation decisions to resolve in O15.1: helper placement and signing/TCC
identity; Safari URL/tab identity availability across supported versions; document
text coverage for dynamic pages; and reliable selected-window screenshot boundaries.
Use actual API/host observations to choose mechanisms; do not advertise background
control or complete webpage extraction until those behaviors are qualified.

## Public implementation references

- [Apple Accessibility APIs](https://developer.apple.com/documentation/applicationservices/axuielement_h)
  for accessible application inspection/control.
- [Apple window capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
  for selected-window capture and OS permission handling.
- [OpenAI Computer Use integration](https://developers.openai.com/api/docs/guides/tools-computer-use)
  for the model/runtime observation-action loop. Provider-specific APIs stay behind
  Relay adapters; this reference does not select a provider or grant execution.


## Background Safari scripting

New automatic scopes use `new-scripting-window` through the helper already bundled
inside Task Relay. This route does not activate Safari or require an unlocked
session; Safari must already be running and the Mac must stay awake. macOS
Automation authorization is checked before creating the research window or calling
a provider. Explicitly selected visual targets keep their foreground requirements.
A frozen scope cannot change transports during execution or recovery.

The adapter binds a dedicated one-tab Safari window to a process launch identity,
validates the exact URL before actions and after reads, and retains tokens, budgets,
committed intents and uncertain outcomes in the normal worker journal. The ownership
panel identifies background use; Stop/Take over and supervisor cancellation stop
subsequent actions. It never silently reopens windows or reclaims focus.

Local 0.13.131 sends its single create-document command through a bounded child
AppleScript process: in-process creation in the AppKit helper repeatedly timed out
on local fixtures. Numeric before/after ID snapshots replace live window iteration,
and the sole new window must have exactly one tab at the granted URL. The native
creation timeout remains eight seconds, with a twelve-second child deadline; a
lost acknowledgement remains uncertain and is never retried. This adds no extension,
worker-supplied script surface, foreground activation or broader URL authorization.
Version 0.13.132 verifies the bound Safari PID, bundle identifier and launch time
instead of rediscovering the process from a global list after each native action.
The successful local worker check is separate from live X and locked-session
qualification of these updates.

Version 0.13.133 percent-encodes non-ASCII path/query text while resolving new
worker plans, before hashing and freezing exact URL grants. Existing percent escapes
and ASCII query bytes are preserved; original planning requests remain in history.
Hosts must use ASCII/IDNA spelling. Canonical duplicates are rejected, and existing
frozen work is unchanged. Window creation uses one blank tab, identifies its exact
window, then assigns only the granted initial URL before recording any evidence.
After an acknowledged navigation, a bounded read-only wait permits only the exact
source while loading and requires the exact destination before evidence capture.
A third URL or failure to arrive stops the action; the URL setter is never retried.

Version 0.13.134 binds background sessions to kernel process ID, start timestamp
and executable path after initial Safari bundle discovery. It rechecks that same
identity before work, without relying on AppKit process-cache refresh. A terminated
process, changed start timestamp or changed executable still ends the session.

Safari's Allow JavaScript from Apple Events setting is optional for text reading and
navigation, and required for fixed viewport scrolling and dynamic DOM link discovery.
Only constant scripts are used; workers cannot supply JavaScript. Without permission,
the scroll tool is omitted and direct scroll requests fail before native dispatch.
HTML-source links may omit dynamic post links; loaded text is bounded and is not
proof of complete timelines, replies or source coverage. No login, posting, following,
liking, messaging or download surface is exposed.

The background route is developed inside one app. Qualification must distinguish
scripted/local checks from installed app permission identity and actual X coverage.

Installed 0.13.119 qualification: an app-associated Aqua background job ran the
real installed worker on two local pages, delivered its declared text output and
completed its journal using four scripted replies. A separate installed-native
X profile trial read loaded posts and dynamic post links and executed one scroll.
Both runs reported the Mac locked before and after execution; neither used paid
provider calls or screenshots. This verifies the bounded background transport,
not a full model-driven research pipeline or complete X source coverage.

A subsequent real configured-model profile job completed the research and reviewer
stages. Read-only auditing verified the output and native evidence hashes. The
requested scroll returned refreshed page evidence with `action_executed=false`;
the worker used the five loaded posts and finished without an executed scroll.
The reviewer received the researcher's summary and structured evidence, not the
immutable native captures. Thus its ACCEPT does not establish independent raw-source
verification. Raw-capture handoff and explicit unmet-action accounting remain open.
User acceptance and this production run's lock state are not inferred.

### Raw-source review and incomplete actions (0.13.120)

New reviewers of computer tasks automatically receive a registered, read-only JSON
pack built from the exact producer attempt's native journal. It includes raw page
text, observation IDs, capture times, URLs, coverage/truncation, original file hashes
and action outcomes. The runtime verifies receipt files and scope before reviewer
creation. It does not open Safari, recapture pages, or replace missing evidence with
the producer's own JSON. Packs obey the normal input byte limit; oversized or
changed evidence blocks before a provider request. Text reviewers must read omitted
source-pack pages before completing their review.

A `refreshed=true` navigation/scroll is a known no-effect receipt. Each observation
now includes `unexecuted_actions`; a later explicit matching operation can complete
it. Observing again or scrolling another URL cannot satisfy it. Successful finish
with remaining gaps is rejected with a correction message. The worker must make
an explicit next decision within its existing budget or report blocked and explain
the limitation. The supervisor enforces the same journal check; no uncertain action
is replayed. This tracks attempted actions with known outcomes, not an automatic
semantic parser of every requirement in the user's prose. The reviewer must still
judge the full request against saved evidence. Frozen legacy results are unchanged.

### Output-generation recovery (0.13.121)

A received generation limit or malformed local file-write/report response may use
one recovery per failure kind inside the existing request/tool/time allowance.
Every dispatched native action must be confirmed with no outstanding no-action
refresh. The entire incomplete candidate, including parseable calls, is retained
but never executed or inserted into the continuing model conversation. Missing
transport responses and partial native-call candidates remain terminal.

Recovery exposes only declared file tools and finish: Safari cannot be driven again
in that attempt. Workers save small substantive sections with `file_write`, followed
by byte-count-checked `file_append`; the final work request permits appends too.
No token budget is raised. Missing required research or exhausted allowance requires
a blocker. Pause, cancellation and ownership still stop the next request. This does
not automatically resume old blocked jobs or grant another paid production attempt.

### Research scope and claim audits (0.13.123)

New Safari plans with a JSON evidence file and Markdown summary receive a frozen
research delivery contract and a separate reviewer audit output. Explicit English
post ceilings such as “up to five visible posts”, “at most 5 posts” and “no more
than five posts” are recognized in the original request and assignment; the stricter
ceiling wins. The planner is instructed to preserve caps as “up to N posts”. This
does not parse every possible natural-language constraint. The preview shows the
frozen cap; the reviewer must still check the full request. Existing plans, attempts
and accepted artifacts retain their original contracts.

The cap applies to selected post records in the delivery, not incidental posts in
Safari's loaded document. Evidence JSON contains distinct post URLs, capture IDs,
literal timestamps and short excerpts. Profile facts are separate, labeled summary
claims: Observation, Inference or Limitation. Worker finish and supervisor checks
reject oversized post lists and unlabeled summary claims. A local correction can
use the remaining original budget; it does not create another native attempt.
Before reviewer dispatch, post URLs and excerpts must occur in the cited raw
capture. Missing or changed sources block; raw observations are never truncated to
make a delivery conform to its cap.

The runtime binds every summary claim and the exact candidate hashes into the raw
review pack. An accept decision additionally requires a structured audit covering
every claim, with a verdict, reason and literal source citations. Missing/duplicate
claims, invented quotes, changed hashes and unsupported/uncertain verdicts reject
acceptance. Coverage statements cannot substantiate profile facts or inferred
tooling interest. The model must judge the entire claim, its label and attribution:
an exact matching quote is necessary evidence, not a deterministic proof of
entailment. Neither a job title nor a platform problem proves expressed AI interest.

Review audits can be written in sections within existing request, response and
tool budgets. The normal Markdown review can still be generated from finish.
Acceptance remains a model judgment followed by the existing user selection gate;
no paid run, source expansion, old-result rewrite or automatic native retry follows
from this change.

### Exact citation correction before delivery (0.13.124)

The producer's finish now checks post citations against the same verified native
journal used by reviewer preflight. The supervisor repeats this check independently.
Citation errors identify the post and field. When only whitespace differs and one
exact captured variant exists, the error returns that literal slice, JSON escaped,
for the worker to copy. Flattened line breaks are still not accepted as verbatim.
Changed words, punctuation, dates, URLs or capture IDs do not acquire support from
normalization. Ambiguous whitespace variants receive no automatic choice.

The worker can correct local files using its remaining request/time/tool allowance;
validation itself never drives Safari, changes a capture or extends that allowance.
Reviewer support quotes receive the same exact-slice diagnostics. Tampered or
unresolved native receipts still block. Existing failed attempts are not resumed,
rewritten or retroactively marked reviewed.

A subsequent configured-model single-profile run passed saved-artifact validation
with five post records, exact captured citations, one executed scroll and a complete
14-claim audit. No local correction errors were recorded in that run. This verifies
the bounded execution/validation path. Semantic review still has limits: a suggested
inventory-automation benefit was labeled inference but accepted without specific
support. Hypothetical suitability is not evidence of expressed interest or demand.
This run does not establish a locked Mac session or broad prospect qualification.

### Twenty-person discovery qualification (0.13.124)

An authorized larger benchmark did not complete discovery. A Desktop-created plan
failed before Safari/model execution because the run's Telegram delivery binding
conflicted with Desktop plan ancestry. Using the existing Telegram planning route
allowed actual background Safari research, but only three of six search pages were
reached. Four navigation calls returned fresh observations without executing; raw
captures differed only in a changing countdown. The following model response hit
its generation output limit, and unresolved navigation prevented file-only recovery.

No candidate delivery or independent review completed. Read-only verification of
all eleven native receipt file sets passed size/hash checks. The original attempts
and source captures remain preserved in private storage. This exposes a navigation
freshness problem on volatile pages and a Desktop ownership handoff gap; it does
not invalidate the separately recorded single-profile qualification or establish
multi-person readiness. Fix these boundaries and use smaller discovery batches
before claiming a complete prospecting run.

### Workflow-owned research batches (0.13.125)

Multi-person research belongs to one durable Relay workflow. The orchestrator
chooses bounded discovery and research stages, passes reviewed sources onward,
retains rejections/holds and consolidates the requested total. The user should not
have to divide the people or manually request each next batch. Existing limits
still apply: 12 workflow stages, 12 tasks per production plan including reviewers,
and 300 seconds/20 native actions/10 exact URLs per Safari session. Intermediate
evidence may advance after independent review without implying user acceptance.
An unsupported full workflow must report its missing capability before dispatch.
This planning guidance is not an adaptive retry engine or proof of live completion.

Background navigation to an exact approved URL no longer requires identical page
text: incidental timers cannot prevent leaving the owned tab. It still validates
the latest token, Safari process, owned window and single tab, current URL, login/
challenge state and destination grant. Scrolling retains changed-text refreshes;
the visual adapter is unchanged. Captured evidence is never normalized or rewritten.

Desktop Start now transfers the unexecuted plan ancestry and production delivery
to Telegram atomically, preserving the previous channels and request/plan hashes
in a production event. Previously executed or foreign-channel ancestors reject
the transfer. Transferred plans remain inspectable from Desktop; existing failed
runs and their frozen assignments remain unchanged.

New 0.13.126 planning contexts enforce a conservative multi-page budget floor:
for N granted URLs where N > 1, at least 2*N+8 provider requests and tool calls,
and an explicit response allowance of at least 8,192 tokens. Planning rejects an
undersized proposal before dispatch, allowing the existing bounded correction to
split work into smaller reviewed workers or propose sufficient limits. It never
raises an explicit user limit. Single-page and historical frozen contexts retain
their contracts. This is a feasibility guard, not proof of full source coverage.
