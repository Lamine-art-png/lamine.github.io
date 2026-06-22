"""Pure-Python readline compatibility shim for local test runs.

The macOS conda Python 3.13 runtime used in this workspace segfaults when the
native ``readline`` extension is imported. Pytest imports ``readline`` during
early capture setup, before project fixtures can run. Keeping this small module
at the backend root makes pytest import a harmless shim instead of the unstable
native extension. The application does not depend on readline behavior.
"""
from __future__ import annotations

backend = "stub"


def parse_and_bind(*args, **kwargs):
    return None


def set_completer(*args, **kwargs):
    return None


def get_completer():
    return None


def set_completer_delims(*args, **kwargs):
    return None


def get_completer_delims():
    return ""


def add_history(*args, **kwargs):
    return None


def clear_history():
    return None


def read_history_file(*args, **kwargs):
    return None


def write_history_file(*args, **kwargs):
    return None

