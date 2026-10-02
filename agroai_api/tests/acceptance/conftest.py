from __future__ import annotations

import pytest

from app.core.security import create_access_token


@pytest.fixture
def auth_headers(test_tenant):
    """Authenticate as the fixture tenant with a real signed bearer token.

    The acceptance suite previously sent no credentials and relied on the
    anonymous tenant fallback in get_current_tenant_id, which resolves to
    "test-tenant" only under APP_ENV=test and to "demo-tenant" otherwise, so
    the fixture block correctly returned 404 to the wrong tenant.
    """
    token = create_access_token({"sub": "acceptance-user", "tenant_id": test_tenant.id})
    return {"Authorization": f"Bearer {token}"}
