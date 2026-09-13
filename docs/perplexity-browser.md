# Perplexity account browser pilot

## App setup: Browser use (requires Chrome)

In the macOS companion, open **Settings → Browser use** and turn it on. Relay
detects installed Google Chrome, prepares its private persistent profile, and
opens a new tab in ordinary Chrome for manual sign-in. **Open browser / sign in**
pauses access to this profile and closes its worker browser before reopening it
without debugging flags or an automation client. Open whichever websites you
want to use. **Done signing in** closes the manual window and enables future
worker access to the same saved sessions; it does not assert verified login.
For this pilot, sign into your usual Perplexity account there; a separate browser profile does
not require a separate website account. Chrome Sync is unnecessary. Website
verification, MFA and expired sessions still require the user's attention.

The desktop build includes the pinned Playwright driver and uses installed Chrome;
no extension, Chromium download, terminal setup or model is needed for this path.
The native lifecycle adapter currently supports macOS. Chrome uses a random
loopback debugging port and its own data directory, so this path does not use the
incoming-debugger permission dialog for the user's everyday Chrome profile.
The worker discovers and validates the browser-instance descriptor itself and
reopens the saved profile when Chrome has closed. It never imports personal cookies.
The app's controls are site-neutral; the Perplexity adapter remains the current
end-to-end test target. Manual sign-in cannot interrupt a browser job that owns
the profile lock. Already queued research waits while manual sign-in is active;
new intake asks the user to finish sign-in first. Failed mode switches retain
the pause, and processes with unverified ownership are never terminated.

With this option enabled, `/perplexity QUESTION` or an ordinary explicit request
such as “Search Perplexity for local building suppliers” can queue the standalone
Chrome worker through Relay's existing provider scheduler. The orchestrator's
`browser_research` action supplies a self-contained `query`, removing instructions
to Relay such as “use browser and search Perplexity for”. For example, that wrapper
around “rebar contractors” becomes “Find rebar contractors.” The original message
is retained unchanged in request history; the separate query is frozen in the
browser journal and previewed in the queue confirmation. The query must preserve
substantive scope and constraints without adding a location or other requirement.
Unambiguous user-provided conversation context may resolve references; essential
ambiguity still needs clarification. Missing or invalid query fields stop dispatch.
It needs no separate model-browser connection check or accounts-profile confirmation. The worker checks the real saved session
before submission, and the catalog includes channel-scoped recent job receipts
with both original text and submitted query. Both texts, selected transport and
pending dispatch commit together. Duplicate input cannot replace the frozen query.
`/perplexity QUESTION` retains its literal question. All natural-language requests,
including “Use Perplexity to …”, go through the orchestrator's intent interpretation
instead of a phrase-stripping shortcut. Completed output and the original
channel's outbox entry also commit together. Queued requests cannot be picked up
by the earlier extension worker. Uncertain submissions require explicit inspection;
restarting the worker never resubmits them. Switching off prevents new managed
browser jobs; already running work can finish and saved sign-ins remain.

Failed or interrupted setup retains the preference and profile for retry. App
status reads never launch Chrome or claim the website is signed in. Without an
app preference, the older CLI/extension pilot remains available; explicit CLI
`--chrome`/`--endpoint` selections retain their original meaning.

Controlled checks cover the app switch, native bridge, queue ownership, crash
recovery and a temporary Chrome profile retaining a synthetic login cookie after
restart. A later read-only worker preflight recognized the authenticated Perplexity
Search UI in the saved profile; no query was submitted by that check. This is
not an end-to-end messenger research result. The changes
are now installed in the locally verified companion: Settings exposes Browser use,
and both existing messenger services reported fresh health after the update.
The option remains off until the user enables it; no live research was submitted
as part of installation.

## Standalone worker: existing Chrome session

The local standalone worker can request Chrome 144+'s permission-based connection
with `--chrome`, or attach to an explicit loopback debugging server with `--endpoint`.
Both paths use no browser extension, Codex
worker or model to choose individual page actions. Chrome retains its own login.
The worker opens a new task tab and leaves the tab and browser open when it
disconnects, including after an uncertain submission.

To reuse the Chrome profile where you are already signed in, enable remote
debugging at `chrome://inspect/#remote-debugging`, then run:

```sh
python3 -m task_relay browser send --chrome --receipt UNIQUE_ID --prompt-file QUESTION_FILE
```

Allow the browser's incoming connection prompt. Relay reads only the published
`DevToolsActivePort` connection descriptor for stable Chrome, attaches to that
browser instance and opens its own Perplexity tab. It does not read credential
files, launch a substitute browser or copy a login from another profile. Discovery
currently covers standard macOS and Linux stable Chrome locations. Chrome can
request permission again when a connection is recreated; unattended reconnection
is not qualified. See [Chrome's existing-session connection](https://developer.chrome.com/docs/devtools/agents/get-started/configuration#connect-to-an-existing-browser-session).

The alternative debugging-port launch method requires a non-default user data
directory, with a separate sign-in retained in that profile. That restriction
applies to command-line debugging switches, not the permission-based method above.
See [Chrome's debugging-port profile requirements](https://developer.chrome.com/blog/remote-debugging-port).

Use the actual loopback endpoint exposed by that browser (the port below is an
example):

```sh
python3 -m task_relay browser login --endpoint http://127.0.0.1:9222
python3 -m task_relay browser send --endpoint http://127.0.0.1:9222 \
  --receipt UNIQUE_ID --prompt-file QUESTION_FILE
python3 -m task_relay browser status UNIQUE_ID
```

The existing receipt preserves the exact question and submission intent. A
completed receipt returns its saved result without reopening the browser;
an uncertain receipt requires `reconcile`, optionally with `--endpoint`, and
never resubmits. Only loopback IP endpoints are accepted, and attachment binds to
the returned browser-instance address. A lost connection has no automatic fallback.

The Chrome attachment and its existing journal passed 20 focused checks, including
a real local Chromium session-cookie fixture and disconnect/tab preservation.
These are controlled checks. CLI attachment does not deploy a background service.
The app preference above now selects Chrome for new channel jobs in source;
installed services need the corresponding application update.

The live existing-Chrome trial submitted once and reused the account's login.
A transitional URL initially stopped capture; read-only reconciliation recovered
the matching complete answer and saved URL. The worker now tolerates same-origin
transitional URLs while requiring a canonical saved URL to complete. That fix has
a focused regression check; a fresh full submission after the fix is not yet
qualified. Manual Chrome connection approval and channel deployment remain separate.

A second live request exposed an inline Copy control inside quoted answer text.
The counter now identifies the answer's Copy/Share/Fork action group instead of
counting all Copy buttons. Eighteen focused checks and the affected standalone CLI
integration test pass. The existing answer was recovered through reconciliation;
fresh completion without recovery remains unqualified.

## Standalone worker: existing Firefox/Zen session

A narrow browser extension lets
Relay submit an explicitly requested ordinary Search, observe its answer and
return the saved conversation URL. The browser retains its own login; Relay does
not export cookies. Routine page actions run through the native helper without
Codex or an API model. Perplexity's account allowances still apply.

**Status: controlled tests pass; live installation, website qualification and
channel deployment are pending.** This is a development connection, not yet a
signed public extension or a one-click desktop installer. It targets Firefox/Zen
on macOS and Linux; Windows registration is not implemented.

Prepare a reviewable local package from the Relay installation using its Python:

```sh
python3 -m task_relay.perplexity_native prepare outputs/perplexity-connection
```

Use the printed paths for the following one-time setup. Keep that directory in
place: the host registration points to its launcher. The launcher freezes the
current installation, interpreter and Relay data directories; prepare it again
when those move. It requires the same shared state database as the channel service.

1. Review `extension/manifest.json` and the native host manifest. The extension
   requests Perplexity origins, local extension storage and native messaging.
   Its fixed operations are open, snapshot and submit; it exposes no arbitrary
   script or shell tool to a webpage.
2. Register the printed host manifest with
   `python3 -m task_relay.perplexity_native register HOST_MANIFEST_PATH`.
   Registration writes Firefox's per-user native messaging directory and refuses
   to replace a different existing helper.
3. For development, open `about:debugging#/runtime/this-firefox` in Firefox/Zen,
   choose **Load Temporary Add-on**, and select the printed extension manifest.
   This installation disappears on browser restart. Public distribution needs a
   signed extension; do not disable browser signature enforcement.
4. Sign in to Perplexity in that browser. Click the extension toolbar button to
   connect. **ON** means the helper is responding, not that website sign-in or
   Search controls have been verified. **!** indicates a disconnected helper;
   its tooltip reports the browser error. Clicking again disconnects. Enabled
   installations reconnect automatically while present in the browser.

Once the live connection is qualified and channel intake deployed, send
`/perplexity YOUR EXACT QUESTION` in the paired Telegram or Messages chat.
“Use Perplexity to research …” also selects this worker directly. A follow-up is
`/perplexity SAVED_CONVERSATION_URL` followed by a newline and the exact question.
There is no implicit last-conversation selection. Replies use the originating
channel; long transcripts are explicitly shortened with a link to the full page.

For local qualification, use a UTF-8 prompt file and a unique receipt:

```sh
python3 -m task_relay.perplexity_native status
python3 -m task_relay.perplexity_native send --receipt UNIQUE_ID --prompt-file QUESTION_FILE
python3 -m task_relay.perplexity_native status RETURNED_RECEIPT
```

Local jobs create no channel message. Each job opens its own browser tab and
retains it for inspection. Keep the browser running and avoid editing worker
tabs while they run. Login challenges, existing drafts, unrecognized controls or
Computer mode stop execution. A connection failure after submit intent leaves an
uncertain receipt; reconnecting does not send it again. Use `reconcile RECEIPT
--url SAVED_CONVERSATION_URL` to inspect without submitting. `retry RECEIPT` is
only available for requests blocked before submit intent. A disconnect cannot
undo a submission already sent to the website.

The controlled checks use synthetic local pages and channel fakes. They cover
exact text, one click, source URLs, changed destinations, draft preservation,
channel ownership and recovery after a lost reply; they do not establish real
Perplexity DOM compatibility or successful delivery from an installed service.

The connection follows Firefox's documented
[native messaging protocol](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging).
Development installs follow Mozilla's
[temporary installation procedure](https://extensionworkshop.com/documentation/develop/temporary-installation-in-firefox/).

## Earlier dedicated Chromium pilot

Relay's existing web tools search and fetch public pages. They cannot sign in,
click, submit forms or continue account conversations. Browser tools provided by
a desktop agent belong to that agent's environment and are not inherited by Relay.

This experimental local adapter targets **ordinary Perplexity Search** in a
dedicated visible Chromium profile. It supports an exact text prompt, a new
conversation or an explicit saved conversation URL, a rendered transcript and
observation-only recovery. It does not use a Perplexity model API or copy the
credentials/session from another browser. Website account allowances still apply.

## Start sign-in from chat

In Telegram, open `/providers` → **Perplexity browser** → **Open Perplexity sign-in**.
In either Telegram or the paired Messages chat, send `/browser connect`.
A supervised setup job opens the dedicated browser on the Relay computer and waits
up to ten minutes. Sign in on that computer, resolve consent/verification prompts
and select Search. Relay detects readiness and reports back in the originating
channel. No terminal command or terminal confirmation is needed. `/browser status`
checks progress; `/browser cancel` stops setup and retains any saved session.

With `/browser connect`, enter credentials only on Perplexity's login page.
Signing in in a phone browser would not
establish the Relay computer's profile. Initial setup therefore needs access to
that computer's desktop. No remote desktop or device-code authorization is claimed.
Setup does not submit a conversation or claim that task execution is qualified.

The Relay installation needs the optional browser component. The setup worker uses
its current Python if available, or the dedicated browser environment discovered by
the host adapter; `TASK_RELAY_BROWSER_PYTHON` can explicitly select an installed
runtime. Missing runtime/desktop access reports a setup failure in chat. Installing
new dependencies through chat is not part of this slice.

## Experimental sign-in through Telegram

Source now includes `/browser chat`, also exposed as **Sign in through this chat**
in Telegram's Perplexity provider menu. **Live account qualification and deployment
are still pending.** Do not send credentials to an older installed bot: wait for
a dedicated login prompt from a version containing this flow.

Reply directly to the current login prompt with the single requested value. Each
prompt expires after three minutes and is bound to the paired private chat, its
message and the current worker. The first website adapter supports recognized
Perplexity email and email-code forms, with same-origin POST form checks and a
recheck before submission. Unknown forms, third-party identity providers,
passwords, passkeys and browser challenges require interaction in the browser.
This is a shared input mechanism with a site-specific adapter, not universal
website sign-in.

Relay intercepts login replies before task and model routing. Values pass through
a process-local pipe; the database records only prompt identity, expiry and input
status. Stale replies are discarded, and uncertain delivery is never replayed.
Telegram receives these messages. Relay requests their deletion, which cannot
guarantee removal from Telegram. The dedicated browser retains its own session
data; the pipe does not provide secure memory erasure.

`/browser status` checks progress and `/browser cancel` stops the worker. During
an active chat-login session, unthreaded non-command messages are discarded rather
than becoming tasks. Browser verification requests no credential. Signing in does
not submit a Search or qualify conversation execution.

The controlled browser gate includes real local Chromium with synthetic login
forms, exact-once pipe input, expiry, cancellation, restart and changed-form
rejection. All 78 checks passed. The live dedicated-profile trial is still at
browser verification. Two user-authorized desktop clicks on the visible
verification checkbox each started verification and returned to an unchecked
challenge. This qualifies the ability to attempt the click, not successful
verification or automatic handling by Relay. No actual login form or
authenticated Search was qualified.

## Optional local administration commands

Install the optional browser extra in the Relay environment, then its Chromium:

```sh
python3 -m pip install '.[browser]'
python3 -m playwright install chromium
python3 -m task_relay browser login
```

Sign in manually in the dedicated browser. Resolve consent or verification prompts
yourself, select Search, then return to the terminal. The profile stores the login
locally below Relay's private data directory. It is separate from your normal
browser profile. Playwright documents this separate-profile requirement in its
[persistent context API](https://playwright.dev/python/docs/api/class-browsertype).

Write the exact prompt into `request.txt`, then:

```sh
python3 -m task_relay browser send --receipt trial-one --prompt-file request.txt
python3 -m task_relay browser status trial-one
```

The result includes the saved `url`. To continue it, use a new receipt and prompt
file, and pass that exact URL as `--url`. The first slice accepts canonical UUID
Search URLs only; other account URL formats fail closed.

If a send becomes uncertain, inspect the website before doing anything else:

```sh
python3 -m task_relay browser reconcile trial-one --url SAVED_CONVERSATION_URL
```

Reconcile observes; it never types or submits. An existing recorded URL cannot be
replaced by a different one. A newly submitted conversation whose URL was not
captured needs the user to supply its saved URL. The observed turn must match the
exact prompt, expected question/answer counts and completion controls. More than
one intervening turn or an unfamiliar UI remains uncertain.

## Identity and recovery

- Exact prompt and intended URL are saved under an immutable request receipt.
- Submission intent commits before filling the composer and clicking Submit once. Errors after intent
  remain uncertain unless the driver explicitly certifies that it stopped before
  invoking the submission control. Those known pre-click stops are blocked and
  require an explicit retry. A failed click stays uncertain.
  Enter is not used as a submission shortcut or fallback; missing or ambiguous
  Submit controls leave the draft without clicking. The empty composer can show
  voice mode; the worker fills the request, waits for Submit to appear, and clicks
  once only after verifying the exact text and rechecking URL, turns and mode.
  Changing prose on an empty homepage does not change conversation identity;
  existing thread text and user drafts remain protected. Completion checks allow
  the empty composer to return to voice mode and reject a visible stop-response
  control.
- `task-relay browser inspect RECEIPT` provides bounded, read-only diagnostics of
  visible controls in matching tabs of the already running Relay Chrome profile.
  It does not launch a browser, navigate, fill, submit or change the receipt.
- Reusing a completed receipt returns its saved result without reopening a browser.
- A changed request cannot reuse a receipt. Pending work blocks another request
  targeting the same recorded conversation.
- Sign-in/preflight failure before claim can be retried explicitly after resolving
  the blocker. An uncertain submission requires observation, not automatic replay.
- A profile lock serializes local browser access. Existing drafts, busy/unrecognized
  controls, changed page state, non-Search mode or dialogs stop submission.
- The transcript is untrusted website content, not instructions to execute more work.

The journal uses `browser_jobs` and `browser_job_events` in Relay's existing
`state.sqlite`. It records rendered text and observations, not hidden browser state.
Prompts are limited to 12,000 characters; transcript capture to 250,000 characters;
the default observation window is 120 seconds. No cancellation of server-side work
is claimed when the local command stops. Browser launch errors may leave a prepared
receipt with no submission intent; retrying that receipt does not replay a sent turn.

## Qualification boundary

The request journal, recovery and profile locking have controlled tests. A separate
interactive desktop-browser pilot showed account-visible creation, follow-up and
persistence. **That is not full live qualification of the app-managed flow.** The installed
worker has since recognized the saved authenticated Search UI without submission.
A new end-to-end research result through the messenger remains to be verified.

The current host adapter permits profile privacy/locking on macOS and Linux only;
this does not establish native Linux browser acceptance. Windows remains unavailable.
The app-managed path now has scheduler, Telegram/Messages reply and orchestrator
integration with these durable receipts. Attachment exchange, Computer tasks and
universal website compatibility are not established by this Perplexity adapter.
