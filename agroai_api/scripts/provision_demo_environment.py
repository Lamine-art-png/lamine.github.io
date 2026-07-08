#!/usr/bin/env python3
"""Provision AGRO-AI full-access and Free demo identities.

Run from the ``agroai_api`` directory after migrations:

    python scripts/provision_demo_environment.py

Credentials are read only from environment-backed Settings and are never printed.
"""
from __future__ import annotations

import json

from app.db.base import SessionLocal
from app.services.demo_environment import provision_demo_environment


def main() -> int:
    db = SessionLocal()
    try:
        results = provision_demo_environment(db)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "identities": [
                        {
                            "email": item.email,
                            "organization_id": item.organization_id,
                            "organization_slug": item.organization_slug,
                            "access_profile": item.access_profile,
                            "created_user": item.created_user,
                            "created_organization": item.created_organization,
                        }
                        for item in results
                    ],
                },
                indent=2,
            )
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
