"""Environment-backed WhatsApp runtime settings.

Kept separate from the main Settings model so the integration remains
deployable across mixed-version worker/API rollouts.
"""
from __future__ import annotations

import os
from typing import Any

from app.core.config import settings


def value(name: str, default: Any = None) -> Any:
    raw = os.getenv(name)
    if raw is not None:
        return raw
    return getattr(settings, name, default)


def boolean(name: str, default: bool = False) -> bool:
    raw = value(name, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def integer(name: str, default: int) -> int:
    return int(value(name, default))


def floating(name: str, default: float) -> float:
    return float(value(name, default))
