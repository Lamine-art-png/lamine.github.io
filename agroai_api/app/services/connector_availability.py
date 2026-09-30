"""Which connectors a customer can actually launch today.

A provider is only launchable when AGRO-AI completes its authorization and
ingests its data. Providers whose authorization would succeed but whose data
never reaches the workspace are ``coming_soon``: the catalog says so and the
launch endpoints refuse them, so a customer is never sent through a provider
consent screen that produces nothing.
"""
from __future__ import annotations

from fastapi import HTTPException, status

COMING_SOON_PROVIDERS = frozenset({"gmail", "box", "slack", "salesforce", "dropbox", "google_earth_engine"})


def assert_connector_launchable(provider: str | None) -> None:
    if str(provider or "").strip().lower() in COMING_SOON_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "connector_coming_soon",
                "message": "This connector is coming soon and cannot be connected yet. Use file upload to bring this data into AGRO-AI.",
            },
        )
