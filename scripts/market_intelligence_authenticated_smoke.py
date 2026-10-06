#!/usr/bin/env python3
"""Authenticated production smoke for AGRO-AI Market / Commercial Intelligence.

Requires a real signed-in AEP session token for an organization that is a
member of the Market Intelligence release cohort:

    MARKET_INTELLIGENCE_SMOKE_TOKEN=<portal session JWT> \\
    python3 scripts/market_intelligence_authenticated_smoke.py [--api https://app.agroai-pilot.com]

Default mode is READ-ONLY: capabilities, home, overview, coverage, market
packs, onboarding inference (pure), provenance, deterministic scenario
comparison (not persisted), alerts and provider status. ``--write`` adds a
clearly labelled smoke position created through onboarding and archives it
afterwards. The script never prints the token and exits non-zero on any
contract violation. Without a token it reports NOT_CONFIGURED (exit 2) rather
than claiming success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

FORBIDDEN_STATES_FOR_CUSTOMER_INPUT = {"LIVE"}


def call(api: str, token: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{api.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "agroai-market-intelligence-smoke/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - operator-supplied AGRO-AI origin
            return response.status, json.loads(response.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "null")
        except ValueError:
            return exc.code, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=os.getenv("MARKET_INTELLIGENCE_SMOKE_API", "https://app.agroai-pilot.com"))
    parser.add_argument("--write", action="store_true", help="create and archive a labelled smoke position")
    args = parser.parse_args()
    token = os.getenv("MARKET_INTELLIGENCE_SMOKE_TOKEN", "").strip()
    if not token:
        print(json.dumps({"status": "NOT_CONFIGURED", "reason": "MARKET_INTELLIGENCE_SMOKE_TOKEN is not set; an authenticated AEP session is required."}))
        return 2
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        results.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(name)

    status, caps = call(args.api, token, "GET", "/v1/market-intelligence/capabilities")
    check("capabilities", status == 200 and caps.get("policy", {}).get("trade_execution") is False, {"status": status, "release_state": (caps or {}).get("release_state")})
    status, home = call(args.api, token, "GET", "/v1/market-intelligence/home")
    check("home", status == 200 and home.get("status") in {"attention", "review", "steady"}, {"status": status, "positions": len((home or {}).get("positions") or [])})
    status, overview = call(args.api, token, "GET", "/v1/market-intelligence/overview")
    check("overview", status == 200, {"status": status})
    status, coverage = call(args.api, token, "GET", "/v1/market-intelligence/coverage")
    providers = (coverage or {}).get("providers") or {}
    check("coverage", status == 200 and "fx_reference" in providers, {"status": status, "providers": {k: v.get("status") for k, v in providers.items()}})
    for licensed in ("cme_futures", "b3_futures", "euronext_futures", "asx_futures"):
        check(f"licensed_boundary_truthful:{licensed}", providers.get(licensed, {}).get("status") == "NOT_CONFIGURED", providers.get(licensed, {}).get("status"))
    status, inferred = call(args.api, token, "POST", "/v1/market-intelligence/onboarding/infer", {"crop": "soja", "country_code": "BR", "region": "Mato Grosso"})
    check("onboarding_infer_br_soy", status == 200 and inferred.get("pack_id") == "br_grains_oilseeds" and inferred.get("quantity_unit") == "saca_60kg", inferred and {k: inferred.get(k) for k in ("pack_id", "quantity_unit", "local_currency")})
    status, inferred = call(args.api, token, "POST", "/v1/market-intelligence/onboarding/infer", {"crop": "almonds", "country_code": "US", "region": "California"})
    check("onboarding_infer_almonds_no_futures", status == 200 and inferred.get("futures_role") == "none", inferred and inferred.get("futures_role"))
    positions = (home or {}).get("positions") or []
    if positions:
        position_id = positions[0]["position_id"]
        status, provenance = call(args.api, token, "GET", f"/v1/market-intelligence/positions/{position_id}/provenance")
        states = {s.get("state") for s in (provenance or {}).get("sources") or []}
        # No configured adapter is entitled to emit LIVE; published sources are DELAYED.
        check("provenance_no_live_claims", status == 200 and not (states & FORBIDDEN_STATES_FOR_CUSTOMER_INPUT), {"status": status, "states": sorted(s for s in states if s)})
        status, compared = call(args.api, token, "POST", "/v1/market-intelligence/scenarios/compare",
                                {"position_id": position_id, "scenarios": [{"label": "zero"}, {"label": "price -8%", "price_pct": "-8"}]})
        zero = ((compared or {}).get("scenarios") or [{}])[0]
        check("scenario_zero_change_invariant", status == 200 and zero.get("zero_change_invariant") is True and zero.get("not_a_forecast") is True, {"status": status})
        status, _risk = call(args.api, token, "GET", f"/v1/market-intelligence/positions/{position_id}/risk")
        check("risk_context", status == 200, {"status": status})
    status, alerts = call(args.api, token, "GET", "/v1/market-intelligence/alerts?status=all")
    check("alerts", status == 200, {"status": status, "count": len((alerts or {}).get("alerts") or [])})
    status, _providers = call(args.api, token, "GET", "/v1/market-intelligence/providers")
    check("providers", status == 200, {"status": status})

    if args.write:
        status, created = call(args.api, token, "POST", "/v1/market-intelligence/onboarding", {
            "crop": "wheat", "country_code": "FR", "region": "Rouen", "season": "smoke", "name": "AGRO-AI smoke test (safe to delete)",
            "expected_production": "1", "production_cost_per_unit": "1",
        })
        check("onboarding_create", status == 201, {"status": status, "pack": (created or {}).get("inferred", {}).get("pack_id")})
        if status == 201:
            archived, _ = call(args.api, token, "DELETE", f"/v1/market-intelligence/positions/{created['id']}")
            check("onboarding_cleanup_archived", archived == 204, {"status": archived})

    print(json.dumps({"status": "ok" if not failures else "failed", "failures": failures, "results": results}, indent=2, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
