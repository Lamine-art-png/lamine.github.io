from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import whatsapp_cloud
from app.services.whatsapp_cloud import WhatsAppCloudError


def test_whatsapp_graph_api_version_is_explicit_and_fail_closed(monkeypatch):
    original = getattr(settings, "WHATSAPP_GRAPH_API_VERSION", "")
    monkeypatch.delenv("WHATSAPP_GRAPH_API_VERSION", raising=False)
    object.__setattr__(settings, "WHATSAPP_GRAPH_API_VERSION", "")
    try:
        with pytest.raises(WhatsAppCloudError, match="not configured"):
            whatsapp_cloud._api_version()
    finally:
        object.__setattr__(settings, "WHATSAPP_GRAPH_API_VERSION", original)


def test_whatsapp_graph_api_version_rejects_malformed_values(monkeypatch):
    original = getattr(settings, "WHATSAPP_GRAPH_API_VERSION", "")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "latest")
    try:
        with pytest.raises(WhatsAppCloudError, match="invalid"):
            whatsapp_cloud._api_version()
    finally:
        object.__setattr__(settings, "WHATSAPP_GRAPH_API_VERSION", original)


def test_whatsapp_graph_api_version_accepts_pinned_version(monkeypatch):
    original = getattr(settings, "WHATSAPP_GRAPH_API_VERSION", "")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v99.0")
    try:
        assert whatsapp_cloud._api_version() == "v99.0"
    finally:
        object.__setattr__(settings, "WHATSAPP_GRAPH_API_VERSION", original)
