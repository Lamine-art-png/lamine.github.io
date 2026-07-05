import asyncio

from app.services.live_intelligence import LiveIntelligence
from app.services.operational_invariants import check_operational_invariants


ORIGINAL = """## Recommendation
- Apply 0.42 acre-ft over 18 acres with WiseConn.
- ETc is 6.3 mm/day for the block.
- Confidence: 0.71.
- Keep irrigation off before 18:00.
- Sources: [1] WiseConn; [2] John Deere.
- SGMA status remains uncertain and the evidence should be reviewed.
"""

SAFE_FRENCH = """## Recommandation
- Appliquez 0,42 acre-ft sur 18 acres avec WiseConn.
- L’ETc est de 6,3 mm/day pour le bloc.
- Confiance : 0,71.
- Gardez l’irrigation arrêtée avant 18:00.
- Sources : [1] WiseConn ; [2] John Deere.
- Le statut SGMA reste incertain et les données doivent être vérifiées.
"""


def test_decimal_comma_preserves_numeric_invariants():
    result = check_operational_invariants(ORIGINAL, SAFE_FRENCH)
    assert result.ok, result.violations


def test_changed_quantity_and_time_fail_closed():
    unsafe = SAFE_FRENCH.replace("0,42", "0,52").replace("18:00", "19:00")
    result = check_operational_invariants(ORIGINAL, unsafe)
    assert not result.ok
    assert "numeric_values_changed" in result.violations
    assert "times_changed" in result.violations


def test_changed_citation_and_protected_term_fail_closed():
    unsafe = SAFE_FRENCH.replace("[2] John Deere", "[3] Deere")
    result = check_operational_invariants(ORIGINAL, unsafe)
    assert not result.ok
    assert "citations_changed" in result.violations
    assert "protected_terms_changed" in result.violations


def test_markdown_structure_change_fails_closed():
    unsafe = SAFE_FRENCH.replace("## Recommandation", "Recommandation", 1)
    result = check_operational_invariants(ORIGINAL, unsafe)
    assert not result.ok
    assert "markdown_structure_changed" in result.violations


def test_live_repair_accepts_safe_translation(monkeypatch):
    async def safe_remote(*_args, **_kwargs):
        return SAFE_FRENCH, "model-a"

    engine = LiveIntelligence()
    monkeypatch.setattr(engine, "run_remote", safe_remote)
    repaired = asyncio.run(engine.repair(
        ("endpoint", "key", "provider"),
        "model-a",
        ORIGINAL,
        "fr",
        "French",
    ))
    assert repaired == SAFE_FRENCH


def test_live_repair_rejects_changed_quantity(monkeypatch):
    async def unsafe_remote(*_args, **_kwargs):
        return SAFE_FRENCH.replace("0,42", "0,52"), "model-a"

    engine = LiveIntelligence()
    monkeypatch.setattr(engine, "run_remote", unsafe_remote)
    repaired = asyncio.run(engine.repair(
        ("endpoint", "key", "provider"),
        "model-a",
        ORIGINAL,
        "fr",
        "French",
    ))
    assert repaired is None
