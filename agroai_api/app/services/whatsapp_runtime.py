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


def _install_settings_aliases() -> None:
    aliases = {
        "WHATSAPP_ENABLED": boolean("WHATSAPP_ENABLED", False),
        "WHATSAPP_VERIFY_TOKEN": str(value("WHATSAPP_VERIFY_TOKEN", "") or ""),
        "WHATSAPP_APP_SECRET": str(value("WHATSAPP_APP_SECRET", "") or ""),
        "WHATSAPP_GRAPH_API_VERSION": str(value("WHATSAPP_GRAPH_API_VERSION", "") or ""),
        "WHATSAPP_GRAPH_API_BASE_URL": str(value("WHATSAPP_GRAPH_API_BASE_URL", "https://graph.facebook.com") or ""),
        "WHATSAPP_WEBHOOK_MAX_BYTES": integer("WHATSAPP_WEBHOOK_MAX_BYTES", 2 * 1024 * 1024),
        "WHATSAPP_MEDIA_MAX_BYTES": integer("WHATSAPP_MEDIA_MAX_BYTES", 50 * 1024 * 1024),
        "WHATSAPP_HTTP_TIMEOUT_SECONDS": floating("WHATSAPP_HTTP_TIMEOUT_SECONDS", 20.0),
        "WHATSAPP_SERVICE_WINDOW_HOURS": integer("WHATSAPP_SERVICE_WINDOW_HOURS", 24),
        "WHATSAPP_MAX_ATTEMPTS": integer("WHATSAPP_MAX_ATTEMPTS", 5),
    }
    for name, resolved in aliases.items():
        try:
            object.__setattr__(settings, name, resolved)
        except Exception:
            # The helpers above still read os.environ directly, so failure to
            # expose an alias cannot disable the integration.
            pass


_install_settings_aliases()
