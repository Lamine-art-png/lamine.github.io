"""
Compatibility shim so `import agroai` works inside the container.

This file should live at the REPO ROOT: ./agroai.py
"""

# Option A: if your real implementation is here:
try:
    from agroai_api.app.agroai import *  # noqa: F401,F403
except ModuleNotFoundError:
    # Option B: if your real implementation is here instead:
    try:
        from agroai_api.agroai import *  # noqa: F401,F403
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "import agroai failed. Create your core module at one of:\n"
            "- agroai_api/app/agroai.py\n"
            "- agroai_api/agroai.py\n"
            "or change `import agroai` in agroai_api/app/main.py to the correct path."
        ) from e

