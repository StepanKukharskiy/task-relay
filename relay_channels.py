"""Compatibility entry point; implementation lives in task_relay.relay_channels."""
if __name__ == "__main__":
    import runpy
    runpy.run_module("task_relay.relay_channels", run_name="__main__")
else:
    import importlib
    import sys
    sys.modules[__name__] = importlib.import_module("task_relay.relay_channels")
