from __future__ import annotations

from fastapi import HTTPException, status

from app.platform_api.principal import PlatformPrincipal


def narrow_restrictions(parent: dict | None, child: dict | None) -> dict:
    parent = dict(parent or {})
    child = dict(child or {})
    if not parent:
        return child
    if not child:
        return parent
    result: dict = {}
    for key in set(parent) | set(child):
        parent_value = parent.get(key)
        child_value = child.get(key)
        if key.startswith("deny"):
            result[key] = sorted(set(parent_value or []) | set(child_value or []))
        elif isinstance(parent_value, list) and isinstance(child_value, list):
            result[key] = sorted(set(parent_value) & set(child_value))
        elif parent_value is not None:
            result[key] = parent_value
        else:
            result[key] = child_value
    return result


def _denied(principal: PlatformPrincipal, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": code,
            "type": "authorization_error",
            "message": message,
            "request_id": principal.request_id,
        },
    )


def provider_allowed(principal: PlatformPrincipal, provider_id: str) -> bool:
    restrictions = principal.provider_restrictions
    if not isinstance(restrictions, dict):
        return False
    allowed = restrictions.get("allow")
    denied = restrictions.get("deny", [])
    if provider_id in set(str(item) for item in denied or []):
        return False
    if allowed is None:
        return True
    return provider_id in set(str(item) for item in allowed or [])


def enforce_provider_access(principal: PlatformPrincipal, provider_id: str) -> None:
    if not provider_allowed(principal, provider_id):
        raise _denied(principal, "provider_restricted", "This API key is not permitted to access the requested provider.")


def enforce_resource_access(
    principal: PlatformPrincipal,
    *,
    resource_id: str | None,
    resource_type: str = "resource",
) -> None:
    restrictions = principal.resource_restrictions
    if not isinstance(restrictions, dict):
        raise _denied(principal, "resource_restricted", "This API key has invalid resource restrictions.")
    allow_keys = [
        key
        for key, value in restrictions.items()
        if key.endswith("_ids") and not key.startswith("deny") and isinstance(value, list)
    ]
    preferred = {"resource_ids", f"{resource_type}_ids"}
    if any(key in restrictions for key in preferred):
        allow_keys = [key for key in allow_keys if key in preferred]
    denied = {
        str(item)
        for key, values in restrictions.items()
        if key.startswith("deny") and key.endswith("_ids") and isinstance(values, list)
        for item in values
    }
    if resource_id and resource_id in denied:
        raise _denied(principal, "resource_restricted", "This API key is not permitted to access the requested resource.")
    if not allow_keys:
        return
    allowed = {
        str(item)
        for key in allow_keys
        for item in restrictions.get(key, [])
    }
    if resource_id is None or resource_id not in allowed:
        raise _denied(principal, "resource_restricted", "This API key is not permitted to access the requested resource.")
