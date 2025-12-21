"""
Shim module so the API can `import agroai` inside the container.

This file MUST exist at repo root: ./agroai.py

Goal: importing `agroai` should NEVER crash the container.
Later, you can move real logic here (or re-export from your real module).
"""

from __future__ import annotations

import warnings

# Try to re-export your real implementation if it exists.
# If it doesn't exist yet, we just keep the shim importable.
try:
    # Option A: if your real code lives here
    from agroai_api.app.agroai import *  # noqa: F401,F403
except Exception:
    try:
        # Option B: if your real code lives here
        from agroai_api.agroai import *  # noqa: F401,F403
    except Exception:
        warnings.warn(
            "agroai shim loaded (no real implementation found yet). "
            "This is OK for boot; implement functions later if endpoints need them.",
            RuntimeWarning,
        )

# Optional: expose a tiny marker so you can tell the shim is present
__all__ = globals().get("__all__", [])
__version__ = "0.1.0-shim"

