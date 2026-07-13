from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.connector_security import ConnectorCredential
from app.models.operational_records import ConnectorConnection
from app.models.platform_api import ApiProject, ApiServiceAccount
from app.platform_api.principal import PlatformPrincipal
from app.services.connector_vault import (
    ALGORITHM,
    credential_reference,
    load_connector_credentials,
    revoke_connector_credentials,
    store_connector_credentials,
    vault_configured,
)


DEFAULT_SECRET_TYPE = "provider_credentials"


@dataclass(frozen=True)
class CredentialVaultContext:
    principal: PlatformPrincipal
    provider_job_authorized: bool
    connection_id: str
    provider: str
    secret_type: str = DEFAULT_SECRET_TYPE


def production_vault_keyring_configured() -> bool:
    """Return whether the shared connector AES-GCM vault can fail closed."""

    return vault_configured()


def _provider_allowed(principal: PlatformPrincipal, provider: str) -> bool:
    allow = principal.provider_restrictions.get("allow") if isinstance(principal.provider_restrictions, dict) else None
    if allow is None:
        return True
    return provider in set(allow)


def _load_connection(db: Session, *, organization_id: str, connection_id: str, provider: str) -> ConnectorConnection:
    row = db.query(ConnectorConnection).filter(
        ConnectorConnection.id == connection_id,
        ConnectorConnection.tenant_id == organization_id,
        ConnectorConnection.provider == provider,
    ).first()
    if row is None:
        raise PermissionError("connector credential custody denied")
    if row.status in {"disabled", "revoked"}:
        raise PermissionError("connector credential custody denied")
    return row


def _assert_project_context(db: Session, *, principal: PlatformPrincipal, connection: ConnectorConnection) -> None:
    if not principal.api_project_id:
        raise PermissionError("api project principal is required")
    project = db.query(ApiProject).filter(
        ApiProject.id == principal.api_project_id,
        ApiProject.organization_id == principal.organization_id,
    ).first()
    if project is None or project.status != "active":
        raise PermissionError("api project principal is invalid")
    if project.workspace_id and connection.workspace_id and project.workspace_id != connection.workspace_id:
        raise PermissionError("workspace custody denied")
    config = connection.config_json or {}
    bound_project_id = config.get("platform_api_project_id")
    if bound_project_id and bound_project_id != principal.api_project_id:
        raise PermissionError("api project custody denied")


def _assert_service_account_context(db: Session, *, principal: PlatformPrincipal) -> None:
    if not principal.service_account_id:
        raise PermissionError("service account principal is required")
    service_account = db.query(ApiServiceAccount).filter(
        ApiServiceAccount.id == principal.service_account_id,
        ApiServiceAccount.organization_id == principal.organization_id,
        ApiServiceAccount.api_project_id == principal.api_project_id,
    ).first()
    if service_account is None or service_account.status != "active":
        raise PermissionError("service account principal is invalid")
    if "connectors:sync" not in set(service_account.scopes or []) or not principal.has_scope("connectors:sync"):
        raise PermissionError("connectors:sync scope is required")


def _assert_retrieval_authorized(db: Session, context: CredentialVaultContext) -> ConnectorConnection:
    principal = context.principal
    if principal.authentication_type != "platform_api_key":
        raise PermissionError("platform api key principal is required")
    if not context.provider_job_authorized:
        raise PermissionError("connector credentials may only be decrypted by authorized provider jobs")
    if not principal.organization_id:
        raise PermissionError("organization principal is required")
    if not _provider_allowed(principal, context.provider):
        raise PermissionError("provider custody denied")
    connection = _load_connection(
        db,
        organization_id=principal.organization_id,
        connection_id=context.connection_id,
        provider=context.provider,
    )
    if principal.workspace_id and connection.workspace_id and principal.workspace_id != connection.workspace_id:
        raise PermissionError("workspace custody denied")
    config = connection.config_json or {}
    if config.get("platform_api_secret_type", DEFAULT_SECRET_TYPE) != context.secret_type:
        raise PermissionError("secret type custody denied")
    _assert_project_context(db, principal=principal, connection=connection)
    _assert_service_account_context(db, principal=principal)
    return connection


def store_platform_connector_secret(
    db: Session,
    *,
    organization_id: str,
    api_project_id: str,
    connection: ConnectorConnection,
    provider: str,
    payload: dict[str, Any],
    secret_type: str = DEFAULT_SECRET_TYPE,
    token_expires_at: datetime | None = None,
    scopes: list[str] | None = None,
) -> ConnectorCredential:
    if connection.tenant_id != organization_id or connection.provider != provider:
        raise ValueError("connector credential ownership mismatch")
    config = dict(connection.config_json or {})
    config["platform_api_project_id"] = api_project_id
    config["platform_api_secret_type"] = secret_type
    connection.config_json = config
    return store_connector_credentials(
        db,
        tenant_id=organization_id,
        connection=connection,
        provider=provider,
        payload=payload,
        token_expires_at=token_expires_at,
        scopes=scopes,
    )


def retrieve_platform_connector_secret(db: Session, *, context: CredentialVaultContext) -> dict[str, Any]:
    connection = _assert_retrieval_authorized(db, context)
    return load_connector_credentials(db, tenant_id=connection.tenant_id, connection_id=connection.id)


def rotate_platform_connector_secret(
    db: Session,
    *,
    organization_id: str,
    api_project_id: str,
    connection: ConnectorConnection,
    provider: str,
    payload: dict[str, Any],
    secret_type: str = DEFAULT_SECRET_TYPE,
) -> ConnectorCredential:
    return store_platform_connector_secret(
        db,
        organization_id=organization_id,
        api_project_id=api_project_id,
        connection=connection,
        provider=provider,
        payload=payload,
        secret_type=secret_type,
    )


def revoke_platform_connector_secret(db: Session, *, organization_id: str, connection_id: str) -> bool:
    return revoke_connector_credentials(db, tenant_id=organization_id, connection_id=connection_id)


def inspect_platform_connector_secret(db: Session, *, organization_id: str, connection_id: str) -> dict[str, Any]:
    row = db.query(ConnectorCredential).filter(
        ConnectorCredential.tenant_id == organization_id,
        ConnectorCredential.connection_id == connection_id,
    ).first()
    if row is None:
        raise LookupError("connector credential metadata not found")
    return {
        "id": row.id,
        "credential_ref": credential_reference(row),
        "provider": row.provider,
        "algorithm": row.algorithm or ALGORITHM,
        "key_version": row.key_version,
        "token_expires_at": row.token_expires_at.isoformat() if row.token_expires_at else None,
        "scopes": list(row.scopes_json or []),
        "revoked": row.revoked_at is not None,
    }
