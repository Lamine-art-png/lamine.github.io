import pytest

from app.services.intelligence_counterfactuals import (
    CounterfactualInput,
    CounterfactualInputError,
    CounterfactualScenario,
    compare_counterfactuals,
)


def _baseline():
    return {
        "opening_storage_mm": CounterfactualInput(value=40.0, information_class="OBSERVED", evidence_ids=["ev-storage"]),
        "effective_rainfall_mm": CounterfactualInput(value=2.0, information_class="OBSERVED", evidence_ids=["ev-rain"]),
        "irrigation_mm": CounterfactualInput(value=0.0, information_class="OBSERVED", evidence_ids=["ev-irrigation"]),
        "capillary_rise_mm": CounterfactualInput(value=0.0, information_class="DERIVED", evidence_ids=["ev-soil"]),
        "crop_et_mm": CounterfactualInput(value=5.0, information_class="DERIVED", evidence_ids=["ev-eto", "ev-kc"]),
        "runoff_mm": CounterfactualInput(value=0.0, information_class="OBSERVED", evidence_ids=["ev-runoff"]),
        "deep_percolation_mm": CounterfactualInput(value=0.0, information_class="OBSERVED", evidence_ids=["ev-drainage"]),
    }


def test_counterfactual_recalculates_registered_science_and_labels_modeled_inputs():
    comparison = compare_counterfactuals(
        tool_id="water.balance.identity.v1",
        baseline_inputs=_baseline(),
        scenarios=[
            CounterfactualScenario(
                scenario_id="wait-one-period",
                kind="WAIT",
                label="Wait through another crop-water-demand period",
                overrides={
                    "crop_et_mm": CounterfactualInput(
                        value=9.0,
                        information_class="MODELED",
                        evidence_ids=["forecast-et"],
                        source_note="Explicit scenario input, not observed state.",
                    )
                },
            )
        ],
    )
    assert comparison.baseline.status == "computed"
    assert comparison.baseline.result["closing_storage_mm"] == 37.0
    scenario = comparison.scenarios[0]
    assert scenario.status == "computed"
    assert scenario.result["closing_storage_mm"] == 33.0
    assert scenario.modeled_inputs == ["crop_et_mm"]
    assert comparison.side_effect_free is True


def test_baseline_cannot_be_modeled_because_it_represents_current_state():
    baseline = _baseline()
    baseline["crop_et_mm"] = CounterfactualInput(value=5.0, information_class="MODELED")
    with pytest.raises(CounterfactualInputError, match="Baseline inputs must be observed"):
        compare_counterfactuals(tool_id="water.balance.identity.v1", baseline_inputs=baseline, scenarios=[])


def test_missing_baseline_state_fails_closed_instead_of_inventing_input():
    baseline = _baseline()
    baseline.pop("effective_rainfall_mm")
    with pytest.raises(CounterfactualInputError, match="effective_rainfall_mm"):
        compare_counterfactuals(tool_id="water.balance.identity.v1", baseline_inputs=baseline, scenarios=[])


def test_evidence_collection_and_inspection_are_explicit_non_calculation_branches():
    comparison = compare_counterfactuals(
        tool_id="water.balance.identity.v1",
        baseline_inputs=_baseline(),
        scenarios=[
            CounterfactualScenario(scenario_id="collect", kind="COLLECT_EVIDENCE", label="Collect another root-zone measurement"),
            CounterfactualScenario(scenario_id="inspect", kind="INSPECT", label="Inspect the flow meter"),
        ],
    )
    assert [row.status for row in comparison.scenarios] == ["evidence_only", "evidence_only"]
    assert all(row.side_effect_free for row in comparison.scenarios)


def test_evidence_only_branch_cannot_smuggle_operating_override():
    with pytest.raises(CounterfactualInputError, match="cannot smuggle"):
        compare_counterfactuals(
            tool_id="water.balance.identity.v1",
            baseline_inputs=_baseline(),
            scenarios=[
                CounterfactualScenario(
                    scenario_id="bad",
                    kind="INSPECT",
                    label="Inspection",
                    overrides={"irrigation_mm": CounterfactualInput(value=10.0, information_class="MODELED")},
                )
            ],
        )


def test_unknown_tool_input_cannot_enter_scenario():
    with pytest.raises(CounterfactualInputError, match="not declared"):
        compare_counterfactuals(
            tool_id="irrigation.gross_requirement.v1",
            baseline_inputs={
                "net_requirement_mm": CounterfactualInput(value=10.0, information_class="DERIVED", evidence_ids=["science-net"]),
                "efficiency": CounterfactualInput(value=0.8, information_class="OBSERVED", evidence_ids=["calibration"]),
            },
            scenarios=[
                CounterfactualScenario(
                    scenario_id="unknown",
                    kind="ACT_NOW",
                    label="Explicit gross requirement scenario",
                    overrides={"magic_factor": CounterfactualInput(value=2.0, information_class="MODELED")},
                )
            ],
        )
