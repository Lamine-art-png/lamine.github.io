from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.platform_api import ApiProject, ApiServiceAccount, PlatformApiKey
from app.models.saas import Organization
from app.platform_api.client_ip import normalize_cidr_allowlist
from app.platform_api.isolation import assert_key_lineage, compatible_workspace_id
from app.platform_api.scopes import normalize_scopes
from app.platform_api.restrictions import narrow_restrictions


KEY_PREFIXES = {"test": "agro_test_", "live": "agro_live_"}


@dataclass(frozen=True)
class VerifiedPlatformKey:
    key: PlatformApiKey
    project: ApiProject
    service_account: ApiServiceAccount


def _pepper() -> bytes:
    configured = str(getattr(settings, "PLATFORM_API_KEY_PEPPER", "") or "").strip()
    if configured:
        return configured.encode("utf-8")
    if str(getattr(settings, "APP_ENV", "development")).lower() == "production":
        raise RuntimeError("PLATFORM_API_KEY_PEPPER is required in production")
    return str(getattr(settings, "SECRET_KEY", "development-secret")).encode("utf-8")


def _digest(secret: str) -> str:
    return hmac.new(_pepper(), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def fingerprint(secret: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"{digest[:8]}...{digest[-8:]}"


def generate_plaintext_key(environment: str) -> tuple[str, str, str, str]:
    prefix = KEY_PREFIXES[environment]
    token = secrets.token_urlsafe(36).replace("-", "").replace("_", "")
    plaintext = f"{prefix}{token}"
    return plaintext, _digest(plaintext), plaintext[:22], fingerprint(plaintext)


def create_platform_key(
    db: Session,
    *,
    project: ApiProject,
    service_account: ApiServiceAccount,
    name: str,
    scopes: list[str],
    created_by_user_id: str | None,
    expires_days: int | None = None,
    workspace_id: str | None = None,
    cidr_allowlist: list[str] | None = None,
    provider_restrictions: dict[str, Any] | None = None,
    resource_restrictions: dict[str, Any] | None = None,
) -> tuple[PlatformApiKey, str]:
    resolved_workspace_id = compatible_workspace_id(
        db,
        organization_id=project.organization_id,
        project=project,
        service_account=service_account,
        supplied_workspace_id=workspace_id,
    )
    normalized_scopes = normalize_scopes(scopes)
    if not set(normalized_scopes).issubset(set(service_account.scopes or [])):
        raise ValueError("API key scopes must be a subset of service account scopes")
    normalized_cidrs = normalize_cidr_allowlist(cidr_allowlist)
    plaintext, key_hash, key_prefix, safe_fingerprint = generate_plaintext_key(project.environment)
    now = datetime.utcnow()
    row = PlatformApiKey(
        organization_id=project.organization_id,
        api_project_id=project.id,
        service_account_id=service_account.id,
        workspace_id=resolved_workspace_id,
        name=name,
        environment=project.environment,
        scopes=normalized_scopes,
        status="active",
        key_hash=key_hash,
        key_prefix=key_prefix,
        fingerprint=safe_fingerprint,
        cidr_allowlist_json=normalized_cidrs,
        provider_restrictions_json=narrow_restrictions(
            dict(service_account.provider_restrictions_json or {}),
            provider_restrictions,
        ),
        resource_restrictions_json=narrow_restrictions(
            dict(service_account.resource_restrictions_json or {}),
            resource_restrictions,
        ),
        expires_at=now + timedelta(days=expires_days) if expires_days else None,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row, plaintext


def verify_platform_key(db: Session, plaintext: str) -> VerifiedPlatformKey | None:
    if not plaintext.startswith(("agro_test_", "agro_live_")):
        return None
    key_hash = _digest(plaintext)
    row = db.query(PlatformApiKey).filter(PlatformApiKey.key_hash == key_hash).first()
    if row is None or row.status != "active" or row.revoked_at is not None:
        return None
    now = datetime.utcnow()
    if row.expires_at and row.expires_at <= now:
        return None
    if row.overlap_expires_at and row.overlap_expires_at <= now:
        return None
    project = db.get(ApiProject, row.api_project_id)
    if project is None or project.status != "active":
        return None
    if project.environment != row.environment:
        return None
    service_account = db.get(ApiServiceAccount, row.service_account_id)
    if service_account is None or service_account.status != "active":
        return None
    if service_account.organization_id != row.organization_id or service_account.api_project_id != row.api_project_id:
        return None
    if not set(row.scopes or []).issubset(set(service_account.scopes or [])):
        return None
    if narrow_restrictions(
        dict(service_account.provider_restrictions_json or {}),
        dict(row.provider_restrictions_json or {}),
    ) != dict(row.provider_restrictions_json or {}):
        return None
    if narrow_restrictions(
        dict(service_account.resource_restrictions_json or {}),
        dict(row.resource_restrictions_json or {}),
    ) != dict(row.resource_restrictions_json or {}):
        return None
    try:
        assert_key_lineage(db, key=row, project=project, service_account=service_account)
    except ValueError:
        return None
    org = db.get(Organization, row.organization_id)
    if org is None:
        return None
    return VerifiedPlatformKey(key=row, project=project, service_account=service_account)


def rotate_platform_key(
    db: Session,
    *,
    old_key: PlatformApiKey,
    overlap_minutes: int,
    rotated_by_user_id: str | None,
) -> tuple[PlatformApiKey, str]:
    project = db.get(ApiProject, old_key.api_project_id)
    service_account = db.get(ApiServiceAccount, old_key.service_account_id)
    if project is None or service_account is None:
        raise ValueError("key ownership is incomplete")
    now = datetime.utcnow()
    if old_key.status != "active" or old_key.revoked_at is not None:
        raise ValueError("only an active, unrevoked key can be rotated")
    if old_key.expires_at is not None and old_key.expires_at <= now:
        raise ValueError("an expired key cannot be rotated")
    if old_key.overlap_expires_at is not None:
        raise ValueError("a key that has already entered rotation overlap cannot be rotated again")
    if project.status != "active":
        raise ValueError("an inactive API project cannot rotate keys")
    if service_account.status != "active":
        raise ValueError("an inactive service account cannot rotate keys")
    assert_key_lineage(db, key=old_key, project=project, service_account=service_account)
    old_key.overlap_expires_at = now + timedelta(minutes=max(0, overlap_minutes))
    old_key.updated_at = now
    new_key, plaintext = create_platform_key(
        db,
        project=project,
        service_account=service_account,
        name=f"{old_key.name} rotation",
        scopes=list(old_key.scopes or []),
        created_by_user_id=rotated_by_user_id,
        expires_days=None,
        workspace_id=old_key.workspace_id,
        cidr_allowlist=list(old_key.cidr_allowlist_json or []),
        provider_restrictions=dict(old_key.provider_restrictions_json or {}),
        resource_restrictions=dict(old_key.resource_restrictions_json or {}),
    )
    new_key.rotate_after_key_id = old_key.id
    new_key.expires_at = old_key.expires_at
    return new_key, plaintext
