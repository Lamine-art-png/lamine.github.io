from __future__ import annotations

from typing import Mapping

import sqlalchemy as sa


HEAD_ALEMBIC_REVISION = "026_platform_api_operations"


HEAD_SCHEMA_REQUIREMENTS: dict[str, set[str]] = {
    "compliance_export_metadata": {"id", "tenant_id"},
    "assurance_passports": {"id"},
    "agent_workflow_runs": {"id"},
    "users": {
        "id",
        "email",
        "credentials_changed_at",
        "account_status",
        "failed_login_attempts",
        "locked_until",
        "access_restriction_reason",
        "access_restricted_at",
    },
    "organizations": {"id", "owner_user_id", "verification_status", "verification_score", "verification_engine_version"},
    "workspaces": {"id", "organization_id"},
    "organization_memberships": {"id", "organization_id", "user_id", "role", "status"},
    "organization_verification_profiles": {"id", "organization_id", "decision", "score", "phone_ciphertext_b64", "evidence_digest"},
    "security_audit_events": {"id", "event_type", "outcome", "subject_hash", "ip_hash", "created_at"},
    "account_access_appeals": {
        "id",
        "user_id",
        "token_hash",
        "token_expires_at",
        "status",
        "submitted_at",
        "reviewed_at",
        "created_at",
    },
    "conversations": {"id", "organization_id", "user_id"},
    "conversation_messages": {"id", "conversation_id", "organization_id"},
    "email_verification_tokens": {"id", "user_id", "token_hash"},
    "team_invitations": {"id", "organization_id", "token_hash"},
    "telemetry": {"id", "tenant_id", "block_id"},
    "recommendations": {"id", "tenant_id", "block_id"},
    "account_recovery_tokens": {"id", "user_id", "token_hash", "expires_at", "used_at"},
    "user_preferences": {"user_id", "locale", "updated_at"},
    "connector_connections": {"id", "tenant_id", "provider", "config_json"},
    "data_sources": {"id", "tenant_id", "provider", "metadata_json", "content_sha256"},
    "ingestion_jobs": {"id", "tenant_id", "status", "input_json", "output_json", "idempotency_key", "attempt_count"},
    "evidence_records": {"id", "tenant_id", "evidence_type", "value_json", "source_updated_at"},
    "intelligence_runs": {"id", "tenant_id", "run_type", "output_json", "provenance_json", "freshness_json"},
    "generated_artifacts": {"id", "tenant_id", "artifact_type"},
    "chat_conversations": {"id", "tenant_id", "status", "last_message_at"},
    "chat_messages": {"id", "conversation_id", "tenant_id", "content"},
    "oauth_state_nonces": {"id", "tenant_id", "connection_id", "nonce_hash", "consumed_at"},
    "connector_credentials": {"id", "tenant_id", "connection_id", "key_version", "ciphertext_b64"},
    "task_outbox": {"id", "job_id", "tenant_id", "status", "publish_attempts"},
    "api_projects": {"id", "organization_id", "workspace_id", "environment", "status"},
    "api_service_accounts": {"id", "organization_id", "api_project_id", "workspace_id", "status"},
    "platform_api_keys": {"id", "organization_id", "api_project_id", "service_account_id", "workspace_id", "cidr_allowlist_json"},
    "platform_idempotency_records": {"id", "organization_id", "api_project_id", "operation", "idempotency_key", "request_hash", "status"},
    "platform_webhook_endpoints": {
        "id",
        "organization_id",
        "api_project_id",
        "signing_secret_key_version",
        "signing_secret_nonce_b64",
        "signing_secret_ciphertext_b64",
        "revoked_at",
    },
    "platform_webhook_events": {"id", "organization_id", "api_project_id", "event_type", "version"},
    "platform_webhook_delivery_attempts": {"id", "event_id", "endpoint_id", "attempt_number", "status"},
    "platform_webhook_outbox": {"id", "organization_id", "api_project_id", "event_id", "endpoint_id", "status"},
    "platform_webhook_audit_events": {"id", "organization_id", "api_project_id", "endpoint_id", "action"},
    "field_capture_sessions": {
        "id", "tenant_id", "workspace_id", "user_id", "client_capture_id",
        "idempotency_key", "status", "asset_manifest_json", "metadata_json",
    },
    "field_observations": {
        "id", "tenant_id", "workspace_id", "capture_session_id", "status",
        "structured_json", "confidence", "provenance_json",
    },
    "field_observation_assets": {
        "id", "tenant_id", "capture_session_id", "client_asset_id", "object_ref",
        "content_sha256", "status",
    },
    "field_observation_processing_runs": {
        "id", "tenant_id", "capture_session_id", "stage", "status", "attempt_count",
    },
    "field_observation_audit_events": {
        "id", "tenant_id", "capture_session_id", "action", "created_at",
    },
    "field_storage_reservations": {
        "id", "tenant_id", "capture_session_id", "size_bytes", "expires_at",
    },
    "platform_api_applications": {"id", "organization_id", "applicant_user_id", "application_type", "status"},
    "platform_program_enrollments": {"id", "organization_id", "program", "status", "allowed_environments_json"},
    "platform_live_access_requests": {"id", "organization_id", "requested_by_user_id", "status"},
    "platform_partner_dossiers": {"id", "organization_id", "provider_id", "production_readiness"},
    "platform_product_audit_events": {"id", "organization_id", "event_type", "subject_type", "subject_id"},
    "platform_terms_documents": {"id", "document_type", "version", "status"},
    "platform_terms_acceptances": {"id", "organization_id", "user_id", "document_id", "accepted_at"},
    "platform_api_plans": {"id", "catalog_version", "plan_identifier", "active", "included_credits"},
    "platform_api_operation_costs": {"id", "catalog_version", "operation_id", "environment", "credits"},
    "platform_api_subscriptions": {"id", "organization_id", "plan_id", "status", "status_slot"},
    "platform_credit_reservations": {"id", "organization_id", "api_project_id", "logical_operation_id", "state"},
    "platform_stripe_meter_outbox": {"id", "organization_id", "usage_event_id", "meter_event_identifier", "status"},
    "platform_stripe_events": {"id", "stripe_event_id", "event_type", "status"},
    "platform_request_logs": {"id", "organization_id", "api_project_id", "request_id", "operation_id"},
    "platform_notifications": {"id", "organization_id", "notification_type", "dedupe_key", "status"},
    "platform_sandbox_states": {"id", "organization_id", "api_project_id", "fixture_version", "reset_counter"},
    "platform_support_requests": {"id", "organization_id", "category", "severity", "status"},
    "platform_support_messages": {"id", "support_request_id", "visibility", "body"},
    "platform_status_components": {"id", "component_key", "status", "public"},
    "platform_status_incidents": {"id", "status", "severity", "public_summary"},
    "platform_status_incident_updates": {"id", "incident_id", "status", "public_message"},
    "platform_abuse_events": {"id", "organization_id", "signal_type", "status"},
}


def schema_contract_gaps(
    connection,
    requirements: Mapping[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    required = requirements or HEAD_SCHEMA_REQUIREMENTS
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    gaps: dict[str, list[str]] = {}
    for table, columns in required.items():
        if table not in tables:
            gaps[table] = sorted(columns)
            continue
        actual = {item["name"] for item in inspector.get_columns(table)}
        missing = columns - actual
        if missing:
            gaps[table] = sorted(missing)
    return gaps


def schema_matches_head_contract(connection) -> bool:
    return not schema_contract_gaps(connection)


def has_any_managed_schema(connection) -> bool:
    tables = set(sa.inspect(connection).get_table_names())
    return bool(tables.intersection(HEAD_SCHEMA_REQUIREMENTS))
