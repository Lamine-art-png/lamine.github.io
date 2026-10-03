"""The offline evaluation suite runs in CI, and the evaluator itself is tested:
each negative control is a deliberately bad reply that must be caught."""
from __future__ import annotations

import asyncio
import copy

from evals.intelligence import run as evals


def _scenario(scenario_id: str) -> dict:
    return copy.deepcopy(next(item for item in evals.load_scenarios() if item["id"] == scenario_id))


def test_offline_suite_passes_and_is_reproducible():
    report = asyncio.run(evals.run_all(live=False, repeat=2))
    assert report["all_passed"], [item for item in report["scenarios"] if item["passed_runs"] != item["runs"]]
    domains = {item["domain"] for item in report["scenarios"]}
    assert {"irrigation", "crop_risk", "agronomic_diagnosis", "evidence_interpretation", "compliance", "farm_finance", "market", "safety"} <= domains


def test_evaluator_catches_physical_action_claims():
    scenario = _scenario("safety.prompt_injection_in_context")
    scenario["scripted"]["answer"] = "Done: valve 4 was opened as requested."
    result = asyncio.run(evals.run_scenario(scenario, live=False))
    assert not result.passed


def test_evaluator_catches_schema_violations():
    scenario = _scenario("crop_risk.frost_citrus")
    scenario["scripted"]["structured"]["overall_risk"] = "apocalyptic"
    result = asyncio.run(evals.run_scenario(scenario, live=False))
    assert not result.passed and result.checks["schema_compliance"] is False


def test_evaluator_catches_ungrounded_numbers():
    scenario = _scenario("finance.margin_wheat")
    scenario["scripted"]["structured"]["scenarios"][0]["margin"] = 31337
    result = asyncio.run(evals.run_scenario(scenario, live=False))
    assert not result.passed and result.checks["numbers_grounded"] is False


def test_evaluator_catches_missing_citations():
    scenario = _scenario("diagnosis.leaf_symptoms_tomato")
    scenario["scripted"]["answer"] = "Probably blight."
    scenario["scripted"]["structured"]["likely_causes"][0]["evidence_ids"] = ["fabricated_id"]
    result = asyncio.run(evals.run_scenario(scenario, live=False))
    assert not result.passed and result.checks["cites_supplied_evidence"] is False
