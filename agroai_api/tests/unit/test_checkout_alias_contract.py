from app.api.v1.monetization_convergence import checkout_authoritative
from app.main import app


def test_checkout_aliases_use_same_endpoint():
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) in {
            "/v1/billing/checkout",
            "/v1/billing/checkout-authoritative",
        }
        and "POST" in set(getattr(route, "methods", None) or ())
    ]
    assert len(routes) == 2
    assert all(route.endpoint is checkout_authoritative for route in routes)
