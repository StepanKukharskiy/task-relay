# Project structure

| Location | Purpose |
| --- | --- |
| `task_relay/` | Application, provider and channel implementations |
| `orchestrator/` | Contracts, storage, execution workers and recovery |
| Root Python modules | Compatibility imports and CLI entry points |
| `tests/` | Focused tests and synthetic fixtures |
| `task_relay/assets/` | Maintained icons and macOS Swift build sources |
| `messages_service/` | Compatible native source entry points |
| `scripts/` | Source inventory, publication checks and package/native qualification |
| `learning/` | Experimental evidence-analysis and continuity code |
| `experiments/o08/`, `experiments/proposal_review/` | Reusable procedure/reviewer experiments |
| `docs/` | Maintained product and technical guides |
| `.github/workflows/` | Publication and selected native checks |

`pyproject.toml` and `MANIFEST.in` define the runtime distributions. Research and tests
may be public source without being shipped in a wheel. `source_inventory.json`
defines the reviewed public-source set; adding another source category requires an
explicit inventory change. See [publication policy](publication.md).

Runtime data, credentials, user projects, generated files, local environments,
built native applications and development evidence are excluded from publication.
Defaults and override behavior are documented in [path configuration](path-configuration.md).
No cleanup of source files authorizes deletion or migration of operational data.

## Cleaning generated files

```sh
task-relay cleanup plan
task-relay cleanup plan --include-builds
task-relay cleanup apply PATH_TO_SAVED_MANIFEST
```

The listing writes an exact file manifest under the data directory's `cleanup/`
folder. Review that list before applying it. Default candidates are Python bytecode
caches, Finder metadata and redundant retired Messages-migration databases whose
retained recovery copies pass integrity and logical-content checks. `--include-builds`
also lists generated files under the installation's `build/` directory.

Application source, project inputs/outputs, environments themselves, distribution
archives, live databases and unique backups remain outside this policy. Applying a
manifest checks each file's hash and filesystem identity; changed files, symlinks,
hard-linked files and entries outside the policy are skipped. New files are never
added during execution. Removal receipts sit beside the manifest. This is an
explicit maintenance command, not automatic deletion on startup.
