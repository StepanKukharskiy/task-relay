# Task Relay website

[Live website](https://task-relay-website-production.up.railway.app)

One static, text-first page describing Relay, supported tools, five development
workflow starters and current download availability. No dependencies or build step.
The website process serves only the public page, stylesheet, favicon and health
endpoint. It does not start Relay, connect providers or access local task data.

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

Place the four named artifacts under `downloads/` before startup or deployment.
The server refuses startup if any advertised artifact is absent. Binary downloads
stream from disk with HEAD and byte-range support; no arbitrary path is served.
The directory is excluded from Git and explicitly allowed in the isolated Railway
upload and Docker context. Build from a reviewed, publication-checked source tree;
never copy personal configuration or installation bindings into a release.

Use a new versioned filename for every changed artifact; published bytes are
immutable. Website and manifest route names must change together for a release.
The beta source and runtime omit concurrent unreviewed development work even if
the website describes broader development capabilities.
