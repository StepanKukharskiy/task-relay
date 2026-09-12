# Public source policy

The public repository contains product code, maintained assets, synthetic tests,
reusable experiments and technical documentation. Personal transcripts, project
research, installation receipts, credentials and operational data belong in private
storage outside the published source set.

`source_inventory.json` defines that source set. Documentation uses explicit paths;
personal analysis/history/replay directories are excluded. `.gitignore` also excludes
private state, development evidence, user projects, generated files and local builds.
The wheel/source archive has a narrower boundary defined by package metadata.

Before committing, inspect the actual staged files and run:

```sh
python3 scripts/check_publication.py --staged
```

The check rejects files outside the inventory, personal home paths, common credential
signatures, embedded credential literals, installation-specific runtime defaults and
links to unpublished evidence. It also scans PNG text metadata. Matched values are
never printed. CI checks committed source with `python3 scripts/check_publication.py`.
These rules are a guard against common mistakes, not proof that arbitrary content
is free of private information. Keep examples synthetic and review new files.

A local repository archive preserves development history separately from the public
baseline. Do not push archive refs, merge old development history into the public
branch or publish local backups. Continue new work from the public baseline.
