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
