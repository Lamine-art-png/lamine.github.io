from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.deps import _assert_credential_freshness
from app.core.config import settings
from app.models.saas import AccountRecoveryToken, User
from app.services.credential_recovery import consume_token, digest_token, issue_token


def _user(db, email="operator@example.com"):
    user = User(
        email=email,
        name="Operator",
        password_hash="placeholder",
        is_active=True,
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_recovery_token_is_hashed_single_use_and_revokes_old_sessions(db):
    user = _user(db)
    token = issue_token(db, user)
    assert token
    db.commit()

    row = db.query(AccountRecoveryToken).filter(AccountRecoveryToken.user_id == user.id).one()
    assert row.token_hash == digest_token(token)
    assert row.token_hash != token
    assert row.used_at is None

    old_exp = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    old_payload = {"sub": user.id, "exp": int(old_exp.timestamp())}

    recovered = consume_token(db, token, "A-strong-new-credential-2026")
    assert recovered is not None
    assert recovered.credentials_changed_at is not None

    with pytest.raises(HTTPException) as exc:
        _assert_credential_freshness(old_payload, recovered)
    assert exc.value.status_code == 401

    assert consume_token(db, token, "Another-strong-credential-2026") is None


def test_new_recovery_request_invalidates_previous_token(db):
    user = _user(db)
    first = issue_token(db, user)
    assert first
    db.commit()

    row = db.query(AccountRecoveryToken).filter(AccountRecoveryToken.user_id == user.id).one()
    row.created_at = datetime.utcnow() - timedelta(minutes=2)
    db.commit()

    second = issue_token(db, user)
    assert second and second != first
    db.commit()

    first_row = db.query(AccountRecoveryToken).filter(AccountRecoveryToken.token_hash == digest_token(first)).one()
    assert first_row.used_at is not None
    assert consume_token(db, first, "A-strong-new-credential-2026") is None
    assert consume_token(db, second, "A-strong-new-credential-2026") is not None


def test_recovery_request_cooldown_prevents_token_flood(db):
    user = _user(db)
    first = issue_token(db, user)
    assert first
    db.commit()

    second = issue_token(db, user)
    assert second is None
    assert db.query(AccountRecoveryToken).filter(AccountRecoveryToken.user_id == user.id).count() == 1


def test_expired_recovery_token_fails_closed(db):
    user = _user(db)
    token = issue_token(db, user)
    assert token
    db.commit()

    row = db.query(AccountRecoveryToken).filter(AccountRecoveryToken.token_hash == digest_token(token)).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    assert consume_token(db, token, "A-strong-new-credential-2026") is None


def test_token_issued_after_credential_change_remains_valid(db):
    user = _user(db)
    user.credentials_changed_at = datetime.utcnow() - timedelta(seconds=10)
    db.commit()

    fresh_payload = {
        "sub": user.id,
        "exp": int((datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "iat": int(datetime.utcnow().timestamp()),
    }
    _assert_credential_freshness(fresh_payload, user)
