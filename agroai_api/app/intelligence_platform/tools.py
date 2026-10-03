"""Tool / capability registry for AGRO-AI Intelligence.

Every tool declares: a versioned name, an input JSON Schema, the scope it
requires, its side-effect class, and an execution budget. v1 deliberately
registers only tools whose side-effect class is ``none``: deterministic
calculations (the fail-closed scientific registry), tenant-scoped reads, and
retrieval. Registration of any tool that could act on the physical world,
write to a provider, or move money is refused here; such capabilities need a
separately designed permission model and are not reachable with an advisory
``intelligence:run`` key.

Tools run server-side, are requested explicitly by the caller (``tools`` on
the request, or ``POST /v1/intelligence/tools/execute``), never by model text,
so prompt-injected content cannot invoke them. Every invocation is recorded
on the run (name, version, status, duration, argument hash) and its result is
supplied to inference as attributable evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException
from jsonschema import Draft202012Validator
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.intelligence_platform.contract import to_naive_utc
from app.platform_api.principal import PlatformPrincipal
from app.services.scientific_tool_registry import get_scientific_tool_registry


MAX_TOOL_CALLS_PER_RUN = 10
TOOL_TIME_BUDGET_MS = 10_000


@dataclass
class ToolContext:
    db: Session
    principal: PlatformPrincipal


@dataclass(frozen=True)
class PlatformTool:
    name: str
    version: str
    category: str  # calculation | data | retrieval
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    required_scope: str = "intelligence:run"
    side_effects: str = "none"
    timeout_ms: int = 5_000
    max_attempts: int = 1
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "input_schema": self.input_schema,
            "required_scope": self.required_scope,
            "side_effects": self.side_effects,
            "physical_action": False,
            "timeout_ms": self.timeout_ms,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, PlatformTool] = {}

    def register(self, tool: PlatformTool) -> None:
        if tool.side_effects != "none":
            raise ValueError("advisory intelligence tools must be side-effect free")
        if tool.required_scope != "intelligence:run":
            raise ValueError("advisory intelligence tools require exactly intelligence:run")
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        Draft202012Validator.check_schema(tool.input_schema)
        self._tools[tool.name] = tool

    def get(self, name: str) -> PlatformTool | None:
        return self._tools.get(name)

    def all(self) -> list[PlatformTool]:
        return [self._tools[name] for name in sorted(self._tools)]


def _finite_numbers(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_numbers(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_numbers(item) for item in value)
    return True


# --------------------------------------------------------------------------- #
# Calculation tools: the existing deterministic scientific registry.


def _scientific_tool(spec: Any) -> PlatformTool:
    registry = get_scientific_tool_registry()
    properties: dict[str, Any] = {}
    for name in [*spec.required_inputs, *spec.optional_inputs]:
        unit = spec.expected_units.get(name)
        properties[name] = {"description": f"{unit}" if unit else name}
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(spec.required_inputs),
        "additionalProperties": False,
    }

    def handler(_ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        result = registry.run(spec.tool_id, arguments)
        return {
            "status": {"COMPUTED": "completed", "NOT_COMPUTABLE": "not_computable", "INVALID_INPUT": "invalid_input"}[result.status],
            "output": result.output,
            "normalized_inputs": result.normalized_inputs,
            "missing_requirements": result.missing_requirements,
            "invalid_inputs": result.invalid_inputs,
            "method": spec.calculation_method,
        }

    return PlatformTool(
        name=spec.tool_id,
        version=spec.version,
        category="calculation",
        description=spec.description,
        input_schema=schema,
        handler=handler,
        timeout_ms=1_000,
        assumptions=tuple(spec.assumptions),
        limitations=tuple(spec.limitations),
        metadata={"domain": spec.domain, "valid_ranges": spec.valid_ranges},
    )


# --------------------------------------------------------------------------- #
# Farm economics: deterministic partial budget from caller-supplied numbers.


def _crop_margin(_ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    area = float(arguments["area_ha"])
    yield_per_ha = float(arguments["expected_yield_per_ha"])
    price = float(arguments["price_per_unit"])
    costs = list(arguments.get("costs") or [])
    scenarios_pct = list(arguments.get("yield_change_pct") or [-20, 0, 20])
    price_scenarios_pct = list(arguments.get("price_change_pct") or [0])
    if area <= 0:
        return {"status": "invalid_input", "invalid_inputs": ["area_ha"], "output": {}}
    total_costs = 0.0
    breakdown = []
    for item in costs:
        amount = float(item["amount"])
        basis = item.get("basis", "total")
        total = amount * area if basis == "per_ha" else amount
        total_costs += total
        breakdown.append({"category": str(item["category"])[:120], "basis": basis, "total": round(total, 2)})
    production = yield_per_ha * area
    revenue = production * price

    def scenario(yield_pct: float, price_pct: float) -> dict[str, Any]:
        scenario_revenue = production * (1 + yield_pct / 100) * price * (1 + price_pct / 100)
        margin = scenario_revenue - total_costs
        return {
            "yield_change_pct": yield_pct,
            "price_change_pct": price_pct,
            "revenue": round(scenario_revenue, 2),
            "margin": round(margin, 2),
            "margin_per_ha": round(margin / area, 2),
        }

    def finite(value: Any) -> bool:
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, dict):
            return all(finite(item) for item in value.values())
        if isinstance(value, list):
            return all(finite(item) for item in value)
        return True

    result = {
        "status": "completed",
        "output": {
            "currency": arguments.get("currency"),
            "production": round(production, 4),
            "revenue": round(revenue, 2),
            "total_costs": round(total_costs, 2),
            "margin": round(revenue - total_costs, 2),
            "margin_per_ha": round((revenue - total_costs) / area, 2),
            "breakeven_price_per_unit": round(total_costs / production, 4) if production > 0 else None,
            "breakeven_yield_per_ha": round(total_costs / (price * area), 4) if price > 0 else None,
            "cost_breakdown": breakdown,
            "scenarios": [scenario(float(y), float(p)) for y in scenarios_pct[:7] for p in price_scenarios_pct[:5]],
        },
        "method": "Partial budget: revenue = yield x area x price; margin = revenue - sum(costs); breakeven from totals.",
    }
    if not finite(result["output"]):
        return {"status": "invalid_input", "invalid_inputs": ["magnitude"], "output": {}}
    return result


_CROP_MARGIN_SCHEMA = {
    "type": "object",
    "properties": {
        "area_ha": {"type": "number", "exclusiveMinimum": 0, "maximum": 10000000},
        "expected_yield_per_ha": {"type": "number", "minimum": 0, "maximum": 1000000},
        "price_per_unit": {"type": "number", "minimum": 0, "maximum": 1000000000},
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "costs": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "minLength": 1, "maxLength": 120},
                    "amount": {"type": "number", "minimum": 0, "maximum": 1000000000000},
                    "basis": {"type": "string", "enum": ["total", "per_ha"]},
                },
                "required": ["category", "amount"],
                "additionalProperties": False,
            },
        },
        "yield_change_pct": {"type": "array", "items": {"type": "number", "minimum": -100, "maximum": 500}, "maxItems": 7},
        "price_change_pct": {"type": "array", "items": {"type": "number", "minimum": -100, "maximum": 500}, "maxItems": 5},
    },
    "required": ["area_ha", "expected_yield_per_ha", "price_per_unit"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Tenant-scoped data tools.


def _knowledge_search(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.intelligence_platform import knowledge

    hits = knowledge.search(
        ctx.db,
        ctx.principal,
        collections=list(arguments["collections"]),
        query=str(arguments["query"]),
        max_results=int(arguments.get("max_results") or 6),
    )
    return {"status": "completed", "output": {"results": hits}}


def _observations_query(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.models.operational_records import EvidenceRecord

    # Same predicates as GET /v1/platform/observations: organization, API
    # project, and the key's workspace when restricted.
    query = ctx.db.query(EvidenceRecord).filter(
        EvidenceRecord.tenant_id == ctx.principal.organization_id,
        EvidenceRecord.metadata_json["platform_api_project_id"].as_string() == ctx.principal.api_project_id,
    )
    if ctx.principal.workspace_id:
        query = query.filter(EvidenceRecord.workspace_id == ctx.principal.workspace_id)
    if arguments.get("field_id"):
        query = query.filter(EvidenceRecord.field_id == str(arguments["field_id"]))
    if arguments.get("evidence_type"):
        query = query.filter(EvidenceRecord.evidence_type == str(arguments["evidence_type"]))
    if arguments.get("since"):
        try:
            since = to_naive_utc(datetime.fromisoformat(str(arguments["since"]).replace("Z", "+00:00")))
        except ValueError:
            return {"status": "invalid_input", "invalid_inputs": ["since"], "output": {}}
        query = query.filter(EvidenceRecord.occurred_at >= since)
    rows = query.order_by(EvidenceRecord.occurred_at.desc().nullslast()).limit(int(arguments.get("limit") or 20)).all()
    return {
        "status": "completed",
        "output": {
            "observations": [
                {
                    "id": row.id,
                    "type": row.evidence_type,
                    "field_id": row.field_id,
                    "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                    "title": row.title,
                    "value": row.value_json,
                    "units": row.units,
                    "confidence": row.confidence,
                    "quality_status": row.quality_status,
                }
                for row in rows
            ]
        },
    }


def _field_get(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.models.saas import ManagedEntity

    row = (
        ctx.db.query(ManagedEntity)
        .filter(
            ManagedEntity.id == str(arguments["field_id"]),
            ManagedEntity.organization_id == ctx.principal.organization_id,
            ManagedEntity.entity_type == "platform_field",
        )
        .first()
    )
    meta = dict(row.metadata_json or {}) if row is not None else {}
    project_id = str(meta.get("api_project_id") or "")
    if (
        row is None
        # Exact project tag, like /v1/platform/fields/{id}: an untagged legacy
        # entity is not visible to any API project.
        or project_id != ctx.principal.api_project_id
        # Exact match for restricted keys (as /v1/platform/fields): a
        # project-wide field (NULL workspace) is not visible to them.
        or (ctx.principal.workspace_id and row.workspace_id != ctx.principal.workspace_id)
    ):
        return {"status": "not_found", "output": {}}
    return {
        "status": "completed",
        "output": {
            "id": row.id,
            "name": row.display_name,
            "external_id": row.external_id,
            "crop": meta.get("crop"),
            "area_hectares": meta.get("area_hectares"),
            "boundary": meta.get("boundary"),
            "metadata": meta.get("customer_metadata") or {},
        },
    }


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for spec in get_scientific_tool_registry().specs():
        registry.register(_scientific_tool(spec))
    registry.register(
        PlatformTool(
            name="finance.crop_margin.v1",
            version="1.0.0",
            category="calculation",
            description="Partial-budget crop margin, breakeven price/yield and yield/price scenarios from caller-supplied economics.",
            input_schema=_CROP_MARGIN_SCHEMA,
            handler=_crop_margin,
            timeout_ms=1_000,
            assumptions=("All inputs are caller-supplied; AGRO-AI adds no prices, yields or costs.",),
            limitations=("Not a cash-flow, tax, financing or insurance model.",),
        )
    )
    registry.register(
        PlatformTool(
            name="knowledge.search.v1",
            version="1.0.0",
            category="retrieval",
            description="Search this project's knowledge collections; returns cited chunks with source and freshness.",
            input_schema={
                "type": "object",
                "properties": {
                    "collections": {"type": "array", "items": {"type": "string", "maxLength": 64}, "minItems": 1, "maxItems": 5},
                    "query": {"type": "string", "minLength": 2, "maxLength": 1000},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["collections", "query"],
                "additionalProperties": False,
            },
            handler=_knowledge_search,
            timeout_ms=5_000,
            max_attempts=2,
        )
    )
    registry.register(
        PlatformTool(
            name="observations.query.v1",
            version="1.0.0",
            category="data",
            description="Read recent observations/evidence records this organization ingested (workspace-restricted keys see only their workspace).",
            input_schema={
                "type": "object",
                "properties": {
                    "field_id": {"type": "string", "maxLength": 200},
                    "evidence_type": {"type": "string", "maxLength": 120},
                    "since": {"type": "string", "maxLength": 40},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
            handler=_observations_query,
            timeout_ms=5_000,
            max_attempts=2,
        )
    )
    registry.register(
        PlatformTool(
            name="fields.get.v1",
            version="1.0.0",
            category="data",
            description="Read one Platform field (boundary, crop, area, metadata) owned by this project.",
            input_schema={
                "type": "object",
                "properties": {"field_id": {"type": "string", "minLength": 1, "maxLength": 200}},
                "required": ["field_id"],
                "additionalProperties": False,
            },
            handler=_field_get,
            timeout_ms=5_000,
            max_attempts=2,
        )
    )
    return registry


REGISTRY = _build_registry()


def validate_calls(calls: list[Any]) -> None:
    """Reject unknown tools and malformed arguments before any money or compute is spent."""
    if len(calls) > MAX_TOOL_CALLS_PER_RUN:
        raise HTTPException(status_code=422, detail={"code": "too_many_tool_calls", "limit": MAX_TOOL_CALLS_PER_RUN})
    for index, call in enumerate(calls):
        tool = REGISTRY.get(call.name)
        if tool is None:
            raise HTTPException(status_code=422, detail={"code": "unknown_tool", "tool": call.name[:80], "index": index})
        errors = sorted(Draft202012Validator(tool.input_schema).iter_errors(call.arguments), key=lambda item: list(item.path))
        if errors or not _finite_numbers(call.arguments):
            message = errors[0].message[:200] if errors else "numbers must be finite"
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_tool_arguments", "tool": call.name, "index": index, "message": message},
            )


def execute(ctx: ToolContext, calls: list[Any]) -> list[dict[str, Any]]:
    """Execute validated calls in order. Failures are recorded, never raised."""
    results: list[dict[str, Any]] = []
    budget_started = time.monotonic()
    for index, call in enumerate(calls):
        tool = REGISTRY.get(call.name)
        assert tool is not None, "validate_calls must run first"
        record: dict[str, Any] = {
            "id": f"tool_{index + 1}",
            "name": tool.name,
            "version": tool.version,
            "category": tool.category,
            "arguments_sha256": hashlib.sha256(
                json.dumps(call.arguments, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest(),
            "argument_keys": sorted(call.arguments.keys())[:50],
        }
        if (time.monotonic() - budget_started) * 1000 > TOOL_TIME_BUDGET_MS:
            record.update({"status": "skipped", "error": "tool_time_budget_exhausted", "duration_ms": 0, "attempts": 0})
            results.append(record)
            continue
        attempts = 0
        started = time.monotonic()
        while True:
            attempts += 1
            try:
                outcome = tool.handler(ctx, dict(call.arguments))
                break
            except OperationalError:
                ctx.db.rollback()
                if attempts >= tool.max_attempts:
                    outcome = {"status": "failed", "error": "tool_data_unavailable", "output": {}}
                    break
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                outcome = {"status": "invalid_input", "error": "tool_input_rejected", "output": {}}
                break
        duration_ms = int((time.monotonic() - started) * 1000)
        if duration_ms > tool.timeout_ms and outcome.get("status") == "completed":
            outcome = {"status": "timeout", "error": "tool_timeout", "output": {}}
        record.update(
            {
                "status": outcome.get("status", "failed"),
                "duration_ms": duration_ms,
                "attempts": attempts,
                "output": outcome.get("output") or {},
                "missing_requirements": outcome.get("missing_requirements") or [],
                "invalid_inputs": outcome.get("invalid_inputs") or [],
                "method": outcome.get("method"),
                "error": outcome.get("error"),
            }
        )
        results.append(record)
    return results


def audit_record(result: dict[str, Any]) -> dict[str, Any]:
    """Durable audit shape stored on the run: no customer argument values."""
    return {
        key: result.get(key)
        for key in ("id", "name", "version", "category", "status", "duration_ms", "attempts", "arguments_sha256", "argument_keys", "error")
    }
