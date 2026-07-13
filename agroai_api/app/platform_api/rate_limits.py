from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.platform_api.principal import PlatformPrincipal


_MEMORY_BUCKETS: dict[str, tuple[int, int]] = {}

_REDIS_SCRIPT = """
local cost = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local allowed = 1
local min_remaining = nil
local selected_limit = 0
local selected_reset = 0
local retry_after = 0

for i = 1, #KEYS do
  local offset = 3 + ((i - 1) * 3)
  local limit = tonumber(ARGV[offset])
  local window_seconds = tonumber(ARGV[offset + 1])
  local reset_epoch = tonumber(ARGV[offset + 2])
  local used = tonumber(redis.call("INCRBY", KEYS[i], cost))
  if used == cost then
    redis.call("EXPIRE", KEYS[i], window_seconds + 5)
  end
  local remaining = limit - used
  if min_remaining == nil or remaining < min_remaining then
    min_remaining = remaining
    selected_limit = limit
    selected_reset = reset_epoch
  end
  if used > limit then
    allowed = 0
    local wait = reset_epoch - now
    if wait > retry_after then
      retry_after = wait
    end
  end
end

if min_remaining == nil then
  min_remaining = 0
end
if retry_after < 1 and allowed == 0 then
  retry_after = 1
end
if min_remaining < 0 then
  min_remaining = 0
end
return {allowed, selected_limit, min_remaining, selected_reset, retry_after}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int
    retry_after: int = 0
    backend: str = "memory"


@dataclass(frozen=True)
class RateLimitWindow:
    name: str
    limit: int
    window_seconds: int


def _policy_windows(principal: PlatformPrincipal, cost: int) -> tuple[RateLimitWindow, ...]:
    if principal.environment == "live":
        burst = 600
        sustained = 6000
    else:
        burst = 60
        sustained = 600
    return (
        RateLimitWindow("burst", max(cost, burst), 60),
        RateLimitWindow("sustained", max(cost, sustained), 3600),
    )


def _rate_limit_subjects(principal: PlatformPrincipal) -> tuple[tuple[str, str], ...]:
    return (
        ("organization", principal.organization_id or "unknown-org"),
        ("project", principal.api_project_id or "unknown-project"),
        ("key", principal.api_key_id or "unknown-key"),
    )


def _bucket_key(subject: str, value: str, *, environment: str, window: RateLimitWindow, now: int) -> tuple[str, int]:
    window_start = now - (now % window.window_seconds)
    redis_safe_value = str(value).replace(":", "_")
    key = f"agroai:platform-rate-limit:v1:{environment}:{subject}:{redis_safe_value}:{window.name}:{window_start}"
    return key, window_start + window.window_seconds


def _memory_check(principal: PlatformPrincipal, *, cost: int) -> RateLimitDecision:
    now = int(time.time())
    allowed = True
    selected_limit = 0
    selected_remaining: int | None = None
    selected_reset = 0
    retry_after = 0
    environment = principal.environment or "unknown-env"
    for subject, value in _rate_limit_subjects(principal):
        for window in _policy_windows(principal, cost):
            key, reset = _bucket_key(subject, value, environment=environment, window=window, now=now)
            used, _reset = _MEMORY_BUCKETS.get(key, (0, reset))
            next_used = used + cost
            _MEMORY_BUCKETS[key] = (next_used, reset)
            remaining = window.limit - next_used
            if selected_remaining is None or remaining < selected_remaining:
                selected_remaining = remaining
                selected_limit = window.limit
                selected_reset = reset
            if next_used > window.limit:
                allowed = False
                retry_after = max(retry_after, reset - now)
    return RateLimitDecision(
        allowed=allowed,
        limit=selected_limit,
        remaining=max(0, selected_remaining or 0),
        reset_epoch=selected_reset,
        retry_after=max(1, retry_after) if not allowed else 0,
        backend="memory",
    )


class RedisRateLimiter:
    """Atomic Redis-backed limiter shared by independent API processes."""

    def __init__(self, *, client: Any | None = None, url: str | None = None) -> None:
        self._client = client
        self._url = url

    def _redis_client(self) -> Any:
        if self._client is not None:
            return self._client
        import redis

        url = (self._url or str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "")).strip()
        if not url:
            raise RuntimeError("Redis rate-limit backend requires PLATFORM_API_REDIS_URL or REDIS_URL")
        self._client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        return self._client

    def check(self, principal: PlatformPrincipal, *, cost: int = 1) -> RateLimitDecision:
        now = int(time.time())
        environment = principal.environment or "unknown-env"
        keys: list[str] = []
        args: list[int] = [cost, now]
        for subject, value in _rate_limit_subjects(principal):
            for window in _policy_windows(principal, cost):
                key, reset = _bucket_key(subject, value, environment=environment, window=window, now=now)
                keys.append(key)
                args.extend([window.limit, window.window_seconds, reset])
        result = self._redis_client().eval(_REDIS_SCRIPT, len(keys), *keys, *args)
        return RateLimitDecision(
            allowed=bool(int(result[0])),
            limit=int(result[1]),
            remaining=int(result[2]),
            reset_epoch=int(result[3]),
            retry_after=int(result[4]),
            backend="redis",
        )


def _redis_check(principal: PlatformPrincipal, *, cost: int) -> RateLimitDecision:
    import redis

    url = str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "").strip()
    if not url:
        raise RuntimeError("Redis rate-limit backend requires PLATFORM_API_REDIS_URL or REDIS_URL")
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    return RedisRateLimiter(client=client).check(principal, cost=cost)


def check_rate_limit(principal: PlatformPrincipal, *, route_id: str, cost: int = 1) -> RateLimitDecision:
    del route_id  # route cost is carried by the caller-supplied weighted cost.
    cost = max(1, int(cost))
    windows = _policy_windows(principal, cost)
    backend = str(getattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory") or "memory").strip().lower()
    try:
        if backend == "redis":
            return _redis_check(principal, cost=cost)
        if backend == "memory":
            if str(getattr(settings, "APP_ENV", "development")).lower() == "production":
                raise RuntimeError("process-local Platform API rate limiting is not permitted in production")
            return _memory_check(principal, cost=cost)
        raise RuntimeError(f"unsupported Platform API rate-limit backend: {backend}")
    except Exception:
        if bool(getattr(settings, "PLATFORM_API_RATE_LIMIT_FAIL_OPEN", False)):
            window = windows[0]
            return RateLimitDecision(True, window.limit, max(0, window.limit - cost), math.ceil(time.time()) + window.window_seconds, backend=backend)
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
