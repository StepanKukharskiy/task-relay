# Native platform qualification

O12 is in progress. The [native workflow](../.github/workflows/native-hosts.yml)
runs Ubuntu 24.04 with Python 3.11 and Windows Server 2025/2022 with Python
3.11/3.14 respectively. A passing
job means only that its named profile passed. Reports record actual OS/runtime,
commands, return codes and open gates. CI receives no provider credentials and uses
small text fixtures with controlled transports.

| Profile | Verified scope | Open gates |
| --- | --- | --- |
| Linux text runtime | Native locks/grants, links/escapes, descendant cancellation, supervisor restart and uncertain API receipt preservation; installed wheel runs one local text bundle and reopens it through the CLI. | Native service activation, authorized provider execution and real Telegram delivery. |
| Windows processes and boundaries (new profile; native run pending) | Intended checks: atomic Job containment, descendant cancellation after parent exit, owner-crash cleanup, supervisor recovery without replay, Unicode argv/pipes and exclusive lock release; installed imports/CLI and remaining unavailable-operation checks. | Native results for the new profile; junction/reparse-point grants, credential ACLs, background startup, actual text execution and Windows 10/11 desktop qualification. |

The initial controlled Linux profile passed 39 checks on x86_64 Linux/glibc with
Python 3.11.16. Windows build 10.0.26100 AMD64 with Python 3.11.9 passed installed
package/CLI checks and one combined unavailable-operation check. Windows reports
`execution_qualified: false`. Current runs and scoped reports are available from
the repository's [Actions page](https://github.com/StepanKukharskiy/task-relay/actions).
Source changes require their affected checks; old runs do not qualify new behavior.

## Windows 10 and later target

Windows-specific process operations live in `task_relay/host_windows.py`; the
workflow state machine and assignment contract remain shared. The adapter uses
the Windows 10+ `PROC_THREAD_ATTRIBUTE_JOB_LIST` startup attribute to create each
worker inside its Job Object. It does not start user code and attach ownership
afterward. The supervisor owns the only job handle; closing it kills descendants.
Only explicit standard I/O handles are inherited. A scheduler-launched supervisor
has a separate lifetime so restarting the scheduler does not cancel the worker.
Recovery checks process creation time and executable identity, not a PID alone.
Native launch failure remains a failure; there is no uncontained fallback.
See Microsoft's [process startup attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
and [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

The bundled Python 3.14 line supports Windows 10+, according to the
[Python Windows documentation](https://docs.python.org/3.14/using/windows.html).
The desktop package still needs a Windows build and WebView2 setup, native
filesystem/credential enforcement, per-user startup, and installation/update
qualification. Real Windows 10 and Windows 11 desktop results are required before
claiming client support. Server CI is useful regression evidence, not a substitute
for either client OS. Browser and CAD executors remain separate qualification
gates. iMessage stays macOS-specific.

Local development checks run the portable contracts and existing POSIX integration
tests. The six native Windows fixtures skip on macOS; skipped tests do not qualify
Windows. No provider credentials, live messages, browsers or CAD apps are used by
this process-foundation profile.

## Linux service operation

`task-relay telegram run` works in the foreground or under a chosen process
supervisor. On hosts with a working systemd user manager, `task-relay telegram install`
installs/enables/restarts `task-relay-telegram.service`. `uninstall` removes the owned
unit while retaining configuration, pairing and execution records.

Installation probes the manager before mutation, records installation/data/project/
output bindings and rejects another installation or locally edited unit. Failed
activation restores prior configuration and enabled/active state where possible;
incomplete recovery is reported. Process-manager status is not provider or delivery
health. The adapter does not enable lingering, create a system service or copy shell
secrets into the unit. Credential environment references must be available to the
chosen supervisor.

The unit uses `KillMode=process` so detached supervisors survive scheduler restarts.
Cancel through Relay to reach owned process groups. Descendants that create separate
sessions are outside that group boundary; shell workers are not confined by
in-process file grants.

## Remaining order

1. Run and qualify the Windows process/lock/recovery profile on native Windows.
2. Windows file/credential enforcement and background startup; extend native
   qualification to actual installed text execution.
3. Native service restart and a bounded authorized provider task with Telegram
   delivery on each host, preserving exact receipts and uncertain outcomes.
4. O13 installation, onboarding, upgrade and explicit data migration.
