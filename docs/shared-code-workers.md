# Shared code and document workers

Included in the locally installed 0.13.24 app. Packaged runtime and native sandbox
checks pass; paid-provider execution has not been live-qualified. A new public
release has not been published by this local update.

Relay uses its bundled Python and document libraries. Users do not install Docker,
Python, or packages to use this feature in the desktop app. In Settings, **Code and
document tools → Check tools and enable** runs fixed local qualification fixtures.
**Check worker connection** verifies the selected provider/model metadata without
generating content. The provider must already be connected with an exact text model.
OpenRouter automatic/free model routing is excluded from these workers.

## Worker profiles

Gemini, OpenAI, Qwen, DeepSeek and OpenRouter share the same declared-file adapter
and the same Python tool. Each provider has an `-agent` text-file profile and a
`-code` profile with `files.text`, `files.binary` and `code.execute`. Models and
roles can vary per task; execution tools are registered implementations, not
arbitrary commands created by a model. Existing browser profiles remain separate.

The planner captures eligible profiles, their verified library report and exact
runtime identity. An approved task freezes its provider, model, runtime, sources,
outputs and limits. Credentials, exact model, runtime identity and enabled state
are checked again before dispatch. Changed/disconnected profiles block; neither
another provider nor unrestricted local Python is substituted. A different backend
still requires the existing stage Start approval.

The shared loop preserves native provider tool IDs and reasoning continuation
fields. It writes a request intent before dispatch and retains actual usage. There
is no automatic retry of an uncertain provider response. Metadata verification is
not proof of generation quota or a model's tool-calling quality.

## Native execution boundary

The current adapter uses macOS Seatbelt (`sandbox-exec`). Windows 10+ remains the
compatibility target, but Windows code execution is unavailable until a native
isolation adapter is implemented and qualified. This does not disable existing
Windows text-file workers. OS-specific execution stays in `native_code_host.py`.

Each `python_run` call receives fresh copies of the exact granted inputs and prior
declared outputs. Python reads them under `RELAY_INPUTS` and writes under
`RELAY_OUTPUTS`. Only declared regular output files are exported through Relay's
file-grant adapter. Sources remain unchanged. Runtime code/libraries are readable;
other host file contents, network access, subprocesses and native applications are
denied. The environment contains no provider credentials or inherited user secrets.
The framework launcher is replaced by its actual interpreter, and MIME defaults
come from Python instead of host server configuration.

Code is limited to 100 KB per call and at most 120 seconds within the task deadline.
The profile permits up to 100 MB of inputs and outputs; lower stage/task ceilings
still apply. CPU and per-file limits, guardian wall-clock limits and output/log
monitoring are enforced. This is not a hard RAM or disk-quota isolation guarantee.
Eight API rounds and 24 total tool calls remain the provider-worker ceilings.

A trusted guardian owns the code child. Closing the worker's lifetime pipe,
including a forced worker termination, kills and reaps that child. The child cannot
fork, and changing its process group cannot escape direct-child cleanup. Logs are
read without following links, and exports reject links/non-regular files. An intent
without a terminal code outcome prevents replay and successful delivery. A known
nonzero exit may be diagnosed and corrected within the same approved task budget.

Binary file reads return metadata; Python can inspect their contents locally.
Assignments, read text, code output and extracted summaries can be sent to the
selected model. This is not a visual reasoning integration. Native modeling,
generation APIs and media rendering retain their registered operation contracts;
Python access does not authorize package installation or host-app execution.

## Document qualification

The desktop build pins and bundles python-docx, python-pptx, openpyxl, pypdf,
ReportLab and Pillow with their dependencies. Source-only installations report
missing libraries instead of installing them during a task. The app performs
small save/reopen fixtures for DOCX, PPTX, XLSX, PDF and PNG; ReportLab is checked
by saving a PDF. Library versions and interpreter/adapter identities bind the
runtime receipt. A failed recheck disables the previous success, and a runtime
change requires another check.

These checks establish format tooling, not layout quality, formula recalculation,
Keynote import compatibility, OCR, photorealistic rendering or an editable video
composition pipeline. Missing capabilities remain explicit planner blockers.

## Validation

Controlled tests use scripted provider transports and small local files. Native
qualification uses the generated desktop Python runtime, with no paid model calls,
browser work, messages or native modeling/media generation. It covers file/network/
subprocess denial, sanitized environment, cancellation, parent SIGKILL, wall-clock
limits, Unicode/spaced paths, substituted-log rejection, and exact XLSX delivery
to an independent review call. App installation and live provider trials remain open.

The native CI command is:

```sh
TASK_RELAY_TEST_NATIVE_CODE=1 TASK_RELAY_REQUIRE_DOCUMENTS=1 python -m unittest tests.test_native_code_host
```

The controlled provider suite is `python -m unittest tests.test_shared_code_workers`.
Windows CI runs the shared contracts and verifies that unsupported native code
never falls back to unrestricted execution.
