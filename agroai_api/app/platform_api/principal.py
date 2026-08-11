from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AuthenticationType = Literal["portal_user", "platform_api_key", "internal_service", "platform_admin"]


@dataclass(frozen=True)
class PlatformPrincipal:
    authentication_type: AuthenticationType
    organization_id: str | None = None
    workspace_id: str | None = None
    api_project_id: str | None = None
    user_id: str | None = None
    service_account_id: str | None = None
    api_key_id: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    environment: str | None = None
    request_id: str | None = None
    client_correlation_id: str | None = None
    billing_operation_id: str | None = None
    resource_restrictions: dict[str, Any] = field(default_factory=dict)
    provider_restrictions: dict[str, Any] = field(default_factory=dict)
    actor_metadata: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes
