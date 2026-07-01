"""Startup compatibility shims for AGRO-AI API runtime.

This module is imported automatically by Python when `agroai_api` is on the
runtime path. It keeps legacy forward-reference route annotations from blocking
FastAPI startup while the product shell routes are consolidated.
"""
from __future__ import annotations

import builtins
from typing import Literal

from pydantic import BaseModel, Field


class TeamInvitationCreateRequest(BaseModel):
    """Request body for creating a team invitation."""

    email: str = Field(min_length=3, max_length=240)
    role: Literal["owner", "admin", "manager", "operator", "viewer"] = "viewer"


# FastAPI/Pydantic resolves postponed annotations with eval(). Keeping this name
# in builtins lets the existing product_shell.py forward reference resolve during
# route registration without changing customer-facing behavior.
builtins.TeamInvitationCreateRequest = TeamInvitationCreateRequest
