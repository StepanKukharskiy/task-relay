# Website work through a Codex desktop task

The supervised pilot below passed, but repeated browser approvals made it too
interactive for routine research. The current P01 priority is the
[standalone Perplexity worker](perplexity-browser.md), which has controlled tests
and still needs live extension qualification. These remain separate paths.

Relay can send website work to an existing Codex desktop task and return its
answer through the normal task reply watcher. The desktop task supplies Browser
or Computer Use tools; Relay does not install a browser extension or drive the
website through its own Playwright profile on this path.

The first live pilot used Perplexity Search in a signed-in Zen session. The
request arrived through Telegram, the worker operated the website, and Relay
delivered its completed answer and saved conversation link to Telegram.

## Use the qualified path

1. Keep Codex and the browser running on the connected Mac. Sign in to the site.
2. Select the intended existing Codex task with `/use TASK_ID`, or reply to its
   Relay task card. `/use` directs subsequent ordinary messages to that task.
3. Ask it to run the research in Perplexity Search and return the answer and
   conversation URL. Include the actual research question.
4. If Codex asks for browser access, approve the desired scope in Codex. Relay's
   Telegram Allow button currently approves one call only; it does not save a
   session or permanent permission. Session approval through Codex avoids having
   to approve every page read and click separately.
5. The worker returns the result; Relay delivers the task's final answer. Reply
   to that task's message to continue. `/orchestrator` returns to the routing chat.

An example request is: “Use Perplexity Search in the signed-in browser to research
[question]. Submit once, wait for the answer, and return its answer and saved
conversation URL. If a login or verification challenge blocks progress, tell me.
Do not substitute your own web search.”

## Evidence and limits

The live pilot used explicit destination selection and individual user approvals.
It establishes the complete research-and-return path, not unattended operation.
Site sign-in and browser-tool permissions are distinct. A new task may require
browser permission even when another task already has access to that app.

The natural-language router now keeps exact named destinations visible in large
catalogs and treats desktop plugins as unverified rather than absent. The context,
routing and capability suites pass 34 tests, and the installed modules match the
tested source. The corrected natural-language dispatch still needs a live check.

Relay's durable intake prevents replay of uncertain task dispatches. It does not
provide an exactly-once guarantee for individual browser submissions made inside
the desktop task. Interrupted submission and follow-up qualification remain open;
inspect the saved conversation before repeating a possibly submitted request.

Personal prompts, URLs and live receipts stay in ignored local `outputs/` storage.
