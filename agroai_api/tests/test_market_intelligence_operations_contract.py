import pytest
from pydantic import ValidationError

from app.api.v1.market_intelligence_operations import ContractPatch, PositionPatch
from app.main import app


def test_market_intelligence_management_routes_are_mounted_once():
    expected = {
        ("PATCH", "/v1/market-intelligence/positions/{position_id}"),
        ("DELETE", "/v1/market-intelligence/positions/{position_id}"),
        ("PATCH", "/v1/market-intelligence/contracts/{contract_id}"),
        ("DELETE", "/v1/market-intelligence/contracts/{contract_id}"),
        ("GET", "/v1/market-intelligence/providers"),
        ("POST", "/v1/market-intelligence/positions/{position_id}/refresh"),
        ("POST", "/v1/market-intelligence/refresh"),
    }

    seen: dict[tuple[str, str], int] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        for method in methods:
            key = (method, path)
            seen[key] = seen.get(key, 0) + 1

    for key in expected:
        assert seen.get(key) == 1, f"expected exactly one mounted route for {key}, got {seen.get(key, 0)}"


def test_market_intelligence_openapi_operation_ids_are_unique():
    schema = app.openapi()
    operation_ids: list[str] = []
    for path, methods in schema.get("paths", {}).items():
        if not path.startswith("/v1/market-intelligence"):
            continue
        for method, payload in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = payload.get("operationId")
            if operation_id:
                operation_ids.append(operation_id)
    assert len(operation_ids) == len(set(operation_ids))


def test_patch_models_reject_explicit_null_for_database_required_fields():
    for field_name in (
        "name", "commodity", "season", "country_code", "market_structure",
        "local_currency", "reporting_currency", "quantity_unit", "expected_production",
        "inventory_quantity", "freight_per_unit", "storage_per_unit", "status",
    ):
        with pytest.raises(ValidationError):
            PositionPatch.model_validate({field_name: None})

    for field_name in ("status", "quantity", "quantity_unit", "price", "currency"):
        with pytest.raises(ValidationError):
            ContractPatch.model_validate({field_name: None})

    # Nullable commercial fields remain intentionally clearable.
    assert PositionPatch.model_validate({"current_realizable_price": None}).current_realizable_price is None
    assert ContractPatch.model_validate({"buyer": None}).buyer is None
