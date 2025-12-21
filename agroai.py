"""
agroai.py (REPO ROOT)

Shim module so the API can `import agroai` inside the container.

Goal: make `import agroai` always succeed so the container boots.
Later, put real logic in:
- agroai_api/app/agroai.py  OR
- agroai_api/agroai.py
…and this shim will re-export it.
"""

from importlib import import_module

_CANDIDATES = ("agroai_api.app.agroai", "agroai_api.agroai")

_loaded = None
for name in _CANDIDATES:
    try:
        _loaded = import_module(name)
        break
    except ModuleNotFoundError:
        continue

if _loaded:
    # Re-export public names from the real module (if present)
    for k in dir(_loaded):
        if not k.startswith("_"):
            globals()[k] = getattr(_loaded, k)

