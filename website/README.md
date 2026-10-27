# Task Relay website

[Live website](https://task-relay-website-production.up.railway.app)

The `/chatgpt` page and `/chatgpt/support`, `/chatgpt/privacy` and `/chatgpt/terms`
describe the separate skills-only Task Relay plugin and its publisher. They use
the website's existing assets and exact static routes. This website is not a
Relay MCP server and receives no plugin conversation/file payloads. Publisher
policies are approved source changes until their deployment is verified.

One static, text-first page introducing jobs, cross-tool workflow examples and
version-change review, followed by supported programs, input/saved file formats
and current download availability. Five workflow starters sit in a disclosure
beneath the examples; Programs and File formats retain direct navigation.
The program/format list describes implemented support, including dedicated editable
PPTX generation. The current release includes browser setup, media provider connections,
editable PPTX and workflow starters; other document exports are worker-dependent. Check the
actual published source archive before claiming an operation is in the beta.
No dependencies or build step.
The `/guides/` section focuses on five current local-tool workflows: site research
into PPTX, precise Rhino model revisions, named-view renders, Blender asset
packing and editable design presentations. Each article links to a reported pain
point, names required inputs and operations, and distinguishes implementation
from complete live workflow proof. The capability audit used bundled 0.13.24;
current releases include those registered operations, without claiming complete live workflow qualification.
Exact routes serve the guides and reviewed sample artifacts. The earlier
invoice/CSV/complaint recipes remain reachable with archive notices and noindex;
the hub and sitemap list only the current collection. The original architecture
request and sample deck retain their bytes; the revised request has a v2 URL.
The architecture deck is a separately authored output example. No app or provider
was run to qualify these new guide prompts. Guide changes are local source changes
until separately deployed. Run `node --test tests/website-downloads.test.cjs` from
the repository root to check routes, local links, archive indexing and downloads.
`/llms.txt` provides a Markdown overview and curated documentation links for AI
readers. The homepage advertises it with `rel="describedby"` and a footer link.
Keep it aligned with the programs, formats and release boundaries on the page.
The website process serves the public page, stylesheet, favicon, llms.txt, health
endpoint and exact versioned downloads. It does not start Relay, connect providers
or access local task data.

## Preview

From this directory with Node.js 22 or newer:

```sh
npm start
```

Open `http://localhost:3000`. Set `PORT` to use another port. Restart the process
after edits; public assets are loaded on startup.

## Railway

Create a dedicated website service in a new Railway project. For GitHub deployment,
select this repository, set the service root directory to `/website`, and set the
config path to `/website/railway.json`. The Dockerfile uses only the website
directory. Generate a Railway domain once the deployment is healthy. No secrets,
database, volume or provider connections are needed.

Alternatively, with an authenticated Railway CLI, create/link the project and
website service, then run `railway up website --path-as-root` from the repository
root and `railway domain`. The current website was deployed with this isolated
CLI upload; it is not connected to GitHub autodeploys.
Keep deployment IDs and installation receipts in ignored private storage.

## Downloads and copy

The primary link downloads the Mac beta DMG for Apple Silicon/macOS 14+. CLI
installation is a secondary disclosure with a matching source archive and guided
terminal setup. Both artifacts have SHA-256 sidecars. The page explicitly labels
the beta as lacking Developer ID/notarization and links Apple's per-app opening
instructions. Windows remains unavailable.

For local previews, retain the legacy artifacts listed in downloads.json under
`downloads/`. The deployment build fetches and checksum-verifies these immutable
legacy files, preserving existing 0.12.1, 0.13.0 and 0.13.26 URLs and byte ranges.

New downloads are discovered at runtime from the public GitHub releases API for
StepanKukharskiy/task-relay. Every five minutes, the first relevant page/API request
refreshes the shared cache; concurrent requests share one fetch. Both stable and
beta releases are eligible. Semantic version order determines the newest complete
release, regardless of list ordering. Drafts, incomplete/duplicate asset sets and
foreign URLs are rejected. Discovery requires these uploaded, nonempty assets:

- `Task-Relay-VERSION-arm64.dmg` and its `.sha256` sidecar.
- `Task-Relay-VERSION-source.tar.gz` and its `.sha256` sidecar.

Publish all assets in a draft release before publishing it. No website edits or
redeployment are needed for subsequent releases using this naming convention.
The homepage and llms.txt are rendered from one resolved release. Immutable GitHub
asset URLs keep the displayed version and downloaded bytes aligned. `/api/release`
exposes that selection. `/downloads/latest/arm64.dmg`, `/downloads/latest/source.tar.gz`
and their `.sha256` routes redirect without permanent caching.

GitHub failures, rate limits or malformed responses retain the last known complete
release. A checked-in complete published release provides the cold-start fallback;
it need not change on each release. Discovery never automatically downgrades a
running server. The source archive must contain `task-relay-VERSION/install.sh`.
The update ZIP/manifest are published alongside these files for the in-app updater.

Run `node --test tests/website-latest-release.test.cjs tests/website-downloads.test.cjs
tests/website-release-assets.test.cjs` from the repository root. These checks use
mock release responses and small download fixtures, without live GitHub calls.

## Excel-to-PowerPoint distribution experiment

Editorial ownership is split from executable assets:

- Canonical experiment: `https://stepankukharskiy.com/ai-work/excel-to-powerpoint-automation`.
- Personal archive: `https://stepankukharskiy.com/ai-work`.
- Relay catalog: `/skills`; package page: `/skills/excel-to-powerpoint`.
- Relay's old `/guides/excel-to-powerpoint` URL returns a 308 redirect to the
  personal original, retaining only an allowlisted campaign.
- Medium is a separate distribution draft. Its author must set the personal
  canonical URL in Medium's editor; the prepared HTML cannot set that option.

The shared generated hero is an editorial illustration. Actual report previews
remain separate and are also stored locally on the personal site. The experiment
retains its declared source policy, prepared template, independent Relay review,
direct Codex check and host/rendering limits. Package v1/v2 bytes remain unchanged;
active downloads still serve v2. Editorial distribution is versioned v3.

Personal article links carry `personal-excel-to-powerpoint-v3`. Medium's primary
CTA goes directly to the Relay Skill with:

```text
https://task-relay-website-production.up.railway.app/skills/excel-to-powerpoint?utm_source=medium&utm_medium=article&utm_campaign=excel-to-powerpoint-v3
```

Historical Medium/guide v1/v2 labels remain accepted. Campaigns carry through Skill
and example downloads, optional Relay handoff and release-download requests.
Personal article counts are emitted by its own server; Relay no longer counts an
article request for the old redirect. Compare Medium Skill requests to Medium's
actual views separately after publication. Untagged visits to the personal original
use the personal label; referrer-based attribution is not inferred.

Events retain only UTC day, fixed Skill, campaign and event labels. They count GET
requests, not unique readers, completed downloads, installations or executions.
No visitor IDs, analytics cookies, IPs, user agents, referrers, raw URLs, request
bodies or work content appear in event JSON. DNT/GPC, known bots and prefetch are
omitted. No cross-site person-level linking is performed. The downloaded Skill has
no publisher execution telemetry. Hosting logs are separate.

`TASK_RELAY_FUNNEL_ANALYTICS=off` disables Relay events. The personal site uses
`PERSONAL_WEBSITE_ANALYTICS=off`; `/ai-work/privacy` documents that scope. Aggregate
non-overlapping private exports separately by service:

```sh
node website/summarize-funnel.mjs < PRIVATE_EXPORT.jsonl > PRIVATE_TOTALS.csv
```

At 1,000 eligible personal article requests or 30 days after distribution starts,
show raw counts and download requests per 1,000 article requests. This proposed
checkpoint is not observed demand or linked-person conversion. Hosting retention
may limit exports, so preserve private checkpoints while available.

Focused checks:

```sh
node --test tests/website-skill-funnel.test.cjs tests/website-downloads.test.cjs tests/website-latest-release.test.cjs
```

Seven controlled Relay checks pass. Two private personal request-count checks pass;
its `npm run check` and `npm run build` pass without diagnostics. Desktop/mobile
layout checks passed at 1280 and 390 px; no mobile horizontal overflow. A scoped
heuristic publication scan covers affected source/assets, separate from a staged
source guard. No Git commit was performed.

Both existing Railway services deployed successfully on 2026-10-05: personal
`e4c89f1c-6287-475f-af96-5f506ce37efd`, Relay
`897ce39f-99b6-43e0-8da2-7dbb63656e83`. Thirty-one controlled deployed responses
verify personal canonical ownership, exact hero/report image bytes, old redirects,
unchanged v1/v2 archives, v3 attribution, release handoff and the preserved Relay
homepage. Excluded-agent DNT/GPC HTTP checks emit no reader events. Browser checks
are controlled page requests and must be excluded from real reader results.

Personal source changes are saved in the requested checkout. GitHub remains at
its original commit until the local changes are committed/pushed. Medium remains
unpublished. Reader acquisition, verified installs, Skill-use telemetry and the
next invoice benchmark remain pending.
