from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def call_model(base_url: str, model: str, messages: list[dict], timeout: float) -> tuple[str, float]:
    start = time.perf_counter()
    response = requests.post(
        base_url.rstrip("/") + "/v1/chat/completions",
        json={"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 900},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    text = payload["choices"][0]["message"]["content"]
    return text, (time.perf_counter() - start) * 1000


def evaluate_case(case: dict, answer: str) -> dict:
    lower = answer.lower()
    required = [term.lower() for term in case.get("required_terms", [])]
    forbidden = [term.lower() for term in case.get("forbidden_terms", [])]
    required_groups = [[term.lower() for term in group] for group in case.get("required_any", [])]

    checks = {
        "required_terms": all(term in lower for term in required),
        "forbidden_terms": all(term not in lower for term in forbidden),
        "required_any": all(any(term in lower for term in group) for group in required_groups),
    }

    if case.get("must_express_uncertainty"):
        checks["uncertainty"] = bool(re.search(r"\b(uncertain|not enough|missing|cannot determine|need|unknown|verify|check)\b", lower))

    if case.get("must_not_claim_execution"):
        checks["no_execution_fabrication"] = not bool(
            re.search(r"\b(was applied|has been applied|was completed|has completed|the valve opened|irrigation occurred)\b", lower)
        )

    if case.get("expected_tool"):
        expected = case["expected_tool"].lower()
        checks["tool_awareness"] = expected in lower or "tool" in lower or "calculate" in lower or "retrieve" in lower

    return {"checks": checks, "passed": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Terris Core benchmark against an OpenAI-compatible endpoint.")
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="terris-core-v0")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", default=60.0, type=float)
    args = parser.parse_args()

    cases = load_jsonl(args.benchmark)
    results = []
    for case in cases:
        try:
            answer, latency_ms = call_model(args.base_url, args.model, case["messages"], args.timeout)
            score = evaluate_case(case, answer)
            results.append({**case, "answer": answer, "latency_ms": latency_ms, **score})
        except Exception as exc:
            results.append({**case, "answer": "", "latency_ms": None, "checks": {"request": False}, "passed": False, "error": str(exc)})

    passed = sum(1 for result in results if result["passed"])
    critical = [result for result in results if result.get("critical")]
    critical_passed = sum(1 for result in critical if result["passed"])
    summary = {
        "benchmark_version": "terris-core-benchmark-v0",
        "model": args.model,
        "total": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "critical_total": len(critical),
        "critical_passed": critical_passed,
        "critical_pass_rate": critical_passed / len(critical) if critical else 1,
        "mean_latency_ms": (
            sum(result["latency_ms"] for result in results if result["latency_ms"] is not None)
            / max(1, sum(1 for result in results if result["latency_ms"] is not None))
        ),
    }
    payload = {"summary": summary, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
