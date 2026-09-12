"""Compatibility entry point; implementation lives in task_relay.approval_ui."""
if __name__ == "__main__":
    import runpy
    runpy.run_module("task_relay.approval_ui", run_name="__main__")
else:
    import importlib
    import sys
    sys.modules[__name__] = importlib.import_module("task_relay.approval_ui")
