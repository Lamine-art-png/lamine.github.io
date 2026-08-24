"""Deterministic change explanations between immutable decision snapshots."""
from __future__ import annotations

from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.intelligence_memory import DecisionSnapshot


CHANGE_DRIVER_TEXT = {
    "first_decision": "No earlier immutable decision exists in the same field/domain scope.",
    "evidence_changed": "The evidence set changed.",
    "science_changed": "One or more deterministic science results changed.",
    "conflicts_changed": "The recorded evidence-conflict set changed.",
    "unknowns_changed": "The unresolved-unknown set changed.",
    "confidence_changed": "Grounding confidence changed.",
    "field_state_changed": "The decision references a different immutable Field State revision.",
    "recommendation_changed": "The governed recommendation text changed after post-validation.",
    "no_material_change": "No material persisted input or decision difference was detected.",
}


def _science_map(snapshot: DecisionSnapshot) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in snapshot.science_trace_json or []:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("rule_id") or "").strip()
        if rule_id:
            output[rule_id] = {
                "status": row.get("status"),
                "value": row.get("value"),
                "unit": row.get("unit"),
                "evidence_ids": sorted(str(value) for value in row.get("evidence_ids", []) if str(value).strip()),
            }
    return output


def _recommendations(snapshot: DecisionSnapshot) -> list[str]:
    decision = snapshot.decision_json or {}
    rows = decision.get("recommendations") if isinstance(decision, dict) else []
    if not isinstance(rows, list):
        return []
    values: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            action = str(row.get("action") or "").strip()
            if action:
                values.append(action)
    return values


def _packet_list(snapshot: DecisionSnapshot, key: str) -> list[Any]:
    graph = snapshot.evidence_graph_json or {}
    value = graph.get(key) if isinstance(graph, dict) else []
    return value if isinstance(value, list) else []


def _driver_text(codes: list[str]) -> list[str]:
    return [CHANGE_DRIVER_TEXT[code] for code in codes]


def previous_decision_snapshot(db: Session, current: DecisionSnapshot) -> DecisionSnapshot | None:
    query = db.query(DecisionSnapshot).filter(
        DecisionSnapshot.organization_id == current.organization_id,
        DecisionSnapshot.domain == current.domain,
        DecisionSnapshot.created_at < current.created_at,
    )
    if current.workspace_id is not None:
        query = query.filter(DecisionSnapshot.workspace_id == current.workspace_id)
    if current.field_id is not None:
        query = query.filter(DecisionSnapshot.field_id == current.field_id)
    if current.block_id is not None:
        query = query.filter(DecisionSnapshot.block_id == current.block_id)
    return query.order_by(desc(DecisionSnapshot.created_at)).first()


def compare_decision_snapshots(current: DecisionSnapshot, previous: DecisionSnapshot | None) -> dict[str, Any]:
    if previous is None:
        codes = ["first_decision"]
        return {
            "current_decision_id": current.id,
            "previous_decision_id": None,
            "first_decision_in_scope": True,
            "changed": False,
            "change_driver_codes": codes,
            "change_drivers": _driver_text(codes),
            "evidence": {"added": sorted(current.evidence_ids_json or []), "removed": []},
            "science": {"changed": []},
            "recommendations": {"changed": False, "previous": [], "current": _recommendations(current)},
            "confidence": {"previous": None, "current": current.grounding_confidence, "delta": None},
            "field_state_revision": {"previous": None, "current": current.field_state_revision_id, "changed": False},
        }

    current_evidence = set(str(value) for value in current.evidence_ids_json or [])
    previous_evidence = set(str(value) for value in previous.evidence_ids_json or [])
    added = sorted(current_evidence - previous_evidence)
    removed = sorted(previous_evidence - current_evidence)

    current_science = _science_map(current)
    previous_science = _science_map(previous)
    science_changes: list[dict[str, Any]] = []
    for rule_id in sorted(set(current_science) | set(previous_science)):
        before = previous_science.get(rule_id)
        after = current_science.get(rule_id)
        if before != after:
            science_changes.append({"rule_id": rule_id, "previous": before, "current": after})

    current_recommendations = _recommendations(current)
    previous_recommendations = _recommendations(previous)
    recommendations_changed = current_recommendations != previous_recommendations
    confidence_delta = round(float(current.grounding_confidence) - float(previous.grounding_confidence), 4)
    current_conflicts = _packet_list(current, "conflicts")
    previous_conflicts = _packet_list(previous, "conflicts")
    current_unknowns = _packet_list(current, "unknowns")
    previous_unknowns = _packet_list(previous, "unknowns")
    state_changed = current.field_state_revision_id != previous.field_state_revision_id

    codes: list[str] = []
    if added or removed:
        codes.append("evidence_changed")
    if science_changes:
        codes.append("science_changed")
    if current_conflicts != previous_conflicts:
        codes.append("conflicts_changed")
    if current_unknowns != previous_unknowns:
        codes.append("unknowns_changed")
    if confidence_delta:
        codes.append("confidence_changed")
    if state_changed:
        codes.append("field_state_changed")
    if recommendations_changed:
        codes.append("recommendation_changed")
    if not codes:
        codes.append("no_material_change")

    return {
        "current_decision_id": current.id,
        "previous_decision_id": previous.id,
        "first_decision_in_scope": False,
        "changed": bool(added or removed or science_changes or recommendations_changed or confidence_delta or state_changed or current_conflicts != previous_conflicts or current_unknowns != previous_unknowns),
        "change_driver_codes": codes,
        "change_drivers": _driver_text(codes),
        "evidence": {"added": added, "removed": removed},
        "science": {"changed": science_changes},
        "recommendations": {
            "changed": recommendations_changed,
            "previous": previous_recommendations,
            "current": current_recommendations,
        },
        "confidence": {
            "previous": previous.grounding_confidence,
            "current": current.grounding_confidence,
            "delta": confidence_delta,
        },
        "conflicts": {"previous": previous_conflicts, "current": current_conflicts, "changed": current_conflicts != previous_conflicts},
        "unknowns": {"previous": previous_unknowns, "current": current_unknowns, "changed": current_unknowns != previous_unknowns},
        "field_state_revision": {
            "previous": previous.field_state_revision_id,
            "current": current.field_state_revision_id,
            "changed": state_changed,
        },
    }