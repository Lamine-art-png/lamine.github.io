from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.claim_provenance import build_claim_provenance
from app.services.evidence_freshness import evaluate_evidence_freshness


def _context(items):
    return SimpleNamespace(evidence=items, citations=[], missing_data=[])


def test_numeric_claim_links_to_one_record():
    now = datetime.now(timezone.utc)
    context = _context([{
        "id": "ev-1",
        "type": "controller_event",
        "title": "North block record",
        "summary": "Apply 120 m3 to North block for 45 minutes",
        "occurred_at": now.isoformat(),
        "value_json": {"volume_m3": 120, "duration_min": 45},
    }])
    result = build_claim_provenance(task="irrigation_recommendation", answer="Apply 120 m3 to North block for 45 minutes.", context=context)
    assert result["claims"][0]["status"] == "supported"
    assert result["claims"][0]["evidence_links"][0]["source_id"] == "ev-1"


def test_unmatched_numeric_claim_is_counted():
    now = datetime.now(timezone.utc)
    context = _context([{"id": "ev-1", "type": "controller_event", "summary": "Apply 120 m3", "occurred_at": now.isoformat()}])
    result = build_claim_provenance(task="irrigation_recommendation", answer="Apply 250 m3 now.", context=context)
    assert result["unsupported_consequential_count"] == 1


def test_old_telemetry_is_stale():
    old = datetime.now(timezone.utc) - timedelta(days=3)
    result = evaluate_evidence_freshness(task="irrigation_recommendation", evidence=[{"id": "t1", "type": "telemetry", "timestamp": old.isoformat()}])
    assert result["blocking_count"] == 1
    assert result["records"][0]["status"] == "stale"


def test_current_telemetry_is_fresh():
    now = datetime.now(timezone.utc)
    result = evaluate_evidence_freshness(task="irrigation_recommendation", evidence=[{"id": "t1", "type": "telemetry", "timestamp": now.isoformat()}])
    assert result["blocking_count"] == 0
    assert result["records"][0]["status"] == "fresh"
