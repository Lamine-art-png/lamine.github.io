from app.api.v1 import (
    connector_connection_upload_secure,
    connector_stream_secure,
    connector_upload_commercial,
)
from app.main import app


def _post_routes(path: str):
    return [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and "POST" in set(getattr(route, "methods", None) or ())
    ]


def test_every_live_customer_file_ingestion_route_is_quota_metered():
    expected = {
        "/v1/evidence/upload": connector_upload_commercial.upload_commercial_evidence_file,
        "/v1/evidence/upload-stream": connector_stream_secure.upload_stream_secure,
        "/v1/connectors/connections/{connection_id}/upload": connector_connection_upload_secure.upload_connection_stream,
        "/v1/connectors/connections/{connection_id}/upload-stream": connector_connection_upload_secure.upload_connection_stream,
    }
    for path, endpoint in expected.items():
        routes = _post_routes(path)
        assert len(routes) == 1, {"path": path, "count": len(routes)}
        assert routes[0].endpoint is endpoint
