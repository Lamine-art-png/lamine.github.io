from __future__ import annotations

import json
import shutil

import httpx
import pytest

from evals.field_vision import staging_smoke as smoke

TOKEN = "staging-token-must-never-appear"
FREE_TEXT = "Severe blight confirmed in block 9"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.agroai-pilot.com",
        "https://API-PREVIEW.agroai-pilot.com/",
        "https://app.agroai-pilot.com",
        "https://agroai-pilot.com",
        "http://staging.example.test",
        "staging.example.test",
    ],
)
def test_production_and_insecure_targets_are_refused(url):
    with pytest.raises(smoke.SmokeRefused):
        smoke.check_target(url)


def test_staging_target_is_normalised():
    assert smoke.check_target("https://fi-staging.example.test/some/path") == "https://fi-staging.example.test"


def test_images_without_consent_are_refused(tmp_path):
    (tmp_path / "row.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    with pytest.raises(smoke.SmokeRefused, match="manifest.json"):
        smoke.load_consented_images(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"images": [{"file": "row.jpg", "consent_basis": "assumed"}]}))
    with pytest.raises(smoke.SmokeRefused, match="consent"):
        smoke.load_consented_images(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"images": [{"file": "row.jpg", "consent_basis": "internal_staff_capture", "crop": "almond"}]}))
    cases = smoke.load_consented_images(tmp_path)
    assert [(case.name, case.crop, case.content_type) for case in cases] == [("row.jpg", "almond", "image/jpeg")]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_synthetic_adversarial_images_are_real_jpegs():
    cases = smoke.synthetic_adversarial_cases()
    assert {case.name for case in cases} == set(smoke.ADVERSARIAL_SOURCES)
    assert all(case.adversarial and case.content.startswith(b"\xff\xd8\xff") for case in cases)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_smoke_reports_structure_without_secrets_or_free_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, json={
            "status": "ok", "analysis_state": "structured", "provider": "cloudflare_workers_ai",
            "model": "@cf/meta/llama-3.2-11b-vision-instruct", "provider_fallback": False, "latency_ms": 4200,
            "analysis": {
                "summary": FREE_TEXT, "severity": "low", "peak_severity": "low", "confidence": None,
                "confidence_summary": {"missing_or_invalid": 1}, "visible_facts": [{"label": FREE_TEXT}],
                "hypotheses": [], "possible_issues": [], "uncertainties": ["x"], "safety_flags": [],
            },
        })

    cases = [smoke.SmokeCase(name="black_frame", content=b"\xff\xd8\xff0", content_type="image/jpeg", adversarial=True)]
    with _client(handler) as client:
        results = smoke.run_smoke(client, "https://fi-staging.example.test", TOKEN, cases)
    assert seen == {"auth": f"Bearer {TOKEN}", "path": smoke.LIVE_PATH}
    payload = smoke.report(results, "https://fi-staging.example.test")
    text = json.dumps(payload)
    assert TOKEN not in text and FREE_TEXT not in text
    result = payload["results"][0]
    assert result["counts"]["visible_facts"] == 1
    assert result["confidence_status"] == "missing_or_invalid"
    assert result["expectation_met"] is True
    assert payload["adversarial_conservative"] == "1/1"


def test_run_smoke_flags_adversarial_escalation_and_unavailable():
    responses = iter([
        httpx.Response(200, json={"status": "ok", "analysis": {"severity": "critical"}}),
        httpx.Response(200, json={"status": "unavailable", "error": "vision_provider_not_configured"}),
        httpx.Response(429, json={"detail": {"code": "field_live_analysis_rate_limited"}}),
    ])
    cases = [smoke.SmokeCase(name=f"case{i}", content=b"\xff\xd8\xff0", content_type="image/jpeg", adversarial=True) for i in range(3)]
    with _client(lambda request: next(responses)) as client:
        results = smoke.run_smoke(client, "https://fi-staging.example.test", TOKEN, cases)
    assert results[0].expectation_met is False
    assert results[1].error == "vision_provider_not_configured"
    assert results[2].error == "field_live_analysis_rate_limited"
    assert smoke.report(results, "https://fi-staging.example.test")["unavailable_or_failed"] == 2


def test_run_smoke_refuses_production_even_when_called_directly():
    with _client(lambda request: httpx.Response(200, json={})) as client:
        with pytest.raises(smoke.SmokeRefused):
            smoke.run_smoke(client, "https://api.agroai-pilot.com", TOKEN, [])


def test_cli_requires_token(monkeypatch, capsys):
    monkeypatch.delenv("AGROAI_SMOKE_TOKEN", raising=False)
    assert smoke.main(["--target", "https://fi-staging.example.test", "--synthetic-adversarial"]) == 2
    assert "AGROAI_SMOKE_TOKEN" in capsys.readouterr().err
