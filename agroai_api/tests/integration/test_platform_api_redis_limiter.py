from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from app.core.config import settings
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.rate_limits import RedisRateLimiter


pytestmark = pytest.mark.integration


def _integration_url() -> str:
    url = os.getenv("PLATFORM_API_REDIS_INTEGRATION_URL", "").strip()
    if not url:
        pytest.skip("PLATFORM_API_REDIS_INTEGRATION_URL is required for real Redis tests")
    return url


@pytest.fixture
def redis_limiters():
    url = _integration_url()
    client_a = redis.Redis.from_url(url, decode_responses=True)
    client_b = redis.Redis.from_url(url, decode_responses=True)
    assert client_a.ping() and client_b.ping()
    prefix = "agroai:platform-rate-limit:v1:*"
    existing = list(client_a.scan_iter(match=prefix, count=1000))
    if existing:
        client_a.delete(*existing)
    yield RedisRateLimiter(client=client_a), RedisRateLimiter(client=client_b), client_a
    created = list(client_a.scan_iter(match=prefix, count=1000))
    if created:
        client_a.delete(*created)
    client_a.close()
    client_b.close()


def _principal(*, organization: str | None = None, project: str | None = None, key: str | None = None, environment: str = "test") -> PlatformPrincipal:
    marker = uuid.uuid4().hex
    return PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=organization or f"org-{marker}",
        api_project_id=project or f"project-{marker}",
        api_key_id=key or f"key-{marker}",
        environment=environment,
    )


def test_real_redis_shares_atomic_counters_across_independent_limiter_instances(redis_limiters):
    limiter_a, limiter_b, client = redis_limiters
    principal = _principal()

    first = limiter_a.check(principal, cost=59)
    denied = limiter_b.check(principal, cost=2)

    assert first.allowed is True
    assert first.remaining == 1
    assert denied.allowed is False
    assert denied.limit == 60
    assert denied.remaining == 0
    assert denied.retry_after >= 1
    counter_keys = list(client.scan_iter(match="agroai:platform-rate-limit:v1:test:*"))
    assert len(counter_keys) == 6
    assert all(client.ttl(key) > 0 for key in counter_keys)


def test_real_redis_atomic_limit_holds_under_two_instance_concurrency(redis_limiters):
    limiter_a, limiter_b, _client = redis_limiters
    principal = _principal()

    def check(index: int) -> bool:
        limiter = limiter_a if index % 2 == 0 else limiter_b
        return limiter.check(principal, cost=1).allowed

    with ThreadPoolExecutor(max_workers=16) as pool:
        decisions = list(pool.map(check, range(100)))

    assert sum(decisions) == 60


def test_real_redis_enforces_dimensions_weighted_costs_and_test_live_policies(redis_limiters):
    limiter_a, limiter_b, _client = redis_limiters
    base = _principal(organization="org-shared", project="project-shared", key="key-a")
    sibling_key = _principal(organization="org-shared", project="project-shared", key="key-b")
    other_org = _principal(organization="org-other", project="project-other", key="key-other")
    live = _principal(organization="org-live", project="project-live", key="key-live", environment="live")

    assert limiter_a.check(base, cost=59).allowed is True
    assert limiter_b.check(sibling_key, cost=1).allowed is True
    assert limiter_a.check(sibling_key, cost=1).allowed is False
    assert limiter_b.check(other_org, cost=60).allowed is True
    assert limiter_a.check(live, cost=600).allowed is True
    assert limiter_b.check(live, cost=1).allowed is False


def test_real_redis_sustained_window_is_enforced_atomically(redis_limiters, monkeypatch):
    limiter_a, limiter_b, _client = redis_limiters
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_BURST_LIMIT", 1000)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_SUSTAINED_LIMIT", 61)
    principal = _principal()

    assert limiter_a.check(principal, cost=60).allowed is True
    denied = limiter_b.check(principal, cost=2)

    assert denied.allowed is False
    assert denied.limit == 61
    assert denied.remaining == 0
    assert denied.retry_after >= 1
