# Task Relay for Chrome

Task Relay turns useful things you do on the web into evidence, reusable know-how,
and work you can continue later — without watching your browsing or requiring a
cloud account.

**New → select text → Turn into Skill → Send → Download SKILL.md.**
No account. No Relay cloud. No Desktop required. Your current AI chat can structure
what you keep; you review the result and own the exported files.

**Relay doesn't watch your browsing. You choose exactly what to keep.** Capture
happens only when you click Turn into Skill, Turn into Relay job or Capture text only on an authorized page.
Source 0.1.10 is a development build; public V1 acceptance and Store publication
remain separate. It uses the existing Task Relay logo and Desktop control style.

## Try the extension

Build the unpacked directory and upload ZIP from the repository root:

```sh
python3 scripts/build_chrome_extension.py --out outputs/chrome-extension
```

1. Load the unpacked directory in Chrome and pin Task Relay.
2. Open your ChatGPT conversation and click the Task Relay toolbar icon.
3. Click **New** if starting another task, then select the useful excerpt.
4. Click **Turn into Skill**. Relay prepares the Skill request and inserts an
   unsent message in ChatGPT.
5. Click **Send** in ChatGPT. When it finishes, click **Download SKILL.md** in
   Relay. The matching response is validated and a single Skill downloads on
   that click. The result remains available for **Edit** and another download.
   Skills needing resources download as a complete `.skill.zip`.

**Turn into Relay job** is the full-width outlined button below **Turn into Skill**
on the New screen. When viewing a result, click **New** to show both conversion
choices again; the result remains retained in the session. This is the secondary action. It produces an instance-specific
portable `.relay.md` job brief with objective, current findings, proposed decisions,
evidence, questions and next actions. It does not create or execute a Desktop job.
Skill and job requests ask for their respective output independently. A response
with the wrong category is rejected without replacing an existing review.

Chrome supplies Task Relay's panel title and logo; the panel does not repeat them.
The main screen has no dropdowns, setup, source preview or JSON fields. **⋯** holds
source details, evidence export, copy/import, **Open files**, optional Desktop
controls and recovery. Other AI sites receive a copied request; paste/send it
there, then use **Paste AI reply**. **Capture text only** retains the general
page/evidence route. Basic Skill/job capture requires a selection, never falling
back to the full page when no text is selected. Supported ChatGPT URLs are the
root page and ordinary `/c/…` conversations.

**New** works while a request is unfinished. A successful replacement capture
retains the previous capture, exact request, edits and receipts in session.
**⋯ → Return to request** restores the current view; **Previous capture** restores
an earlier one. Explicit New followed by a conversion can replace only the exact
unchanged Relay draft in the same tab and conversation. Edited drafts, unrelated
text and attachments remain protected. After a reload, bounded composer inspection
can retain the visible Relay request for that same explicit replacement; it does
not read history. Relay never clicks Send, waits in the background or automatically
saves a result.

If the message was cleared, clicking Download changes the primary action to
**Restore message**. That next explicit click restores the exact retained request;
Send remains the user's action. **⋯ → Restore message** also exposes recovery after
an uncertain insertion. Downloads are explicit exports, not background saving.

**This portable path requires neither Relay Desktop nor a configured provider.**
The ChatGPT adapter inserts a draft and retrieves a response only on explicit
clicks. It never sends a message or waits in the background. Continuation still
uses the prepared-context copy route. Installed 0.1.4 successfully captured a
selection and inserted the prepared draft in signed-in Chrome. Live response
recovery in 0.1.5 opened the user's existing response for review. Reviewed export
and fresh-chat reuse still need qualification before public V1. This build does not imply
Chrome Web Store installation or publication.

Desktop is an optional advanced mode for local library persistence, documented
at the end of this guide. Portable users are not prompted for native-app access.

## Review and recovery

Chrome clears temporary panel state when the extension reloads or the browser
restarts. In the original ChatGPT tab, open **⋯**
and click **Recover this chat’s result**. Relay reads the latest loaded user
message only, requires a Relay request marker and its single matching completed
reply, and validates the embedded source and proposals before opening review.
It preserves an existing preview and never reinserts or sends the request.
For requests using a saved Work or Skill base, open the original files and use
manual import. Incomplete/collapsed requests must be expanded first.

Capturing and reviewing never creates a saved Work, Skill or Source. Preview text
and drafts are retained in Chrome's session storage, not browsing-history storage;
clear them with **Clear preview**. A deliberately invoked Relay analysis
retains its local provider job request and result for recovery, before object Save.

Each explicit Save binds a request key to the exact capture, edited object,
selected base revision and request. Changed Work or Skill bases require a new
review. A lost reply can recover the committed receipt without duplicating Work.
Database mutations are atomic; Skill files are projected after commit. If file
projection fails, retry the same Save to repair it without another database save.
Uncertain provider requests are not automatically repeated.

ChatGPT handoffs retain the exact request, a unique request marker, original tab
and conversation, and insertion state in session storage before editing the page.
A lost insertion reply is not automatically retried. **Restore message**
reuses an identical draft, refuses any other draft, and refuses to insert a request
already present in the conversation. Download checks the exact request (allowing
display whitespace normalization), its response marker, generation indicators and
conversation boundaries. A new chat may acquire a `/c/…` URL after the user sends;
its matching request is still required. Later user messages, multiple response
sections, ambiguous code blocks and invalid proposals require manual review/import.
Rendered code is read directly, excluding language and Copy controls. Invalid
responses preserve the previous review. A replacement capture switches to a new
handoff while retaining the previous capture, request, reviewed edits and receipts
in temporary session storage. **⋯ → Previous capture** returns to them
without inserting or sending anything. **New** preserves the ChatGPT message box until an explicit conversion. Only an
unchanged Relay draft in that same conversation can then be replaced; unrelated
text must be moved aside by the user.
If ChatGPT collapses the sent request, expand **Show more** on that request before
Get result can verify its complete text. Its unique marker prevents re-insertion
even while collapsed. Retrieval never reopens an already reviewed response over
the user's edits.

Artifact references may use an exact URL in the captured text or the exact saved
source URL. Referring back to the captured chat does not require its URL to appear
in the selected excerpt. Other unrecorded links and unsafe references are rejected;
references do not grant access to files or the rest of that conversation.

Saving Work preserves conclusions, decision proposals, reported status,
dependencies, questions, next actions and referenced artifacts separately from
Relay's reviewed decisions and selected artifact versions. It grants no execution
permission. Newly reported decisions remain proposals until reviewed through the
owning Relay decision workflow. Every retained browser state includes its exact
captured source and save request; subsequent captures append history.

Portable Work exports preserve stable identity, revision and parent content hash
when continuing a selected portable snapshot. Local database Work identities and
portable snapshot identities are separate in V1; exporting a current panel
proposal does not synchronize a saved file with the database. Export full Source
text separately when retaining a portable Work snapshot. A `SKILL.md`-only portable
continuation does not include supporting files; supply those explicitly in the AI
chat when the Skill needs them.

## Extraction and permissions

Explicit **Turn into Skill**, **Turn into Relay job** or **Capture text only** injects an extractor into the active tab's main document.
Preparing ChatGPT analysis checks its composer; Insert edits that composer, and
Download reads the matching loaded message, each only on the relevant click.
There are no browsing history reads, content-script registrations, all-site host
permissions, navigation observers or background capture. Required permissions are
`activeTab`, `scripting`, `sidePanel` and `storage`. `nativeMessaging` is optional
and requested only when the user clicks **Connect Relay Desktop**. Portable
startup does not probe a native host, even when permission was previously granted.
A successful explicit connection is remembered; its permission is checked before
reconnecting. Every native call is also gated in the service worker. **Disconnect
Desktop** removes the optional permission. Denial, unavailable bridges and access
revocation preserve portable mode, captured text and user-edited review.
Click the toolbar on each new tab to grant
access. Restricted Chrome pages cannot be captured.
The toolbar uses an explicit action listener to open the panel synchronously;
opening the panel never reads the page. Declarative panel opening is disabled
because the installed Chrome test opened the UI without granting `activeTab`.
If Keep reports no access, select the webpage and click the pinned Task Relay
icon beside Chrome's address bar. Opening a panel through Chrome's side-panel
selector does not substitute for this tab authorization. Unsupported internal
pages have a separate error.

Selection mode keeps exact selected text. Page mode extracts loaded visible text,
excluding hidden elements, form controls, editable fields and navigation. Images,
downloads, PDF internals, iframes and unloaded conversation history are outside
V1's capture. Thin ChatGPT, Claude, Gemini and Perplexity adapters identify available
message roles; unrecognized markup falls back to generic visible text with an
explicit limitation. They share the same normalized `relay_analyze_capture`
pipeline. Page instructions remain untrusted evidence.

Capture and continuation budgets are 60,000 characters. Oversized material is
rejected, never silently truncated. Continuation contains current shared state,
the latest browser state, reviewed decisions, selected artifact metadata and at
most 20 recent browser Sources, with explicit coverage. It does not include the
original full conversation or claim that referenced files are accessible.

## Qualification boundary

Focused Python tests cover cross-site evidence in one shared Work item, source
integrity, stale review rejection, atomic rollback, exact save recovery, reviewed
Skill improvement, file-projection recovery, provider-call recovery and native
message bounds. Controlled JavaScript DOM/Chrome doubles exercise the actual
panel and Python dispatcher, generic/selection extraction, four synthetic site
adapters, review gates, portable ZIP/Markdown compatibility, fresh-panel reuse,
navigation races and extension-origin isolation. The 0.1.1 checks also cover
permission denial/revocation, missing hosts, no unsolicited native probe, automatic
copying and copy fallback, response block/file import, invalid/ambiguous response
rejection, preserved review edits and portable Work association for evidence.
The 0.1.2 checks execute the serialized ChatGPT adapter with controlled DOM
fixtures, covering textarea/contenteditable insertion, existing drafts and known
attachments, uncertain-edit recovery, exact request matching, streaming and
incomplete responses, rendered JSON extraction, conversation changes and bounded
responses. Panel/worker fixtures also cover retained handoffs across reopening,
wrong-tab rejection, no automatic insertion/retry, response identity, preserved
review and the portable path without Desktop.
The 0.1.3 fixtures cover the currently inspected signed-in Work composer, role
headings, paragraph-based user messages, rendered CodeContent blocks, collapsed
request detection and corresponding source extraction without role/control text.
The layout was inspected read-only in Chrome; that is not an end-to-end handoff
qualification.
The 0.1.4 checks cover missing URL access before a toolbar action, explicit panel
opening after the grant boundary, and no extractor invocation until Keep. The
installed Chrome failure showed the toolbar still wanted site access after the
declarative action. After reloading 0.1.4, the explicit toolbar click granted
access; Keep captured the selected paragraph and Insert placed the prepared
request in the actual ChatGPT composer. The draft was left unsent.

The 0.1.6 panel checks also cover the combined capture/prepare/insert action,
refusal to replace an uncertain request, direct downloads outside editors,
retained edits after Done and complete Skill packages when resources exist.
Installed Chrome was reloaded to 0.1.6. The minimal opening, recovered Skill and
Work cards, direct download controls and Edit/Done were inspected; original
proposal fields remained intact. No new AI request, save or download was made.
The combined primary action has controlled coverage only.

The 0.1.7 extractor fixtures cover selected rendered citations with accessibility
attributes and empty SVG whitespace, exact selection preservation, hidden/form
rejection and budget errors returned across the injection boundary. Panel/worker
checks cover readable extraction errors and retained review after a failed New
text capture. Installed Chrome was reloaded to 0.1.7: the previously failing
selection captured successfully and Make reusable inserted its draft into the
current chat. The draft was left unsent.

The 0.1.8 checks cover explicit restoration of a deleted draft with its original
identity, preservation of unrelated drafts and sent-request deduplication,
unfinished New text, retained state after panel reopening, Back and previous
capture restoration without dispatch. The updated installed panel was reopened
without reloading the extension to preserve its pending session. Restore request
returned the original deleted draft; New text and Back worked before completion.
The original source context matched exactly; the draft was left unsent. Full
manifest reload and live replacement capture were not exercised.

The 0.1.5 adapter checks cover display-contents wrappers, inline links marked
inert/aria-hidden but visually displayed, explicit line breaks and recovery of
the latest request. Panel/worker checks cover transported errors, missing results,
real navigation rejection, preservation of existing previews, invalid recovered
responses and review after session loss. Installed Chrome 0.1.5 recovered the
user-sent request and completed response into one Skill and one Work review card,
preserving the original source text and capture time. No new request or save was
performed by this check.

Controlled fixtures and installed observations are separate evidence. Reviewed
export/reuse, native registration in a real profile, broader site compatibility
and Chrome Web Store submission remain unqualified. No paid provider was run by
Relay. Private commands,
outcomes and build receipts belong under ignored `outputs/`, not public source.

Chrome API references: [Side Panel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel),
[activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab),
[Native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

## Optional advanced mode: connect Relay Desktop

Choose **Optional: connect Relay Desktop** only when you want a persistent local
library. The native bridge enables Recent Work, Current Work, Skills and Sources using
the shared Relay runtime. The current source supports bridge installation on
macOS and Linux; the installed Desktop release must include this bridge before
its installer can configure it automatically. V1's development installer is a
separate explicit step. Do not install into a random existing data folder.

Use a Python environment containing Task Relay's existing PyYAML dependency.
Copy the extension's ID from `chrome://extensions`, then register that exact ID
and an explicitly selected Relay data folder:

```sh
python3 scripts/install_chrome_bridge.py \
  --extension-id EXTENSION_ID_FROM_CHROME \
  --data-dir /absolute/path/to/selected-relay-data
```

For a first controlled local test, choose a new empty folder. For shared Desktop
Work, choose the Desktop runtime's actual configured data directory. The bridge
uses its `state.sqlite`, existing `work_projects`/`work_records`, and additive
browser Source/Skill/receipt tables. Browser Work is shared work-state context;
it is not automatically a production execution job in Desktop's Jobs screen.

The installer writes one native host manifest scoped to the selected extension,
plus a launcher in the selected data folder. Chrome starts that process on request;
there is no localhost HTTP server, tunnel, cloud storage, account or background
page capture. After registering the bridge, click **Connect Relay Desktop** in the
panel and approve Chrome's native-app permission request. Only a successful bridge
check enables the local library. If the bridge is unavailable, portable export
remains usable; retry Connect after registration. The protocol exposes only
capture review, local save, library inspection, export and bounded continuation.
It cannot invoke the Desktop's general action dispatcher.

The same **Make this reusable** flow uses your current AI chat and requires no
Relay model connection even with the local library connected. **Analyze with
Relay** is an optional separate action, shown only when Relay's existing Gemini
configuration is available. It sends the reviewed capture and bounded selected
state to that configured provider; provider charges may apply. No new provider or
account setup is implemented by the extension. Source saving never needs a model.

Select an existing Work before capture to attach new Source evidence or propose
progress. Select an existing Skill explicitly to propose a reusable improvement.
Review and save each independently. Skill improvements compare the exact parent
hash; earlier versions remain available in SQLite and in versioned local
`browser-skills/<name>/revisions/<hash>/SKILL.md` directories. This does not install
Skills into agents' global skill directories.

The 0.1.9 controlled checks cover selection-only conversion, independent Skill/job
requests, direct validated export, primary restoration after a deleted draft,
exact owned-draft replacement and unrelated/edited-draft protection. They use
small DOM fixtures and the actual shared Python bridge, without a live model run.
Live result export and fresh-chat continuation remain separate qualification.

The existing unpacked extension was reloaded with 0.1.9 source. Live inspection
confirmed one panel logo, New, Turn into Skill and the secondary job action.
Conversion without a selection gave a clear prompt and preserved the original
unsent ChatGPT draft. No Send, new provider run or result download was performed.
Chrome’s refreshed details page rendered blank, so its registered manifest version
display was not qualified; new panel and selection-only worker behavior were.

The 0.1.10 source-reference fix was loaded by reopening the installed panel while
retaining the exact pending request. Retrying the original response produced a
completed `.relay.md` download; the downloaded file passed the portable importer
and retained its source URL and capture time. No new message or model run occurred.
The registered manifest was not reloaded for this panel update.
