"""Authenticated live-analysis smoke test against an ISOLATED STAGING API.

Usage::

    export AGROAI_SMOKE_TOKEN=...   # staging user token; never printed or stored
    python -m evals.field_vision.staging_smoke \\
        --target https://<staging-api-host> --images ./consented --synthetic-adversarial \\
        --out smoke-report.json

What it checks, per image: HTTP status, ``status``/``analysis_state``,
severity, peak severity, confidence status, provider/model, server and
client latency, and the error class when unavailable.

What it refuses:

- known production hosts (the production API edge may route to the backend
  that also serves ``api-preview``, so that host is refused too);
- any image in ``--images`` that is not listed with a consent basis in that
  folder's ``manifest.json``;
- printing or storing the token, image bytes, or model free text (summaries,
  facts and recommendations are reduced to counts).

Synthetic adversarial images (black, noise, overexposed, test pattern) are
generated with ffmpeg and are not crops. The expectation is conservative
behaviour (no high or critical severity), not a correct diagnosis. Passing
this smoke test proves wiring and safety behaviour, never accuracy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

LIVE_PATH = "/v1/field-intelligence/live-analysis"
REFUSED_HOSTS = {
    "agroai-pilot.com",
    "www.agroai-pilot.com",
    "app.agroai-pilot.com",
    "api.agroai-pilot.com",
    "api-preview.agroai-pilot.com",
}
CONSENT_BASES = {"customer_written_consent", "internal_staff_capture", "licensed_dataset"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_FRAME_BYTES = 1_500_000
ADVERSARIAL_SOURCES = {
    "black_frame": "color=c=black:s=640x480",
    "uniform_noise": "nullsrc=s=640x480,geq=random(1)*255:128:128",
    "overexposed": "color=c=white:s=640x480",
    "test_pattern": "testsrc=s=640x480",
}


class SmokeRefused(ValueError):
    """Raised when a run would touch production or unconsented media."""


@dataclass
class SmokeCase:
    name: str
    content: bytes
    content_type: str
    crop: str | None = None
    adversarial: bool = False


@dataclass
class SmokeResult:
    name: str
    adversarial: bool
    http_status: int | None
    status: str | None
    analysis_state: str | None = None
    severity: str | None = None
    peak_severity: str | None = None
    confidence_status: str | None = None
    provider: str | None = None
    model: str | None = None
    provider_fallback: bool | None = None
    server_latency_ms: int | None = None
    client_latency_ms: int | None = None
    error: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    safety_flags: list[str] = field(default_factory=list)
    expectation_met: bool | None = None


def check_target(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise SmokeRefused("target must be an https staging URL")
    if host in REFUSED_HOSTS:
        raise SmokeRefused(f"refusing production host {host}; use the isolated staging API")
    return f"{parsed.scheme}://{parsed.netloc}"


def load_consented_images(folder: Path) -> list[SmokeCase]:
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise SmokeRefused(f"{manifest_path} is required: list each image with its consent basis")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {str(item.get("file")): item for item in manifest.get("images", []) if isinstance(item, dict)}
    cases: list[SmokeCase] = []
    for path in sorted(folder.iterdir()):
        content_type = IMAGE_TYPES.get(path.suffix.lower())
        if content_type is None:
            continue
        entry = entries.get(path.name)
        if not entry or entry.get("consent_basis") not in CONSENT_BASES:
            raise SmokeRefused(f"{path.name} has no consent basis in manifest.json")
        content = path.read_bytes()
        if len(content) > MAX_FRAME_BYTES:
            raise SmokeRefused(f"{path.name} exceeds the live frame limit of {MAX_FRAME_BYTES} bytes")
        cases.append(SmokeCase(name=path.name, content=content, content_type=content_type, crop=entry.get("crop")))
    return cases


def synthetic_adversarial_cases(ffmpeg: str = "ffmpeg") -> list[SmokeCase]:
    cases: list[SmokeCase] = []
    with tempfile.TemporaryDirectory(prefix="agroai-smoke-") as directory:
        for name, source in ADVERSARIAL_SOURCES.items():
            output = Path(directory) / f"{name}.jpg"
            completed = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", source,
                 "-frames:v", "1", "-q:v", "4", str(output)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
            )
            if completed.returncode == 0 and output.exists():
                cases.append(SmokeCase(name=name, content=output.read_bytes(), content_type="image/jpeg", crop="tomato", adversarial=True))
    return cases


def _summarize(case: SmokeCase, response: httpx.Response | None, client_latency_ms: int, error: str | None) -> SmokeResult:
    result = SmokeResult(name=case.name, adversarial=case.adversarial, http_status=None, status=None,
                         client_latency_ms=client_latency_ms, error=error)
    if response is None:
        return result
    result.http_status = response.status_code
    try:
        body = response.json()
    except ValueError:
        result.error = result.error or "non_json_response"
        return result
    if not isinstance(body, dict):
        return result
    analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else {}
    result.status = body.get("status")
    result.analysis_state = body.get("analysis_state") or analysis.get("analysis_state")
    result.severity = analysis.get("severity")
    result.peak_severity = analysis.get("peak_severity")
    summary = analysis.get("confidence_summary") or {}
    result.confidence_status = "reported" if analysis.get("confidence") is not None else (
        "missing_or_invalid" if summary.get("missing_or_invalid") else None
    )
    result.provider = body.get("provider")
    result.model = body.get("model")
    result.provider_fallback = body.get("provider_fallback")
    result.server_latency_ms = body.get("latency_ms")
    if response.status_code >= 400 or result.status != "ok":
        detail = body.get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        result.error = result.error or str(body.get("error") or code or f"http_{response.status_code}")[:120]
    result.counts = {
        key: len(analysis.get(key) or []) for key in ("visible_facts", "hypotheses", "possible_issues", "uncertainties")
    }
    result.safety_flags = list(analysis.get("safety_flags") or [])
    if case.adversarial and result.status == "ok":
        result.expectation_met = result.severity not in {"high", "critical"}
    return result


def run_smoke(client: httpx.Client, base_url: str, token: str, cases: Iterable[SmokeCase],
              *, workspace_id: str | None = None, language: str = "en") -> list[SmokeResult]:
    base = check_target(base_url)
    results: list[SmokeResult] = []
    for case in cases:
        data = {"language": language, "field_name": "Smoke test block", "note_text": "Automated staging smoke test."}
        if case.crop:
            data["crop"] = case.crop
        if workspace_id:
            data["workspace_id"] = workspace_id
        started = time.monotonic()
        response: httpx.Response | None = None
        error: str | None = None
        try:
            response = client.post(
                f"{base}{LIVE_PATH}",
                headers={"Authorization": f"Bearer {token}"},
                data=data,
                files={"file": (case.name if "." in case.name else f"{case.name}.jpg", case.content, case.content_type)},
            )
        except httpx.HTTPError as exc:
            error = exc.__class__.__name__
        results.append(_summarize(case, response, int((time.monotonic() - started) * 1000), error))
    return results


def report(results: list[SmokeResult], target: str) -> dict[str, Any]:
    ok = [result for result in results if result.status == "ok"]
    adversarial = [result for result in results if result.adversarial and result.status == "ok"]
    return {
        "target_host": urlparse(target).hostname,
        "cases": len(results),
        "ok": len(ok),
        "unavailable_or_failed": len(results) - len(ok),
        "degraded": sum(1 for result in ok if result.analysis_state == "degraded"),
        "fallback_model": sum(1 for result in ok if result.provider_fallback),
        "adversarial_conservative": f"{sum(1 for result in adversarial if result.expectation_met)}/{len(adversarial)}",
        "note": "Wiring and safety smoke only. This is not an accuracy measurement.",
        "results": [asdict(result) for result in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Field Vision staging smoke test")
    parser.add_argument("--target", required=True, help="isolated staging API base URL (https)")
    parser.add_argument("--images", type=Path, help="folder of consented images with manifest.json")
    parser.add_argument("--synthetic-adversarial", action="store_true", help="add generated non-crop images")
    parser.add_argument("--workspace-id")
    parser.add_argument("--language", default="en")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        target = check_target(args.target)
        token = os.environ.get("AGROAI_SMOKE_TOKEN", "").strip()
        if not token:
            raise SmokeRefused("set AGROAI_SMOKE_TOKEN to a staging user token")
        cases = load_consented_images(args.images) if args.images else []
        if args.synthetic_adversarial:
            cases.extend(synthetic_adversarial_cases())
        if not cases:
            raise SmokeRefused("no cases: pass --images and/or --synthetic-adversarial")
    except SmokeRefused as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2

    with httpx.Client(timeout=60.0) as client:
        results = run_smoke(client, target, token, cases, workspace_id=args.workspace_id, language=args.language)
    payload = report(results, target)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0 if payload["ok"] == payload["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
