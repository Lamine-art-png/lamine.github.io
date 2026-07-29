import pytest
from fastapi import HTTPException

from app.models.operational_records import ConnectorConnection
from app.models.saas import Organization, User
from app.services import connector_commercial_guard  # noqa: F401


def _org(db, *, suffix: str, plan: str, subscription_status: str) -> Organization:
    user = User(
        id=f"user-{suffix}",
        email=f"{suffix}@example.com",
        password_hash="test",
        is_active=True,
        email_verification_status="verified",
    )
    org = Organization(
        id=f"org-{suffix}",
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
        owner_user_id=user.id,
        plan=plan,
        subscription_status=subscription_status,
    )
    db.add_all([user, org])
    db.commit()
    return org


def _connection(org: Organization, provider: str) -> ConnectorConnection:
    return ConnectorConnection(
        tenant_id=org.id,
        provider=provider,
        display_name=provider,
        status="connected",
        mode="oauth" if provider in {"gmail", "google_drive", "slack"} else "api_credentials",
        required_plan="free",
        config_json={},
    )


def test_free_plan_keeps_manual_import_connector_access(db):
    org = _org(db, suffix="free-manual", plan="free", subscription_status="inactive")
    row = _connection(org, "manual_csv")
    row.mode = "manual_upload"
    db.add(row)
    db.commit()
    assert row.id is not None


def test_free_plan_cannot_create_live_connector_by_direct_db_write(db):
    org = _org(db, suffix="free-live", plan="free", subscription_status="inactive")
    db.add(_connection(org, "weather"))
    with pytest.raises(HTTPException) as exc:
        db.flush()
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "upgrade_required"
    db.rollback()


def test_professional_live_connector_capacity_is_enforced(db):
    org = _org(db, suffix="professional", plan="professional", subscription_status="active")
    for provider in ("weather", "openet", "wiseconn"):
        db.add(_connection(org, provider))
        db.commit()

    db.add(_connection(org, "talgil"))
    with pytest.raises(HTTPException) as exc:
        db.flush()
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "quota_exceeded"
    assert exc.value.detail["metric"] == "active_connector"
    assert exc.value.detail["limit"] == 3
    db.rollback()


def test_professional_org_and_connector_can_be_created_in_one_transaction(db):
    user = User(
        id="user-same-transaction",
        email="same-transaction@example.com",
        password_hash="test",
        is_active=True,
        email_verification_status="verified",
    )
    org = Organization(
        id="org-same-transaction",
        name="Same Transaction Farms",
        slug="org-same-transaction",
        owner_user_id=user.id,
        plan="professional",
        subscription_status="active",
    )
    connection = _connection(org, "whatsapp")

    db.add_all([user, org, connection])
    db.commit()

    assert connection.id is not None
    assert connection.tenant_id == org.id
