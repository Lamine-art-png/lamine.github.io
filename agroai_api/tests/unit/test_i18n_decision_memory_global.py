from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api.v1 import i18n
from app.services.language_registry import enabled_ui_locales


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DECISION_MEMORY_SOURCE = _REPO_ROOT / "shared" / "ui-decision-memory.en.json"


def _source() -> dict[str, str]:
    payload = json.loads(_DECISION_MEMORY_SOURCE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict) and payload
    return payload


def test_decision_memory_source_is_part_of_authoritative_translation_catalog():
    i18n.canonical_source_catalog.cache_clear()
    source = _source()
    canonical = i18n.canonical_source_catalog()
    assert set(source).issubset(canonical)
    assert all(canonical[key] == value for key, value in source.items())
    assert i18n.requested_source_catalog(source) == source


def test_decision_memory_source_drift_fails_closed():
    i18n.canonical_source_catalog.cache_clear()
    source = _source()
    first_key = next(iter(source))
    drifted = {**source, first_key: source[first_key] + " changed"}
    with pytest.raises(ValueError, match="ui_source_catalog_mismatch"):
        i18n.requested_source_catalog(drifted)


def test_every_enabled_portal_locale_is_accepted_by_backend_registry():
    locales = enabled_ui_locales()
    assert len(locales) >= 50
    for locale in locales:
        assert i18n._canonical_enabled_locale(locale) == locale


def test_decision_memory_covers_full_governed_operating_vocabulary():
    source = _source()
    required = {
        "decisionMemory.approve",
        "decisionMemory.reject",
        "decisionMemory.startExecution",
        "decisionMemory.executionEvidence",
        "decisionMemory.recordExecution",
        "decisionMemory.startVerification",
        "decisionMemory.verificationEvidence",
        "decisionMemory.verify",
        "decisionMemory.state.awaiting_approval",
        "decisionMemory.state.execution_pending",
        "decisionMemory.state.verification_pending",
        "decisionMemory.state.verified",
        "decisionMemory.domain.water",
        "decisionMemory.domain.crop_health",
        "decisionMemory.domain.equipment",
        "decisionMemory.domain.assurance",
        "decisionMemory.domain.reporting",
        "decisionMemory.domain.operations",
        "decisionMemory.outcome.effective",
        "decisionMemory.outcome.partially_effective",
        "decisionMemory.outcome.ineffective",
        "decisionMemory.outcome.matched",
        "decisionMemory.outcome.partially_matched",
        "decisionMemory.outcome.deviated",
        "decisionMemory.outcome.failed",
        "decisionMemory.outcome.agronomically_ineffective",
        "decisionMemory.outcome.inconclusive",
        "decisionMemory.outcome.no_change",
        "decisionMemory.change.first_decision",
        "decisionMemory.change.evidence_changed",
        "decisionMemory.change.science_changed",
        "decisionMemory.change.conflicts_changed",
        "decisionMemory.change.unknowns_changed",
        "decisionMemory.change.confidence_changed",
        "decisionMemory.change.field_state_changed",
        "decisionMemory.change.recommendation_changed",
        "decisionMemory.change.no_material_change",
    }
    assert required.issubset(source)
