from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.platform_api import ApiProject, PlatformIdempotencyRecord
from app.models.saas import Organization, User, Workspace
from app.platform_api.idempotency import begin_idempotent_operation, complete_idempotent_operation
from app.platform_api.principal import PlatformPrincipal


POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is not configured")


def test_postgres_atomic_claim_uses_two_independent_sessions_and_executes_once():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seed = Session()
    suffix = uuid.uuid4().hex
    user = User(
        email=f"platform-idempotency-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    seed.add(user)
    seed.flush()
    organization = Organization(
        name="Platform idempotency concurrency",
        slug=f"platform-idempotency-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    seed.add(organization)
    seed.flush()
    workspace = Workspace(organization_id=organization.id, name="Concurrency", mode="evaluation")
    seed.add(workspace)
    seed.flush()
    project = ApiProject(
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Concurrency",
        slug="concurrency",
        environment="test",
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=user.id,
    )
    seed.add(project)
    seed.commit()

    barrier = threading.Barrier(2)
    counter_lock = threading.Lock()
    executions = 0

    def request(request_id: str) -> str:
        nonlocal executions
        db = Session()
        principal = PlatformPrincipal(
            authentication_type="platform_api_key",
            organization_id=organization.id,
            api_project_id=project.id,
            request_id=request_id,
        )
        try:
            barrier.wait()
            try:
                row, replay = begin_idempotent_operation(
                    db,
                    principal=principal,
                    operation="physical-provider-write",
                    idempotency_key="same-request",
                    payload={"provider": "test", "resource_id": "resource-1"},
                )
            except HTTPException as exc:
                assert exc.status_code == 409
                assert exc.detail["code"] == "operation_in_progress"
                return "operation_in_progress"
            if replay:
                return "replayed"
            with counter_lock:
                executions += 1
            time.sleep(0.25)
            complete_idempotent_operation(row, response_status=200, response_json={"operation_id": "one"})
            db.commit()
            return "executed"
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ("request-a", "request-b")))
        verify = Session()
        try:
            count = (
                verify.query(PlatformIdempotencyRecord)
                .filter(
                    PlatformIdempotencyRecord.organization_id == organization.id,
                    PlatformIdempotencyRecord.api_project_id == project.id,
                    PlatformIdempotencyRecord.operation == "physical-provider-write",
                    PlatformIdempotencyRecord.idempotency_key == "same-request",
                )
                .count()
            )
        finally:
            verify.close()
        assert executions == 1
        assert "executed" in results
        assert set(results) in (
            {"executed", "replayed"},
            {"executed", "operation_in_progress"},
        )
        assert count == 1
    finally:
        cleanup = Session()
        try:
            cleanup.query(PlatformIdempotencyRecord).filter(
                PlatformIdempotencyRecord.organization_id == organization.id
            ).delete()
            cleanup.query(ApiProject).filter(ApiProject.organization_id == organization.id).delete()
            cleanup.query(Workspace).filter(Workspace.organization_id == organization.id).delete()
            cleanup.query(Organization).filter(Organization.id == organization.id).delete()
            cleanup.query(User).filter(User.id == user.id).delete()
            cleanup.commit()
        finally:
            cleanup.close()
            seed.close()
            engine.dispose()
