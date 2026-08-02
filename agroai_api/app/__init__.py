"""AGRO-AI API application package."""
from __future__ import annotations

from typing import Literal

from app.billing_bootstrap import apply_live_billing_bootstrap


# This package is imported before ``app.main`` and therefore before
# ``app.core.config`` constructs the immutable Settings snapshot. The helper is
# deliberately fail-closed and records only non-secret diagnostics when the
# live wiring is incomplete.
apply_live_billing_bootstrap()


from pydantic import BaseModel, Field  # noqa: E402

__version__ = "1.1.0"


class TeamInvitationCreateRequest(BaseModel):
    """Request body for creating a team invitation.

    FastAPI resolves some postponed route annotations during router
    registration. This package module is imported before app.main, so exposing
    the request model here keeps legacy product-shell annotations resolvable at
    startup.
    """

    email: str = Field(min_length=3, max_length=240)
    role: Literal["owner", "admin", "manager", "operator", "viewer"] = "viewer"


__import__("builtins").TeamInvitationCreateRequest = TeamInvitationCreateRequest
