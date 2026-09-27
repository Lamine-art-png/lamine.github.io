"""Internal fast-decision layer for AGRO-AI.

This module is deliberately vendor-hidden from customer responses. It evaluates a
small, redacted operating snapshot with a typed decision model and either:
- runs in shadow mode (observe only), or
- conservatively reorders equal-priority Command Center items in assist mode.

The deterministic AGRO-AI operating loop remains the safety source of truth.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("agroai.decision_model")

_DEFAULT_BASE_URL = "https://api.typesafe.ai"
_DEFAULT_MODEL = "jev-latest"
_ALLOWED_MODES = {"off", "shadow", "assist"}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|secret|token|password|credential|authorization)\s*[:=]\s*[^\s,;]+"
)
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_LONG_TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


@dataclass(frozen=True)
class DecisionModelConfig:
    enabled: bool
    mode: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    min_confidence: float

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key and self.mode in {"shadow", "assist"})


@dataclass(frozen=True)
class CommandCenterAssessment:
    focus_ref: str | None
    focus_confidence: float
    urgency: str | None
    urgency_confidence: float
    needs_human_review: float
    data_sufficient: float
    should_act_now: float
    model: str | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, low: float, high: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def decision_model_config() -> DecisionModelConfig:
    mode = (os.getenv("AGROAI_DECISION_MODEL_MODE") or "off").strip().lower()
    if mode not in _ALLOWED_MODES:
        mode = "off"
    return DecisionModelConfig(
        enabled=_env_bool("AGROAI_DECISION_MODEL_ENABLED", False),
        mode=mode,
        api_key=(os.getenv("TYPESAFE_API_KEY") or "").strip(),
        base_url=(os.getenv("AGROAI_DECISION_MODEL_BASE_URL") or _DEFAULT_BASE_URL).strip().rstrip("/"),
        model=(os.getenv("AGROAI_DECISION_MODEL_MODEL") or _DEFAULT_MODEL).strip(),
        timeout_seconds=_env_float(
            "AGROAI_DECISION_MODEL_TIMEOUT_SECONDS",
            2.0,
            low=0.25,
            high=10.0,
        ),
        min_confidence=_env_float(
            "AGROAI_DECISION_MODEL_MIN_CONFIDENCE",
            0.85,
            low=0.5,
            high=1.0,
        ),
    )


def shadow_enabled() -> bool:
    config = decision_model_config()
    return config.configured and config.mode == "shadow"


def assist_enabled() -> bool:
    config = decision_model_config()
    return config.configured and config.mode == "assist"


def _safe_text(value: Any, *, limit: int = 220) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _SECRET_PATTERN.sub("[redacted]", text)
    text = _BEARER_PATTERN.sub("Bearer [redacted]", text)
    text = _EMAIL_PATTERN.sub("[redacted-email]", text)
    text = _LONG_TOKEN_PATTERN.sub("[redacted-token]", text)
    text = " ".join(text.split())
    return text[:limit]


def _candidate_rows(command_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(list(command_state.get("field_queue") or [])[:8]):
        ref = f"item_{index + 1}"
        missing = list(row.get("missing_evidence") or [])
        rows.append(
            {
                "ref": ref,
                "priority": row.get("priority") if row.get("priority") in _PRIORITY_ORDER else "low",
                "status": _safe_text(row.get("status"), limit=40),
                "issue": _safe_text(row.get("issue")),
                "recommended_action": _safe_text(row.get("recommended_action")),
                "latest_signal": _safe_text(row.get("latest_signal")),
                "missing_evidence_count": len(missing),
                "has_next_operator_task": bool(row.get("next_operator_task")),
            }
        )
    return rows


def _redacted_command_state(command_state: dict[str, Any]) -> dict[str, Any]:
    candidates = _candidate_rows(command_state)
    tasks = list(command_state.get("operator_tasks") or [])
    open_tasks = [task for task in tasks if task.get("status") != "done"]
    task_priority_counts = {
        level: sum(1 for task in open_tasks if task.get("priority") == level)
        for level in ("high", "medium", "low")
    }
    return {
        "operating_status": _safe_text(command_state.get("operating_status"), limit=80),
        "current_priority_level": _safe_text(
            (command_state.get("today_priority") or {}).get("risk"),
            limit=20,
        ),
        "candidates": candidates,
        "open_task_count": len(open_tasks),
        "task_priority_counts": task_priority_counts,
        "missing_evidence_count": len(list(command_state.get("missing_evidence") or [])),
        "recent_signal_count": len(list(command_state.get("recent_signals") or [])),
    }


def _command_center_questions(candidate_count: int) -> dict[str, Any]:
    criteria = {
        f"item_{index + 1}": f"Candidate item_{index + 1} from the state."
        for index in range(candidate_count)
    }
    criteria["none"] = "No candidate requires priority attention now."
    return {
        "focus_item": {
            "type": "choice",
            "instructions": (
                "Which candidate should an agricultural operations team focus on first? "
                "Prefer concrete operational risk, time sensitivity, blocked work, and evidence gaps. "
                "Do not invent facts beyond the supplied state."
            ),
            "criteria": criteria,
        },
        "urgency": {
            "type": "choice",
            "instructions": "What is the overall operational urgency of the supplied state?",
            "criteria": {
                "critical": "Immediate attention is needed to avoid material operational harm or a safety issue.",
                "high": "Action or review should happen soon because a meaningful operating issue is open.",
                "normal": "Routine follow-through is appropriate; no urgent intervention is indicated.",
                "low": "Little or no action is needed now beyond ordinary monitoring.",
            },
        },
        "needs_human_review": {
            "type": "noul",
            "instructions": (
                "A human operator should review the situation before any material operating action is executed."
            ),
        },
        "data_sufficient": {
            "type": "noul",
            "instructions": (
                "The supplied evidence is sufficient to prioritize the next operational step without requesting more data first."
            ),
        },
        "should_act_now": {
            "type": "noul",
            "instructions": "The current state warrants an operational action now rather than passive monitoring.",
        },
    }


def _system_one_request(command_state: dict[str, Any], config: DecisionModelConfig) -> dict[str, Any] | None:
    redacted = _redacted_command_state(command_state)
    candidate_count = len(redacted["candidates"])
    if candidate_count == 0:
        return None
    return {
        "state": json.dumps(redacted, sort_keys=True, separators=(",", ":")),
        "model": config.model,
        "questions": _command_center_questions(candidate_count),
    }


def _bounded_probability(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _parse_assessment(payload: dict[str, Any]) -> CommandCenterAssessment | None:
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None

    focus = answers.get("focus_item") if isinstance(answers.get("focus_item"), dict) else {}
    urgency = answers.get("urgency") if isinstance(answers.get("urgency"), dict) else {}
    human = answers.get("needs_human_review") if isinstance(answers.get("needs_human_review"), dict) else {}
    sufficient = answers.get("data_sufficient") if isinstance(answers.get("data_sufficient"), dict) else {}
    act = answers.get("should_act_now") if isinstance(answers.get("should_act_now"), dict) else {}

    focus_ref = focus.get("choice")
    if focus_ref is not None:
        focus_ref = str(focus_ref)
    urgency_value = urgency.get("choice")
    if urgency_value is not None:
        urgency_value = str(urgency_value)

    return CommandCenterAssessment(
        focus_ref=focus_ref,
        focus_confidence=_bounded_probability(focus.get("confidence")),
        urgency=urgency_value,
        urgency_confidence=_bounded_probability(urgency.get("confidence")),
        needs_human_review=_bounded_probability(human.get("noul")),
        data_sufficient=_bounded_probability(sufficient.get("noul")),
        should_act_now=_bounded_probability(act.get("noul")),
        model=str(payload.get("model")) if payload.get("model") else None,
    )


def assess_command_center(command_state: dict[str, Any]) -> CommandCenterAssessment | None:
    config = decision_model_config()
    if not config.configured:
        return None
    request_payload = _system_one_request(command_state, config)
    if request_payload is None:
        return None
    try:
        response = httpx.post(
            f"{config.base_url}/v1/systemone",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agroai-internal-decision/1.0",
            },
            json=request_payload,
            timeout=config.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning(
            "decision_model_unavailable",
            extra={"mode": config.mode, "error_type": exc.__class__.__name__},
        )
        return None
    if not isinstance(body, dict):
        return None
    return _parse_assessment(body)


def _selected_index(focus_ref: str | None, queue_length: int) -> int | None:
    if not focus_ref or not focus_ref.startswith("item_"):
        return None
    try:
        index = int(focus_ref.split("_", 1)[1]) - 1
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= queue_length:
        return None
    return index


def apply_command_center_assessment(
    command_state: dict[str, Any],
    assessment: CommandCenterAssessment | None,
    *,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Apply only a conservative tie-break to existing deterministic priorities.

    The decision model cannot lower a deterministic priority, invent actions, or
    bypass a human-review requirement. It may only choose among items already in
    the highest deterministic priority tier.
    """
    if assessment is None:
        return command_state
    threshold = (
        decision_model_config().min_confidence
        if min_confidence is None
        else max(0.5, min(1.0, float(min_confidence)))
    )
    if assessment.focus_confidence < threshold:
        return command_state
    if assessment.focus_ref in {None, "none"}:
        return command_state

    queue = list(command_state.get("field_queue") or [])
    selected_index = _selected_index(assessment.focus_ref, len(queue))
    if selected_index is None or not queue:
        return command_state

    best_rank = min(_PRIORITY_ORDER.get(str(row.get("priority")), 9) for row in queue)
    selected = queue[selected_index]
    selected_rank = _PRIORITY_ORDER.get(str(selected.get("priority")), 9)
    if selected_rank != best_rank:
        return command_state

    updated = copy.deepcopy(command_state)
    updated_queue = list(updated.get("field_queue") or [])
    chosen = updated_queue.pop(selected_index)
    updated_queue.insert(0, chosen)
    updated["field_queue"] = updated_queue

    # Preserve an explicit high-priority operator task as the top priority.
    current_priority = updated.get("today_priority") or {}
    if str(current_priority.get("risk")) == "high" and any(
        task.get("priority") == "high" and task.get("status") != "done"
        for task in list(updated.get("operator_tasks") or [])
    ):
        return updated

    updated["today_priority"] = {
        "title": chosen.get("issue") or "Review field",
        "reason": chosen.get("recommended_action") or "Review field evidence.",
        "field": chosen.get("field_name"),
        "risk": chosen.get("priority") or "low",
        "recommended_action": chosen.get("next_operator_task")
        or chosen.get("recommended_action")
        or "Review field evidence.",
    }
    return updated


def command_center_with_decision_layer(command_state: dict[str, Any]) -> dict[str, Any]:
    """Assist-mode entry point. No vendor/model metadata is returned to customers."""
    if not assist_enabled():
        return command_state
    assessment = assess_command_center(command_state)
    return apply_command_center_assessment(command_state, assessment)


def shadow_command_center(command_state: dict[str, Any]) -> None:
    """Run a hidden comparison after the response; never mutates customer output."""
    if not shadow_enabled():
        return
    assessment = assess_command_center(command_state)
    if assessment is None:
        return
    logger.info(
        "decision_model_shadow_evaluation",
        extra={
            "focus_ref": assessment.focus_ref,
            "focus_confidence": round(assessment.focus_confidence, 4),
            "urgency": assessment.urgency,
            "urgency_confidence": round(assessment.urgency_confidence, 4),
            "needs_human_review": round(assessment.needs_human_review, 4),
            "data_sufficient": round(assessment.data_sufficient, 4),
            "should_act_now": round(assessment.should_act_now, 4),
        },
    )
