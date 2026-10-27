# Task Relay Chrome Web Store release

Published: **0.1.18**, verified in the publisher dashboard October 13, 2026.
Store submission and publication are separate from local
installation. The candidate keeps the two main actions, **Turn into Skill** and
**Save work**, and packages correctly sized versions of the existing Task Relay
logo at 16, 32, 48 and 128 pixels.

## Store acquisition attribution — October 15, 2026

The publisher enabled Store-managed Google Analytics 4. The dashboard confirmed
“Opted in to Google Analytics” and links to the new property. This measures Store
listing visits and completed install events, separately from extension usage.
The extension has no added telemetry, permissions or package changes.

Published install links use `utm_medium=referral` and
`utm_campaign=chrome_extension`, with distinct `utm_source` values:

- `personal_website`: the shared install link on stepankukharskiy.com.
- `github`: the public Task Relay repository README install link.

The website deployment succeeded and its live install link was checked. GitHub
read-back confirmed the README link after publication. The website build passed;
the isolated GitHub staged publication check passed with no findings. Receipts,
exact links and pre/post observations remain in ignored private storage.

In Google Analytics, use Traffic acquisition and compare Session source / medium
and Session campaign with the `install` event. UI labels may vary. Reports can
take 24–48 hours to finalize and low-volume data may be withheld. Tags identify
which tagged link was used; they do not reveal every visitor's original discovery
path, reconstruct prior attribution or establish exact Store search keywords.
No installs or campaign results have yet been verified in the new property.
See [Google's Store analytics documentation](https://developer.chrome.com/docs/webstore/google-analytics).

## Listing update 0.1.19 — October 13, 2026

Prepare the clearer title **Task Relay – Web & ChatGPT to Skills**, a shorter
description and two screenshots of a real neutral walkthrough: selected webpage
text, Turn into Skill, reviewed output and `review-software-release-notes.md`
downloaded successfully. Browser profile, unrelated tabs, conversation body,
research, source URLs and analytics downloads are excluded from the public crops.
The exact 0.1.19 ZIP differs from qualified 0.1.18 only in manifest name,
description and version. Runtime files and permissions are unchanged.

The publisher dashboard confirms 0.1.18 is Published. After account
re-verification, the existing 0.1.19 draft was confirmed without reuploading.
The saved listing has the shorter description and the two workflow screenshots
first; the original neutral overview remains third. Existing publisher
certifications, privacy declarations and free/public/all-region distribution
were inspected and preserved. On October 14, 2026, Google confirmed submission
and **Pending review**, with automatic publication after approval enabled.
Approval and publication of 0.1.19 remain separate. Materials, exact neutral
request/response, recovery reactions, image provenance and private analytics
exports are retained under
`private qualification records`.

The analytics report ends October 11; it does not measure Skill exports.
Acquisition-source breakdowns are incomplete. No Store GA4 opt-in or extension
telemetry was enabled by this work.

## Update 0.1.18 — October 10, 2026

The exact locally qualified 0.1.18 ZIP is prepared for the existing public item.
It adds selected-text capture on ordinary webpages, optional ChatGPT-only autofill,
simpler handoff controls, collapsed/attached request recovery and descriptive
Skill filenames. The optional origin is `https://chatgpt.com/*`; base permissions
and optional Desktop access remain unchanged. Send stays the user's action.

The listing and reviewer notes now describe those behaviors and the permission's
purpose. Existing neutral Store images and publisher/distribution settings are
preserved. The updated Chrome homepage, privacy and support pages are deployed
and verified publicly; preexisting homepage, release API and Skill catalog
responses match their prior live bytes.

After Google account re-verification, Package confirmed draft **0.1.18** and
published **0.1.12**; no upload was repeated. Updated listing and privacy
explanations, reviewer instructions and free/public/all-region distribution
were verified. Existing publisher certifications remained checked.
On October 10, 2026, submission succeeded and the dashboard shows **Pending
review**, with automatic publication after approval enabled. This is not approval
or publication of 0.1.18. The saved homepage is the publisher's dedicated
[Relay for Chrome page](https://stepankukharskiy.com/relay/chrome); extension
support and privacy retain their direct URLs.
Receipts and the release copy are in ignored
`private qualification records`.

The release is free, with public availability in all countries supported by the
Chrome Web Store. The intended publisher is Stepan Kukharskiy. The listing leads
with selected text, explicit user Send, reviewed portable exports and reuse.
Relay Desktop is optional and requires separate native-bridge registration.

## Public materials

The Store homepage points to the publisher's dedicated Relay for Chrome page.
Chrome-specific privacy, support and terms live under `/chrome`
on Task Relay's existing website. The privacy page describes selected page/chat
content and source metadata, temporary local session storage, explicit AI-chat
handoff, user-controlled downloads and optional native Desktop/provider actions.
It does not reuse the skills-only ChatGPT plugin's policy as an extension policy.

Store artwork uses the Task Relay logo and a crop of the real extension panel on
a blank tab. Personal conversations, research, browser tabs, source URLs and
profile details are excluded. No generated AI result is represented as tested.

## Reviewer instructions

1. Use Chrome 116 or later. The portable flow needs no Relay account, Desktop
   installation, native permission or Relay provider configuration. To test direct
   ChatGPT handoff, use the reviewer's own ordinary ChatGPT conversation/account.
2. Supply neutral sample material, for example: “When checking a company's
   venture backing, disambiguate the company, look for named investors and dated
   primary announcements, and record uncertainty if evidence is missing.”
3. Select that text, click the Task Relay toolbar icon, and choose **Turn into
   Skill**. Check the prepared draft. Send it yourself; the extension does not
   click Send. Wait for the completed response, then use **Download Skill**.
4. Inspect the resulting standard Agent Skill. **Edit** allows changing a
   proposed result before another explicit export. Specific subjects should be
   represented as inputs, while preserving the actual kind of check.
5. Use **New**, select instance-specific neutral findings and choose **Save
   work**. After explicit user Send and response completion, download the portable
   `.relay.md` work snapshot. Check findings, proposed decisions, questions,
   source references and next actions. This does not execute a Desktop job.
6. Supply the exported file in another AI chat. Alternatively, use **Options →
   Open files**, enter the next request and copy the prepared continuation context.
   There is no automatic Library discovery or background synchronization.
7. A missing selection must produce a prompt rather than capturing the whole
   conversation. Existing unrelated drafts/attachments must remain intact. If a
   Relay draft is deleted, **Restore message** restores that exact request;
   sending it remains the user's action.

No reviewer credentials are supplied or required by Task Relay. ChatGPT's own
account access and terms are separate. Other AI sites use manual request/reply
copy and paste; direct handoff is advertised for ChatGPT only.

## Verification and remaining publication steps

Controlled extractor, serialized ChatGPT adapter and panel/worker/shared-bridge
checks pass for the candidate source. The exact ZIP is checked for manifest
permissions, contained files, icon dimensions and private-source findings.
Static website routes are checked with small local fixtures. Earlier installed
checks establish selection/draft insertion and a valid work export; revised
Skill wording and fresh-chat reuse still have no new live model qualification.

The actual version 0.1.12 draft is uploaded, saved and inspected in the publisher
dashboard. Package version, description, neutral images, permission explanations,
reviewer instructions, free pricing and all-region public availability are
confirmed. The Chrome-specific website pages are deployed and verified; the
preexisting Desktop homepage and release are preserved.

The publisher completed the three data-use certifications and verified the
contact email. The approved display name is saved. The user submitted version
0.1.12. On October 6, 2026, Google's dashboard confirms Published — public, and
the public listing displays version 0.1.12, Stepan Kukharskiy as publisher and
Add to Chrome. This verifies public availability; a new installation from the
store has not been tested. The automatic-publication preference was not inspected.

[Install Task Relay from the Chrome Web Store](https://chromewebstore.google.com/detail/task-relay/alicbjedflapdighdmadgbopahfhbgbd).

Official guidance: [publishing](https://developer.chrome.com/docs/webstore/publish),
[listing images](https://developer.chrome.com/docs/webstore/images), and
[privacy declarations](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy).
