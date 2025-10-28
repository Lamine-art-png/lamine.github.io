"""API Key management service for tenant authentication."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.api_key import APIKey
from app.models.tenant import Tenant
from app.services.audit import AuditService


class APIKeyService:
    """Manage API keys for tenant authentication and authorization."""

    @staticmethod
    def generate_key() -> Tuple[str, str, str]:
        """
        Generate a new API key.

        Returns:
            Tuple of (full_key, key_hash, key_prefix)
        """
        # Generate 32-byte random key
        key_bytes = secrets.token_bytes(32)
        full_key = f"agro_{key_bytes.hex()}"

        # Hash for storage
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()

        # Prefix for identification (first 12 chars after agro_)
        key_prefix = full_key[:17]  # "agro_" + 12 chars

        return full_key, key_hash, key_prefix

    @staticmethod
    def create_api_key(
        db: Session,
        tenant_id: str,
        name: str,
        role: str = "analyst",
        field_restrictions: Optional[List[str]] = None,
        expires_days: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> Tuple[APIKey, str]:
        """
        Create a new API key for a tenant.

        Args:
            db: Database session
            tenant_id: Tenant ID
            name: Human-readable name for the key
            role: Role (owner, analyst, viewer)
            field_restrictions: Optional list of field IDs this key can access
            expires_days: Optional expiration in days (None = no expiration)
            created_by: Who created the key

        Returns:
            Tuple of (APIKey object, actual key string)
        """
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Validate role
        valid_roles = ["owner", "analyst", "viewer"]
        if role not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {valid_roles}")

        # Generate key
        full_key, key_hash, key_prefix = APIKeyService.generate_key()

        # Calculate expiration
        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        # Create API key record
        api_key = APIKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            role=role,
            field_restrictions=field_restrictions,
            active=True,
            created_at=datetime.utcnow(),
            created_by=created_by,
            expires_at=expires_at,
        )

        db.add(api_key)
        db.commit()
        db.refresh(api_key)

        # Audit log
        AuditService.log(
            db=db,
            tenant_id=tenant_id,
            action="create_api_key",
            resource_type="api_key",
            resource_id=api_key.id,
            actor=created_by,
            status="success",
            details={
                "name": name,
                "role": role,
                "key_prefix": key_prefix,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        )

        return api_key, full_key

    @staticmethod
    def verify_api_key(db: Session, api_key: str) -> Optional[APIKey]:
        """
        Verify an API key and return the associated APIKey object.

        Args:
            db: Database session
            api_key: The full API key string

        Returns:
            APIKey object if valid, None otherwise
        """
        # Hash the provided key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Look up key
        key_obj = db.query(APIKey).filter(
            and_(
                APIKey.key_hash == key_hash,
                APIKey.active == True,
            )
        ).first()

        if not key_obj:
            return None

        # Check expiration
        if key_obj.expires_at and key_obj.expires_at < datetime.utcnow():
            return None

        # Update usage tracking
        key_obj.last_used_at = datetime.utcnow()
        key_obj.usage_count = str(int(key_obj.usage_count or "0") + 1)
        db.commit()

        return key_obj

    @staticmethod
    def revoke_api_key(
        db: Session,
        api_key_id: str,
        revoked_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Revoke an API key.

        Args:
            db: Database session
            api_key_id: ID of API key to revoke
            revoked_by: Who revoked the key
            reason: Reason for revocation

        Returns:
            True if revoked, False if not found
        """
        api_key = db.query(APIKey).filter(APIKey.id == api_key_id).first()

        if not api_key:
            return False

        api_key.active = False
        api_key.revoked_at = datetime.utcnow()
        api_key.revoked_by = revoked_by
        api_key.revoke_reason = reason

        db.commit()

        # Audit log
        AuditService.log(
            db=db,
            tenant_id=api_key.tenant_id,
            action="revoke_api_key",
            resource_type="api_key",
            resource_id=api_key_id,
            actor=revoked_by,
            status="success",
            details={
                "name": api_key.name,
                "key_prefix": api_key.key_prefix,
                "reason": reason,
            }
        )

        return True

    @staticmethod
    def list_api_keys(
        db: Session,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[APIKey]:
        """
        List API keys for a tenant.

        Args:
            db: Database session
            tenant_id: Tenant ID
            active_only: Only return active keys

        Returns:
            List of APIKey objects
        """
        query = db.query(APIKey).filter(APIKey.tenant_id == tenant_id)

        if active_only:
            query = query.filter(APIKey.active == True)

        return query.order_by(APIKey.created_at.desc()).all()

    @staticmethod
    def rotate_api_key(
        db: Session,
        api_key_id: str,
        rotated_by: Optional[str] = None,
    ) -> Tuple[APIKey, str]:
        """
        Rotate an API key (revoke old, create new).

        Args:
            db: Database session
            api_key_id: ID of API key to rotate
            rotated_by: Who initiated rotation

        Returns:
            Tuple of (new APIKey object, actual new key string)
        """
        old_key = db.query(APIKey).filter(APIKey.id == api_key_id).first()

        if not old_key:
            raise ValueError(f"API key {api_key_id} not found")

        # Revoke old key
        APIKeyService.revoke_api_key(
            db=db,
            api_key_id=api_key_id,
            revoked_by=rotated_by,
            reason="rotated"
        )

        # Create new key with same properties
        new_key, full_key = APIKeyService.create_api_key(
            db=db,
            tenant_id=old_key.tenant_id,
            name=f"{old_key.name} (rotated)",
            role=old_key.role,
            field_restrictions=old_key.field_restrictions,
            expires_days=(old_key.expires_at - datetime.utcnow()).days if old_key.expires_at else None,
            created_by=rotated_by,
        )

        return new_key, full_key
