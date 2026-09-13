# Perplexity account browser pilot

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

This is chat-initiated setup, not sign-in inside the chat. Passwords and login codes
belong only on Perplexity's login page. Signing in in a phone browser would not
establish the Relay computer's profile. Initial setup therefore needs access to
that computer's desktop. No remote desktop or device-code authorization is claimed.
Setup does not submit a conversation or claim that task execution is qualified.

The Relay installation needs the optional browser component. The setup worker uses
its current Python if available, or the dedicated browser environment discovered by
the host adapter; `TASK_RELAY_BROWSER_PYTHON` can explicitly select an installed
runtime. Missing runtime/desktop access reports a setup failure in chat. Installing
new dependencies through chat is not part of this slice.

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
- Submission intent commits before typing or pressing Enter. Errors after intent
  are conservative uncertainty, even if no request actually reached the website.
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
persistence. **That is not live qualification of this standalone driver.** Its DOM
completion contract, dedicated-profile sign-in and actual browser installation need
verification against the account before deployment.

The current host adapter permits profile privacy/locking on macOS and Linux only;
this does not establish native Linux browser acceptance. Windows remains unavailable.
Conversation execution has no background service, Telegram command, orchestrator action, attachment exchange,
Computer task, model selector or general browser tool catalog is enabled by this
slice. After standalone qualification, the next step is existing managed-job and
Telegram reply integration with the same durable receipts.
