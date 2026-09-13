# Account sites and saved browser sessions

Relay's `accounts` browser profile has an explicit list of permitted sites.
Users complete sign-in once, confirm it, and reuse that browser's session for
subsequent authorized tasks. Site membership and task authorization are separate:
each assignment still declares its exact origins, permitted interactions and file
grants. Public research can continue in a separate anonymous profile.

This implementation is available in source. Deployment to an existing installed
app and live account qualification are separate steps. The older Perplexity
`/browser connect` and experimental `/browser chat` adapter remain separate from
this general account profile.

## Manage the list from chat

In the paired Telegram or Messages chat:

```text
/browser sites
/browser sites add https://www.perplexity.ai
/browser sites login https://www.perplexity.ai
```

Adding a site records `needs_verification`; it does not start a task or claim a
signed-in account. `login` queues a supervised manual setup job and opens a new
browser tab. When the browser-open notice arrives, sign in on the Relay computer,
complete any verification, and return to the exact site. Then send:

```text
/browser sites done https://www.perplexity.ai
```

Relay checks that the tab is back on the exact origin and that recognized login or
verification controls are absent. It records `confirmed_by_user`, not independently
verified authentication. The browser retains the session; Relay stores no passwords
or codes in this registry. Enter credentials in the browser, not in ordinary chat.

`/browser cancel` stops queued/open browser setup. Setup times out after ten minutes.
Late confirmation, cancellation, restart and a changed browser connection do not
produce a successful sign-in receipt. Setup notices return to the initiating channel.

Remove future account access with:

```text
/browser sites remove https://www.perplexity.ai
```

This retains browser cookies and the request history. It cancels pending setup for
the site and stops subsequent Relay observations/interactions. It does not undo
website actions or sign the browser out.

## Connect an existing browser

By default, `accounts` uses its own persistent local Chromium profile. To reuse
a browser where you are already signed in, explicitly attach its local Chrome
DevTools Protocol endpoint on the Relay host:

```sh
python3 -m task_relay browser sites attach --endpoint http://127.0.0.1:9222
```

The browser must already expose that debugging endpoint. This command neither
enables browser debugging nor discovers/copies credentials from other profiles.
Only an explicit loopback IP, port and one browser context are supported. The
attachment is bound to the returned browser-instance endpoint; if that browser is
restarted, reattach explicitly. Changing the connection invalidates prior site
confirmations. This path requires Playwright 1.62 or later and a POSIX host.
Firefox/Zen, Chrome-extension attachment and Chrome MCP approval-based attachment
are not implemented here.

Relay creates and manages its own task tabs in that browser's existing context.
It does not adopt personal tabs by position or close the external browser. Its
navigation handler passes unrelated tabs through. Attached mode uses Playwright's
`no_defaults` option to preserve browser defaults. Request interception may affect
the shared context's cache, and website session storage is shared with that context;
this is controlled access to an account browser, not browser-level site isolation.

To select the separate managed browser again:

```sh
python3 -m task_relay browser sites managed
```

Local `browser sites list|add|login|done|remove` commands expose the same registry.
`login` queues the normal setup worker, so a Relay service containing this code
must be running. Neither attachment nor site registration launches model work.

## During tasks

The planner sees site origins and confirmation status, never the debugging
endpoint or browser credentials. Signed-in work selects profile `accounts`.
Before opening its browser, Relay checks every declared origin against the list.
A missing/unconfirmed origin requests explicit addition and manual sign-in.
Unknown navigation destinations remain blocked by the task's frozen origin scope;
adding a site cannot expand an existing assignment.

Visible password/email/code fields and recognized verification pages invalidate
the saved confirmation and request manual sign-in again before page contents
reach the worker. These are conservative detection rules, not a universal test
of authentication: unusual login interfaces may still require a reported manual
blocker, and ordinary email-entry forms can also trigger a pause.

Verification encountered during a read/navigation produces a blocked receipt.
If a website interaction was already attempted, its outcome remains uncertain and
must be reconciled separately. Manual sign-in never replays that action or resumes
an uncertain submission automatically.

## Qualification

Controlled tests use small local pages and a real external Chromium process.
They cover session-cookie reuse, unrelated-tab survival, exact-origin redirects,
revoked site access, login detection without secret retention, channel-specific
manual confirmation, cancellation, restart and atomic setup receipts. These
checks do not establish live Perplexity sign-in or guarantee CAPTCHA completion.
