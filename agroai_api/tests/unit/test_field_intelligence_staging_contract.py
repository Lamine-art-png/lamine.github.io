"""Fail-closed Field Intelligence staging contracts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "agroai_api" / "scripts" / "field_intelligence_staging_contract.py"
WORKFLOW = REPO / ".github" / "workflows" / "field-intelligence-staging.yml"

BASE_ENV = {
    "FIELD_STAGING_API_URL": "https://agroai-api-staging.onrender.com",
    "FIELD_STAGING_PORTAL_URL": "https://field-intelligence-staging.agroai-portal-staging.pages.dev",
    "FIELD_STAGING_DATABASE_URL": "postgresql://staging@db-staging.internal:5432/agroai_staging",
    "FIELD_STAGING_DEPLOY_PROVIDER": "render",
    "FIELD_STAGING_API_SERVICE_ID": "srv-stage-api-123",
    "FIELD_STAGING_DEPLOY_HOOK": "https://api.render.com/deploy/srv-stage-api-123?key=redacted",
    "FIELD_STAGING_WORKER_MODE": "dedicated",
    "FIELD_STAGING_WORKER_SERVICE_ID": "srv-stage-worker-123",
    "FIELD_STAGING_WORKER_DEPLOY_HOOK": "https://api.render.com/deploy/srv-stage-worker-123?key=redacted",
    "FIELD_STAGING_OBJECT_STORAGE_BACKEND": "r2",
    "FIELD_STAGING_OBJECT_BUCKET": "agroai-field-staging",
    "FIELD_STAGING_OBJECT_ACCOUNT_ID": "stageacct123",
    "FIELD_STAGING_OBJECT_ENDPOINT_URL": "https://stageacct123.r2.cloudflarestorage.com",
    "FIELD_STAGING_R2_ACCESS_KEY_ID": "staging-key",
    "FIELD_STAGING_R2_SECRET_ACCESS_KEY": "staging-secret",
    "FIELD_STAGING_TRANSCRIPTION_PROVIDER": "openai_whisper",
    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://stt-staging.example/v1/audio/transcriptions",
    "FIELD_STAGING_TRANSCRIPTION_API_KEY": "staging-stt-key",
    "FIELD_STAGING_TRANSCRIPTION_MODEL": "whisper-1",
    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS": "org-staging-internal",
    "FIELD_STAGING_PORTAL_PROJECT": "agroai-portal-staging",
    "FIELD_STAGING_RELEASE_STATE": "internal",
    "PRODUCTION_DATABASE_RESOURCE_FINGERPRINT": "prod-db.internal:5432/agroai_production",
    "PRODUCTION_OBJECT_BUCKET_FINGERPRINT": "prodacct123:agroai-connectors",
    "PRODUCTION_API_SERVICE_ID": "srv-prod-api-123",
    "PRODUCTION_WORKER_SERVICE_ID": "srv-prod-worker-123",
    "PRODUCTION_PORTAL_PROJECT": "agroai-portal",
}


def run_contract(overrides: dict | None = None, removals: tuple = ()) -> tuple[int, dict]:
    env = {"PATH": os.environ.get("PATH", ""), **BASE_ENV, **(overrides or {})}
    for name in removals:
        env.pop(name, None)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(proc.stdout[proc.stdout.index("{"):]) if "{" in proc.stdout else {}
    return proc.returncode, payload


def test_valid_staging_configuration_passes():
    code, payload = run_contract()
    assert code == 0 and payload["ok"], payload
    assert payload["checks"]["database_fingerprint"] == "db-staging.internal:5432/agroai_staging"
    assert payload["checks"]["object_fingerprint"] == "stageacct123:agroai-field-staging"


def test_missing_required_fingerprints_fail_closed():
    code, payload = run_contract(removals=(
        "PRODUCTION_DATABASE_RESOURCE_FINGERPRINT",
        "PRODUCTION_OBJECT_BUCKET_FINGERPRINT",
        "PRODUCTION_API_SERVICE_ID",
    ))
    assert code == 1
    assert any("missing required staging configuration" in item for item in payload["failures"])


def test_production_application_hosts_are_refused():
    for hostname in (
        "api.agroai-pilot.com",
        "api-preview.agroai-pilot.com",
        "agroai-api-preview.onrender.com",
        "app.agroai-pilot.com",
    ):
        code, payload = run_contract({"FIELD_STAGING_API_URL": f"https://{hostname}"})
        assert code == 1, hostname
        assert any("PRODUCTION hostname" in item for item in payload["failures"])


def test_database_and_bucket_fingerprints_must_differ_from_production():
    code, payload = run_contract({
        "FIELD_STAGING_DATABASE_URL": "postgresql://u@prod-db.internal:5432/agroai_production",
    })
    assert code == 1
    assert any("database resource fingerprint equals production" in item for item in payload["failures"])

    code, payload = run_contract({
        "FIELD_STAGING_OBJECT_ACCOUNT_ID": "prodacct123",
        "FIELD_STAGING_OBJECT_BUCKET": "agroai-connectors",
    })
    assert code == 1
    assert any("object bucket fingerprint equals production" in item for item in payload["failures"])


def test_deploy_hook_must_resolve_to_declared_staging_service():
    code, payload = run_contract({
        "FIELD_STAGING_DEPLOY_HOOK": "https://api.render.com/deploy/srv-prod-api-123?key=redacted",
    })
    assert code == 1
    assert any("production service" in item or "declared staging service" in item for item in payload["failures"])

    code, payload = run_contract({
        "FIELD_STAGING_DEPLOY_HOOK": "https://example.com/deploy/srv-stage-api-123",
    })
    assert code == 1
    assert any("recognized Render deploy hook" in item for item in payload["failures"])


def test_worker_mode_contract_is_explicit():
    code, payload = run_contract({"FIELD_STAGING_WORKER_MODE": "mystery"})
    assert code == 1
    code, payload = run_contract({
        "FIELD_STAGING_WORKER_MODE": "in_process",
        "FIELD_STAGING_WORKER_SERVICE_ID": "",
        "FIELD_STAGING_WORKER_DEPLOY_HOOK": "",
    })
    assert code == 0, payload


def test_real_transcription_is_required():
    code, payload = run_contract({"FIELD_STAGING_TRANSCRIPTION_PROVIDER": "fake"})
    assert code == 1
    assert any("real configured provider" in item for item in payload["failures"])


def test_release_state_general_is_refused_and_canary_is_double_confirmed():
    code, payload = run_contract({"FIELD_STAGING_RELEASE_STATE": "general"})
    assert code == 1
    code, payload = run_contract({"FIELD_STAGING_RELEASE_STATE": "canary"})
    assert code == 1
    code, payload = run_contract({
        "FIELD_STAGING_RELEASE_STATE": "canary",
        "FIELD_STAGING_CONFIRM_CANARY": "CONFIRM_STAGING_CANARY",
    })
    assert code == 0, payload


def test_production_runtime_credentials_are_not_inherited():
    for name in ("CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_API_TOKEN", "DATABASE_URL"):
        code, payload = run_contract({name: "production-value"})
        assert code == 1
        assert any(name in item for item in payload["failures"])


def test_staging_portal_project_must_be_distinct():
    code, payload = run_contract({"FIELD_STAGING_PORTAL_PROJECT": "agroai-portal"})
    assert code == 1
    assert any("portal project equals production" in item for item in payload["failures"])


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_dispatch_only_and_requires_exact_head_and_merge_ref():
    text = _workflow_text()
    lines = [line.strip() for line in text.splitlines()]
    trigger_index = lines.index("on:")
    trigger_block = "\n".join(lines[trigger_index:trigger_index + 40])
    assert "workflow_dispatch:" in trigger_block
    assert "push:" not in trigger_block and "pull_request:" not in trigger_block and "schedule:" not in trigger_block
    assert "STAGE_FIELD_INTELLIGENCE" in text
    assert "merge_sha:" in text
    assert "pulls/258" in text
    assert "origin/main" in text
    assert "merge_commit_sha" in text
    assert "PR head SHA does not equal the requested staging SHA" in text
    assert "PR base SHA is not current origin/main" in text


def test_workflow_requires_every_expected_pr_workflow_terminal_and_green():
    text = _workflow_text()
    for name in (
        "Field Intelligence CI",
        "Platform Hardening CI",
        "Platform Hardening Extended CI",
        "Platform API Foundation CI",
        "Alembic Revision Contract CI",
        "Production Startup Contract CI",
        "PostgreSQL Adoption Smoke CI",
        "Deployment DB Preflight CI",
        "Distributed Runtime Integration CI",
        "Compliance Kernel CI",
        "I18n Inventory CI",
        "Locale Browser Contract CI",
        "Cloudflare Pages Topology Contract CI",
        "CI - Cloudflare Release Contract",
    ):
        assert name in text
    assert "missing expected workflow" in text
    assert "is not terminal and successful" in text


def test_workflow_proves_deploy_identity_before_network_post():
    text = _workflow_text()
    contract_index = text.index("Validate immutable staging resource identities")
    deploy_index = text.index("Trigger staging API deployment")
    assert contract_index < deploy_index
    assert "FIELD_STAGING_API_SERVICE_ID" in text
    assert "PRODUCTION_API_SERVICE_ID" in text
    assert "FIELD_STAGING_WORKER_SERVICE_ID" in text


def test_workflow_uses_only_protected_staging_environment_secrets():
    text = _workflow_text()
    assert "environment: field-intelligence-staging" in text
    assert "environment: production" not in text
    for forbidden in (
        "secrets.CLOUDFLARE_API_TOKEN",
        "secrets.QUEUE_PUBLISH_TOKEN",
        "secrets.EDGE_ORIGIN_AUTH_TOKEN",
    ):
        assert forbidden not in text


def test_workflow_checks_runtime_readiness_worker_storage_and_live_portal():
    text = _workflow_text()
    assert "Probe staging object storage" in text
    assert "/v1/readiness" in text
    assert "/v1/field-intelligence/admin/rollout" in text
    assert "field_worker_heartbeats" in text
    assert "deployment-meta.json" in text
    assert "Verify the live staging portal" in text
    assert "VITE_DEPLOYMENT_ENVIRONMENT: staging" in text
    assert "027_field_intelligence_launch" in text


def test_workflow_cleans_disposable_rollback_database_on_success_and_failure():
    text = _workflow_text()
    assert "DROP DATABASE IF EXISTS" in text
    assert "trap cleanup_proof_db EXIT" in text
    assert "fi_stage_proof_${GITHUB_RUN_ID}_${GITHUB_RUN_ATTEMPT}" in text


def test_workflow_smoke_is_manual_and_artifacts_are_redacted():
    text = _workflow_text()
    assert "inputs.run_smoke == 'true'" in text
    assert "field-intelligence-staging-${{ needs.validate-source.outputs.sha }}" in text
    assert "upload-artifact" in text
    assert "echo ${{ secrets." not in text
