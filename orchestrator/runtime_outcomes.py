"""Code-owned holds, independent of provider, role and application."""
from .operation_session import outcome


class Hold(ValueError):
    def __init__(self, code, message, *, phase='compile', effect='none'):
        super().__init__(message)
        self.outcome = outcome(phase, 'needs_user', code, effect=effect)
        self.outcome['detail'] = message


class UncertainOperation(Hold, RuntimeError):
    """Dispatched work without a verified terminal receipt must not be replayed."""
    def __init__(self, message):
        super().__init__('operation_uncertain', message, phase='produce', effect='uncertain')

