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
from .app_updates import UpdateError as AppUpdateError


def _cleanup_paths():
    root = PATHS.data.parent
    source = ((root / 'source_inventory.json').is_file() and (root / 'pyproject.toml').is_file()
              and (root / 'task_relay').is_dir())
    return Paths(root if source else PATHS.data, PATHS.data, PATHS.workspaces, PATHS.generated)


def dispatch(action, value):
    if action.startswith('app-update-'):
        from .app_updates import Updater
        updater = Updater()
        if not isinstance(value, dict): raise ValueError('Expected update settings.')
        if action == 'app-update-status': return updater.status()
        if action == 'app-update-check': return updater.check(value.get('beta', False))
        if action == 'app-update-download': return updater.download(value.get('id'))
        if action == 'app-update-install': return updater.install(value.get('id'))
        if action == 'app-update-recover': return updater.recover(value.get('id'))
        raise ValueError('Unknown app update action.')
    # Serialize desktop mutations with the replacement helper. Read-only status
    # remains available so an interrupted update can be inspected.
    reads = {'status', 'companion-status', 'conversation', 'channel-status', 'handoff-status',
             'service-status', 'tasks', 'plans', 'approval-inbox', 'automation-tools', 'workflows',
             'usage-summary', 'storage-breakdown', 'approval-detail', 'task-detail', 'plan-detail',
             'revision-candidates', 'revision-detail', 'pipeline-delete-preview',
             'pipeline-delete-pending', 'job-delete-preview', 'job-delete-pending',
             'task-delete-preview', 'task-delete-pending',
             'shared-history-list', 'shared-history-preview',
             'computer-sessions', 'computer-session-detail', 'computer-setup-status'}
    reads.update({'workspace-jobs', 'workspace-detail', 'workspace-artifact', 'workspace-request', 'workspace-plan', 'workspace-source-changes', 'workspace-compare'})
    reads.update({'workspace-source', 'workspace-chat', 'workspace-chat-source', 'conversation-delete-preview'})
    if action not in reads:
        from .app_updates import Updater, read, TERMINAL
        updater = Updater()
        if updater.host.support()['supported']:
            with updater.lock():
                pending = read(updater.receipt, {})
                if pending.get('approved') and pending.get('phase') not in TERMINAL:
                    raise AppUpdateError('Finish app update recovery before changing Relay settings or submitting work.')
                return _dispatch(action, value)
    return _dispatch(action, value)


def _dispatch(action, value):
    if action in ('conversation-delete-preview','conversation-delete','conversation-delete-recover'):
        from . import conversation_delete
        if action == 'conversation-delete-preview':return conversation_delete.preview(value.get('id'))
        if action == 'conversation-delete':return conversation_delete.delete(value.get('id'),value.get('digest'))
        return conversation_delete.recover(value.get('id'))
    if action.startswith('workspace-'):
        from . import desktop_workspace
        if action == 'workspace-jobs': return desktop_workspace.jobs(value.get('offset', 0), include_archived=value.get('include_archived', False))
        if action == 'workspace-chat': return desktop_workspace.chat_detail(value.get('id'))
        if action == 'workspace-chat-source': return desktop_workspace.chat_source(value.get('id'), value.get('url'))
        if action == 'workspace-detail': return desktop_workspace.detail(value.get('run'))
        if action == 'workspace-source':
            from .desktop_sources import source_url
            return source_url(value.get('run'), value.get('source'))
        if action == 'workspace-plan': return plan_detail(value.get('plan_id'), shared=True)
        if action == 'workspace-request': return desktop_workspace.request_detail(value.get('request_id'))
        if action == 'workspace-artifact': return desktop_workspace.artifact_path(value.get('artifact'))
        if action in ('workspace-source-changes', 'workspace-compare'):
            from . import desktop_file_changes
            if action == 'workspace-source-changes': return desktop_file_changes.check_sources(value.get('run'))
            return desktop_file_changes.compare(value.get('run'), value.get('change'), value.get('new_sha256'))
        if action == 'workspace-decide':
            return desktop_workspace.decide(value.get('run'), value.get('verb'), value.get('review_digest'),
                value.get('request_id'), value.get('group'), value.get('note', ''))
    if action in ('computer-sessions', 'computer-session-detail', 'computer-session-control', 'computer-setup-status', 'computer-request-permissions'):
        from .desktop_computer import dispatch as computer_dispatch
        return computer_dispatch(action, value)
    if action == 'app-access-update':
        from .app_access import update
        return update(value)
    if action == 'code-runtime-configure':
        from .code_runtime import configure
        if set(value)!={'enabled'}:raise ValueError('Choose whether to enable code tools.')
        return configure(value['enabled'])
    if action == 'worker-verify':
        from orchestrator.executors import probe,PROVIDERS
        if set(value)!={'provider'} or value['provider'] not in PROVIDERS:raise ValueError('Choose a supported worker provider.')
        return probe(value['provider'])
    if action == 'rhino-preference':
        from .rhino_preferences import update
        return update(value)
    if action == 'image-model-refresh':
        from .capability_defaults import refresh_images
        return refresh_images(value)
    if action == 'media-provider':
        from .cloud_providers import connect
        try: return connect(value)
        except ValueError as exc: raise launcher.LauncherError(str(exc)) from None
    if action == 'model-default':
        from .capability_defaults import update
        try:
            return update(value)
        except ValueError as exc:
            raise launcher.LauncherError(str(exc)) from None
    if action in ('browser-configure', 'browser-open', 'browser-sign-in-done'):
        from . import managed_browser
        if not isinstance(value, dict):
            raise ValueError('Expected browser settings.')
        try:
            if action == 'browser-sign-in-done':
                return managed_browser.finish_sign_in()
            return (managed_browser.configure(value.get('enabled')) if action == 'browser-configure'
                    else managed_browser.open_browser())
        except ValueError as exc:
            raise launcher.LauncherError(str(exc)) from None
    if action == 'channel-update':
        from .channel_policy import update
        return update(value)
    if action == 'channel-status':
        from .channel_policy import snapshot
        return snapshot()
    if action == 'companion-status':
        from .companion import status
        return status()
    if action == 'conversation':
        from .companion import conversation
        return conversation()
    if action in ('shared-history-list','shared-history-preview','shared-history-forget'):
        from . import shared_history_delete
        if action == 'shared-history-list':
            return {'items':shared_history_delete.available()}
        if not isinstance(value,dict):
            raise DesktopTaskError('Choose exact local channel history.')
        try:
            if action == 'shared-history-preview':
                return shared_history_delete.preview(value.get('id'))
            return shared_history_delete.forget(value.get('id'),value.get('digest'))
        except shared_history_delete.SharedHistoryDeleteError as exc:
            raise DesktopTaskError(str(exc)) from None
    if action == 'handoff-status':
        from .desktop_handoff import Handoff
        return Handoff().inspect()
    if action == 'status':
        return launcher.status()
    if action == 'service-status':
        return DesktopService().status()
    if action == 'tasks':
        if not isinstance(value, dict):
            raise DesktopTaskError('Expected a task query.')
        return list_tasks(offset=value.get('offset', 0))
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
    if action in ('pipeline-delete-preview', 'pipeline-delete', 'pipeline-delete-recover',
                  'pipeline-delete-pending', 'job-delete-preview', 'job-delete',
                  'job-delete-recover', 'job-delete-pending', 'job-delete-register'):
        from . import job_delete
        if action.endswith('-pending'): return {'items': job_delete.pending()}
        if not isinstance(value, dict): raise DesktopTaskError('Choose a saved job.')
        try:
            if action == 'job-delete-register':
                from .job_ownership import backfill_standalone
                return {'id': backfill_standalone(value.get('run'))}
            if action.endswith('-preview'): return job_delete.preview(value.get('id'))
            if action in ('pipeline-delete', 'job-delete'):
                return job_delete.delete(value.get('id'), value.get('digest'))
            return job_delete.recover(value.get('id'))
        except (job_delete.JobDeleteError, ValueError) as exc:
            raise DesktopTaskError(str(exc)) from None
    if action in ('task-delete-preview','task-delete','task-delete-recover','task-delete-pending'):
        from . import task_delete
        if action == 'task-delete-pending': return {'items':task_delete.pending()}
        if not isinstance(value, dict): raise DesktopTaskError('Choose a saved task.')
        try:
            if action == 'task-delete-preview': return task_delete.preview(value.get('id'))
            if action == 'task-delete': return task_delete.delete(value.get('id'),value.get('digest'))
            return task_delete.recover(value.get('id'))
        except (task_delete.TaskDeleteError, ValueError) as exc:
            raise DesktopTaskError(str(exc)) from None
    if action in ('revision-candidates', 'revision-detail', 'revision-decide'):
        from . import revision_review
        if not isinstance(value, dict):
            raise DesktopTaskError('Expected a revision request.')
        if action == 'revision-candidates':
            return revision_review.candidates()
        if action == 'revision-detail':
            return revision_review.detail(value.get('candidate_artifact'))
        return revision_review.decide(candidate_artifact=value.get('candidate_artifact'),
            verb=value.get('verb'), actor=value.get('actor'), note=value.get('note'),
            expected_sha256=value.get('expected_sha256'),
            expected_plan_digest=value.get('expected_plan_digest'),
            request_id=value.get('request_id'))
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
                           value.get('parent_id'), value.get('request_id'), files=value.get('files'), previous_run=value.get('previous_run'), research_mode=value.get('research_mode', 'suggest'), entry_mode=value.get('entry_mode', 'plan'))
    if action == 'conversation-followup':
        from .conversation_flow import choose
        return choose(value.get('id'),value.get('index'),value.get('digest'),value.get('request_id'))
    if action == 'plan-detail':
        return plan_detail(value.get('plan_id'))
    if action == 'plan-prepare':
        return prepare_plan(value.get('plan_id'), review_digest=value.get('review_digest'))
    if action == 'plan-decide':
        return decide_plan(value.get('plan_id'), value.get('verb'), value.get('review_digest'), request_id=value.get('request_id'))
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
    except (AppUpdateError, launcher.LauncherError, DesktopServiceError, DesktopTaskError, DesktopPlanError, DesktopBindingError, UnsupportedHost) as exc:
        reply = {'ok': False, 'error': str(exc)}
    except (ValueError, UnicodeError):
        reply = {'ok': False, 'error': 'Invalid setup request.'}
    except Exception:
        reply = {'ok': False, 'error': 'Action could not finish. Saved steps remain; run task-relay doctor for details.'}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, separators=(',', ':')) + '\n')
    return 0 if reply['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
