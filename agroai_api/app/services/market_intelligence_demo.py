"""Clearly labelled global demo fixtures for Market Intelligence.

Fixtures exercise different currencies, units and market structures. They are
synthetic and can never be emitted as LIVE data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_intelligence import MarketContractPosition, MarketObservation, MarketPosition


DEMO_CASES: tuple[dict[str, Any], ...] = (
    {
        "key": "demo-br-soy-2027", "name": "Brazil Soybean 2027", "commodity": "soybeans", "season": "2027",
        "country": "BR", "region": "Mato Grosso", "structure": "hybrid", "currency": "BRL", "reporting": "USD",
        "unit": "tonne", "production": "5200", "inventory": "0", "cost": "355.00", "spot": "2185.00", "price_currency": "BRL",
        "fx": "0.1840", "freight": "22.00", "storage": "6.00",
        "contracts": [("BR-SOY-001", "Cooperativa Demo", "1768", "tonne", "2140.00", "BRL", "0.1840")],
        "observations": [("benchmark_price", "B3-compatible demo benchmark", "2185.00", "BRL/tonne"), ("fx", "Synthetic BRL/USD", "0.1840", "USD/BRL")],
    },
    {
        "key": "demo-us-corn-2026", "name": "United States Corn 2026", "commodity": "corn", "season": "2026",
        "country": "US", "region": "Iowa", "structure": "hybrid", "currency": "USD", "reporting": "USD",
        "unit": "bushel", "production": "310000", "inventory": "85000", "cost": "3.82", "spot": "4.67", "price_currency": "USD",
        "fx": None, "freight": "0.18", "storage": "0.11",
        "contracts": [("US-CORN-001", "Elevator Demo", "124000", "bushel", "4.61", "USD", None)],
        "observations": [("cash_price", "Synthetic local elevator cash", "4.67", "USD/bushel"), ("basis", "Synthetic local basis", "-0.24", "USD/bushel")],
    },
    {
        "key": "demo-us-almond-2026", "name": "California Almonds 2026", "commodity": "almonds", "season": "2026",
        "country": "US", "region": "California", "structure": "physical", "currency": "USD", "reporting": "USD",
        "unit": "pound", "production": "4100000", "inventory": "1650000", "cost": "1.72", "spot": "2.38", "price_currency": "USD",
        "fx": None, "freight": "0.08", "storage": "0.04",
        "contracts": [("CA-ALM-001", "Processor Demo", "1435000", "pound", "2.31", "USD", None)],
        "observations": [("physical_price", "Synthetic California almond market", "2.38", "USD/pound")],
    },
    {
        "key": "demo-au-wheat-2026", "name": "Australia Wheat 2026", "commodity": "wheat", "season": "2026",
        "country": "AU", "region": "Western Australia", "structure": "hybrid", "currency": "AUD", "reporting": "AUD",
        "unit": "tonne", "production": "8900", "inventory": "2100", "cost": "248.00", "spot": "337.00", "price_currency": "AUD",
        "fx": None, "freight": "31.00", "storage": "9.50",
        "contracts": [("AU-WHT-001", "Grain Buyer Demo", "2670", "tonne", "329.00", "AUD", None)],
        "observations": [("cash_price", "Synthetic WA wheat cash", "337.00", "AUD/tonne")],
    },
    {
        "key": "demo-in-rice-2026", "name": "India Rice 2026", "commodity": "rice", "season": "2026",
        "country": "IN", "region": "Punjab", "structure": "physical", "currency": "INR", "reporting": "INR",
        "unit": "tonne", "production": "2750", "inventory": "640", "cost": "20500", "spot": "26400", "price_currency": "INR",
        "fx": None, "freight": "950", "storage": "320",
        "contracts": [("IN-RICE-001", "Buyer Demo", "825", "tonne", "25800", "INR", None)],
        "observations": [("physical_price", "Synthetic mandi reference", "26400", "INR/tonne")],
    },
    {
        "key": "demo-ke-maize-2026", "name": "Kenya Maize Cooperative 2026", "commodity": "maize", "season": "2026",
        "country": "KE", "region": "Rift Valley", "structure": "physical", "currency": "KES", "reporting": "KES",
        "unit": "kg", "production": "1850000", "inventory": "390000", "cost": "31.50", "spot": "44.80", "price_currency": "KES",
        "fx": None, "freight": "2.40", "storage": "1.10",
        "contracts": [("KE-MAIZE-001", "Aggregator Demo", "555000", "kg", "43.20", "KES", None)],
        "observations": [("physical_price", "Synthetic regional maize price", "44.80", "KES/kg")],
    },
)


def seed_demo_markets(db: Session, organization_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    """Idempotently create six synthetic global cases for one organization."""
    now = datetime.utcnow()
    position_ids: list[str] = []
    created = 0
    for case in DEMO_CASES:
        position = (
            db.query(MarketPosition)
            .filter(MarketPosition.organization_id == organization_id, MarketPosition.position_key == case["key"])
            .first()
        )
        if position is None:
            position = MarketPosition(
                organization_id=organization_id,
                workspace_id=workspace_id,
                position_key=case["key"],
                name=case["name"], commodity=case["commodity"], season=case["season"],
                country_code=case["country"], region=case["region"], market_structure=case["structure"],
                local_currency=case["currency"], reporting_currency=case["reporting"], quantity_unit=case["unit"],
                expected_production=Decimal(case["production"]), inventory_quantity=Decimal(case["inventory"]),
                production_cost_per_unit=Decimal(case["cost"]), current_realizable_price=Decimal(case["spot"]),
                price_currency=case["price_currency"], fx_rate_to_reporting=Decimal(case["fx"]) if case["fx"] else None,
                freight_per_unit=Decimal(case["freight"]), storage_per_unit=Decimal(case["storage"]),
                metadata_json={
                    "fixture": "global-market-intelligence-v1",
                    "synthetic": True,
                    "production_cost_behavior": "fixed_total_at_baseline_yield",
                    "inventory_cost_per_unit": case["cost"],
                },
            )
            db.add(position)
            db.flush()
            created += 1
        position_ids.append(position.id)

        for code, buyer, quantity, unit, price, currency, fx in case["contracts"]:
            exists = (
                db.query(MarketContractPosition)
                .filter(MarketContractPosition.organization_id == organization_id, MarketContractPosition.contract_code == code)
                .first()
            )
            if exists is None:
                db.add(MarketContractPosition(
                    organization_id=organization_id, position_id=position.id, contract_code=code, buyer=buyer,
                    status="active", quantity=Decimal(quantity), quantity_unit=unit, price=Decimal(price), currency=currency,
                    fx_rate_to_reporting=Decimal(fx) if fx else None,
                    metadata_json={"fixture": "global-market-intelligence-v1", "synthetic": True},
                ))

        for idx, (kind, source_name, value, unit) in enumerate(case["observations"], start=1):
            evidence_id = f"{case['key']}-{kind}-{idx}"
            exists = (
                db.query(MarketObservation)
                .filter(MarketObservation.organization_id == organization_id, MarketObservation.evidence_id == evidence_id)
                .first()
            )
            if exists is None:
                db.add(MarketObservation(
                    organization_id=organization_id, position_id=position.id, evidence_id=evidence_id,
                    observation_type=kind, provider="agroai_demo_fixture", source_name=source_name,
                    source_status="DEMO", value=Decimal(value), unit=unit,
                    currency=case["price_currency"] if kind != "fx" else case["reporting"],
                    observed_at=now - timedelta(minutes=15), retrieved_at=now,
                    quality_json={"synthetic": True, "fitness": "product-demonstration-only"},
                    licensing_json={"display_allowed": True, "derived_values_allowed": True, "fixture": True},
                    metadata_json={"warning": "Synthetic DEMO data. Not a live market observation."},
                ))
    db.commit()
    return {"status": "ok", "source_status": "DEMO", "created_positions": created, "positions": position_ids, "total_cases": len(DEMO_CASES)}
