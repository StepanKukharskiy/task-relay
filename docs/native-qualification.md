# Native platform qualification

O12 is in progress. The [native workflow](../.github/workflows/native-hosts.yml)
runs separate Ubuntu 24.04 and Windows Server 2025 jobs with Python 3.11. A passing
job means only that its named profile passed. Reports record actual OS/runtime,
commands, return codes and open gates. CI receives no provider credentials and uses
small text fixtures with controlled transports.

| Profile | Verified scope | Open gates |
| --- | --- | --- |
| Linux text runtime | Native locks/grants, links/escapes, descendant cancellation, supervisor restart and uncertain API receipt preservation; installed wheel runs one local text bundle and reopens it through the CLI. | Native service activation, authorized provider execution and real Telegram delivery. |
| Windows boundaries | Installed imports/CLI and environment-reference resolution; unavailable process, lock, filesystem and service operations reject before effects. | Process ownership/recovery, locking, junction/reparse-point grants, credential ACLs, service support and actual text execution. |

The initial controlled Linux profile passed 39 checks on x86_64 Linux/glibc with
Python 3.11.16. Windows build 10.0.26100 AMD64 with Python 3.11.9 passed installed
package/CLI checks and one combined unavailable-operation check. Windows reports
`execution_qualified: false`. Current runs and scoped reports are available from
the repository's [Actions page](https://github.com/StepanKukharskiy/task-relay/actions).
Source changes require their affected checks; old runs do not qualify new behavior.

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

1. Windows process-tree ownership and recovery.
2. Windows locks, file/credential enforcement and service support; extend native
   qualification to actual installed text execution.
3. Native service restart and a bounded authorized provider task with Telegram
   delivery on each host, preserving exact receipts and uncertain outcomes.
4. O13 installation, onboarding, upgrade and explicit data migration.
