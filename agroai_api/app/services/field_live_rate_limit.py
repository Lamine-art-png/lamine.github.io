"""Tenant/user rate limits for near-real-time Field Intelligence analysis."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import settings

_CHANNEL_WINDOWS = {
    "vision": (("minute", 8, 60), ("hour", 240, 3600)),
    "speech": (("minute", 6, 60), ("hour", 180, 3600)),
}
_MEMORY: dict[str, tuple[int, int]] = {}
_MEMORY_LOCK = threading.Lock()

_REDIS_SCRIPT = """
local now = tonumber(ARGV[1])
local allowed = 1
local remaining = nil
local retry_after = 0
for i = 1, #KEYS do
  local offset = 2 + ((i - 1) * 2)
  local limit = tonumber(ARGV[offset])
  local ttl = tonumber(ARGV[offset + 1])
  local used = tonumber(redis.call('INCR', KEYS[i]))
  if used == 1 then redis.call('EXPIRE', KEYS[i], ttl) end
  local left = limit - used
  if remaining == nil or left < remaining then remaining = left end
  if used > limit then
    allowed = 0
    local key_ttl = tonumber(redis.call('TTL', KEYS[i]))
    if key_ttl > retry_after then retry_after = key_ttl end
  end
end
if remaining == nil or remaining < 0 then remaining = 0 end
if allowed == 0 and retry_after < 1 then retry_after = 1 end
return {allowed, remaining, retry_after}
"""


@dataclass(frozen=True)
class FieldLiveRateDecision:
    allowed: bool
    remaining: int
    retry_after: int
    backend: str


@lru_cache(maxsize=2)
def _redis_client(url: str) -> Any:
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        health_check_interval=30,
    )


def _subject(organization_id: str, user_id: str) -> str:
    raw = f"{organization_id}:{user_id}"
    return raw.replace(" ", "_").replace("/", "_")[:240]


def _memory_check(subject: str, windows: tuple[tuple[str, int, int], ...]) -> FieldLiveRateDecision:
    now = int(time.time())
    allowed = True
    remaining: int | None = None
    retry_after = 0
    with _MEMORY_LOCK:
        for name, limit, seconds in windows:
            window_start = now - (now % seconds)
            reset = window_start + seconds
            key = f"{subject}:{name}:{window_start}"
            used, _ = _MEMORY.get(key, (0, reset))
            used += 1
            _MEMORY[key] = (used, reset)
            left = limit - used
            remaining = left if remaining is None else min(remaining, left)
            if used > limit:
                allowed = False
                retry_after = max(retry_after, reset - now)
        if len(_MEMORY) > 5000:
            expired = [key for key, (_, reset) in _MEMORY.items() if reset <= now]
            for key in expired[:2500]:
                _MEMORY.pop(key, None)
    return FieldLiveRateDecision(allowed, max(0, remaining or 0), max(1, retry_after) if not allowed else 0, "memory")


def check_field_live_analysis_limit(
    organization_id: str, user_id: str, *, channel: str = "vision"
) -> FieldLiveRateDecision:
    normalized_channel = channel if channel in _CHANNEL_WINDOWS else "vision"
    windows = _CHANNEL_WINDOWS[normalized_channel]
    subject = f"{normalized_channel}:{_subject(str(organization_id), str(user_id))}"
    url = str(getattr(settings, "REDIS_URL", "") or "").strip()
    if url:
        now = int(time.time())
        keys: list[str] = []
        args: list[int] = [now]
        for name, limit, seconds in windows:
            window_start = now - (now % seconds)
            keys.append(f"agroai:field-live:v1:{subject}:{name}:{window_start}")
            args.extend([limit, seconds + 5])
        try:
            result = _redis_client(url).eval(_REDIS_SCRIPT, len(keys), *keys, *args)
            return FieldLiveRateDecision(
                allowed=bool(int(result[0])),
                remaining=max(0, int(result[1])),
                retry_after=max(0, int(result[2])),
                backend="redis",
            )
        except Exception:  # noqa: BLE001 - bounded in-process fallback remains protective
            pass
    return _memory_check(subject, windows)
