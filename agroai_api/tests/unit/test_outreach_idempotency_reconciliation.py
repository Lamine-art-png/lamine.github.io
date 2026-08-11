from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.outreach import execution_v2
from app.outreach.idempotency_reconciliation import provider_error_type


def test_provider_error_type_reads_resend_error_schema():
    assert provider_error_type('{"name":"invalid_idempotent_request","message":"different payload"}') == "invalid_idempotent_request"
    assert provider_error_type('{"type":"concurrent_idempotent_requests"}') == "concurrent_idempotent_requests"
    assert provider_error_type("not-json") is None


def _fake_prospect():
    return SimpleNamespace(
        prospect_id="wave46-152",
        email="buyer@example.com",
        account="Example GSA",
        email_verification_status=SimpleNamespace(value="verified_public_direct"),
    )


def _fake_router(detail):
    def original_execute_one(prospect, *, send_now):
        raise HTTPException(status_code=502, detail=detail)

    rendered = SimpleNamespace(
        subject="Example GSA: one groundwater workflow worth reviewing",
        language="en",
        language_source="explicit_preference",
        language_confidence="high",
        localization_ready=True,
    )
    return SimpleNamespace(
        settings=SimpleNamespace(reply_to="agroaicontact@gmail.com"),
        resend=None,
        _execute_one=original_execute_one,
        _rendered=lambda prospect: rendered,
        _idempotency_key=lambda prospect, email: "agroai-stable-key",
        _TRACKED_LINK_KEYS=("portal", "meeting", "video", "live_demo"),
        _message_metadata=lambda prospect: {
            "message_type": "cold_outreach",
            "recipient_provenance": prospect.email_verification_status.value,
        },
        _language_metadata=lambda email: {
            "language": email.language,
            "language_source": email.language_source,
            "language_confidence": email.language_confidence,
            "localization_ready": email.localization_ready,
        },
    )


def test_invalid_idempotent_request_reconciles_original_tracking_record(monkeypatch):
    fake_router = _fake_router(
        {
            "message": "Resend rejected request with HTTP 409 [invalid_idempotent_request]",
            "record_id": "new-failed-attempt",
        }
    )
    monkeypatch.setattr(
        execution_v2,
        "reconcile_provider_accepted_send",
        lambda **kwargs: "original-provider-accepted-record",
    )
    execution_v2.install_provider_reconciliation(fake_router)

    result = fake_router._execute_one(_fake_prospect(), send_now=True)

    assert result["status"] == "sent"
    assert result["record_id"] == "original-provider-accepted-record"
    assert result["provider_reconciled"] is True
    assert result["resend_id"] is None


def test_concurrent_idempotent_request_is_not_promoted(monkeypatch):
    fake_router = _fake_router(
        {
            "message": "Resend rejected request with HTTP 409 [concurrent_idempotent_requests]",
            "record_id": "failed-attempt",
        }
    )
    monkeypatch.setattr(
        execution_v2,
        "reconcile_provider_accepted_send",
        lambda **kwargs: pytest.fail("concurrent requests must not be reconciled"),
    )
    execution_v2.install_provider_reconciliation(fake_router)

    with pytest.raises(HTTPException) as exc:
        fake_router._execute_one(_fake_prospect(), send_now=True)
    assert exc.value.status_code == 502
