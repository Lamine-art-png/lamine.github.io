from decimal import Decimal
from collections import Counter

from app.api.deps import AuthContext, get_auth_context
from app.main import app
from app.models.market_intelligence import MarketPosition
from app.models.saas import Organization, OrganizationMembership, User, Workspace


def identity(db, *, suffix="one", role="owner"):
    user = User(email=f"market-{suffix}@example.com", email_verification_status="verified")
    db.add(user)
    db.flush()
    org = Organization(name=f"Market {suffix}", slug=f"market-{suffix}", owner_user_id=user.id, verification_status="approved")
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role=role, status="active")
    db.add(membership)
    db.commit()
    return user, org, membership


def set_context(user, org, membership):
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, organization=org, membership=membership)


def position_payload(**overrides):
    payload = {
        "position_key": "customer-corn-2026",
        "name": "Customer Corn 2026",
        "commodity": "corn",
        "season": "2026",
        "country_code": "US",
        "market_structure": "hybrid",
        "local_currency": "USD",
        "reporting_currency": "USD",
        "quantity_unit": "bushel",
        "expected_production": "100000",
        "inventory_quantity": "0",
        "production_cost_per_unit": "3.50",
        "current_realizable_price": "4.50",
        "price_currency": "USD",
        "freight_per_unit": "0.10",
        "storage_per_unit": "0.05",
    }
    payload.update(overrides)
    return payload


def test_market_intelligence_routes_are_materialized():
    expected = {
        ("GET", "/v1/market-intelligence/capabilities"),
        ("GET", "/v1/market-intelligence/overview"),
        ("GET", "/v1/market-intelligence/positions"),
        ("POST", "/v1/market-intelligence/positions"),
        ("GET", "/v1/market-intelligence/positions/{position_id}"),
        ("PATCH", "/v1/market-intelligence/positions/{position_id}"),
        ("DELETE", "/v1/market-intelligence/positions/{position_id}"),
        ("GET", "/v1/market-intelligence/positions/{position_id}/contracts"),
        ("GET", "/v1/market-intelligence/positions/{position_id}/observations"),
        ("POST", "/v1/market-intelligence/positions/{position_id}/refresh"),
        ("POST", "/v1/market-intelligence/contracts"),
        ("PATCH", "/v1/market-intelligence/contracts/{contract_id}"),
        ("DELETE", "/v1/market-intelligence/contracts/{contract_id}"),
        ("POST", "/v1/market-intelligence/observations"),
        ("GET", "/v1/market-intelligence/providers"),
        ("POST", "/v1/market-intelligence/refresh"),
        ("POST", "/v1/market-intelligence/scenarios"),
        ("GET", "/v1/market-intelligence/scenarios"),
        ("GET", "/v1/market-intelligence/scenarios/{scenario_id}"),
        ("POST", "/v1/market-intelligence/ask"),
        ("POST", "/v1/market-intelligence/decision-journal"),
        ("GET", "/v1/market-intelligence/decision-journal"),
        ("POST", "/v1/market-intelligence/demo/seed"),
    }
    actual = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/v1/market-intelligence")
    ]
    assert set(actual) == expected
    assert Counter(actual) == {item: 1 for item in expected}
    assert not any(
        "market-intelligence" in route.path and route.path.startswith(("/v1/brain/", "/v1/platform/"))
        for route in app.routes
    )

    schema = app.openapi()
    market_paths = {path for path in schema["paths"] if "market-intelligence" in path}
    assert market_paths == {path for _, path in expected}
    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert "/v1/auth/me" in schema["paths"]


def test_global_demo_seed_is_idempotent_and_never_claims_live(client, db):
    user, org, membership = identity(db)
    set_context(user, org, membership)
    first = client.post("/v1/market-intelligence/demo/seed")
    second = client.post("/v1/market-intelligence/demo/seed")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total_cases"] == 6
    assert first.json()["created_positions"] == 6
    assert second.json()["created_positions"] == 0

    overview = client.get("/v1/market-intelligence/overview")
    assert overview.status_code == 200
    data = overview.json()
    assert data["position_count"] == 6
    assert data["data_health"]["status"] == "demo"
    source_states = {
        source["status"]
        for position in data["positions"]
        for source in position["data_health"]["sources"]
    }
    assert source_states == {"DEMO"}
    structures = {position["market_structure"] for position in data["positions"]}
    assert "physical" in structures
    assert "hybrid" in structures


def test_scenarios_persist_and_viewer_is_read_only(client, db):
    user, org, membership = identity(db, suffix="scenario")
    set_context(user, org, membership)
    assert client.post("/v1/market-intelligence/demo/seed").status_code == 200
    overview = client.get("/v1/market-intelligence/overview").json()
    position_id = overview["positions"][0]["position_id"]

    created = client.post("/v1/market-intelligence/scenarios", json={
        "position_id": position_id,
        "name": "Downside",
        "price_pct": -8,
        "yield_pct": -3,
        "fx_pct": 0,
        "production_cost_pct": 4,
        "freight_per_unit_delta": 0,
        "storage_per_unit_delta": 0,
        "sell_pct_now": 0,
    })
    assert created.status_code == 201
    scenario_id = created.json()["id"]
    listing = client.get("/v1/market-intelligence/scenarios")
    assert listing.status_code == 200
    assert any(row["id"] == scenario_id for row in listing.json()["scenarios"])

    membership.role = "viewer"
    db.commit()
    blocked = client.post("/v1/market-intelligence/scenarios", json={"position_id": position_id, "name": "Blocked"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "market_intelligence_read_only"


def test_cross_tenant_position_is_404(client, db):
    user1, org1, membership1 = identity(db, suffix="tenant-one")
    _, org2, _ = identity(db, suffix="tenant-two")
    row = MarketPosition(
        organization_id=org2.id,
        position_key="private-position",
        name="Private",
        commodity="wheat",
        season="2026",
        country_code="AU",
        market_structure="physical",
        local_currency="AUD",
        reporting_currency="AUD",
        quantity_unit="tonne",
        expected_production=Decimal("100"),
        inventory_quantity=Decimal("0"),
        production_cost_per_unit=Decimal("200"),
        current_realizable_price=Decimal("300"),
        price_currency="AUD",
        freight_per_unit=Decimal("10"),
        storage_per_unit=Decimal("2"),
    )
    db.add(row)
    db.commit()
    set_context(user1, org1, membership1)
    response = client.get(f"/v1/market-intelligence/positions/{row.id}")
    assert response.status_code == 404


def test_cross_tenant_workspace_cannot_be_attached_to_position(client, db):
    user1, org1, membership1 = identity(db, suffix="workspace-one")
    _, org2, _ = identity(db, suffix="workspace-two")
    foreign_workspace = Workspace(organization_id=org2.id, name="Foreign operation", mode="evaluation")
    db.add(foreign_workspace)
    db.commit()
    set_context(user1, org1, membership1)

    response = client.post(
        "/v1/market-intelligence/positions",
        json=position_payload(position_key="workspace-isolation", workspace_id=foreign_workspace.id),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found"


def test_customer_observation_can_never_self_grant_live_authority(client, db):
    user, org, membership = identity(db, suffix="manual-source")
    set_context(user, org, membership)
    position_response = client.post(
        "/v1/market-intelligence/positions",
        json=position_payload(position_key="manual-source-position"),
    )
    assert position_response.status_code == 201
    position_id = position_response.json()["id"]

    response = client.post(
        "/v1/market-intelligence/observations",
        json={
            "position_id": position_id,
            "evidence_id": "customer-live-attempt-1",
            "observation_type": "cash_price",
            "provider": "claimed_exchange_provider",
            "source_name": "Customer supplied benchmark",
            "source_status": "LIVE",
            "value": "4.75",
            "unit": "USD/bushel",
            "currency": "USD",
            "observed_at": "2026-09-13T20:00:00Z",
        },
    )
    assert response.status_code == 201
    assert response.json()["source_status"] == "MANUAL"

    overview = client.get("/v1/market-intelligence/overview").json()
    source_states = {
        source["status"]
        for position in overview["positions"]
        for source in position["data_health"]["sources"]
    }
    assert "LIVE" not in source_states
    assert "MANUAL" in source_states
    source = next(
        source
        for position in overview["positions"]
        for source in position["data_health"]["sources"]
        if source["evidence_id"] == "customer-live-attempt-1"
    )
    assert source["observation_type"] == "cash_price"
    assert source["unit"] == "USD/bushel"
    assert source["currency"] == "USD"
    assert source["age_minutes"] >= 0


def test_observation_value_is_redacted_when_licensing_disallows_display(client, db):
    user, org, membership = identity(db, suffix="licensed-source")
    set_context(user, org, membership)
    position = client.post(
        "/v1/market-intelligence/positions",
        json=position_payload(position_key="licensed-source-position"),
    )
    assert position.status_code == 201
    position_id = position.json()["id"]

    created = client.post(
        "/v1/market-intelligence/observations",
        json={
            "position_id": position_id,
            "evidence_id": "licensed-source-1",
            "observation_type": "cash_price",
            "provider": "restricted_provider",
            "source_name": "Restricted benchmark",
            "source_status": "DELAYED",
            "value": "4.75",
            "unit": "USD/bushel",
            "currency": "USD",
            "observed_at": "2026-09-13T20:00:00Z",
            "licensing": {"display_allowed": False, "license": "derived-use-only"},
        },
    )
    assert created.status_code == 201

    observations = client.get(f"/v1/market-intelligence/positions/{position_id}/observations")
    assert observations.status_code == 200
    observation = observations.json()["observations"][0]
    assert observation["value"] is None
    assert observation["redacted"] is True
    assert observation["licensing"] == {"display_allowed": False, "license": "derived-use-only"}


def test_portfolio_suppresses_partial_projected_totals(client, db):
    user, org, membership = identity(db, suffix="partial-portfolio")
    set_context(user, org, membership)
    created = client.post(
        "/v1/market-intelligence/positions",
        json=position_payload(
            position_key="partial-portfolio-position",
            reporting_currency="USD",
            current_realizable_price="20",
            price_currency="BRL",
            fx_rate_to_reporting=None,
        ),
    )
    assert created.status_code == 201
    overview = client.get("/v1/market-intelligence/overview")
    assert overview.status_code == 200
    bucket = overview.json()["portfolio_by_reporting_currency"][0]
    assert bucket["partial"] is True
    assert bucket["projected_revenue"] is None
    assert bucket["projected_margin"] is None


def test_release_state_fails_closed(client, db, monkeypatch):
    user, org, membership = identity(db, suffix="disabled")
    set_context(user, org, membership)
    monkeypatch.setenv("MARKET_INTELLIGENCE_RELEASE_STATE", "disabled")
    response = client.get("/v1/market-intelligence/overview")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "market_intelligence_not_released"
