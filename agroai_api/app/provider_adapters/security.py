from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings


def _allowed_hosts() -> set[str]:
    raw = str(getattr(settings, "PROVIDER_BASE_URL_ALLOWLIST", "") or "")
    return {item.strip().lower() for item in raw.replace(";", ",").split(",") if item.strip()}


def validate_provider_base_url(url: str, *, allow_local_dev: bool = False) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https":
        if not (allow_local_dev and parsed.scheme == "http" and str(getattr(settings, "APP_ENV", "development")).lower() != "production"):
            raise ValueError("provider base URL must use HTTPS")
    if not parsed.hostname:
        raise ValueError("provider base URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("provider base URL must not include user info")
    host = parsed.hostname.lower()
    allowed = _allowed_hosts()
    if allowed and host not in allowed:
        raise ValueError("provider host is not allowlisted")
    if str(getattr(settings, "APP_ENV", "development")).lower() == "production":
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
        except socket.gaierror as exc:
            raise ValueError("provider host cannot be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_multicast or ip.is_reserved:
                raise ValueError("provider host resolves to an unsafe network address")
    return parsed.geturl()
