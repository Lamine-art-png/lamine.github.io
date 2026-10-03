"""Resolve the SDK packages from this directory, not the monorepo root.

CI runs these tests from the repository root, whose legacy top-level
``agroai/`` demo package would otherwise shadow the SDK's ``agroai``.
Installed users are unaffected.
"""
import sys
from pathlib import Path

_SDK_ROOT = str(Path(__file__).resolve().parents[1])
if sys.path[:1] != [_SDK_ROOT]:
    sys.path.insert(0, _SDK_ROOT)
for _name in [name for name in sys.modules if name == "agroai" or name.startswith("agroai.")]:
    del sys.modules[_name]
