"""Deterministic, provenance-bearing counterfactual comparisons.

This module does not choose an action. It re-runs one registered scientific tool
against explicitly supplied scenario inputs and preserves whether each input is
observed, derived, or modeled. Missing state fails closed.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.scientific_tool_registry import ScientificToolResult, get_scientific_tool_registry


InformationClass = Literal["OBSERVED", "DERIVED", "MODELED"]
ScenarioKind = Literal["CURRENT_STATE", "ACT_NOW", "WAIT", "ALTERNATE_TIMING", "COLLECT_EVIDENCE", "INSPECT"]


class CounterfactualInput(BaseModel):
    value: Any
    information_class: InformationClass
    evidence_ids: list[str] = Field(default_factory=list)
    source_note: str | None = None


class CounterfactualScenario(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    kind: ScenarioKind
    label: str = Field(min_length=1, max_length=240)
    overrides: dict[str, CounterfactualInput] = Field(default_factory=dict)
    rationale: str | None = Field(default=None, max_length=1000)


class CounterfactualResult(BaseModel):
    scenario_id: str
    kind: ScenarioKind
    label: str
    status: Literal["computed", "not_computable", "invalid_input", "evidence_only"]
    result: dict[str, Any] = Field(default_factory=dict)
    normalized_inputs: dict[str, Any] = Field(default_factory=dict)
    input_provenance: dict[str, CounterfactualInput] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    invalid_inputs: list[str] = Field(default_factory=list)
    modeled_inputs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    side_effect_free: bool = True


class CounterfactualComparison(BaseModel):
    tool_id: str
    tool_version: str
    baseline: CounterfactualResult
    scenarios: list[CounterfactualResult]
    interpretation_rule: str = (
        "Scenario results are deterministic calculations under explicit inputs. "
        "They are not forecasts, approvals, or execution instructions."
    )
    side_effect_free: bool = True


class CounterfactualInputError(ValueError):
    pass


def _raw_inputs(inputs: dict[str, CounterfactualInput]) -> dict[str, Any]:
    return {name: item.value for name, item in inputs.items()}


def _evidence_ids(inputs: dict[str, CounterfactualInput]) -> list[str]:
    return sorted({eid for item in inputs.values() for eid in item.evidence_ids if str(eid).strip()})


def _validate_baseline_provenance(inputs: dict[str, CounterfactualInput]) -> None:
    for name, item in inputs.items():
        evidence = [str(value).strip() for value in item.evidence_ids if str(value).strip()]
        note = str(item.source_note or "").strip()
        if item.information_class == "MODELED":
            raise CounterfactualInputError("Baseline inputs must be observed or deterministically derived, not modeled")
        if item.information_class == "OBSERVED" and not evidence:
            raise CounterfactualInputError(f"Observed baseline input {name} requires at least one evidence ID")
        if item.information_class == "DERIVED" and not evidence and not note:
            raise CounterfactualInputError(f"Derived baseline input {name} requires evidence IDs or a derivation source note")


def _to_result(
    scenario: CounterfactualScenario,
    inputs: dict[str, CounterfactualInput],
    science: ScientificToolResult | None,
) -> CounterfactualResult:
    modeled = sorted(name for name, item in inputs.items() if item.information_class == "MODELED")
    if science is None:
        return CounterfactualResult(
            scenario_id=scenario.scenario_id,
            kind=scenario.kind,
            label=scenario.label,
            status="evidence_only",
            input_provenance=inputs,
            evidence_ids=_evidence_ids(inputs),
            modeled_inputs=modeled,
            limitations=["This scenario requests evidence collection or inspection and does not produce a scientific calculation."],
        )
    status_map = {"COMPUTED": "computed", "NOT_COMPUTABLE": "not_computable", "INVALID_INPUT": "invalid_input"}
    return CounterfactualResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        label=scenario.label,
        status=status_map[science.status],
        result=science.output,
        normalized_inputs=science.normalized_inputs,
        input_provenance=inputs,
        evidence_ids=_evidence_ids(inputs),
        missing_requirements=science.missing_requirements,
        invalid_inputs=science.invalid_inputs,
        modeled_inputs=modeled,
        limitations=science.limitations,
    )


def compare_counterfactuals(
    *,
    tool_id: str,
    baseline_inputs: dict[str, CounterfactualInput],
    scenarios: list[CounterfactualScenario],
) -> CounterfactualComparison:
    """Re-run one scientific identity over explicit scenario changes.

    The baseline must be fully computable and provenance-bearing. Scenarios may
    be computation scenarios or evidence-only COLLECT_EVIDENCE/INSPECT branches.
    Computation scenarios inherit baseline inputs and replace only explicit
    overrides, preserving their modeled/evidenced classification.
    """
    registry = get_scientific_tool_registry()
    spec = registry.spec(tool_id)
    missing_baseline = [name for name in spec.required_inputs if name not in baseline_inputs]
    if missing_baseline:
        raise CounterfactualInputError(
            "Baseline is missing required inputs: " + ", ".join(missing_baseline)
        )
    _validate_baseline_provenance(baseline_inputs)

    baseline_science = registry.run(tool_id, _raw_inputs(baseline_inputs))
    if baseline_science.status != "COMPUTED":
        raise CounterfactualInputError(
            "Baseline scientific calculation is not computable: "
            + ", ".join(baseline_science.missing_requirements + baseline_science.invalid_inputs)
        )
    baseline_scenario = CounterfactualScenario(
        scenario_id="baseline",
        kind="CURRENT_STATE",
        label="Current evidenced state",
    )
    baseline_result = _to_result(baseline_scenario, baseline_inputs, baseline_science)

    seen = {"baseline"}
    outputs: list[CounterfactualResult] = []
    for scenario in scenarios[:12]:
        if scenario.scenario_id in seen:
            raise CounterfactualInputError(f"Duplicate scenario_id: {scenario.scenario_id}")
        seen.add(scenario.scenario_id)
        if scenario.kind in {"COLLECT_EVIDENCE", "INSPECT"}:
            if scenario.overrides:
                raise CounterfactualInputError(f"{scenario.kind} scenarios cannot smuggle modeled operating inputs")
            outputs.append(_to_result(scenario, baseline_inputs, None))
            continue
        if not scenario.overrides:
            raise CounterfactualInputError(f"{scenario.kind} scenario requires at least one explicit changed input")
        unknown_names = sorted(set(scenario.overrides) - set(spec.required_inputs) - set(spec.optional_inputs))
        if unknown_names:
            raise CounterfactualInputError(
                f"Scenario {scenario.scenario_id} changes inputs not declared by {tool_id}: " + ", ".join(unknown_names)
            )
        scenario_inputs = dict(baseline_inputs)
        scenario_inputs.update(scenario.overrides)
        science = registry.run(tool_id, _raw_inputs(scenario_inputs))
        outputs.append(_to_result(scenario, scenario_inputs, science))

    return CounterfactualComparison(
        tool_id=tool_id,
        tool_version=spec.version,
        baseline=baseline_result,
        scenarios=outputs,
    )
