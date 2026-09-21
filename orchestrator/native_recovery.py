"""Translate native executor receipts into the shared recovery policy.

The executor/host adapter owns phase semantics. Error messages and provider
suggestions are deliberately not inputs to the retry decision.
"""
from .recovery import Evidence, decide

PHASES = {
    'rhino3dm.run_python': ('before', 'model', 'verify'),
    'rhino.run_python': ('before', 'model', 'verify'),
    'blender.run_python': ('before', 'edit', 'verify'),
    'sketchup.run_ruby': ('before', 'model', 'verify'),
}


def evidence(receipt, capability):
    unknown = Evidence()
    if not isinstance(receipt, dict) or capability not in PHASES:
        return unknown
    if receipt.get('capability', capability) != capability or receipt.get('passed') is True:
        return unknown
    runs = receipt.get('runs')
    if not isinstance(runs, list) or not runs or not all(isinstance(r, dict) for r in runs):
        return unknown
    phases = tuple(r.get('mode') for r in runs)
    # Legacy repair callers may supply only the terminal phase. Such fragments
    # can diagnose a failure, but never prove that execution did not start.
    before_only = phases == ('before',)
    if phases != PHASES[capability][:len(phases)] and not (len(phases) == 1 and phases[0] in PHASES[capability][1:]):
        return unknown
    last = runs[-1]
    if receipt.get('validation_error'):
        return Evidence(reason='Execution evidence failed validation; inspect the retained receipt before retry.')
    if before_only and capability != 'blender.run_python':
        no_worker = last.get('worker') is None
        unsubmitted = last.get('submitted') is not True and last.get('transport') != 'shared_document'
        if (last.get('launched') is False and unsubmitted and no_worker
                and last.get('pid') is None and last.get('returncode') is None):
            return Evidence('not_started', True, reason='The adapter confirms that no host worker was launched or submitted.')
        # Only an owned, terminated baseline process; no later script phase.
        if (last.get('launched') is True and unsubmitted and no_worker
                and type(last.get('pid')) is int and last['pid'] > 0
                and type(last.get('returncode')) is int and last['returncode'] != 0):
            return Evidence('not_started', True, reason='The owned baseline process terminated before the script execution phase.')
    if before_only and capability == 'blender.run_python':
        if type(last.get('returncode')) is int and last['returncode'] != 0 and not last.get('timeout'):
            return Evidence('not_started', True, reason='Blender terminated in the baseline phase before the approved edit script ran.')
    if phases[-1] not in PHASES[capability][1:] or last.get('timeout') or last.get('error_code'):
        return unknown
    if capability == 'blender.run_python':
        terminal = type(last.get('returncode')) is int and last['returncode'] != 0
        script_error = 'Traceback (most recent call last)' in (last.get('stderr', '') + last.get('stdout', ''))
    else:
        worker = last.get('worker')
        terminal = isinstance(worker, dict) and worker.get('passed') is False
        script_error = terminal and bool(worker.get('error'))
    if terminal and script_error:
        return Evidence('failed', True, True, 'The adapter records a terminal script or verification failure.')
    return unknown


def assess(receipt, capability):
    return decide(evidence(receipt, capability))


def require_ready(receipt, capability):
    """Readiness is checked again at Start; this check does not grant execution."""
    from .native_apps import profile
    app = profile(capability).discover()
    if not app.get('available', bool(app.get('executable'))) or not app.get('executable'):
        raise ValueError('The selected native application is unavailable; restore it before recovery.')
    if capability == 'rhino.run_python':
        from task_relay import rhino_host
        rhino_host.require_recovery_ready(app['executable'], receipt['runs'][-1])
    elif capability == 'sketchup.run_ruby':
        from task_relay import sketchup_host
        if sketchup_host.running_instances(app['executable']):
            raise ValueError('SketchUp is still running; resolve its host readiness before recovery.')
    return app
