from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_demo_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """
    Simple API-key guard for evaluation endpoints.

    - If key is missing  -> 401
    - If key is wrong    -> 401
    """

    expected = settings.DEMO_API_KEY

    # You *want* this set in ECS env; if it's empty, treat as misconfigured.
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evaluation API key not configured",
        )

    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

async def get_api_key_context(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_organization_id: str | None = Header(None, alias="X-Organization-Id"),
):
    """Lightweight API-key context placeholder for routes that need tenant scoping.

    Full database validation is performed inside route dependencies that have a DB
    session. This helper documents the accepted headers and keeps compatibility
    with existing demo headers.
    """
    return {"api_key": x_api_key, "organization_id": x_organization_id}
