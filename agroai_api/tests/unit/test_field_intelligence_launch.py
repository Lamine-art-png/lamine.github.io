"""Stage A launch contracts: rollout states, kill switch, canary allowlist,
release alignment, worker topology, migration tooling, provider hardening,
metrics redaction and production-configuration truthfulness."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from app.models.saas import EntitlementOverride
from app.services import field_intelligence_rollout as rollout
from app.services.field_intelligence_metrics import _redact
from app.services.field_transcription import (
    CloudflareWorkersAITranscriptionProvider,
    OpenAIWhisperTranscriptionProvider,
    get_transcription_provider,
)

from tests.unit.test_field_intelligence import _auth, _initiate


# --------------------------------------------------------------------------- #
# Release states and cohorts
# --------------------------------------------------------------------------- #

def _set_state(monkeypatch, value):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", value)


def _auth_headers_for_existing_user(db, email: str):
    from app.core.security import create_access_token
    from app.models.saas import OrganizationMembership, User

    user = db.query(User).filter(User.email == email).one()
    membership = db.query(OrganizationMembership).filter(OrganizationMembership.user_id == user.id).one()
    token = create_access_token({
        "sub": user.id,
        "tenant_id": membership.organization_id,
        "org_id": membership.organization_id,
        "role": membership.role,
    })
    return {"Authorization": f"Bearer {token}"}


def test_default_state_is_disabled_in_production(monkeypatch, db):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr("app.core.config.settings.INTERNAL_FULL_ACCESS_EMAILS", "")
    _set_state(monkeypatch, "")
    assert rollout.configured_release_state() == "disabled"
    assert rollout.effective_release_state(db) == "disabled"


def test_configured_platform_admin_organization_gets_internal_launch(client, db, monkeypatch):
    _auth(db)
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    monkeypatch.setattr("app.core.config.settings.INTERNAL_FULL_ACCESS_EMAILS", "")
    _set_state(monkeypatch, "")
    headers = _auth_headers_for_existing_user(db, "fi@example.com")
    assert rollout.configured_release_state() == "internal"
    result = _initiate(client, headers, client_capture_id="internal-live", idempotency_key="internal-live")
    assert result.status_code == 200, result.text


def test_default_state_is_general_in_development(monkeypatch, db):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "development")
    _set_state(monkeypatch, "")
    assert rollout.configured_release_state() == "general"


def test_disabled_state_blocks_all_routes(client, db, monkeypatch):
    _, _, headers = _auth(db)
    _set_state(monkeypatch, "disabled")
    res = _initiate(client, headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "field_intelligence_not_released"
    assert client.get("/v1/field-intelligence/observations", headers=headers).status_code == 403


def test_internal_state_admits_only_internal_cohort(client, db, monkeypatch):
    org, _, headers = _auth(db)
    _set_state(monkeypatch, "internal")
    assert _initiate(client, headers).status_code == 403
    monkeypatch.setattr("app.core.config.settings.FIELD_INTERNAL_ORGANIZATION_IDS", org.id)
    assert _initiate(client, headers, client_capture_id="i1", idempotency_key="i1").status_code == 200


def test_canary_state_admits_env_allowlist_and_db_override(client, db, monkeypatch):
    org, _, headers = _auth(db)
    _set_state(monkeypatch, "canary")
    assert _initiate(client, headers).status_code == 403

    # Environment allowlist admits the canary organization…
    monkeypatch.setattr("app.core.config.settings.FIELD_CANARY_ORGANIZATION_IDS", org.id)
    assert _initiate(client, headers, client_capture_id="c1", idempotency_key="c1").status_code == 200

    # …and so does a database rollout override with no hardcoded identifiers.
    monkeypatch.setattr("app.core.config.settings.FIELD_CANARY_ORGANIZATION_IDS", "")
    assert _initiate(client, headers, client_capture_id="c2", idempotency_key="c2").status_code == 403
    db.add(EntitlementOverride(organization_id=org.id,
                               feature_key=rollout.ROLLOUT_FEATURE_KEY,
                               value_json={"value": "canary"}))
    db.commit()
    assert _initiate(client, headers, client_capture_id="c3", idempotency_key="c3").status_code == 200


def test_plan_override_can_never_grant_general(db, monkeypatch):
    org, _, _headers = _auth(db)
    db.add(EntitlementOverride(organization_id=org.id,
                               feature_key=rollout.ROLLOUT_FEATURE_KEY,
                               value_json={"value": "general"}))
    db.commit()
    # "general" is not an admissible override cohort: the org classifies as a
    # normal general-population org and is NOT admitted in internal/canary.
    _set_state(monkeypatch, "internal")
    allowed, state, cohort = rollout.field_intelligence_access(db, org)
    assert (allowed, state, cohort) == (False, "internal", "general")


def test_kill_switch_blocks_immediately_and_is_audited(client, db, monkeypatch):
    from app.models.saas import SecurityAuditEvent

    org, _, headers = _auth(db)
    _set_state(monkeypatch, "general")
    assert _initiate(client, headers).status_code == 200
    rollout.set_kill_switch(db, active=True, actor_user_id="admin-x", reason="incident drill")
    res = _initiate(client, headers, client_capture_id="k1", idempotency_key="k1")
    assert res.status_code == 403
    assert res.json()["detail"]["release_state"] == "disabled"
    audits = db.query(SecurityAuditEvent).filter(
        SecurityAuditEvent.event_type == "field_intelligence_rollout_change").all()
    assert any(a.outcome == "kill_switch_enabled" for a in audits)
    rollout.set_kill_switch(db, active=False, actor_user_id="admin-x")
    assert _initiate(client, headers, client_capture_id="k2", idempotency_key="k2").status_code == 200


def test_kill_switch_pauses_processing_but_not_deletion(db, monkeypatch):
    from app.services.field_intelligence_worker import drain_once

    rollout.set_kill_switch(db, active=True, actor_user_id="admin-x")
    monkeypatch.setattr("app.services.field_intelligence_worker.SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    tick = drain_once(worker_id="test-worker-pause")
    assert tick["paused"] is True
    assert tick["processing"] == {"skipped": "kill_switch"}
    assert "deleted" in tick["deletions"]  # deletion plane still ran


def test_general_activation_requires_alignment_in_production(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    _set_state(monkeypatch, "general")
    # Test database has no alembic_version and no live workers: misaligned.
    assert rollout.effective_release_state(db) == "canary"


def test_release_override_is_audited_and_wins_over_config(db, monkeypatch):
    _set_state(monkeypatch, "general")
    rollout.set_release_override(db, state="internal", actor_user_id="admin-x", reason="staged rollout")
    assert rollout.effective_release_state(db) == "internal"
    rollout.set_release_override(db, state=None, actor_user_id="admin-x")
    assert rollout.effective_release_state(db) == "general"
    with pytest.raises(ValueError):
        rollout.set_release_override(db, state="everything", actor_user_id="admin-x")


# --------------------------------------------------------------------------- #
# Admin surface authorization
# --------------------------------------------------------------------------- #

def test_admin_surface_requires_platform_admin(client, db, monkeypatch):
    _, _, headers = _auth(db)
    for path in ("/v1/field-intelligence/admin/rollout",
                 "/v1/field-intelligence/admin/operations",
                 "/v1/field-intelligence/admin/workers"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post("/v1/field-intelligence/admin/kill-switch",
                       json={"active": True}, headers=headers).status_code == 403

    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    assert client.get("/v1/field-intelligence/admin/rollout", headers=headers).status_code == 200
    ops = client.get("/v1/field-intelligence/admin/operations", headers=headers)
    assert ops.status_code == 200
    body = ops.json()
    assert {"rollout", "tenants", "jobs", "workers"} <= set(body)
    flip = client.post("/v1/field-intelligence/admin/kill-switch",
                       json={"active": True, "reason": "drill"}, headers=headers)
    assert flip.status_code == 200 and flip.json()["rollout"]["kill_switch"] is True
    client.post("/v1/field-intelligence/admin/kill-switch", json={"active": False}, headers=headers)


def test_admin_surface_reachable_while_feature_disabled(client, db, monkeypatch):
    _, _, headers = _auth(db)
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    _set_state(monkeypatch, "disabled")
    assert client.get("/v1/field-intelligence/admin/rollout", headers=headers).status_code == 200



def test_admin_audit_is_platform_admin_only_bounded_and_metadata_only(client, db, monkeypatch):
    from app.models.field_intelligence import FieldObservationAuditEvent

    org, _, headers = _auth(db)
    db.add(FieldObservationAuditEvent(
        id="audit-proof-1", tenant_id=org.id, observation_id="obs-audit-proof",
        action="observation_deleted", actor="sensitive-actor-id", actor_type="user",
        details_json={"private_detail": "must-not-leak"},
    ))
    db.commit()
    path = "/v1/field-intelligence/admin/audit?observation_id=obs-audit-proof&limit=10"
    assert client.get(path, headers=headers).status_code == 403
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1 and payload["events"][0]["action"] == "observation_deleted"
    assert set(payload["events"][0]) == {"id", "action", "actor_type", "created_at"}
    assert "sensitive-actor-id" not in response.text and "private_detail" not in response.text


# --------------------------------------------------------------------------- #
# Worker topology
# --------------------------------------------------------------------------- #

def test_worker_heartbeat_and_queue_health(db):
    from app.services.field_intelligence_worker import queue_health, record_worker_heartbeat, worker_status

    record_worker_heartbeat(db, "wk-test-1", {"processed": 0})
    status = worker_status(db)
    ids = [i["worker_id"] for i in status["instances"]]
    assert "wk-test-1" in ids
    assert status["instances"][0]["live"] is True
    health = queue_health(db)
    assert "field_intelligence_process" in health["depth"]


def test_worker_drain_records_heartbeat(db, monkeypatch):
    from app.models.field_intelligence import FieldWorkerHeartbeat
    from app.services.field_intelligence_worker import drain_once

    monkeypatch.setattr("app.services.field_intelligence_worker.SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    tick = drain_once(worker_id="wk-test-2")
    assert "error" not in tick
    assert db.get(FieldWorkerHeartbeat, "wk-test-2") is not None


# --------------------------------------------------------------------------- #
# Production configuration truthfulness
# --------------------------------------------------------------------------- #

def _readiness_codes(monkeypatch, **overrides):
    from app.core.config import settings as live_settings
    from app.services.production_readiness import evaluate_production_readiness

    for key, value in overrides.items():
        monkeypatch.setattr(f"app.core.config.settings.{key}", value)
    report = evaluate_production_readiness(live_settings)
    return {finding.code for finding in report.blockers}


def test_activation_requires_object_storage_and_real_provider(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        FIELD_INTELLIGENCE_RELEASE_STATE="canary",
        CONNECTOR_OBJECT_STORAGE_BACKEND="disabled",
        FIELD_TRANSCRIPTION_PROVIDER="fake",
    )
    assert "field_intelligence.object_storage_missing" in codes
    assert "field_intelligence.transcription_provider_fake" in codes


def test_disabled_state_needs_no_field_contract(monkeypatch):
    codes = _readiness_codes(monkeypatch, FIELD_INTELLIGENCE_RELEASE_STATE="disabled")
    assert not any(code.startswith("field_intelligence.") for code in codes)


def test_general_requires_release_shas(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        FIELD_INTELLIGENCE_RELEASE_STATE="general",
        FIELD_RELEASE_PORTAL_SHA="",
        FIELD_RELEASE_EDGE_SHA="",
    )
    assert "field_intelligence.release_shas_unreported" in codes


def test_missing_provider_credentials_block(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        FIELD_INTELLIGENCE_RELEASE_STATE="internal",
        FIELD_TRANSCRIPTION_PROVIDER="openai_whisper",
        FIELD_TRANSCRIPTION_ENDPOINT="",
        FIELD_TRANSCRIPTION_API_KEY="",
    )
    assert "field_intelligence.transcription_credentials_missing" in codes


# --------------------------------------------------------------------------- #
# Transcription provider hardening
# --------------------------------------------------------------------------- #

def test_whisper_provider_selected_and_bounded(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "openai_whisper")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", "https://stt.example/v1/audio/transcriptions")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "k")
    provider = get_transcription_provider()
    assert provider.name == "openai_whisper"
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MAX_BYTES", 10)
    result = provider.transcribe_bytes(audio=b"x" * 11, content_type="audio/ogg", language=None)
    assert result.status == "failed" and result.retryable is False
    assert result.error == "audio_exceeds_provider_input_bound"


def test_whisper_provider_multilingual_language_provenance(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", "https://stt.example/v1/audio/transcriptions")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "k")

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"text": "riego de 45 minutos en el bloque A", "language": "es"}

    class _Client:
        def __init__(self, timeout=None):
            _Client.seen_timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, files=None):
            _Client.seen = {"url": url, "data": data, "has_file": bool(files)}
            assert "Authorization" in headers
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    provider = OpenAIWhisperTranscriptionProvider()
    result = provider.transcribe_bytes(audio=b"\x00" * 100, content_type="audio/webm", language=None)
    assert result.succeeded and result.language == "es"
    assert result.metadata["detected_language"] == "es"
    assert _Client.seen["has_file"] is True
    assert "language" not in (_Client.seen["data"] or {})  # detection when no hint


def test_whisper_provider_retryable_vs_terminal(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", "https://stt.example/x")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "k")

    def _client_for(status_code):
        class _Resp:
            pass
        _Resp.status_code = status_code
        _Resp.json = staticmethod(lambda: {})

        class _Client:
            def __init__(self, timeout=None): ...
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def post(self, *a, **k): return _Resp()
        return _Client

    import httpx
    provider = OpenAIWhisperTranscriptionProvider()
    monkeypatch.setattr(httpx, "Client", _client_for(503))
    assert provider.transcribe_bytes(audio=b"x", content_type=None, language="en").retryable is True
    monkeypatch.setattr(httpx, "Client", _client_for(400))
    assert provider.transcribe_bytes(audio=b"x", content_type=None, language="en").retryable is False



def _configure_cloudflare_transcription(monkeypatch):
    model = "@cf/openai/whisper-large-v3-turbo"
    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/stage-account-123/ai/run/"
        + model
    )
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "cloudflare_workers_ai")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", endpoint)
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "cf-staging-token")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MODEL", model)
    return endpoint, model


def test_cloudflare_workers_ai_provider_selected_and_bounded(monkeypatch):
    _configure_cloudflare_transcription(monkeypatch)
    provider = get_transcription_provider()
    assert provider.name == "cloudflare_workers_ai"
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MAX_BYTES", 10)
    result = provider.transcribe_bytes(audio=b"x" * 11, content_type="audio/wav", language=None)
    assert result.status == "failed" and result.retryable is False
    assert result.error == "audio_exceeds_provider_input_bound"


def test_cloudflare_workers_ai_json_base64_and_response_provenance(monkeypatch):
    endpoint, model = _configure_cloudflare_transcription(monkeypatch)

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "success": True,
                "errors": [],
                "messages": [],
                "result": {
                    "text": "irrigation ran forty five minutes on Block A",
                    "transcription_info": {"language": "en", "word_count": 8},
                    "segments": [{"start": 0.0, "end": 2.0}],
                    "vtt": "WEBVTT",
                },
            }

    class _Client:
        def __init__(self, timeout=None):
            _Client.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            _Client.seen = {"url": url, "headers": headers, "json": json}
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    audio = b"RIFF" + b"field-audio"
    result = CloudflareWorkersAITranscriptionProvider().transcribe_bytes(
        audio=audio, content_type="audio/wav", language=None
    )
    assert result.succeeded and result.model == model and result.language == "en"
    assert result.metadata["transport"] == "cloudflare_workers_ai_json_base64"
    assert result.metadata["word_count"] == 8
    assert result.metadata["segment_count"] == 1
    assert result.metadata["vtt_available"] is True
    assert _Client.seen["url"] == endpoint
    assert _Client.seen["headers"]["Authorization"] == "Bearer cf-staging-token"
    assert base64.b64decode(_Client.seen["json"]["audio"]) == audio
    assert _Client.seen["json"]["task"] == "transcribe"
    assert _Client.seen["json"]["vad_filter"] is True
    assert _Client.seen["json"]["condition_on_previous_text"] is False
    assert "language" not in _Client.seen["json"]


def test_cloudflare_workers_ai_language_hint_endpoint_guard_and_retry(monkeypatch):
    endpoint, _model = _configure_cloudflare_transcription(monkeypatch)

    class _EnvelopeError:
        status_code = 200

        @staticmethod
        def json():
            return {"success": False, "errors": [{"message": "rate limit exceeded"}]}

    class _Client:
        calls = 0

        def __init__(self, timeout=None): ...
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, headers=None, json=None):
            _Client.calls += 1
            assert url == endpoint and json["language"] == "fr"
            return _EnvelopeError()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    provider = CloudflareWorkersAITranscriptionProvider()
    result = provider.transcribe_bytes(audio=b"audio", content_type="audio/wav", language="fr")
    assert result.status == "failed" and result.error == "provider_envelope_error"
    assert result.retryable is True and _Client.calls == 1

    monkeypatch.setattr(
        "app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT",
        "https://evil.example/client/v4/accounts/x/ai/run/@cf/openai/whisper-large-v3-turbo",
    )
    blocked = provider.transcribe_bytes(audio=b"audio", content_type="audio/wav", language=None)
    assert blocked.error == "invalid_cloudflare_workers_ai_endpoint"
    assert blocked.retryable is False and _Client.calls == 1


def test_cloudflare_workers_ai_readiness_requires_official_matching_endpoint(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        FIELD_INTELLIGENCE_RELEASE_STATE="internal",
        FIELD_TRANSCRIPTION_PROVIDER="cloudflare_workers_ai",
        FIELD_TRANSCRIPTION_ENDPOINT="https://evil.example/ai/run/@cf/openai/whisper-large-v3-turbo",
        FIELD_TRANSCRIPTION_API_KEY="configured",
        FIELD_TRANSCRIPTION_MODEL="@cf/openai/whisper-large-v3-turbo",
    )
    assert "field_intelligence.transcription_endpoint_invalid" in codes



def test_cloudflare_workers_ai_production_edge_fallback(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.API_URL", "https://api.agroai-pilot.com")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MODEL", "")
    monkeypatch.setattr("app.core.config.settings.CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "edge-consumer-secret")
    provider = get_transcription_provider()
    assert provider.name == "cloudflare_workers_ai"
    assert provider.available() is True
    assert provider.uses_internal_edge() is True
    assert provider._resolved_endpoint() == "https://api.agroai-pilot.com/v1/internal/edge/field-transcription"
    assert provider._resolved_api_key() == "edge-consumer-secret"


def test_internal_launch_readiness_accepts_protected_edge_transcription(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        APP_ENV="production",
        FIELD_INTELLIGENCE_RELEASE_STATE="",
        PLATFORM_ADMIN_EMAILS="fi@example.com",
        INTERNAL_FULL_ACCESS_EMAILS="",
        FIELD_TRANSCRIPTION_PROVIDER="",
        FIELD_TRANSCRIPTION_ENDPOINT="",
        FIELD_TRANSCRIPTION_API_KEY="",
        FIELD_TRANSCRIPTION_MODEL="",
        API_URL="https://api.agroai-pilot.com",
        CLOUDFLARE_QUEUE_CONSUMER_TOKEN="edge-consumer-secret",
        CONNECTOR_OBJECT_STORAGE_BACKEND="r2",
        CONNECTOR_OBJECT_BUCKET="agroai-connector-objects-prod",
    )
    assert "field_intelligence.transcription_provider_missing" not in codes
    assert "field_intelligence.transcription_credentials_missing" not in codes
    assert "field_intelligence.transcription_endpoint_invalid" not in codes


def test_portal_allows_first_party_field_capture_devices():
    headers_path = Path(__file__).resolve().parents[3] / "figma-enterprise-v4" / "public" / "_headers"
    headers = headers_path.read_text(encoding="utf-8")
    assert "microphone=(self)" in headers
    assert "geolocation=(self)" in headers
    assert "microphone=()" not in headers
    assert "geolocation=()" not in headers


# --------------------------------------------------------------------------- #
# Metrics / logging redaction
# --------------------------------------------------------------------------- #

def test_structured_event_redaction():
    redacted = _redact({
        "transcript": "the whole confidential field note",
        "note_text": "secret",
        "object_ref": "s3://bucket/private/key",
        "filename": "customer.wav",
        "api_key": "sk-123",
        "stage": "transcription",
        "latency_ms": 42,
        "nested": {"Authorization": "Bearer x", "count": 3},
    })
    assert redacted["transcript"] == "[redacted]"
    assert redacted["note_text"] == "[redacted]"
    assert redacted["object_ref"] == "[redacted]"
    assert redacted["filename"] == "[redacted]"
    assert redacted["api_key"] == "[redacted]"
    assert redacted["nested"]["Authorization"] == "[redacted]"
    assert redacted["stage"] == "transcription" and redacted["latency_ms"] == 42
    assert redacted["nested"]["count"] == 3


# --------------------------------------------------------------------------- #
# Migration tooling (SQLite path; the PostgreSQL path runs in CI and locally)
# --------------------------------------------------------------------------- #

def test_migration_cli_roundtrip_sqlite(tmp_path):
    import subprocess
    import sys

    url = f"sqlite:///{tmp_path}/launch.db"
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "field_intelligence_migration.py")

    def run(cmd):
        proc = subprocess.run(
            [sys.executable, script, cmd, "--database-url", url],
            capture_output=True, text=True, timeout=300,
        )
        stdout = proc.stdout.strip()
        payload = json.loads(stdout[stdout.index("{"):]) if "{" in stdout else {}
        return proc.returncode, payload

    code, payload = run("preflight")
    assert code == 0 and payload["ok"], payload
    code, payload = run("upgrade")
    assert code == 0 and payload["ok"], payload
    code, payload = run("verify")
    assert code == 0 and payload["ok"], payload
    code, payload = run("downgrade")
    assert code == 0 and payload["ok"], payload
    code, payload = run("verify-rollback")
    assert code == 0 and payload["ok"], payload
    code, payload = run("upgrade")
    assert code == 0 and payload["ok"], payload


# --------------------------------------------------------------------------- #
# Model-routed extraction (Stage B1)
# --------------------------------------------------------------------------- #

class _FakeRouterResult:
    def __init__(self, content, status="ok"):
        self.status = status
        self.content = content
        self.provider = "fake-hosted"
        self.model = "fake-extractor-1"


def _install_fake_router(monkeypatch, payload: dict, *, status="ok"):
    import json as _json

    class _FakeRouter:
        def mode(self):
            return "hosted"

        async def run(self, **kwargs):
            _FakeRouter.seen = kwargs
            class _Sel:
                model = "fake-extractor-1"
            return _FakeRouterResult(_json.dumps(payload), status=status), _Sel()

    monkeypatch.setattr("app.services.model_router.ModelRouter", lambda: _FakeRouter())
    return _FakeRouter


def test_model_extraction_grounded_and_provenanced(monkeypatch):
    from app.services.field_observation_extraction import extract_observation

    _install_fake_router(monkeypatch, {
        "event_type": "irrigation_event",
        "field_candidate": "north ranch",
        "block_candidate": "Block A",
        "crop": "Almonds",
        "severity": "medium",
        "measurements": [{"label": "irrigation_duration", "value": 45, "unit": "minutes"}],
        "irrigation_duration_minutes": 45,
        "applied_water_gallons": 1200,
        "summary": "Irrigated Block A for 45 minutes, 1200 gallons.",
        "confidence": 0.9,
        "uncertain_fields": [],
    })
    result = extract_observation(
        "Irrigation ran 45 minutes on Block A, applied 1200 gallons.",
        workspace_fields=["North Ranch"], workspace_blocks=["Block A"], workspace_crops=["Almonds"],
    )
    assert result.method == "model-routed-v1"
    assert result.provider == "fake-hosted" and result.model == "fake-extractor-1"
    assert result.prompt_version
    assert result.field_candidate == "North Ranch"  # authorized spelling wins
    assert result.irrigation_duration_minutes == 45
    assert result.applied_water_gallons == 1200


def test_model_extraction_rejects_hallucinated_values(monkeypatch):
    from app.services.field_observation_extraction import extract_observation

    _install_fake_router(monkeypatch, {
        "event_type": "irrigation_event",
        "field_candidate": "Secret Government Field",  # not authorized, not in text
        "severity": "critical",
        "measurements": [{"label": "applied_water", "value": 99999, "unit": "gallons"}],
        "applied_water_gallons": 99999,  # number not present in the note
        "occurrence_time": "2020-01-01T00:00:00Z",  # model may never set times
        "people": ["Nonexistent Person"],
        "summary": "made up",
        "confidence": 0.99,
    })
    result = extract_observation(
        "Checked the pump today, everything nominal.",
        workspace_fields=["North Ranch"],
    )
    assert result.method == "model-routed-v1"
    assert result.field_candidate is None
    assert result.applied_water_gallons is None
    assert not result.measurements
    assert result.occurrence_time is None
    assert result.people == []
    assert "applied_water_gallons" in result.uncertain_fields
    assert result.confidence <= 0.85  # uncertainty caps confidence


def test_model_extraction_falls_back_truthfully(monkeypatch):
    from app.services.field_observation_extraction import extract_observation

    class _OfflineRouter:
        def mode(self):
            return "offline"

    monkeypatch.setattr("app.services.model_router.ModelRouter", lambda: _OfflineRouter())
    result = extract_observation("Irrigation ran 45 minutes on Block A.")
    assert result.method == "deterministic-v1"
    assert result.fallback_reason == "model_unavailable_or_invalid"


def test_extraction_mode_deterministic_never_calls_model(monkeypatch):
    from app.services.field_observation_extraction import extract_observation

    monkeypatch.setattr("app.core.config.settings.FIELD_EXTRACTION_MODE", "deterministic")

    def _boom():
        raise AssertionError("model router must not be constructed")

    monkeypatch.setattr("app.services.model_router.ModelRouter", _boom)
    result = extract_observation("Irrigation ran 45 minutes.")
    assert result.method == "deterministic-v1"
    assert result.fallback_reason is None


def test_model_extraction_multilingual_passthrough(monkeypatch):
    from app.services.field_observation_extraction import extract_observation

    _install_fake_router(monkeypatch, {
        "event_type": "irrigation_event",
        "severity": "info",
        "measurements": [{"label": "duracion", "value": 45, "unit": "minutos"}],
        "irrigation_duration_minutes": 45,
        "summary": "Riego de 45 minutos en el bloque A.",
        "confidence": 0.8,
    })
    result = extract_observation("Riego de 45 minutos en el bloque A.")
    assert result.summary.startswith("Riego")
    assert result.irrigation_duration_minutes == 45


# --------------------------------------------------------------------------- #
# Expanded correlation (Stage B2)
# --------------------------------------------------------------------------- #

def test_correlation_reports_expanded_context(client, db, fake_store):
    from tests.unit.test_field_intelligence import _complete, _process

    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = client.get(f"/v1/field-intelligence/observations/{obs_id}", headers=headers).json()["observation"]
    correlation = obs["correlation"]
    assert correlation["schema_version"] == "field-observation-correlation/1.2.0"
    for key in ("telemetry", "satellite_evidence_ids", "recent_decisions", "missing_evidence",
                "verification_required", "recently_completed_tasks", "time_window"):
        assert key in correlation, key
    assert correlation["telemetry"]["weather_et"]["available"] is False
    assert correlation["telemetry"]["weather_et"]["freshness"] == "unavailable"


@pytest.fixture
def fake_store(monkeypatch):
    from app.services import field_intelligence as svc
    from app.services.object_storage import S3ObjectStore
    from tests.unit.test_field_intelligence import FakeStoreClient

    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix="agroai", client=client)
    monkeypatch.setattr(svc, "get_object_store", lambda **_: store)
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    return store


# --------------------------------------------------------------------------- #
# Commercial packaging (Stage B8)
# --------------------------------------------------------------------------- #

def test_free_plan_voice_note_monthly_quota(client, db, monkeypatch):
    from app.models.saas import Organization

    org, _, headers = _auth(db)
    org.plan = "free"
    db.commit()
    # Tighten the cap for the test via override semantics (plan default is 25).
    from app.models.saas import EntitlementOverride as _EO
    db.add(_EO(organization_id=org.id, feature_key="quota.field_intelligence.voice_notes.monthly",
               value_json={"value": 2}))
    db.commit()
    for index in range(2):
        response = _initiate(client, headers, capture_source="voice", note_text=None,
                             client_capture_id=f"vn{index}", idempotency_key=f"vn{index}")
        assert response.status_code == 200, response.text
    blocked = _initiate(client, headers, capture_source="voice", note_text=None,
                        client_capture_id="vn9", idempotency_key="vn9")
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "voice_note_quota_exceeded"
    # Typed capture is unaffected by the voice cap.
    typed = _initiate(client, headers, client_capture_id="tn1", idempotency_key="tn1")
    assert typed.status_code == 200
    # Replaying an existing voice capture still succeeds at the cap.
    replay = _initiate(client, headers, capture_source="voice", note_text=None,
                       client_capture_id="vn0", idempotency_key="vn0")
    assert replay.status_code == 200


def test_free_plan_model_extraction_locked(db, monkeypatch):
    from app.models.saas import Organization
    from app.services.commercial_control import resolve_effective_entitlements

    org, _, _headers = _auth(db)
    org.plan = "free"
    db.commit()
    effective = resolve_effective_entitlements(db, org)
    assert effective.state("field_intelligence.model_extraction") == "locked"
    assert effective.value("quota.field_intelligence.voice_notes.monthly") == 25
    org.plan = "professional"
    db.commit()
    effective = resolve_effective_entitlements(db, org)
    assert effective.enabled("field_intelligence.model_extraction")
    assert effective.value("quota.field_intelligence.voice_notes.monthly") is None


def test_pipeline_honors_model_extraction_entitlement(client, db, fake_store, monkeypatch):
    """A Free-plan tenant gets deterministic extraction with a truthful
    fallback label even when the model router is configured."""
    from tests.unit.test_field_intelligence import _complete, _process

    org, _, headers = _auth(db)
    org.plan = "free"
    db.commit()
    _install_fake_router(monkeypatch, {"event_type": "observation", "severity": "info",
                                       "summary": "model output", "confidence": 0.9})
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = client.get(f"/v1/field-intelligence/observations/{obs_id}", headers=headers).json()["observation"]
    structured = obs["structured"]
    assert structured["method"] == "deterministic-v1"
    assert structured["fallback_reason"] == "model_extraction_not_entitled"
