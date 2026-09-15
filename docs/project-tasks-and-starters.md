# Project tasks and starter workflows

This extension adds explicit local Codex task creation and an installed catalog of
five cross-tool workflows. The companion remains a small settings/decision surface;
messengers remain the main interface.

## New Codex tasks

In conversation, request either:

- “Create a new Codex task in Project Alpha titled Review sources. Don't start work.”
- “Create a new Codex task in Project Alpha and inspect the source files. Do not edit them.”

Telegram also supports `/new codex "/absolute/path/to/known/project" Review sources`.
That command creates only; reply to the returned task receipt to start work.
Natural-language requests use the configured interpreter and record its usage.
The direct command skips model interpretation. Task routing must be enabled.

Projects come from saved local Codex roots, existing local tasks, and Relay's saved
setup project. The chosen directory must still have the same filesystem identity
at dispatch. The adapter uses the existing local checkout. It does not create git
worktrees, choose branches, create remote tasks, change sidebar assignments, or
override Codex's configured model and permissions.

The control client uses Codex's documented
[app-server protocol](https://developers.openai.com/codex/app-server): initialize,
thread/start, and thread/name/set. It never starts a model turn itself. Requested
work is handed to the existing desktop owner after the task is created and its
history is readable. Selected source copies and guide choices accompany the exact
original request. This requires the desktop application for the first-turn route.

The queue commits before every external side effect. Creation response, task ID,
title request and first-turn submission are recorded separately. A known ID is
preserved if naming, persistence verification or desktop submission fails. On
restart, a saved creation response can restore its ID without another creation.
An unknown creation or turn remains uncertain; Relay never retries it or switches
providers automatically. Inspect the saved task/receipt before continuing.

For empty tasks, Relay recognizes only the exact unchanged initial history it
recorded. Changed unknown histories remain unknown. A technical success is not
user acceptance.

## Installed workflow catalog

The catalog is packaged Python data; no separate seed, download, model call or
installation action is required. List and inspect it with:

```text
task-relay workflows
task-relay workflows architecture-presentation
task-relay workflows --json
```

In Telegram or Messages use `/templates` and `/templates ID`. The existing
`/workflow` and `/workflows` linked-workflow controls retain their meaning.

Starter requirements are provider-neutral. The production planner composes roles
and resolves each worker against its frozen capability/executor catalog; it does
not need a dedicated domain worker per starter. See
[capability-driven workers](capability-workers.md) for supported profiles and
the approval boundary when a proposed worker uses a different backend.

| ID | Stages | Tool requirements and boundaries |
| --- | --- | --- |
| research-report | Research → report | Qualified browser/research executor, then file/document tools |
| architecture-presentation | Research → concept → model → optional visualization → presentation | Research/file workers, registered Blender or Rhino, configured reference-image provider, PPTX tooling; native Keynote/Slides remain unqualified |
| model-revision | Inspect → prepare edit → apply | Exact Blender/Rhino source, reviewed script/checks, separately approved host operation |
| carousel-reel | Adaptation → production | Exact approved cards/assets/guides, then qualified media tools; preserve the first render for review |
| data-presentation | Analysis → presentation | Exact CSV/XLSX, reproducible calculations, chart/PPTX tooling |

Each stage lists inputs, outputs, tools and its review point. Request, for example,
“Prepare the analysis stage of data-presentation for Project Alpha.” The interpreter
selects `plan_production` with `template=custom`, `starter_workflow` and optionally
`starter_stage`. A request for the full workflow instead uses `plan_pipeline` to
derive all requested stages and continue through their agreed boundaries. Existing
source, executor, budget and exact-plan approval checks still apply.

The complete definition, version, hash and selected stage are captured in the
planning context. A clarification keeps that captured definition even if the
installed catalog changes. A single-stage plan grants only that stage. A saved
full workflow continues after completed work and explicit selections without a new
continuation request at every stage. Required tools must be available and missing
inputs must be resolved. Templates describe stages; registered operations or
capable workers execute them. Native code still needs exact Start.
No provider, application installation, publication or user acceptance is inferred.

See the [workflow implementation audit and reusable procedures](reusable-procedures.md)
for automation coverage, media-worker dependencies and saving completed workflows.

## Validation boundary

Controlled tests cover interpreter-to-queue dispatch, the real local stdio client
against a fake subprocess server, exact request/receipt identity, interrupted and
lost responses, source/project changes, first replies to empty tasks, and frozen
starter-stage planning. They run no models or application production.

The installed Codex schema was inspected. Actual empty-thread persistence, project
visibility in the desktop, owner discovery and model intent recognition remain
connected acceptance checks. No live task, provider work, service reload or delivery
is claimed by these tests. End-to-end creative workflow quality is also unqualified.
