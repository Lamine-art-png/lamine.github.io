"""AGRO-AI API application package."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
