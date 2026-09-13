"""Bounded JSON request bridge for the packaged desktop setup window."""
import contextlib
import json
import sys

from .desktop_binding import DesktopBindingError, apply_binding, connect, disconnect
apply_binding()

from . import launcher
from .desktop_macos import DesktopService, DesktopServiceError
from .desktop_tasks import DesktopTaskError, enqueue, enqueue_create, enqueue_file, list_tasks, stop, task_detail
from .desktop_plans import DesktopPlanError, create as create_plan, decide as decide_plan, detail as plan_detail, list_plans, prepare as prepare_plan
from .desktop_usage import summary as usage_summary, breakdown as storage_breakdown
from .desktop_approvals import decide as decide_approval
from .host import UnsupportedHost
from .relay_paths import PATHS, Paths


def _cleanup_paths():
    root = PATHS.data.parent
    source = ((root / 'source_inventory.json').is_file() and (root / 'pyproject.toml').is_file()
              and (root / 'task_relay').is_dir())
    return Paths(root if source else PATHS.data, PATHS.data, PATHS.workspaces, PATHS.generated)


def dispatch(action, value):
    if action == 'companion-status':
        from .companion import status
        return status()
    if action == 'conversation':
        from .companion import conversation
        return conversation()
    if action == 'handoff-status':
        from .desktop_handoff import Handoff
        return Handoff().inspect()
    if action == 'status':
        return launcher.status()
    if action == 'service-status':
        return DesktopService().status()
    if action == 'tasks':
        return list_tasks()
    if action == 'plans':
        return list_plans()
    if action == 'approval-inbox':
        from .desktop_approvals import inbox
        return inbox()
    if action == 'automation-tools':
        from .desktop_library import automation_tools
        return automation_tools()
    if action == 'workflows':
        from .desktop_library import workflows
        if not isinstance(value, dict):
            raise DesktopTaskError('Expected a workflow query.')
        return workflows(value.get('kind', 'linked'), value.get('offset', 0))
    if action == 'usage-summary':
        return usage_summary()
    if action == 'storage-breakdown':
        return storage_breakdown()
    if action == 'cleanup-preview':
        from . import cleanup
        try:
            manifest, report = cleanup.plan(_cleanup_paths())
        except (OSError, ValueError):
            raise DesktopTaskError('Could not prepare a safe cleanup plan at this data location.') from None
        kinds = {}
        for item in report['files']:
            bucket = kinds.setdefault(item['kind'], {'files': 0, 'bytes': 0})
            bucket['files'] += 1
            bucket['bytes'] += item['bytes']
        return {'manifest': str(manifest), 'files': len(report['files']),
                'bytes': report['bytes'], 'kinds': kinds}
    if action == 'service-connect':
        return connect()
    if action == 'service-disconnect':
        return disconnect()
    if not isinstance(value, dict):
        raise launcher.LauncherError('Expected a setup object.')
    if action == 'project':
        return launcher.set_project(value.get('path'))
    if action == 'provider':
        return launcher.set_provider(value.get('name'), value.get('key', ''),
                                     value.get('model', ''), value.get('endpoint', ''))
    if action == 'telegram':
        return launcher.set_telegram(value.get('token', ''))
    if action == 'update-check':
        return launcher.update_check()
    if action == 'service-start':
        return DesktopService().start()
    if action == 'service-stop':
        return DesktopService().stop()
    if action == 'messages-start':
        from .desktop_messages import MessagesService
        return MessagesService().start()
    if action == 'messages-stop':
        from .desktop_messages import MessagesService
        return MessagesService().stop()
    if action in ('handoff-prepare', 'handoff-apply', 'handoff-restore'):
        from .desktop_handoff import Handoff
        handoff = Handoff()
        if action == 'handoff-prepare':
            return handoff.prepare(value.get('channel'))
        if action == 'handoff-apply':
            return handoff.apply(value.get('id'), value.get('digest'))
        return handoff.restore(value.get('id'))
    if action == 'approval-detail':
        from .companion import approval_detail
        return approval_detail(value.get('task_id'))
    if action == 'task-detail':
        return task_detail(value.get('task_id'))
    if action == 'task-create':
        return enqueue_create(value.get('backend'), value.get('project'), value.get('title', ''), value.get('request_id'))
    if action == 'task-send':
        return enqueue(value.get('task_id'), value.get('text'), value.get('request_id'))
    if action == 'task-send-file':
        return enqueue_file(value.get('task_id'), value.get('path'), value.get('text', ''), value.get('request_id'))
    if action == 'task-stop':
        return stop(value.get('task_id'))
    if action == 'task-approval-decide':
        try:
            return decide_approval(value.get('task_id'), value.get('token'), value.get('fingerprint'),
                                   value.get('allow'), value.get('answer'))
        except ValueError as exc:
            raise DesktopTaskError(str(exc)) from None
    if action == 'cleanup-apply':
        from . import cleanup
        manifest = value.get('manifest')
        if not isinstance(manifest, str) or len(manifest) > 4096:
            raise DesktopTaskError('Review a current cleanup plan first.')
        try:
            return cleanup.apply(manifest, _cleanup_paths())
        except (OSError, ValueError):
            raise DesktopTaskError('The cleanup plan changed or could not be applied. Prepare a new plan.') from None
    if action == 'plan-create':
        return create_plan(value.get('goal'), value.get('constraints', ''), value.get('project'),
                           value.get('parent_id'), value.get('request_id'))
    if action == 'plan-detail':
        return plan_detail(value.get('plan_id'))
    if action == 'plan-prepare':
        return prepare_plan(value.get('plan_id'))
    if action == 'plan-decide':
        return decide_plan(value.get('plan_id'), value.get('verb'), value.get('review_digest'))
    raise launcher.LauncherError('Unknown setup action.')


def main():
    try:
        if len(sys.argv) != 2:
            raise launcher.LauncherError('Choose a setup action.')
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise launcher.LauncherError('Request is too large.')
        value = json.loads(raw) if raw else {}
        # Legacy setup functions may print instructions; keep stdout a single
        # machine-readable response and never send entered secrets to the UI.
        with contextlib.redirect_stdout(sys.stderr):
            result = dispatch(sys.argv[1], value)
        reply = {'ok': True, 'value': result}
    except (launcher.LauncherError, DesktopServiceError, DesktopTaskError, DesktopPlanError, DesktopBindingError, UnsupportedHost) as exc:
        reply = {'ok': False, 'error': str(exc)}
    except (ValueError, UnicodeError):
        reply = {'ok': False, 'error': 'Invalid setup request.'}
    except Exception:
        reply = {'ok': False, 'error': 'Action could not finish. Saved steps remain; run task-relay doctor for details.'}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, separators=(',', ':')) + '\n')
    return 0 if reply['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
