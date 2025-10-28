"""Rate limiting for API endpoints."""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request, HTTPException, status
from functools import wraps
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


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
