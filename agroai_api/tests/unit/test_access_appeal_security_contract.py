from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_EMAILS = {
    "emmanuel.ahoa@wur.nl",
    "apoorvakaushal.2001@gmail.com",
    "hichemabidiaz@gmail.com",
    "omt91560@gmail.com",
    "a.heckmann@agvolution.com",
    "geraldjtb@gmail.com",
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_migration_restricts_exactly_the_six_selected_legacy_accounts():
    source = _read("alembic/versions/022_account_access_appeals.py")

    for email in TARGET_EMAILS:
        assert f'"{email}"' in source

    assert source.count("@") == len(TARGET_EMAILS)
    assert 'account_status="suspended_pending_appeal"' in source
    assert "is_active=False" in source
    assert 'verification_status="suspended_pending_appeal"' in source
    assert "credentials_changed_at=now" in source


def test_appeal_links_are_non_enumerating_hashed_single_use_and_rate_limited():
    source = _read("app/api/v1/access_appeals.py")

    assert 'GENERIC_RESPONSE = "If the account is eligible for an appeal, a secure link has been sent."' in source
    assert "secrets.token_urlsafe(32)" in source
    assert 'hashlib.sha256(token.encode("utf-8")).hexdigest()' in source
    assert "token_used_at" in source
    assert "timedelta(hours=48)" in source
    assert '@limiter.limit("3/minute")' in source
    assert '@limiter.limit("5/minute")' in source


def test_appeal_review_is_platform_admin_only_and_restores_access_explicitly():
    source = _read("app/api/v1/platform_admin.py")

    assert 'Depends(require_platform_admin)' in source
    assert 'Literal["approve", "reject", "request_information"]' in source
    assert 'user.account_status = "active"' in source
    assert 'user.account_status = "suspended_pending_appeal"' in source
    assert 'organization.verification_status = "approved_manual_appeal"' in source
    assert 'event_type="access_appeal_decision"' in source


def test_portal_exposes_public_appeal_and_private_admin_review_routes():
    routes = _read("../figma-enterprise-v4/src/app/routes.tsx")
    client = _read("../figma-enterprise-v4/src/app/api/client.ts")

    assert '{ path: "/appeal", Component: AccessAppealPage' in routes
    assert 'path: "admin/access-appeals"' in routes
    assert 'accessAppeals:' in client
    assert 'platformAdmin/access-appeals' not in client
    assert '/v1/platform-admin/access-appeals' in client
