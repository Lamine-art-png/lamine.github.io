"""Local full-stack API for browser end-to-end tests. Never for production.

Serves the real FastAPI app on a throwaway SQLite database, seeds one verified
Team-plan owner, and captures transactional email into a JSON-lines outbox
file instead of calling a provider, so a browser test can follow the exact
link a customer would receive.

    python scripts/e2e_fullstack_server.py --port 8765 --db /tmp/e2e.db \
        --outbox /tmp/outbox.jsonl --seed /tmp/seed.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", required=True)
    parser.add_argument("--outbox", required=True)
    parser.add_argument("--seed", required=True, help="where to write the seeded owner credentials")
    args = parser.parse_args()

    if os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}:
        sys.exit("refusing to run the e2e server with APP_ENV=production")
    Path(args.db).unlink(missing_ok=True)
    Path(args.outbox).write_text("")
    os.environ["APP_ENV"] = "development"
    os.environ["DATABASE_URL"] = f"sqlite:///{args.db}"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import uvicorn
    from fastapi.testclient import TestClient

    import app.models  # noqa: F401  (register every table)
    from app.db.base import Base, SessionLocal, engine
    from app.main import app
    from app.models.saas import Organization, User

    Base.metadata.create_all(bind=engine)

    def capture(**message):
        record = {key: value for key, value in message.items() if key in {"to_email", "subject", "text_body", "html_body"}}
        with open(args.outbox, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return {"ok": True, "provider": "e2e-outbox", "status_code": 200}

    import app.services.operations_notifications as operations_notifications
    import app.services.team_invitations as team_invitations

    team_invitations.send_email = capture
    operations_notifications.send_email = capture

    owner = {"email": "owner@e2e.agroai.test", "password": "Harvest-Ledger-Pump-2026", "organization": "E2E Orchard Co"}
    with TestClient(app) as client:
        response = client.post("/v1/auth/register", json={
            "email": owner["email"], "password": owner["password"], "name": "E2E Owner",
            "organization_name": owner["organization"], "workspace_name": "Main", "crop": "Almonds", "region": "California",
        })
        if response.status_code != 201:
            sys.exit(f"seeding failed: {response.status_code} {response.text}")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == owner["email"]).one()
        user.email_verification_status, user.email_verified_at, user.account_status = "verified", datetime.utcnow(), "active"
        org = db.query(Organization).filter(Organization.name == owner["organization"]).one()
        org.plan, org.subscription_status = "team", "active"
        db.commit()
    Path(args.seed).write_text(json.dumps(owner))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
