from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class TeamInvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    role: Literal["owner", "admin", "manager", "operator", "viewer"] = "viewer"


__import__("builtins").TeamInvitationCreateRequest = TeamInvitationCreateRequest
