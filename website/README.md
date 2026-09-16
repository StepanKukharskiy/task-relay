# Task Relay website

[Live website](https://task-relay-website-production.up.railway.app)

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
