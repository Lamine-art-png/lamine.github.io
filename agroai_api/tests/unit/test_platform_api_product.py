from __future__ import annotations

from datetime import datetime, timedelta

from app.api.v1 import platform_access, platform_operations
from app.api.v1.platform_api import platform_openapi
from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import (
    PlatformAbuseEvent,
    PlatformApiApplication,
    PlatformApiOperationCost,
    PlatformCreditReservation,
    PlatformNotification,
    PlatformProductAuditEvent,
    PlatformProgramEnrollment,
    PlatformTermsAcceptance,
    PlatformTermsDocument,
)
from app.platform_api.credits import commit_credits, reserve_credits
from app.platform_api.notifications import process_key_expiration_notifications
from app.platform_api.principal import PlatformPrincipal
from app.platform_api.route_manifest import public_routes
from app.platform_api.sandbox import sandbox_dataset
from app.services.object_storage import StoredObject
from tests.unit.test_platform_api_foundation import _project_and_key


def _application_payload(email: str, application_type: str = "developer_beta") -> dict:
    payload = {
        "application_type": application_type,
        "organization_website": "https://example-agtech.test",
        "corporate_email": email,
        "company_description": "An agriculture software organization building verified field workflows.",
        "intended_product": "A field operations product with recommendations and reporting.",
        "use_case": "Synchronize field data and request evidence-backed recommendations.",
        "target_users": "Agronomists and enterprise farm operators",
        "expected_api_operations": ["fields.read", "recommendations.create"],
        "expected_monthly_volume": "100000 requests",
        "expected_data_volume": "20 GB",
        "requested_environment": "test",
        "required_providers": [],
        "geography": ["United States"],
        "security_contact": email,
        "technical_contact": email,
        "billing_contact": email,
        "requested_support": "documentation",
        "terms_version": "draft-2026-07",
        "privacy_version": "draft-2026-07",
        "document_references": [],
        "bot_field": "",
    }
    if application_type == "strategic_partner":
        payload.update(
            {
                "provider_company": "Example Controller Co",
                "integration_category": "controller_manufacturer",
                "contract_status": "awaiting_partner_contract",
            }
        )
    return payload


def test_new_product_flags_are_all_disabled_by_default():
    names = {
        "PLATFORM_API_MARKETING_ENABLED",
        "PLATFORM_API_APPLICATIONS_ENABLED",
        "PLATFORM_API_PRIVATE_BETA_ENABLED",
        "PLATFORM_API_PARTNER_PROGRAM_ENABLED",
        "PLATFORM_API_SELF_SERVICE_SANDBOX_ENABLED",
        "PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED",
        "PLATFORM_API_BILLING_ENABLED",
        "PLATFORM_API_STRIPE_CHECKOUT_ENABLED",
        "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED",
        "PLATFORM_API_PRICING_ENABLED",
        "PLATFORM_API_SDK_DOWNLOADS_ENABLED",
        "PLATFORM_API_STATUS_PAGE_ENABLED",
        "PLATFORM_API_SUPPORT_ENABLED",
        "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED",
        "PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED",
    }
    assert all(getattr(settings, name) is False for name in names)


def test_application_submit_review_enrollment_email_dedupe_and_audit(client, db, monkeypatch):
    user, organization, _workspace, _project, _service_account, _key, _plaintext = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATIONS_ENABLED", True)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}

    submitted = client.post("/v1/platform/applications", headers=headers, json=_application_payload(user.email))
    assert submitted.status_code == 202
    application_id = submitted.json()["application"]["id"]
    assert db.query(PlatformApiApplication).filter_by(id=application_id, status="submitted").one()

    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", user.email)
    needs_information = client.post(
        f"/v1/platform/admin/applications/{application_id}/review",
        headers=headers,
        json={
            "status": "needs_information",
            "reason": "Clarify the expected integration deployment model.",
        },
    )
    assert needs_information.status_code == 200
    additional_information = client.post(
        f"/v1/platform/applications/{application_id}/additional-information",
        headers=headers,
        json={
            "notes": "The integration will run as a server-side service in our managed cloud account.",
            "document_references": [],
        },
    )
    assert additional_information.status_code == 202
    assert additional_information.json()["application"]["status"] == "submitted"

    reviewed = client.post(
        f"/v1/platform/admin/applications/{application_id}/review",
        headers=headers,
        json={
            "status": "approved",
            "reason": "Technical review completed for test access.",
            "program": "developer_private_beta",
            "allowed_environments": ["test"],
            "maximum_projects": 1,
            "maximum_live_projects": 0,
            "maximum_service_accounts": 2,
            "maximum_keys": 2,
            "maximum_webhooks": 1,
            "billing_mode": "none",
            "support_tier": "documentation",
        },
    )
    assert reviewed.status_code == 200
    enrollment = db.query(PlatformProgramEnrollment).filter_by(organization_id=organization.id, program="developer_private_beta").one()
    assert enrollment.status == "active"
    assert enrollment.allowed_environments_json == ["test"]
    assert db.query(PlatformProductAuditEvent).filter_by(subject_id=application_id).count() >= 2


def test_application_isolation_and_spam_limit(client, db, monkeypatch):
    first_user, first_org, *_ = _project_and_key(db)
    second_user, second_org, *_ = _project_and_key(db)
    first_org.verification_status = second_org.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATION_LIMIT_PER_DAY", 1)
    first_headers = {"Authorization": f"Bearer {create_access_token({'sub': first_user.id})}"}
    second_headers = {"Authorization": f"Bearer {create_access_token({'sub': second_user.id})}"}
    assert client.post("/v1/platform/applications", headers=first_headers, json=_application_payload(first_user.email)).status_code == 202
    assert client.post("/v1/platform/applications", headers=first_headers, json=_application_payload(first_user.email)).status_code == 429
    assert db.query(PlatformAbuseEvent).filter_by(
        organization_id=first_org.id,
        signal_type="application_spam_threshold",
        automated_action="throttle",
    ).count() == 1
    assert client.get("/v1/platform/applications", headers=second_headers).json()["applications"] == []


def test_strategic_partner_fields_and_truthful_contract_status(client, db, monkeypatch):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_PARTNER_PROGRAM_ENABLED", True)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}
    payload = _application_payload(user.email, "strategic_partner")
    response = client.post("/v1/platform/applications", headers=headers, json=payload)
    assert response.status_code == 202
    row = db.get(PlatformApiApplication, response.json()["application"]["id"])
    assert row.contract_status == "awaiting_partner_contract"


def test_live_access_is_review_gated_and_never_auto_approved(client, db, monkeypatch):
    user, organization, _workspace, project, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_LIVE_ACCESS_REQUESTS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_LIVE_AUTO_APPROVAL_ENABLED", False)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}
    response = client.post(
        "/v1/platform/live-access",
        headers=headers,
        json={
            "api_project_id": project.id,
            "intended_production_use": "Serve evidence-backed recommendations to approved enterprise operators.",
            "expected_users": "500",
            "expected_volume": "2 million credits monthly",
            "expected_peak_rate": "20 requests per second",
            "data_categories": ["field boundaries", "observations"],
            "provider_dependencies": [],
            "geographic_regions": ["California"],
            "security_contact": user.email,
            "incident_contact": user.email,
            "cidr_strategy": "Fixed corporate egress ranges",
            "data_retention": "30 days",
            "billing_plan": "developer",
        },
    )
    assert response.status_code == 202
    request_id = response.json()["live_access_request_id"]
    assert client.get("/v1/platform/live-access", headers=headers).json()["requests"][0]["status"] == "submitted"
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", user.email)
    reviewed = client.post(
        f"/v1/platform/admin/live-access/{request_id}/review",
        headers=headers,
        json={"status": "approved", "reason": "Security and production review completed.", "conditions": ["read-only provider access"]},
    )
    assert reviewed.status_code == 200
    enrollment = db.query(PlatformProgramEnrollment).filter_by(organization_id=organization.id).first()
    assert "live" in enrollment.allowed_environments_json


def test_program_suspension_immediately_invalidates_existing_key(client, db, monkeypatch):
    _user, organization, _workspace, _project, _service_account, _key, plaintext = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    headers = {"Authorization": f"Bearer {plaintext}"}
    assert client.get("/v1/platform/me", headers=headers).status_code == 200
    enrollment = db.query(PlatformProgramEnrollment).filter_by(organization_id=organization.id).first()
    enrollment.status = "suspended"
    db.commit()
    denied = client.get("/v1/platform/me", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == "platform_api_entitlement_inactive"


def test_sandbox_is_deterministic_synthetic_and_never_executes(db):
    _user, _organization, _workspace, project, *_ = _project_and_key(db)
    first = sandbox_dataset(project)
    second = sandbox_dataset(project)
    assert first == second
    assert first["organization"]["synthetic"] is True
    assert all(item["provider_credentials"] is False for item in first["fields"])
    assert first["recommendations"][0]["physical_execution_enabled"] is False
    assert first["irrigation_systems"][0]["execution_enabled"] is False


def test_credit_reservation_and_usage_are_logical_operation_idempotent(db, monkeypatch):
    _user, organization, _workspace, project, _service_account, key, _plaintext = _project_and_key(db)
    db.add(
        PlatformApiOperationCost(
            catalog_version=settings.PLATFORM_API_OPERATION_COST_CATALOG_VERSION,
            operation_id="fields.create",
            operation_class="metadata_write",
            environment="test",
            credits=3,
            active=True,
            description="test",
        )
    )
    db.commit()
    principal = PlatformPrincipal(
        authentication_type="platform_api_key",
        organization_id=organization.id,
        api_project_id=project.id,
        service_account_id=key.service_account_id,
        api_key_id=key.id,
        environment="test",
        request_id="req_credit_test",
        scopes=frozenset({"fields:write"}),
    )
    first = reserve_credits(db, principal=principal, operation_id="fields.create", logical_operation_id="logical-1")
    second = reserve_credits(db, principal=principal, operation_id="fields.create", logical_operation_id="logical-1")
    assert first.id == second.id
    event = commit_credits(db, first, principal=principal, status_code=201)
    replay = commit_credits(db, first, principal=principal, status_code=201)
    db.commit()
    assert event.id == replay.id
    rows = db.query(PlatformCreditReservation).all()
    assert len(rows) == 1
    assert rows[0].logical_operation_id != "logical-1"


def test_terms_enforcement_is_user_scoped_for_console_and_org_scoped_for_keys(client, db, monkeypatch):
    user, organization, _workspace, _project, _service_account, _key, plaintext = _project_and_key(db)
    organization.verification_status = "approved"
    db.add(
        PlatformTermsDocument(
            document_type="api_terms",
            version="legal-approved-v1",
            status="approved_effective",
            content_digest="a" * 64,
            effective_at=datetime.utcnow() - timedelta(minutes=1),
            reacceptance_required=True,
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TERMS_ENFORCEMENT_ENABLED", True)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}

    denied = client.get("/v1/platform/developer/overview", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == "platform_terms_acceptance_required"

    accepted = client.post(
        "/v1/platform/terms/accept",
        headers=headers,
        json={"document_type": "api_terms", "document_version": "legal-approved-v1"},
    )
    assert accepted.status_code == 200
    assert db.query(PlatformTermsAcceptance).filter_by(
        organization_id=organization.id,
        user_id=user.id,
        document_id=db.query(PlatformTermsDocument).filter_by(
            document_type="api_terms",
            version="legal-approved-v1",
        ).one().id,
        document_type="api_terms",
        document_version="legal-approved-v1",
    ).count() == 1
    assert client.get("/v1/platform/developer/overview", headers=headers).status_code == 200

    monkeypatch.setattr(settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_PRIVATE_BETA_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    assert client.get(
        "/v1/platform/me",
        headers={"Authorization": f"Bearer {plaintext}"},
    ).status_code == 200

    rejected = client.post(
        "/v1/platform/terms/accept",
        headers=headers,
        json={"document_type": "api_terms", "document_version": "draft-attacker-version"},
    )
    assert rejected.status_code == 422


def test_curated_openapi_contains_domain_contract_and_no_control_plane(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)
    document = platform_openapi()
    paths = document["paths"]
    assert "/platform/fields" in paths
    assert "/platform/sources/uploads" in paths
    assert "/platform/recommendations" in paths
    assert "/platform/usage" in paths
    assert all("/developer/" not in path and "/admin/" not in path and "/queue/" not in path for path in paths)
    assert document["components"]["securitySchemes"]["PlatformApiKey"]["scheme"] == "bearer"
    assert "StandardError" in document["components"]["schemas"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in paths["/platform/fields"]["post"]["parameters"])


def test_public_route_manifest_matches_fastapi_and_curated_openapi(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "PLATFORM_API_PUBLIC_DOCS_ENABLED", True)
    document = platform_openapi()
    fastapi_methods = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    for route in public_routes():
        method = route["method"]
        path = route["route"]
        openapi_path = path.removeprefix("/v1")
        assert (path, method) in fastapi_methods
        assert openapi_path in document["paths"]
        assert method.lower() in document["paths"][openapi_path]

    assert "202" in document["paths"]["/platform/providers/{provider_id}/sync"]["post"]["responses"]
    assert "202" in document["paths"]["/platform/observations"]["post"]["responses"]
    assert "202" in document["paths"]["/platform/recommendations"]["post"]["responses"]
    assert "202" in document["paths"]["/platform/reports"]["post"]["responses"]
    assert (
        document["paths"]["/platform/providers/{provider_id}/sync"]["post"]["responses"]["202"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/JobResponse"
    )


def test_support_attachments_are_presigned_and_server_verified(client, db, monkeypatch):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_SUPPORT_ENABLED", True)

    class FakeStore:
        def create_presigned_upload(self, **kwargs):
            assert kwargs["tenant_id"] == organization.id
            assert kwargs["connection_id"] == "platform-support"
            return (
                "https://storage.test/presigned",
                f"s3://test/platform-support/{organization.id}/attachment.pdf",
                {"x-amz-meta-sha256": kwargs["expected_sha256"]},
            )

        def inspect(self, uri, **kwargs):
            if "foreign" in uri:
                raise ValueError("outside tenant namespace")
            assert kwargs["tenant_id"] == organization.id
            assert kwargs["connection_id"] == "platform-support"
            return StoredObject(
                uri=uri,
                key="scoped-key",
                size_bytes=128,
                sha256="a" * 64,
                content_type="application/pdf",
            )

    monkeypatch.setattr(platform_operations, "object_storage_configured", lambda: True)
    monkeypatch.setattr(platform_operations, "get_object_store", lambda: FakeStore())
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}
    initiated = client.post(
        "/v1/platform/developer/support/attachments",
        headers=headers,
        json={
            "filename": "diagnostic.pdf",
            "content_type": "application/pdf",
            "sha256": "a" * 64,
            "size_bytes": 128,
        },
    )
    assert initiated.status_code == 201
    attachment = initiated.json()["attachment"]
    assert "url" not in attachment
    assert initiated.json()["upload"]["url"] == "https://storage.test/presigned"

    ticket = client.post(
        "/v1/platform/developer/support",
        headers=headers,
        json={
            "category": "integration",
            "severity": "normal",
            "subject": "Provider integration question",
            "description": "Please inspect the attached sanitized integration diagnostic.",
            "contact_email": user.email,
            "attachments": [attachment],
        },
    )
    assert ticket.status_code == 201
    assert ticket.json()["support_request"]["attachments"] == [attachment]

    foreign = {
        **attachment,
        "object_id": "s3://test/platform-support/foreign/attachment.pdf",
    }
    denied = client.post(
        "/v1/platform/developer/support",
        headers=headers,
        json={
            "category": "integration",
            "severity": "normal",
            "subject": "Foreign attachment",
            "description": "This reference must not cross organization boundaries.",
            "contact_email": user.email,
            "attachments": [foreign],
        },
    )
    assert denied.status_code == 422
    assert denied.json()["code"] == "support_attachment_invalid"


def test_key_expiration_notification_is_deduplicated_without_secret_material(db):
    _user, organization, _workspace, _project, _service_account, key, _plaintext = _project_and_key(db)
    key.expires_at = datetime.utcnow() + timedelta(days=3)
    db.commit()

    first = process_key_expiration_notifications(db)
    second = process_key_expiration_notifications(db)
    db.commit()

    assert first == {"eligible": 1, "created": 1}
    assert second == {"eligible": 1, "created": 0}
    notification = db.query(PlatformNotification).filter_by(
        organization_id=organization.id,
        notification_type="key_nearing_expiration",
    ).one()
    assert notification.safe_context_json == {
        "key_fingerprint": key.fingerprint,
        "expires_at": key.expires_at.isoformat(),
    }
    assert "key_hash" not in notification.safe_context_json


def test_application_documents_are_org_scoped_and_cannot_be_forged(client, db, monkeypatch):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_APPLICATIONS_ENABLED", True)

    class FakeStore:
        def create_presigned_upload(self, **kwargs):
            assert kwargs["tenant_id"] == organization.id
            assert kwargs["connection_id"] == "platform-applications"
            return (
                "https://storage.test/application-upload",
                f"s3://test/applications/{organization.id}/security.pdf",
                {"x-amz-meta-sha256": kwargs["expected_sha256"]},
            )

        def inspect(self, uri, **kwargs):
            if "foreign" in uri:
                raise ValueError("outside tenant namespace")
            assert kwargs["tenant_id"] == organization.id
            return StoredObject(
                uri=uri,
                key="scoped-application-document",
                size_bytes=256,
                sha256="b" * 64,
                content_type="application/pdf",
            )

    monkeypatch.setattr(platform_access, "object_storage_configured", lambda: True)
    monkeypatch.setattr(platform_access, "get_object_store", lambda: FakeStore())
    headers = {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}
    initiated = client.post(
        "/v1/platform/applications/documents",
        headers=headers,
        json={
            "filename": "security.pdf",
            "content_type": "application/pdf",
            "sha256": "b" * 64,
            "size_bytes": 256,
        },
    )
    assert initiated.status_code == 201
    document = initiated.json()["document"]
    payload = _application_payload(user.email)
    payload["document_references"] = [document]
    accepted = client.post("/v1/platform/applications", headers=headers, json=payload)
    assert accepted.status_code == 202

    forged_payload = _application_payload(user.email)
    forged_payload["document_references"] = [
        {**document, "object_id": "s3://test/applications/foreign/security.pdf"}
    ]
    denied = client.post("/v1/platform/applications", headers=headers, json=forged_payload)
    assert denied.status_code == 422
    assert denied.json()["code"] == "application_document_invalid"
