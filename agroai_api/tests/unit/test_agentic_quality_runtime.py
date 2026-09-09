from __future__ import annotations

from app.services import artifact_intelligence
from app.services import gpt56_intelligence


def test_premium_intelligence_reuses_realtime_openai_key(monkeypatch):
    monkeypatch.delenv("AGROAI_INTELLIGENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGROAI_REALTIME_API_KEY", "shared-production-openai-key")
    monkeypatch.setenv("AGROAI_GPT56_ENABLED", "true")
    assert gpt56_intelligence._openai_quality_key() == "shared-production-openai-key"
    assert gpt56_intelligence.enabled() is True


def test_standard_and_report_work_use_sol():
    standard_model, standard_effort = gpt56_intelligence.select_model("reasoning", "Review this operation")
    report_model, report_effort = gpt56_intelligence.select_model("report", "Build a customer-ready deck")
    assert standard_model == "gpt-5.6-sol"
    assert standard_effort == "medium"
    assert report_model == "gpt-5.6-sol"
    assert report_effort == "xhigh"


def test_artifact_planner_has_safe_structured_fallback(monkeypatch):
    monkeypatch.delenv("AGROAI_ARTIFACT_API_KEY", raising=False)
    monkeypatch.delenv("AGROAI_INTELLIGENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGROAI_REALTIME_API_KEY", raising=False)
    plan = artifact_intelligence.create_artifact_plan(
        format_name="pptx",
        title="Operations Review",
        question="Build a concise operating deck.",
        answer="Irrigation pressure needs review. Evidence is incomplete. Verify the controller logs before changing the schedule.",
        evidence=[{"filename": "controller.csv", "rows_parsed": 12}],
        analysis_context={},
    )
    assert plan["fallback"] is True
    assert len(plan["slides"]) >= 4
    assert all("layout" in slide and "title" in slide for slide in plan["slides"])
