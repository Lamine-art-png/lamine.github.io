from decimal import Decimal

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.main import app
from app.models.market_intelligence import MarketPosition
from app.models.saas import Organization, OrganizationMembership, User


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


def test_market_intelligence_routes_are_materialized():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/market-intelligence/overview" in paths
    assert "/v1/market-intelligence/scenarios" in paths
    assert "/v1/market-intelligence/positions" in paths


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
    user2, org2, _ = identity(db, suffix="tenant-two")
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


def test_release_state_fails_closed(client, db, monkeypatch):
    user, org, membership = identity(db, suffix="disabled")
    set_context(user, org, membership)
    monkeypatch.setattr(settings, "MARKET_INTELLIGENCE_RELEASE_STATE", "disabled", raising=False)
    response = client.get("/v1/market-intelligence/overview")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "market_intelligence_not_released"
