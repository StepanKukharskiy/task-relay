# General website execution

Website task translation is shared with the orchestrator and all Gemini, OpenAI
and Qwen browser workers. It separates the destination, website task content and
Relay delivery/control instructions. Search fields receive a self-contained query;
other tasks retain their scoped actions. Exact quoted queries, identifiers, code
and supplied message/form text stay unchanged. The worker must preserve substantive
constraints and cannot invent missing locations or expand authorization. This rule
is independent of site naming or user phrasing; actual website support still
depends on the registered browser tools, scope and session.


Task Relay has `gemini-browser`, `openai-browser` and `qwen-browser` worker profiles
for bounded work on websites without a site-specific adapter. Each reuses its
provider's configured text model,
production scheduler, immutable assignments, independent review, usage records and
delivery paths. The Perplexity Search pilot remains a separate adapter.

OpenAI and Qwen execution requires that provider's API connection and a model
supporting function calling. Neither requires Gemini or the Codex app. Qwen here
means the configured Alibaba Model Studio API; local Qwen serving is not included.
Connect the provider and choose its default text model through `/providers`.
Model metadata checks establish catalog access, not tool compatibility or quota;
unsupported execution stops with its provider error and never changes providers.

This is a controlled implementation, not live qualification of ChatGPT, Perplexity
or every website. No live account action, paid model call, service reload or chat
delivery was performed for this change.

For reusable signed-in sessions, see [Account sites](account-sites.md). The
`accounts` profile adds an explicit site list, manual confirmation and optional
attachment to an existing local Chromium browser. Other profiles remain separate.

## Scope

The worker can open multiple explicitly managed tabs, inspect visible DOM text and
controls, navigate, fill empty text fields, select options, click, press a small set
of keys, wait and close its tabs. Each interaction names the observed tab, page
revision and control. A changed page requires another observation. Old tab IDs
remain in receipts after exit; a subsequent worker must open URLs explicitly.
It never adopts a tab by its position or repeats an old action to restore a session.
Observations include select-menu choices and bounded current field values. Full
non-secret field hashes detect edits beyond the displayed prefix; password/OTP
values and hashes are excluded. A changed draft invalidates an earlier observation
before a submit control can be used.

Each assignment includes this exact scope object:

```json
{
  "profile": "research",
  "origins": ["https://example.com"],
  "interaction_scope": "",
  "max_tabs": 3,
  "max_actions": 20,
  "uploads": [],
  "downloads": []
}
```

An empty interaction scope allows reading and navigation. A nonempty scope must
describe the actions authorized by the user's request. The model still interprets
that scope; this is not a semantic firewall for purchases, messages or account
changes. The reviewed plan must make those actions explicit when requested.
Website text is untrusted evidence and cannot authorize additional work.

Enforced boundaries include exact top-level document origins, profile ownership,
tab/action budgets, declared text file paths and stale observations. Site scripts,
subresources and background requests are not a network sandbox. Read-only jobs
block non-GET/HEAD/OPTIONS requests, which can also prevent some sites from loading;
navigation itself is not a guarantee that a site performs no server-side changes.
No arbitrary JavaScript, shell, cookie or credential tools are exposed to the model.

Uploads and downloads support UTF-8 text only in this first slice. Their paths must
also appear in declared inputs/outputs. Uploads verify the selected file hash;
downloads use the existing output byte limit. The convenience `prepare` command
does not grant transfers; use an authored graph with exact registered artifacts
for that work. Password and OTP fields, replacing existing drafts, canvas-only
interfaces requiring visual interaction, visual reasoning, arbitrary frames and automatic account
setup are outside this slice. Body text is capped at 24,000 characters per
observation; the controller considers up to 150 DOM controls.

## Viewport screenshots

Browser workers can save the current managed tab as a PNG through
`browser_screenshot`. The optional `browser.screenshots` list grants exact relative
PNG output paths. Each path must be declared as `image/png`, together with a
provenance output at the PNG path plus `.json` declared as `application/json`.
Older scopes without this list grant no captures. Uploads/downloads remain text-only.

For example, ask Relay in the paired chat:

> Open Google Maps at Parc de la Ciutadella, Barcelona, and capture one standard
> map viewport as study-location.png. Keep the location and Google's attribution
> visible. Return the PNG and its source URL and capture time. I will review the
> screenshot; stop before making a presentation.

On a runtime containing this change, the planner should show the browser executor,
exact website origins, `screenshots: ["study-location.png"]`, and the PNG/provenance
outputs before Start. This is a suggested first trial, not a verified Google Maps
workflow. Existing provider connection and browser setup requirements still apply.
The implementation has been exercised with a local Chromium canvas fixture and
scripted provider responses; installed-app and live Google Maps delivery are separate.

The tool takes `tab`, the latest `observation`, `path` and `purpose`. It captures
only the viewport, at CSS pixel resolution, with a five-second capture timeout.
There is no crop, automatic scrolling, full-page stitching or coordinate clicking.
Dimensions are limited to 4096 pixels per side and eight million pixels; the total
browser output allowance is 10 MB, with text outputs still capped at 200 KB.
PNG inputs have a separate combined 10 MB bound; text inputs remain capped at 512 KB.

The provenance records URL, title, UTC capture time, tab/observation, assignment and
action IDs, dimensions, byte count and SHA-256. Capture intent commits before work.
PNG/provenance files are written exclusively; prior outputs are not overwritten.
A repeated completed action returns its receipt. Failed or interrupted capture
remains uncertain and cannot be automatically replayed under another action ID.
Collection checks that the PNG and provenance agree before treating delivery as
successful. Normal artifact registration, downstream input copies and delivery apply.

PNG `file_read` returns container metadata only. Image pixels are saved locally and
are not sent to Gemini/OpenAI/Qwen by this tool. Capturing canvas content therefore
does not give the worker visual understanding or prove that map tiles loaded,
attribution is readable, or a study boundary is correct. Keep those checks for a
capable visual reviewer or the user. Native browser interaction remains DOM-based.

## Local use

Install the existing optional browser component and Chromium in the Relay runtime:

```sh
python -m pip install 'task-relay[browser]'
python -m playwright install chromium
```

In a source checkout, an existing `.venv-browser` is also recognized. The host
adapter selects the runtime; `TASK_RELAY_BROWSER_PYTHON` can specify its absolute
executable path. This implementation uses the existing POSIX host ownership
adapter. Native Windows browser execution is not qualified.

For a site requiring authentication, open a dedicated profile and sign in yourself:

```sh
task-relay browser general login --profile research --url https://example.com
```

Use additional `--origin https://signin.example.com` arguments for explicitly
selected sign-in domains when needed. Credentials remain in the local dedicated
browser profile. Pressing Enter saves the session; it does not prove authentication.
Profiles live below the configured data directory at `browser-general/<profile>`.
Names use lowercase ASCII identifiers to avoid filesystem case aliases. Profiles
do not share the user's normal browser or the Perplexity pilot profile.

Prepare a reviewable producer/reviewer plan from an exact UTF-8 request file:

```sh
task-relay browser general prepare --profile research \
  --origin https://example.com --request-file request.txt \
  --model YOUR_CONFIGURED_GEMINI_MODEL --id website-check --out browser-plan.json
```

For screenshot work, add `--screenshot study-location.png` to `prepare`; repeat the
option for up to three views explicitly requested in the request file. Preparation
adds PNG/provenance outputs, reviewer inputs and a visual selection gate without
starting a browser or provider. Inspect the saved plan before creating/running it.

For OpenAI or Qwen, add `--provider openai` or `--provider qwen` and use that
provider's configured model. The default remains Gemini.

This registers the request and saves a plan; it makes no browser or model call.
For interactive work, add `--interaction-scope 'the precise requested actions'`.
Inspect both the original request and the generated plan. A transfer or site change
requires a correspondingly revised plan, not a hidden permission expansion.

When choosing to execute that plan, use the existing local runtime:

```sh
python -m orchestrator.executors verify-gemini
task-relay orchestrator create browser-plan.json
task-relay orchestrator run website-check
task-relay orchestrator status website-check
```

The connection check reads model metadata. `run` starts the approved local work and
can incur model usage and perform the declared website actions. The selected model
must match the selected provider's configured model; there is no provider fallback.
Use `verify-openai` or `verify-qwen` instead of `verify-gemini` for those providers. Custom
`--root` choices must be used consistently for preparation and orchestration.
Browser profiles and their action journal use the configured Relay data directory.

Natural-language production planning can choose any of the three browser profiles from the
executor catalog. The existing Start card displays each task's profile, origins,
interaction scope and transfer paths, alongside model/data-transfer limits.
Send `/browser openai TASK` or `/browser qwen TASK` in Telegram or Messages to select
that provider explicitly, even when conversational mode is off. `/browser TASK`
and `/browser gemini TASK` retain Gemini. The original message remains the production
request; the model proposes the website scope and the existing Start card authorizes
execution. Public information searches can use a dedicated public-search profile
without signing in. Reasonable search assumptions, including an inferred year,
must be disclosed. The planner refreshes expired model metadata before preparing
the card; this check does not generate content or start the browser.
The independent reviewer receives reading/navigation scope only. Chat `/browser
connect` still belongs to the Perplexity setup pilot; general-profile sign-in uses
the local command above.

## Recovery and evidence

Every browser action first commits an intent to `general_browser_actions` and
`general_browser_events` in the shared state database. Results retain observations,
URLs and exact tool arguments. A duplicate completed action returns its saved
receipt; an uncertain action is never dispatched again. A failure after claim
conservatively remains uncertain, even when the action may not have reached the
site. An observed click is not user acceptance or independent proof of a remote
transaction.

The scheduler reserves a resource per profile. A host lock also prevents another
process from owning the same profile. Different profiles can run concurrently.
Unresolved actions block further interactions on their profile across jobs.
The worker stops its model loop on uncertainty; scheduler recovery does not replay
it. Cancellation preserves pending receipts and cannot undo a remote action.
Each browser task has one attempt; requested revisions need an explicit new stage.

Inspect receipts and, if useful, make a fresh read-only observation:

```sh
task-relay browser general status --profile research
task-relay browser general inspect --profile research --url https://example.com/result
```

Only after inspecting the actual outcome, record the exact operator decision:

```sh
task-relay browser general resolve --profile research --job ASSIGNMENT_ID \
  --action-id call-03-00 --outcome occurred --note 'Evidence for the inspected outcome'
```

Use `not_occurred` only with supporting inspection. This appends a resolution and
clears the profile blocker; it does not retry or resume the stopped production.
Cancel the stopped production through its existing controls before authorizing a
new stage; its uncertain scheduler attempt also retains the profile reservation.
Authentication
cookies and captured page/request text are private local data. Declared inputs and
observations used in execution are sent to the selected provider's model.

The existing worker envelope bounds each task to at most eight API requests,
24 tool calls, 600 seconds, 512 KB of input files, 200 KB of output files and 4,096
generated tokens per request. Browser action/tab limits may be smaller. Actual
provider usage is recorded against the exact provider and model; absent costs remain unknown.
Browser tasks reserve request seven for writing declared outputs and request eight
for the final report. Tool availability narrows during finalization and is checked
locally; a model cannot extend browsing by ignoring the advertised tools. Missing
evidence must be reported as a limitation or blocker, never inferred as success.
The same reservation starts earlier when the tool-call budget is nearly exhausted.

### Browser request qualification, 2026-09-12

`python3 -m unittest tests.test_browser_requests tests.test_browser_executor tests.test_gemini_executor`
passed 29 focused checks with local subprocess access, recorded in
`outputs/browser-flight/finalization-tests-host.log`. The sandboxed attempt could
not observe a cancelled supervisor. A new test fixture initially had a syntax error;
the corrected fixture is included in the passing run.

`.venv-browser/bin/python scripts/test_browser_pipeline.py --out outputs/browser-pipeline/browser-request-host-run`
passed 57 checks in 14.51 seconds, including explicit channel intake, reviewed Start,
late-call enforcement and the complete existing browser gate. The earlier sandboxed
run failed on local sockets/process inspection and remains recorded under
`browser-request-run/`. The model transport is scripted in these checks.

The first real configured-model information-search attempt exhausted eight requests
without writing its report; all responses and action receipts were retained, with
no uncertain browser action. This exposed the finalization defect described above.
Live trial evidence is kept separately under ignored `outputs/browser-flight/`.

The second trial wrote a report but falsely explained missing fares as a booking
horizon issue; the reviewer accepted it without browsing. Current host date context
is now supplied to planning and execution. A browser delivery or acceptance report
requires a nonempty page observation from that same attempt. This only establishes
that inspection occurred; it cannot prove each claim or citation correct.

After that change, the focused command above passed **30 checks** in
`evidence-tests-host.log`. The complete gate passed **58 checks in 14.49 seconds**
with `--out outputs/browser-pipeline/browser-evidence-host-run`.

A separate isolated real-model chat/planning check produced a ready browser plan
after the planner's one allowed structural correction (scope was initially an array
instead of a string). The final worker trial used the original locally prepared
scope, with a new run ID and the same model/budgets; both workers finished and the
reviewer inspected airline pages. Exact-date fares were still not obtained. General
route/monthly values must not be presented as results for the requested travel dates.
Some ancillary claims and the reviewer's blanket endorsement still require scrutiny.
This is partial public-site qualification, not reliable autonomous flight shopping.

All three live attempts remain preserved; `usage-summary.json` records 122,336,
101,961 and 234,147 native total tokens respectively (producer plus reviewer where
run). Planning usage is stored separately in the isolated chat database. Missing
monetary cost is unknown; these historical trial totals are not a per-job estimate.
No uncertain browser action was recorded. No booking or contact was performed.

The existing installed Telegram service was reloaded only after checking it was
the matching checkout/data root and that production, planning and provider queues
were idle. Its PID changed and fresh scan/chat/planning/production heartbeats were
recorded in `service-reload.log` and `service-health-after.json`. No live Telegram
test message was sent. A separately running Messages pilot was not restarted.

## Complete browser regression gate

From the source checkout, run this with the Python environment containing the
browser extra and installed Chromium:

```sh
.venv-browser/bin/python scripts/test_browser_pipeline.py
```

The default output directory is a new timestamped folder below
`outputs/browser-pipeline/`. `--out PATH` chooses a different **new** directory;
existing evidence is never overwritten. Local listening sockets, Chromium and
supervised child processes must be permitted by the host. A sandbox refusal is a
failed gate, not a skipped success.

This gate runs the actual command entry point, profile persistence, model metadata
verification path, producer/reviewer scheduler, browser worker, immutable outputs,
export, usage receipts, cancellation and operator resolution. A local website
records real browser form submissions. Separate real-browser scenarios exercise
every exposed tool, text transfers, all supported keys, stale drafts, restricted
fields, scope errors, dialogs and binary download rejection. Perplexity commands
use its real DOM adapter against a controlled page fixture, including saved
conversation continuation and reconciliation.

The model transport is scripted and headless mode is selected by a **test-only**
subprocess hook; product modules have no fixture switch. Tests use isolated data
directories and dummy provider credentials. This provides repeatable integration
coverage without paid generation, user accounts or messages. It does not measure
model judgment, real authentication/SSO, anti-bot behavior or live-site DOM changes.
Those still require separately scoped live qualification. Coverage of every option
does not mean every possible combination or website has been tested.

Each run retains:

- `result.json`: overall result and failing test IDs; a failure or skip exits nonzero.
- `cases.json` and `tests.log`: individual outcomes, durations and failure details.
- `coverage.json`: executed commands/flags, browser tools, key choices and scope fields.
- Scenario folders: exact CLI invocations, stdout/stderr, isolated databases,
  frozen assignments, API/tool receipts, exported results and browser profiles.
  The all-tools scenario also captures screenshots on failure where available.

The coverage check reads the actual CLI parsers and browser tool definitions.
Adding an operational command, flag or tool without exercising it fails the gate.
Existing unit/recovery tests run alongside the complete pipeline. The common
argparse help aliases are excluded from the operational-option coverage count.

### Recorded gate result

Command: `.venv-browser/bin/python scripts/test_browser_pipeline.py --out outputs/browser-pipeline/final-run`.
Result: **49 checks passed in 13.88 seconds**, covering nine browser commands, all
their operational flags, 12 browser tools, five key choices and seven policy fields.
Evidence: `outputs/browser-pipeline/final-run/`. These are software checks, not 49
independent live trials. No service reload or deployment was performed.

The first attempt could not bind its local server under the sandbox. After granting
local process/socket access, the next run exposed three product failures: command
errors returned exit code zero, select options were absent from observations, and
changing a nonempty draft did not invalidate an earlier page observation. All three
were fixed and their failing scenarios retained. Browser CLI errors and interrupted
sign-in also now return concise failures. `second-run/` retains the original
failures; `third-run/` passed before the final structured-report checks were added.

## Earlier checks run, 2026-09-12

Logs are retained under the ignored `outputs/general-browser/` directory.

| Command | Result and scope |
| --- | --- |
| `python3 -m unittest tests.test_general_browser tests.test_browser_executor` | 21 checks passed in `final-unit.log`: action identity, uncertainty, committed dispatch, scope, stale pages, profile serialization/case aliases, supervised restart, usage attribution, local preparation and reviewed planning. Scripted model/driver; no paid calls. |
| `TASK_RELAY_LOCAL_BROWSER_FIXTURE=1 .venv-browser/bin/python -m unittest tests.test_browser_local` | Two checks passed in `local-browser.log`: real headless Chromium against a local HTTP fixture, with one form submission, two tabs, text upload/download and an out-of-scope redirect blocked before dispatch to that site. Scripted model; no accounts. |
| `python3 -m unittest tests.test_general_browser tests.test_browser_executor tests.test_browser_jobs tests.test_browser_setup tests.test_perplexity_browser` | 38 checks passed in `integration.log` before the additional scheduler-serialization case; includes existing Perplexity setup/recovery coverage. Initial new-fixture SQLite cleanup warnings were corrected before the final focused run. |
| `python3 -m task_relay browser general --help` | Passed in `cli-help.log`; optional browser dependencies are loaded lazily. |

An earlier `unit.log` run passed 31 checks, including imported existing Gemini and
planning fixture classes. Those classes are now imported as modules to avoid
duplicate test discovery. Counts describe software checks, not independent trials
of model judgment or real-site reliability. The next qualification is one explicitly
authorized website task with the real configured model and account.

## Redirect regression discovered in live use

A live Google Flights navigation redirected to a consent origin outside its frozen
scope. The prior driver used `route.continue_()`, whose routing handler is not called
again for HTTP redirect hops. The original local fixture redirected to a nonexistent
host, so its failure did not prove that the scope guard prevented remote contact.
See the [Playwright routing contract](https://playwright.dev/python/docs/api/class-page#page-route).

The driver now fetches a single document response with automatic redirects and
transport retries disabled, checks its Location, and follows permitted GET redirects
through a bounded sequence of fresh navigations. Each hop retains its real URL for
relative links. Intermediate blank transport responses are not exposed as website
evidence. Redirects that would repeat a submitted request stop for inspection.

A recorded scope block on a navigation is returned to the model as a known blocked
result, including the requested/blocked URLs. It can navigate the same managed tab
to another permitted site. The completed blocked receipt is returned unchanged on
a duplicate tool ID. Errors following potentially effectful interactions remain
uncertain; this change neither resolves existing uncertain receipts nor restarts
an exhausted attempt. No consent domain is automatically added to a reviewed plan.

The replacement regression uses a reachable second local server, asserting zero
requests arrive there across a redirect chain. It also checks allowed redirects,
continued navigation, one POST followed by an allowed GET redirect, and a POST
whose forbidden redirect stays uncertain without repeating the submission. This
checks the remote effects, not merely the presence of an exception.

Recorded checks, 2026-09-12:

- `python3 -m unittest tests.test_general_browser tests.test_browser_executor`:
  26 passed; `outputs/browser-navigation/unit.log`.
- `TASK_RELAY_LOCAL_BROWSER_FIXTURE=1 .venv-browser/bin/python -m unittest tests.test_browser_pipeline.Tests.test_read_navigation_blocks_reachable_redirect_before_contact_and_can_continue`:
  one focused scenario passed; `outputs/browser-navigation/redirect-focused.log`.
- `.venv-browser/bin/python scripts/test_browser_pipeline.py --out outputs/browser-pipeline/navigation-qualified-run`:
  61 checks passed in 16.41 seconds. Earlier attempts retain the multi-hop and
  Chrome error-page race failures; no failed run is counted as qualification.
- A single fresh, read-only Google Flights navigation with the original origin
  policy produced an explicit consent-origin blocker; the browser remained on the
  requested origin. No model call or form submission was performed. Evidence:
  `outputs/browser-navigation/fixed-live.log`.

The original stopped production and its uncertainty receipts are preserved.
No live message, service reload or automatic production replay was performed for
this correction. Command/option coverage remains distinct from site and outcome
coverage; a passing count does not qualify every website.
