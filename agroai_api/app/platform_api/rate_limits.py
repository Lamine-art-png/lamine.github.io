from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.platform_api.principal import PlatformPrincipal


_MEMORY_BUCKETS: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int
    retry_after: int = 0
    backend: str = "memory"


def _policy_limit(principal: PlatformPrincipal, cost: int) -> tuple[int, int]:
    base = 60 if principal.environment == "test" else 300
    if principal.environment == "live":
        base = 600
    return max(cost, base), 60


def _memory_check(key: str, *, limit: int, window_seconds: int, cost: int) -> RateLimitDecision:
    now = int(time.time())
    window_start = now - (now % window_seconds)
    reset = window_start + window_seconds
    bucket_key = f"{key}:{window_start}"
    used, _reset = _MEMORY_BUCKETS.get(bucket_key, (0, reset))
    next_used = used + cost
    _MEMORY_BUCKETS[bucket_key] = (next_used, reset)
    return RateLimitDecision(
        allowed=next_used <= limit,
        limit=limit,
        remaining=max(0, limit - next_used),
        reset_epoch=reset,
        retry_after=max(1, reset - now) if next_used > limit else 0,
        backend="memory",
    )


def _redis_check(key: str, *, limit: int, window_seconds: int, cost: int) -> RateLimitDecision:
    import redis

    url = str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "").strip()
    if not url:
        raise RuntimeError("Redis rate-limit backend requires PLATFORM_API_REDIS_URL or REDIS_URL")
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    now = int(time.time())
    window_start = now - (now % window_seconds)
    reset = window_start + window_seconds
    redis_key = f"agroai:platform-rate-limit:{key}:{window_start}"
    used = int(client.incrby(redis_key, max(1, int(cost))))
    if used == cost:
        client.expire(redis_key, window_seconds + 5)
    return RateLimitDecision(
        allowed=used <= limit,
        limit=limit,
        remaining=max(0, limit - used),
        reset_epoch=reset,
        retry_after=max(1, reset - now) if used > limit else 0,
        backend="redis",
    )


def check_rate_limit(principal: PlatformPrincipal, *, route_id: str, cost: int = 1) -> RateLimitDecision:
    limit, window = _policy_limit(principal, max(1, cost))
    key = ":".join(
        [
            principal.organization_id or "unknown-org",
            principal.api_project_id or "unknown-project",
            principal.api_key_id or "unknown-key",
            principal.environment or "unknown-env",
            route_id,
        ]
    )
    backend = str(getattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory") or "memory").strip().lower()
    try:
        if backend == "redis":
            return _redis_check(key, limit=limit, window_seconds=window, cost=cost)
        if backend == "memory":
            if str(getattr(settings, "APP_ENV", "development")).lower() == "production":
                raise RuntimeError("process-local Platform API rate limiting is not permitted in production")
            return _memory_check(key, limit=limit, window_seconds=window, cost=cost)
        raise RuntimeError(f"unsupported Platform API rate-limit backend: {backend}")
    except Exception:
        if bool(getattr(settings, "PLATFORM_API_RATE_LIMIT_FAIL_OPEN", False)):
            return RateLimitDecision(True, limit, max(0, limit - cost), math.ceil(time.time()) + window, backend=backend)
        raise


def enforce_rate_limit(principal: PlatformPrincipal, *, route_id: str, cost: int = 1) -> RateLimitDecision:
    try:
        decision = check_rate_limit(principal, route_id=route_id, cost=cost)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "rate_limiter_unavailable",
                "type": "rate_limit_error",
                "message": "The Platform API rate limiter is unavailable.",
                "request_id": principal.request_id,
            },
        ) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={
                "RateLimit-Limit": str(decision.limit),
                "RateLimit-Remaining": str(decision.remaining),
                "RateLimit-Reset": str(decision.reset_epoch),
                "Retry-After": str(decision.retry_after),
            },
            detail={
                "code": "rate_limit_exceeded",
                "type": "rate_limit_error",
                "message": "The Platform API rate limit was exceeded.",
                "request_id": principal.request_id,
                "details": {"retry_after_seconds": decision.retry_after},
            },
        )
    return decision
