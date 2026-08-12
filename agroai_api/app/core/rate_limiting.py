"""Rate limiting for API endpoints.

SlowAPI wraps endpoint callables before FastAPI inspects their signatures. When
an endpoint module uses ``from __future__ import annotations``, those annotations
are strings. A third-party wrapper then has a different ``__globals__`` mapping,
so FastAPI/Pydantic can fail to resolve request-model forward references while
building the route.

Resolve postponed annotations against the endpoint's own module globals before
SlowAPI creates its wrapper. This preserves the normal SlowAPI behavior while
making decorated FastAPI routes deterministic across the pinned dependency set.
"""
from __future__ import annotations

from functools import wraps
import logging
from typing import Any, Callable, get_type_hints

from fastapi import HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)


class AnnotationSafeLimiter(Limiter):
    """SlowAPI limiter that resolves postponed endpoint annotations first.

    ``functools.wraps`` copies ``__annotations__`` to SlowAPI's wrapper, but the
    wrapper itself lives in SlowAPI's module. Leaving string forward references
    unresolved therefore makes FastAPI evaluate names in the wrong global
    namespace. Resolve them on the original function before delegating to
    SlowAPI. If a deliberately unresolved forward reference exists, preserve the
    library's original behavior rather than hiding the error here.
    """

    def limit(self, limit_value: Any, *args: Any, **kwargs: Any) -> Callable:
        slowapi_decorator = super().limit(limit_value, *args, **kwargs)

        def decorator(func: Callable) -> Callable:
            annotations = getattr(func, "__annotations__", None)
            if annotations and any(isinstance(value, str) for value in annotations.values()):
                try:
                    func.__annotations__ = get_type_hints(
                        func,
                        globalns=func.__globals__,
                        localns=func.__globals__,
                    )
                except (NameError, TypeError):
                    # Do not manufacture types. SlowAPI/FastAPI will surface a
                    # genuinely unresolved annotation through the normal path.
                    pass
            return slowapi_decorator(func)

        return decorator


# Initialize rate limiter.
limiter = AnnotationSafeLimiter(
    key_func=get_remote_address,
    storage_uri=(str(getattr(settings, "REDIS_URL", "") or "").strip() or "memory://"),
    headers_enabled=False,
)


class RateLimiterDependency:
    """Rate limiter dependency for FastAPI routes."""

    def __init__(self, limit: int = 100):
        """
        Initialize rate limiter.

        Args:
            limit: Requests per minute (default: 100)
        """
        self.limit = limit
        self.window = "1 minute"

    async def __call__(self, request: Request):
        """Apply rate limit."""
        # Extract tenant_id from request state if available
        tenant_id = getattr(request.state, "tenant_id", None)

        # Rate limit key includes tenant for tenant-specific limits
        if tenant_id:
            key = f"tenant:{tenant_id}"
        else:
            key = get_remote_address(request)

        # Check limit (simplified - production should use Redis)
        # For now, just log and allow (actual limiting would need stateful backend)
        logger.debug(f"Rate limit check for {key}: {self.limit}/{self.window}")

        return None
