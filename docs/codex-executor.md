# Codex as Relay's model provider

The purpose is to compare another model using the user's existing ChatGPT sign-in.
Relay retains its current owner, compiler, tool execution, review and recovery.
This is a provider transport, not a second orchestration architecture.

`codex-agent` and `codex-code` route through the existing shared worker loop.
The CLI app-server holds a native thread during each invocation and supplies
dynamic tool calls; Relay validates and executes them, then returns committed
results. Restarts use Relay's saved context and receipts. The historical
`codex-cli` shell-worker profile remains distinct.

The transport verifies ChatGPT authentication before starting a thread and sets
`forced_login_method=chatgpt`. API-key or missing authentication fails before a
model turn. It does not extract credentials, log account details, or fall back to
another provider/model. Native shell, ambient MCP servers and unrelated CLI tools
are disabled; the shared Relay tools retain their original authority.

Public-source operations `web.sources.codex` and `web.sources.prepared.codex`
select Codex search while reusing registered source contracts, page parsing and
evidence handoffs. Source URLs must come from recorded search results. Model
prose is not source evidence. A completed search without those results produces
an explicit missing outcome; uncertain dispatch holds without replay. Codex-only
owner grants reject registered operations known to require another model provider
unless trusted admission explicitly captures that tool's independent provider.
The source-qualified [context and search boundary update](context-and-search-boundaries.md)
keeps agent selection separate from tool-provider selection; it does not switch
existing trials or make Gemini-backed search part of a Codex subscription.

## Accounting and observation

The explicit backend policy `cli-exchanges-v1` bounds Relay decision exchanges,
tool executions and elapsed time. Existing API-shaped request fields represent
decision exchanges for this profile. They do not cap internal CLI inference
requests or enforce a per-response output-token limit. CLI retries are internal.
Physical request counts remain unknown; reported cumulative token usage is saved
once, with its completeness limitation. The UI labels this distinction.
Do not silently convert a saved Gemini grant into CLI capacity or claim a dollar
cap. Subscription sign-in is not proof of unlimited included usage.

Image bytes are returned through native image fields. A queued parallel tool
call cannot prove that newly returned pixels were observed. Newly delivered
images require a later reported generation in the same thread/turn before Relay
marks them supplied to the model. Missing usage evidence conservatively leaves
that observation unconfirmed. Semantic visual judgment still belongs to review.

## Qualification status

Source integration passed 100 affected controlled tests on 2026-10-11. These use
scripted model responses and synthetic web pages, actual app-server JSONL pipes,
the existing owner/compiler/worker lifecycle, native PPTX/PDF build and correction,
and independent scripted final review. They also exercise authentication refusal,
disconnects, denied permissions, source provenance and image observation ordering.
The real installed CLI accepted an ephemeral thread and Relay tool declarations
with ChatGPT sign-in, with **zero model turns**. Structural registry conformance
reported 49 interfaces and no missing parameter schemas or producer bindings.

These are source checks and non-generative protocol checks. The adapter has not
been packaged or installed; no live Codex judgment, search yield, token efficiency
or completed sourcing deck is established. Exact-package qualification and a
separately admitted comparison run remain pending. Existing installed Relay and
saved Gemini jobs were not changed. See `outputs/codex-executor/CHECKS.md`.

Subsequent deployment: 0.13.222 passed 182 exact-package checks and was installed,
but its first live turn exposed a missing transcript lifecycle case: the normal
userMessage echo was rejected as an executable operation. No Relay tools ran;
model usage remains unknown. 0.13.223 separates passive transcript items from
tool actions across workers and search, passed 183 exact-package checks and an
exact-event replay, and was installed with verified bundle/overlays/services.
The uncertain trial is preserved without replay. Live deck completion remains
unverified. See `private qualification records`.
