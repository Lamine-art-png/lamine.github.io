from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import Response, status

from app.core.config import settings
from app.core.metrics import platform_rate_limit_checks, platform_rate_limit_latency
from app.platform_api.errors import PlatformApiHTTPException
from app.platform_api.principal import PlatformPrincipal


_MEMORY_BUCKETS: dict[str, tuple[int, int]] = {}

ROUTE_COSTS: dict[str, int] = {
    "platform.me": 1,
    "platform.providers": 1,
    "platform.provider.validate": 2,
    "platform.actions.plan": 2,
    "platform.actions.execute": 5,
    "/v1/platform/providers/{provider_id}/validate-credentials": 2,
    "/v1/platform/actions/plan": 2,
    "/v1/platform/actions/execute": 5,
    "/v1/platform/observations": 2,
    "/v1/platform/recommendations": 3,
    "/v1/platform/reports": 3,
    "/v1/platform/sources/uploads": 2,
}

_REDIS_SCRIPT = """
local cost = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local counter_count = tonumber(ARGV[3])
local retry_key = KEYS[counter_count + 1]
local cached = redis.call("GET", retry_key)
if cached then
  return cjson.decode(cached)
end
local allowed = 1
local min_remaining = nil
local selected_limit = 0
local selected_reset = 0
local retry_after = 0

for i = 1, counter_count do
  local offset = 4 + ((i - 1) * 3)
  local limit = tonumber(ARGV[offset])
  local window_seconds = tonumber(ARGV[offset + 1])
  local reset_epoch = tonumber(ARGV[offset + 2])
  local used = tonumber(redis.call("INCRBY", KEYS[i], cost))
  if used == cost then
    redis.call("EXPIREAT", KEYS[i], reset_epoch + 5)
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
local result = {allowed, selected_limit, min_remaining, selected_reset, retry_after}
redis.call("SET", retry_key, cjson.encode(result), "EX", 10, "NX")
return result
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


@lru_cache(maxsize=4)
def _shared_redis_client(url: str, connect_timeout: float, socket_timeout: float) -> Any:
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=connect_timeout,
        socket_timeout=socket_timeout,
        health_check_interval=30,
    )


def _policy_windows(principal: PlatformPrincipal) -> tuple[RateLimitWindow, ...]:
    if principal.environment == "live":
        burst = int(getattr(settings, "PLATFORM_API_LIVE_BURST_LIMIT", 600))
        sustained = int(getattr(settings, "PLATFORM_API_LIVE_SUSTAINED_LIMIT", 6000))
    elif principal.environment == "test":
        burst = int(getattr(settings, "PLATFORM_API_TEST_BURST_LIMIT", 60))
        sustained = int(getattr(settings, "PLATFORM_API_TEST_SUSTAINED_LIMIT", 600))
    else:
        raise RuntimeError("Platform API rate limiting requires a test or live environment")
    if burst < 1 or sustained < 1:
        raise RuntimeError("Platform API rate-limit policies must be positive")
    return (
        RateLimitWindow("burst", burst, 60),
        RateLimitWindow("sustained", sustained, 3600),
    )


def _rate_limit_subjects(principal: PlatformPrincipal) -> tuple[tuple[str, str], ...]:
    if not principal.organization_id or not principal.api_project_id or not principal.api_key_id:
        raise RuntimeError("Platform API rate limiting requires organization, project, and API key identities")
    return (
        ("organization", principal.organization_id),
        ("project", principal.api_project_id),
        ("key", principal.api_key_id),
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
        for window in _policy_windows(principal):
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

    def __init__(self, *, client: Any | None = None, url: str | None = None, max_retries: int | None = None) -> None:
        self._client = client
        self._url = url
        self._max_retries = max(0, int(max_retries if max_retries is not None else getattr(settings, "PLATFORM_API_REDIS_MAX_RETRIES", 1)))

    def _redis_client(self) -> Any:
        if self._client is not None:
            return self._client
        url = (self._url or str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "")).strip()
        if not url:
            raise RuntimeError("Redis rate-limit backend requires PLATFORM_API_REDIS_URL or REDIS_URL")
        self._client = _shared_redis_client(
            url,
            float(getattr(settings, "PLATFORM_API_REDIS_CONNECT_TIMEOUT_SECONDS", 2.0)),
            float(getattr(settings, "PLATFORM_API_REDIS_SOCKET_TIMEOUT_SECONDS", 2.0)),
        )
        return self._client

    def ping(self) -> bool:
        return bool(self._redis_client().ping())

    @staticmethod
    def _retryable_errors() -> tuple[type[Exception], ...]:
        from redis.exceptions import ConnectionError as RedisConnectionError
        from redis.exceptions import TimeoutError as RedisTimeoutError

        return RedisConnectionError, RedisTimeoutError

    def check(self, principal: PlatformPrincipal, *, cost: int = 1, operation_id: str | None = None) -> RateLimitDecision:
        now = int(time.time())
        environment = principal.environment or "unknown-env"
        keys: list[str] = []
        args: list[int] = [cost, now, 0]
        for subject, value in _rate_limit_subjects(principal):
            for window in _policy_windows(principal):
                key, reset = _bucket_key(subject, value, environment=environment, window=window, now=now)
                keys.append(key)
                args.extend([window.limit, window.window_seconds, reset])
        args[2] = len(keys)
        retry_token = operation_id or secrets.token_hex(16)
        keys.append(f"agroai:platform-rate-limit:v1:retry:{retry_token}")
        client = self._redis_client()
        attempt = 0
        while True:
            try:
                with platform_rate_limit_latency.labels(backend="redis").time():
                    result = client.eval(_REDIS_SCRIPT, len(keys), *keys, *args)
                break
            except self._retryable_errors():
                if attempt >= self._max_retries:
                    raise
                attempt += 1
                time.sleep(min(0.05 * (2 ** (attempt - 1)), 0.2))
        return RateLimitDecision(
            allowed=bool(int(result[0])),
            limit=int(result[1]),
            remaining=int(result[2]),
            reset_epoch=int(result[3]),
            retry_after=int(result[4]),
            backend="redis",
        )


def _redis_check(principal: PlatformPrincipal, *, cost: int, operation_id: str) -> RateLimitDecision:
    url = str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "").strip()
    if not url:
        raise RuntimeError("Redis rate-limit backend requires PLATFORM_API_REDIS_URL or REDIS_URL")
    return RedisRateLimiter(url=url).check(principal, cost=cost, operation_id=operation_id)


def check_rate_limit(principal: PlatformPrincipal, *, route_id: str, cost: int | None = None) -> RateLimitDecision:
    cost = max(1, int(cost if cost is not None else ROUTE_COSTS.get(route_id, 1)))
    windows = _policy_windows(principal)
    backend = str(getattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory") or "memory").strip().lower()
    operation_id = secrets.token_hex(16)
    try:
        if backend == "redis":
            decision = _redis_check(principal, cost=cost, operation_id=operation_id)
        elif backend == "memory":
            if str(getattr(settings, "APP_ENV", "development")).lower() == "production":
                raise RuntimeError("process-local Platform API rate limiting is not permitted in production")
            with platform_rate_limit_latency.labels(backend="memory").time():
                decision = _memory_check(principal, cost=cost)
        else:
            raise RuntimeError(f"unsupported Platform API rate-limit backend: {backend}")
        platform_rate_limit_checks.labels(
            backend=decision.backend,
            environment=principal.environment,
            outcome="allowed" if decision.allowed else "denied",
        ).inc()
        return decision
    except Exception:
        platform_rate_limit_checks.labels(
            backend=backend,
            environment=principal.environment or "unknown",
            outcome="unavailable",
        ).inc()
        fail_open = bool(getattr(settings, "PLATFORM_API_RATE_LIMIT_FAIL_OPEN", False))
        production = str(getattr(settings, "APP_ENV", "development")).strip().lower() == "production"
        if fail_open and not production:
            window = windows[0]
            return RateLimitDecision(True, window.limit, max(0, window.limit - cost), math.ceil(time.time()) + window.window_seconds, backend=backend)
        raise


def enforce_rate_limit(principal: PlatformPrincipal, *, route_id: str, cost: int | None = None) -> RateLimitDecision:
    try:
        decision = check_rate_limit(principal, route_id=route_id, cost=cost)
    except Exception as exc:
        raise PlatformApiHTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "rate_limiter_unavailable",
                "type": "rate_limit_error",
                "message": "The Platform API rate limiter is unavailable.",
                "request_id": principal.request_id,
            },
        ) from exc
    if not decision.allowed:
        raise PlatformApiHTTPException(
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


def apply_rate_limit_headers(response: Response, decision: RateLimitDecision) -> None:
    response.headers["RateLimit-Limit"] = str(decision.limit)
    response.headers["RateLimit-Remaining"] = str(decision.remaining)
    response.headers["RateLimit-Reset"] = str(decision.reset_epoch)


def platform_rate_limiter_readiness() -> dict[str, Any]:
    backend = str(getattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory") or "memory").strip().lower()
    url = str(getattr(settings, "PLATFORM_API_REDIS_URL", "") or getattr(settings, "REDIS_URL", "") or "").strip()
    if backend != "redis":
        return {"ready": False, "backend": backend, "reason": "redis_backend_required"}
    if not url:
        return {"ready": False, "backend": backend, "reason": "redis_url_missing"}
    try:
        ready = RedisRateLimiter(url=url).ping()
    except Exception:
        return {"ready": False, "backend": backend, "reason": "redis_unavailable"}
    return {"ready": ready, "backend": backend, "reason": None if ready else "redis_unavailable"}
