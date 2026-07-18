from __future__ import annotations

import hmac
import ipaddress

from fastapi import Request

from app.core.config import settings


EDGE_AUTH_HEADER = "x-agroai-edge-auth"
EDGE_CLIENT_IP_HEADER = "x-agroai-edge-client-ip"
UNTRUSTED_FORWARDING_HEADERS = (
    "cf-connecting-ip",
    "true-client-ip",
    "x-forwarded-for",
    "x-real-ip",
)


def normalize_cidr_allowlist(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in values or []:
        try:
            network = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid CIDR allowlist entry: {raw}") from exc
        canonical = str(network)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def resolve_authoritative_client_ip(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    configured = str(getattr(settings, "PLATFORM_API_EDGE_AUTH_SECRET", "") or "").strip()
    supplied = request.headers.get(EDGE_AUTH_HEADER, "").strip()
    edge_ip = request.headers.get(EDGE_CLIENT_IP_HEADER, "").strip()
    if configured and supplied and hmac.compare_digest(configured, supplied):
        try:
            return ipaddress.ip_address(edge_ip)
        except ValueError:
            return None

    # Forwarding headers supplied without the authenticated Cloudflare-to-Render
    # edge context are attacker-controlled and must never influence authorization.
    if edge_ip or supplied or any(request.headers.get(name) for name in UNTRUSTED_FORWARDING_HEADERS):
        return None
    return None


def client_ip_allowed(request: Request, cidrs: list[str] | None) -> bool:
    networks = [ipaddress.ip_network(value, strict=False) for value in normalize_cidr_allowlist(cidrs)]
    if not networks:
        return True
    client_ip = resolve_authoritative_client_ip(request)
    if client_ip is None:
        return False
    return any(client_ip.version == network.version and client_ip in network for network in networks)
