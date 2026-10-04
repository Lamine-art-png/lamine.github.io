"""Structured output schemas and validation.

A structured result is returned as ``valid`` only after JSON Schema validation
(Draft 2020-12) against the requested schema. Citations inside the result are
checked against the evidence AGRO-AI actually supplied to the run; ids that do
not trace to real evidence are removed and reported, never passed through.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


MAX_SCHEMA_BYTES = 32_000
MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_NODES = 1_500
# Caller regexes would execute against model output inside AGRO-AI; remote or
# dynamic references could reach outside the request. Neither is needed for
# agricultural result shapes.
_FORBIDDEN_KEYWORDS = {"pattern", "patternProperties", "$dynamicRef", "$recursiveRef", "$dynamicAnchor", "$recursiveAnchor", "$anchor"}


class SchemaRejected(ValueError):
    pass


_CONFIDENCE = {"type": "string", "enum": ["low", "medium", "high"]}
_EVIDENCE_IDS = {"type": "array", "items": {"type": "string"}, "maxItems": 20}
_STRINGS = {"type": "array", "items": {"type": "string"}, "maxItems": 30}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "diagnosis": _obj(
        {
            "summary": {"type": "string"},
            "likely_causes": {
                "type": "array",
                "maxItems": 10,
                "items": _obj(
                    {
                        "name": {"type": "string"},
                        "likelihood": {"type": "string", "enum": ["low", "medium", "high"]},
                        "reasoning": {"type": "string"},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["name", "likelihood", "reasoning"],
                ),
            },
            "differential_checks": _STRINGS,
            "recommended_next_steps": _STRINGS,
            "confidence": _CONFIDENCE,
            "limitations": _STRINGS,
        },
        ["summary", "likely_causes", "recommended_next_steps", "confidence"],
    ),
    "recommendations": _obj(
        {
            "summary": {"type": "string"},
            "recommendations": {
                "type": "array",
                "maxItems": 20,
                "items": _obj(
                    {
                        "action": {"type": "string"},
                        "rationale": {"type": "string"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "timing": {"type": "string"},
                        "requires_human_approval": {"type": "boolean"},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["action", "rationale", "priority"],
                ),
            },
            "confidence": _CONFIDENCE,
            "limitations": _STRINGS,
        },
        ["recommendations", "confidence"],
    ),
    "risk_assessment": _obj(
        {
            "overall_risk": {"type": "string", "enum": ["unknown", "low", "medium", "high", "critical"]},
            "risks": {
                "type": "array",
                "maxItems": 20,
                "items": _obj(
                    {
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "likelihood": {"type": "string", "enum": ["unknown", "low", "medium", "high"]},
                        "impact": {"type": "string", "enum": ["unknown", "low", "medium", "high"]},
                        "drivers": _STRINGS,
                        "mitigations": _STRINGS,
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["name", "likelihood", "impact"],
                ),
            },
            "confidence": _CONFIDENCE,
            "limitations": _STRINGS,
        },
        ["overall_risk", "risks", "confidence"],
    ),
    "irrigation_schedule": _obj(
        {
            "events": {
                "type": "array",
                "maxItems": 60,
                "items": _obj(
                    {
                        "date": {"type": "string"},
                        "depth_mm": {"type": ["number", "null"], "minimum": 0},
                        "duration_minutes": {"type": ["number", "null"], "minimum": 0},
                        "rationale": {"type": "string"},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["date", "rationale"],
                ),
            },
            "assumptions": _STRINGS,
            "missing_data": _STRINGS,
            "confidence": _CONFIDENCE,
        },
        ["events", "missing_data", "confidence"],
    ),
    "financial_projection": _obj(
        {
            "currency": {"type": "string"},
            "scenarios": {
                "type": "array",
                "maxItems": 10,
                "items": _obj(
                    {
                        "name": {"type": "string"},
                        "revenue": {"type": ["number", "null"]},
                        "costs": {"type": ["number", "null"]},
                        "margin": {"type": ["number", "null"]},
                        "assumptions": _STRINGS,
                    },
                    ["name", "assumptions"],
                ),
            },
            "breakeven_price": {"type": ["number", "null"]},
            "breakeven_yield": {"type": ["number", "null"]},
            "sensitivities": _STRINGS,
            "confidence": _CONFIDENCE,
            "limitations": _STRINGS,
        },
        ["scenarios", "confidence", "limitations"],
    ),
    "compliance_findings": _obj(
        {
            "overall_status": {"type": "string", "enum": ["met", "not_met", "partially_met", "unclear"]},
            "findings": {
                "type": "array",
                "maxItems": 40,
                "items": _obj(
                    {
                        "requirement": {"type": "string"},
                        "status": {"type": "string", "enum": ["met", "not_met", "unclear"]},
                        "gap": {"type": "string"},
                        "remediation": {"type": "string"},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["requirement", "status"],
                ),
            },
            "limitations": _STRINGS,
        },
        ["overall_status", "findings", "limitations"],
    ),
    "task_list": _obj(
        {
            "tasks": {
                "type": "array",
                "maxItems": 50,
                "items": _obj(
                    {
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "due": {"type": ["string", "null"]},
                        "owner_role": {"type": ["string", "null"]},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["title", "priority"],
                ),
            },
            "confidence": _CONFIDENCE,
        },
        ["tasks", "confidence"],
    ),
    "evidence_summary": _obj(
        {
            "claims": {
                "type": "array",
                "maxItems": 40,
                "items": _obj(
                    {
                        "statement": {"type": "string"},
                        "support": {"type": "string", "enum": ["supported", "partially_supported", "unsupported"]},
                        "evidence_ids": _EVIDENCE_IDS,
                    },
                    ["statement", "support"],
                ),
            },
            "gaps": _STRINGS,
        },
        ["claims", "gaps"],
    ),
}

BUILTIN_DESCRIPTIONS = {
    "diagnosis": "Likely causes with reasoning, checks that discriminate between them, and next steps.",
    "recommendations": "Prioritised advisory actions with rationale; nothing is executed.",
    "risk_assessment": "Overall and per-risk likelihood/impact with drivers and mitigations.",
    "irrigation_schedule": "Dated irrigation events with depth/duration only where evidence supports a number.",
    "financial_projection": "Scenario revenue/cost/margin and breakeven from caller-supplied economics.",
    "compliance_findings": "Requirement-by-requirement status against supplied evidence (not legal advice).",
    "task_list": "Prioritised operational work items.",
    "evidence_summary": "Claims classified by how well supplied evidence supports them.",
}


def _depth_and_nodes(value: Any, depth: int = 0) -> tuple[int, int]:
    if depth > MAX_SCHEMA_DEPTH:
        raise SchemaRejected(f"response_format.schema nesting must be {MAX_SCHEMA_DEPTH} levels or fewer")
    if isinstance(value, dict):
        deepest, nodes = depth, 1
        for key, child in value.items():
            if key in _FORBIDDEN_KEYWORDS:
                raise SchemaRejected(f"response_format.schema keyword '{key}' is not supported")
            if key == "$ref" and not (isinstance(child, str) and child.startswith("#")):
                raise SchemaRejected("response_format.schema supports only local '#/...' references")
            child_depth, child_nodes = _depth_and_nodes(child, depth + 1)
            deepest, nodes = max(deepest, child_depth), nodes + child_nodes
        return deepest, nodes
    if isinstance(value, list):
        deepest, nodes = depth, 1
        for child in value:
            child_depth, child_nodes = _depth_and_nodes(child, depth + 1)
            deepest, nodes = max(deepest, child_depth), nodes + child_nodes
        return deepest, nodes
    return depth, 1


def validate_caller_schema(schema: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(schema, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SchemaRejected("response_format.schema must be plain JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise SchemaRejected("response_format.schema must be 32 KB or smaller")
    _depth, nodes = _depth_and_nodes(schema)
    if nodes > MAX_SCHEMA_NODES:
        raise SchemaRejected("response_format.schema is too large")
    if schema.get("type") != "object":
        raise SchemaRejected("response_format.schema root must be {\"type\": \"object\"}")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaRejected(f"response_format.schema is not valid JSON Schema: {exc.message[:200]}") from exc
    _resolve_local_refs(schema, schema)


def _resolve_pointer(document: Any, ref: str) -> None:
    pointer = ref[1:]
    if pointer == "":
        return  # "#" is the document root; "#/" is the property named "".
    if not pointer.startswith("/"):
        raise SchemaRejected(
            f"response_format.schema reference '{ref[:80]}': plain-name ($anchor) references are not supported; "
            "use a JSON pointer such as '#/$defs/name'"
        )
    node = document
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise SchemaRejected(f"response_format.schema reference '{ref[:80]}' does not resolve")


def _resolve_local_refs(node: Any, root: dict[str, Any]) -> None:
    """Every permitted local $ref must resolve at admission (422), not mid-run."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            _resolve_pointer(root, ref)
        for child in node.values():
            _resolve_local_refs(child, root)
    elif isinstance(node, list):
        for child in node:
            _resolve_local_refs(child, root)


def resolve_schema(response_format: Any) -> tuple[str, dict[str, Any]] | None:
    """Return (name, schema) for a structured request, or None for text."""
    if response_format is None or response_format.type == "text":
        return None
    if response_format.type == "agroai_schema":
        schema = BUILTIN_SCHEMAS.get(str(response_format.name))
        if schema is None:
            raise SchemaRejected(f"Unknown AGRO-AI schema '{response_format.name}'")
        return str(response_format.name), schema
    return str(response_format.name or "custom"), dict(response_format.schema_ or {})


def _prune_additional(instance: Any, schema: dict[str, Any]) -> Any:
    """Drop keys a closed object schema forbids. Removes, never invents."""
    if isinstance(instance, dict) and isinstance(schema, dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False and properties:
            instance = {key: value for key, value in instance.items() if key in properties}
        return {
            key: _prune_additional(value, properties.get(key, {})) if key in properties else value
            for key, value in instance.items()
        }
    if isinstance(instance, list) and isinstance(schema, dict) and isinstance(schema.get("items"), dict):
        return [_prune_additional(item, schema["items"]) for item in instance]
    return instance


def validation_errors(instance: Any, schema: dict[str, Any], *, limit: int = 8) -> list[str]:
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    try:
        for error in validator.iter_errors(instance):
            path = "/".join(str(part) for part in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message[:200]}")
            if len(errors) >= limit:
                break
    except Exception as exc:  # noqa: BLE001 - defensive: never surface as a server error
        errors.append(f"(schema): validation could not complete ({exc.__class__.__name__})")
    return errors


def scrub_unverifiable_citations(instance: Any, known_ids: set[str]) -> tuple[Any, list[str]]:
    """Remove evidence ids that do not trace to evidence supplied to this run."""
    removed: list[str] = []

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key in {"evidence_ids", "source_ids", "citations"} and isinstance(child, list):
                    kept = []
                    for item in child:
                        if not isinstance(item, str):
                            kept.append(visit(item))
                        elif item in known_ids:
                            kept.append(item)
                        else:
                            removed.append(item[:120])
                    result[key] = kept
                else:
                    result[key] = visit(child)
            return result
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return visit(copy.deepcopy(instance)), removed


def finalize_structured_output(
    candidate: Any,
    schema: dict[str, Any],
    known_ids: set[str],
) -> tuple[Any | None, list[str], list[str]]:
    """Return (output or None, validation_errors, removed_citation_ids)."""
    if not isinstance(candidate, dict):
        return None, ["(root): structured output must be a JSON object"], []
    pruned = _prune_additional(candidate, schema)
    scrubbed, removed = scrub_unverifiable_citations(pruned, known_ids)
    errors = validation_errors(scrubbed, schema)
    if errors:
        return None, errors, removed
    return scrubbed, [], removed
