"""AGRO-AI Intelligence evaluation runner.

Usage::

    python -m evals.intelligence.run            # offline (CI): scripted model
    python -m evals.intelligence.run --live     # real AGRO-AI runtime (needs AI env)
    python -m evals.intelligence.run --live --repeat 3 --out report.json

Offline mode drives the real platform pipeline (contract validation,
reference resolution, tools, DATA block construction, structured-output
validation and citation verification) with scripted model replies. It proves
the platform's guarantees, not model quality.

Live mode runs the same scenarios against the configured AGRO-AI runtime and
scores each run with the same checks. It reports per-check pass/fail, latency
and run-to-run agreement of deterministic parts; it deliberately computes no
"accuracy percentage", because a handful of scenarios cannot support one.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class ScenarioResult:
    id: str
    domain: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    latency_ms: int = 0
    structured_status: str | None = None
    tool_outputs: dict[str, Any] = field(default_factory=dict)


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-3, abs_tol=1e-6)
    return a == b


def _numbers(value: Any) -> set[float]:
    return {round(float(item), 4) for item in _NUMBER.findall(json.dumps(value, default=str))}


def _grounded_numbers(structured: Any, sources: list[Any]) -> list[float]:
    """Numbers in the structured result that appear nowhere in inputs or tool outputs.

    A heuristic: derived arithmetic the model performs itself is flagged too,
    which is intended — AGRO-AI should compute through tools, not freehand.
    """
    known: set[float] = set()
    for source in sources:
        known |= _numbers(source)
    unknown = []
    for number in _numbers(structured):
        if number in {0.0, 1.0} or any(math.isclose(number, item, rel_tol=1e-2) for item in known):
            continue
        unknown.append(number)
    return sorted(unknown)


async def run_scenario(scenario: dict[str, Any], *, live: bool) -> ScenarioResult:
    from app.api.v1 import commercial_intelligence as legacy
    from app.api.v1.commercial_intelligence_input_guard import reject_credentials
    from app.intelligence_platform import runtime
    from app.platform_api.principal import PlatformPrincipal
    from app.schemas.ai import EvidenceContext

    expect = scenario.get("expect") or {}
    result = ScenarioResult(id=scenario["id"], domain=scenario["domain"], passed=False)
    principal = PlatformPrincipal(
        authentication_type="eval", organization_id="eval-org", api_project_id="eval-project",
        scopes=frozenset({"intelligence:run"}), environment="live", request_id=f"eval-{scenario['id']}",
    )
    started = time.monotonic()
    try:
        payload = legacy.IntelligenceRequest(**scenario["request"])
        reject_credentials(payload)
        resolved = runtime.resolve(None, principal, payload)  # scenarios reference no stored resources
    except (HTTPException, ValidationError) as exc:
        status = exc.status_code if isinstance(exc, HTTPException) else 422
        result.checks["rejected_as_expected"] = expect.get("rejected_status") == status
        result.passed = all(result.checks.values())
        result.notes.append(f"rejected with {status}")
        return result
    if "rejected_status" in expect:
        result.checks["rejected_as_expected"] = False
        return result

    context = EvidenceContext(organization_id="eval-org")
    prepared = await runtime.prepare(None, principal, payload, resolved, context)

    scripted = scenario.get("scripted") or {}
    if live:
        instruction = f"AGRO-AI commercial intelligence task: {payload.task}.\nCustomer question: {payload.question}\n" + runtime.instruction_suffix(prepared, resolved)
        body, model_result = await legacy._run_ai(task=str(legacy.TASK_CATALOG[payload.task]["internal_task"]), user_instruction=instruction, context=context)
        if model_result.status != "ok":
            result.notes.append("runtime degraded or unavailable")
    else:
        body = {"answer": scripted.get("answer", ""), "summary": scripted.get("answer", "")}

    structured_output = None
    if resolved.schema is not None:
        if live:
            outcome = await runtime.structure(
                question=payload.question, schema_name=resolved.schema[0], schema=resolved.schema[1], analysis=body,
                data_block=prepared.data_block, known_ids=prepared.known_ids, language=payload.language,
            )
        else:
            replies = [json.dumps({"agroai_structured_output": scripted.get("structured")})]

            async def scripted_json(_messages):
                return (replies.pop(0), "scripted") if replies else ("", None)

            original = runtime.generate_json
            runtime.generate_json = scripted_json
            try:
                outcome = await runtime.structure(
                    question=payload.question, schema_name=resolved.schema[0], schema=resolved.schema[1], analysis=body,
                    data_block=prepared.data_block, known_ids=prepared.known_ids, language=payload.language,
                )
            finally:
                runtime.generate_json = original
        result.structured_status = outcome.status
        structured_output = outcome.output
        if "structured_valid" in expect:
            result.checks["schema_compliance"] = (outcome.status == "valid") == bool(expect["structured_valid"])
        result.checks["no_unverifiable_citations_returned"] = not outcome.removed_citations or outcome.output is not None
        if outcome.removed_citations:
            result.notes.append(f"removed unverifiable citations: {outcome.removed_citations}")

    result.latency_ms = int((time.monotonic() - started) * 1000)
    tools_by_name = {item["name"]: item for item in prepared.tool_results}
    result.tool_outputs = {name: item.get("output") for name, item in tools_by_name.items()}
    for name, status in (expect.get("tool_status") or {}).items():
        result.checks[f"tool_status:{name}"] = (tools_by_name.get(name) or {}).get("status") == status
    for name, values in (expect.get("tool_output") or {}).items():
        output = (tools_by_name.get(name) or {}).get("output") or {}
        result.checks[f"tool_output:{name}"] = all(_close(output.get(key), value) for key, value in values.items())

    answer_text = json.dumps(body, default=str, ensure_ascii=False) + json.dumps(structured_output, default=str, ensure_ascii=False)
    for pattern in expect.get("forbid_patterns") or []:
        result.checks[f"forbid:{pattern[:40]}"] = re.search(pattern, answer_text) is None
    if expect.get("must_cite_any"):
        cited = set(re.findall(r"[A-Za-z0-9_.:-]+", answer_text))
        result.checks["cites_supplied_evidence"] = bool(cited & set(expect["must_cite_any"]))
    if expect.get("data_block_intact"):
        block = prepared.data_block
        result.checks["data_block_intact"] = block.count("<<<AGROAI_DATA") == 1 and block.count("AGROAI_DATA>>>") == 1
    if expect.get("numbers_grounded") and structured_output is not None:
        ungrounded = _grounded_numbers(structured_output, [scenario["request"], result.tool_outputs])
        result.checks["numbers_grounded"] = not ungrounded
        if ungrounded:
            result.notes.append(f"numbers not traceable to inputs or tools: {ungrounded[:10]}")
    result.passed = bool(result.checks) and all(result.checks.values())
    return result


async def run_all(*, live: bool, repeat: int = 1, only: str | None = None) -> dict[str, Any]:
    scenarios = [item for item in load_scenarios() if not only or item["id"].startswith(only)]
    runs: list[list[ScenarioResult]] = []
    for _ in range(max(1, repeat)):
        runs.append([await run_scenario(item, live=live) for item in scenarios])
    report: dict[str, Any] = {"mode": "live" if live else "offline", "repeat": repeat, "scenarios": []}
    for index, scenario in enumerate(scenarios):
        attempts = [run[index] for run in runs]
        deterministic = all(json.dumps(item.tool_outputs, sort_keys=True, default=str) == json.dumps(attempts[0].tool_outputs, sort_keys=True, default=str) for item in attempts)
        report["scenarios"].append(
            {
                "id": scenario["id"],
                "domain": scenario["domain"],
                "passed_runs": sum(1 for item in attempts if item.passed),
                "runs": len(attempts),
                "deterministic_components_reproducible": deterministic,
                "checks": attempts[-1].checks,
                "notes": sorted({note for item in attempts for note in item.notes}),
                "latency_ms": [item.latency_ms for item in attempts],
                "structured_status": [item.structured_status for item in attempts],
            }
        )
    report["all_passed"] = all(item["passed_runs"] == item["runs"] and item["deterministic_components_reproducible"] for item in report["scenarios"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--only", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    report = asyncio.run(run_all(live=args.live, repeat=args.repeat, only=args.only))
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
