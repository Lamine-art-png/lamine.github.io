from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_tracking_token_is_opaque_signed_and_tamper_evident():
    from app.outreach.tracking import InvalidTrackingToken, create_tracking_token, verify_tracking_token

    send_id = "37d8de95-fcb0-4edc-91a2-28d80353c5da"
    token = create_tracking_token(send_id=send_id, secret="test-secret")

    assert "person@example.com" not in token
    assert verify_tracking_token(token, "test-secret").send_id == send_id
    with pytest.raises(InvalidTrackingToken):
        verify_tracking_token(token + "tampered", "test-secret")
    with pytest.raises(InvalidTrackingToken):
        verify_tracking_token(token, "wrong-secret")


def test_live_html_instrumentation_tracks_allowlisted_ctas_and_open_signal(monkeypatch):
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_SECRET", "test-secret")
    monkeypatch.setenv("OUTREACH_PUBLIC_API_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("OUTREACH_ENTERPRISE_PORTAL_URL", "https://portal.example.test")
    monkeypatch.setenv("OUTREACH_CALENDLY_URL", "https://meeting.example.test/30min")
    monkeypatch.setenv("OUTREACH_LAUNCH_VIDEO_URL", "https://video.example.test/watch")

    router_module = importlib.import_module("app.outreach.router")
    from app.outreach.config import OutreachSettings
    from app.outreach.templates import RenderedEmail

    settings = OutreachSettings.from_env()
    monkeypatch.setattr(router_module, "settings", settings)
    rendered = RenderedEmail(
        subject="Test",
        html=(
            '<html><body><a href="https://portal.example.test">Portal</a>'
            '<a href="https://meeting.example.test/30min">Meeting</a>'
            '<a href="https://video.example.test/watch">Video</a></body></html>'
        ),
        text="plain text remains readable",
        unsubscribe_url="https://api.example.test/u",
        language="en",
        language_source="test",
        language_confidence="high",
        localization_ready=True,
    )

    tracked = router_module._instrument_rendered(
        rendered,
        send_id="37d8de95-fcb0-4edc-91a2-28d80353c5da",
    )

    assert "/v1/outreach/t/open?token=" in tracked.html
    assert "/v1/outreach/t/click/portal?token=" in tracked.html
    assert "/v1/outreach/t/click/meeting?token=" in tracked.html
    assert "/v1/outreach/t/click/video?token=" in tracked.html
    assert "https://portal.example.test\">Portal" not in tracked.html
    assert tracked.text == rendered.text


def test_production_mounts_engagement_observability_routes(monkeypatch):
    monkeypatch.setenv("OUTREACH_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_SECRET", "test-unsubscribe-secret")
    monkeypatch.setenv("OUTREACH_RESEND_API_KEY", "re_test_outreach")

    main = importlib.import_module("app.main")
    paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/v1/outreach/recent" in paths
    assert "/v1/outreach/engagement" in paths
    assert "/v1/outreach/events" in paths
    assert "/v1/outreach/t/open" in paths
    assert "/v1/outreach/t/click/{link_key}" in paths


def test_engagement_migration_is_chained_and_contains_required_indexes():
    root = Path(__file__).resolve().parents[2]
    migration = (root / "alembic" / "versions" / "018_outreach_engagement.py").read_text(encoding="utf-8")

    assert 'revision = "018_outreach_engagement"' in migration
    assert 'down_revision = "017_outreach_machine"' in migration
    assert '"outreach_events"' in migration
    assert '"send_id"' in migration
    assert '"event_type"' in migration
    assert '"link_key"' in migration
    assert "ix_outreach_events_send_created" in migration
    assert "ix_outreach_events_type_created" in migration
    assert "ip_address" not in migration


def test_trackable_send_count_ignores_historical_uninstrumented_sends(monkeypatch):
    store_module = importlib.import_module("app.outreach.store")

    class Result:
        def all(self):
            return [
                ('{"engagement_tracking": true}',),
                ('{"engagement_tracking": false}',),
                ('{}',),
                (None,),
                ('{"engagement_tracking": true}',),
            ]

    class Connection:
        def execute(self, *_args, **_kwargs):
            return Result()

    class Begin:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return False

    class Engine:
        def begin(self):
            return Begin()

    monkeypatch.setattr(store_module, "engine", Engine())
    assert store_module.OutreachStore().count_trackable_live_sends() == 2


def test_engagement_rates_use_trackable_send_denominator(monkeypatch):
    from app.outreach.store import OutreachStore

    outreach_store = OutreachStore()
    monkeypatch.setattr(outreach_store, "count_live_sends", lambda: 50)
    monkeypatch.setattr(outreach_store, "count_trackable_live_sends", lambda: 2)
    monkeypatch.setattr(
        outreach_store,
        "recent_events",
        lambda **_kwargs: [
            {
                "id": "event-1",
                "send_id": "send-1",
                "event_type": "first_party.opened",
                "link_key": None,
                "created_at": "2026-07-12T09:00:00+00:00",
                "prospect_id": "prospect-1",
                "email": "one@example.com",
                "account": "Account One",
                "subject": "Subject One",
                "resend_id": "resend-1",
            },
            {
                "id": "event-2",
                "send_id": "send-1",
                "event_type": "first_party.clicked.portal",
                "link_key": "portal",
                "created_at": "2026-07-12T09:01:00+00:00",
                "prospect_id": "prospect-1",
                "email": "one@example.com",
                "account": "Account One",
                "subject": "Subject One",
                "resend_id": "resend-1",
            },
        ],
    )

    summary = outreach_store.engagement_summary()

    assert summary["sent_total_all_time"] == 50
    assert summary["trackable_sent_total"] == 2
    assert summary["measurement_denominator"] == "trackable_sent_total"
    assert summary["open_signal_rate_percent"] == 50.0
    assert summary["click_through_rate_percent"] == 50.0
