"""Compatibility entry point; implementation lives in task_relay.production_status."""
if __name__ == "__main__":
    import runpy
    runpy.run_module("task_relay.production_status", run_name="__main__")
else:
    import importlib
    import sys
    sys.modules[__name__] = importlib.import_module("task_relay.production_status")
