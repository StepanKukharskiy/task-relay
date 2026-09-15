# Task Relay website

[Live website](https://task-relay-website-production.up.railway.app)

One static, text-first page introducing jobs, cross-tool workflow examples and
version-change review, followed by supported programs, input/saved file formats
and current download availability. Five workflow starters sit in a disclosure
beneath the examples; Programs and File formats retain direct navigation.
The program/format list describes implemented support, including dedicated editable
PPTX generation. The 0.13.26 beta download includes browser setup, media provider connections,
editable PPTX and workflow starters; other document exports are worker-dependent. Check the
actual published source archive before claiming an operation is in the beta.
No dependencies or build step.
The `/guides/` section focuses on five current local-tool workflows: site research
into PPTX, precise Rhino model revisions, named-view renders, Blender asset
packing and editable design presentations. Each article links to a reported pain
point, names required inputs and operations, and distinguishes implementation
from complete live workflow proof. The capability audit used bundled 0.13.24;
the public 0.13.26 beta includes those registered operations, without claiming complete live workflow qualification.
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

For local previews, place all three versions’ twelve named artifacts under `downloads/`.
Deployment fetches the exact URLs, sizes and SHA-256 digests in downloads.json
during the Docker build. Publish new GitHub assets before deploying the website.
Old 0.12.1 assets use the existing immutable website URLs; later assets use GitHub.
The server refuses startup if any advertised artifact is absent. Binary downloads
stream from disk with HEAD and byte-range support; no arbitrary path is served.
The directory is excluded from Git, Railway uploads and the Docker context so
retained installers do not exceed upload limits. Any missing or changed remote
asset fails the build before the live site is replaced. Build from a reviewed, publication-checked source tree;
never copy personal configuration or installation bindings into a release.

Use a new versioned filename for every changed artifact; published bytes are
immutable. Website and manifest route names must change together for a release.
The beta source and runtime omit concurrent unreviewed development work even if
the website describes broader development capabilities.

The current primary download is 0.13.26. Retain the immutable 0.13.0-beta.1 and 0.12.1-beta.1
files for existing links. The CLI tarball includes the reviewed source installer;
its optional browser/image/presentation extras are separate from core installation.
