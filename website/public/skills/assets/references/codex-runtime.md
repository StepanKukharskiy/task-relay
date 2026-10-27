# Codex reference adapter

Read this when executing the supplied adapter. It uses Codex-provided document tools; no Relay installation, API, configuration or job is needed.

The reference adapter is [../scripts/update-report.mjs](../scripts/update-report.mjs). It requires the Codex bundled `@oai/artifact-tool` runtime and the installed Presentations validation tools. Discover those paths with the host's dependency loader. Call it with:

```text
NODE SKILL_DIR/scripts/update-report.mjs --template SOURCE.pptx --data MONTH.xlsx --mapping MAPPING.json --output NEW.pptx --tools-dir PRESENTATIONS_SKILL_DIR --python BUNDLED_PYTHON
```

Run the adapter from a directory where its dependencies resolve; provide a local `node_modules` link to the host's bundled modules and set `RUNTIME_NODE_MODULES` to that directory for the finalizer's import check. Do not install dependencies or call a network service silently. Other hosts can implement the same mapping contract with their native spreadsheet/presentation tools; the reference adapter has only been exercised in Codex.


Resolve NODE, SKILL_DIR, PRESENTATIONS_SKILL_DIR and BUNDLED_PYTHON for the current host. Set up only a local dependency link; do not copy another user's installation paths. If the host lacks these tools, report the missing capability. A standard Agent Skill manifest does not install a document runtime. The adapter was tested directly in Codex desktop with bundled document tools. Other hosts and a standalone CLI without those tools are untested.
