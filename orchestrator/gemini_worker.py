"""Compatibility entry point for the shared agent runtime.

Saved launch paths and imports retain this name; there is only one implementation.
"""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator import agent_loop
if __name__ == '__main__':
    agent_loop.main()
else:
    sys.modules[__name__] = agent_loop
