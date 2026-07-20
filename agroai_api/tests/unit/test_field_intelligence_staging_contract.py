"""Staging isolation contracts.

Proves the staging configuration validator and the manually gated staging
workflow can never target production, fail closed on missing resources, and
keep the release state at internal.
"""
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
    "FIELD_STAGING_OBJECT_STORAGE_BACKEND": "r2",
    "FIELD_STAGING_OBJECT_BUCKET": "agroai-field-staging",
    "FIELD_STAGING_OBJECT_ENDPOINT_URL": "https://acc.r2.cloudflarestorage.com",
    "FIELD_STAGING_R2_ACCESS_KEY_ID": "staging-key",
    "FIELD_STAGING_R2_SECRET_ACCESS_KEY": "staging-secret",
    "FIELD_STAGING_TRANSCRIPTION_PROVIDER": "openai_whisper",
    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://stt-staging.example/v1/audio/transcriptions",
    "FIELD_STAGING_TRANSCRIPTION_API_KEY": "staging-stt-key",
    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS": "org-staging-internal",
    "FIELD_STAGING_RELEASE_STATE": "internal",
}


def run_contract(overrides: dict | None = None, removals: tuple = ()) -> tuple[int, dict]:
    env = {"PATH": os.environ.get("PATH", ""), **BASE_ENV, **(overrides or {})}
    for name in removals:
        env.pop(name, None)
    proc = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    payload = json.loads(proc.stdout[proc.stdout.index("{"):]) if "{" in proc.stdout else {}
    return proc.returncode, payload


def test_valid_staging_configuration_passes():
    code, payload = run_contract()
    assert code == 0 and payload["ok"], payload


def test_missing_staging_resources_fail_closed():
    code, payload = run_contract(removals=("FIELD_STAGING_DATABASE_URL", "FIELD_STAGING_OBJECT_BUCKET"))
    assert code == 1 and not payload["ok"]
    assert any("missing required staging configuration" in f for f in payload["failures"])


def test_production_api_urls_are_refused():
    for hostname in ("api.agroai-pilot.com", "api-preview.agroai-pilot.com",
                     "agroai-api-preview.onrender.com", "app.agroai-pilot.com"):
        code, payload = run_contract({"FIELD_STAGING_API_URL": f"https://{hostname}"})
        assert code == 1, hostname
        assert any("PRODUCTION hostname" in f for f in payload["failures"]), (hostname, payload)


def test_staging_database_cannot_equal_production_fingerprint():
    code, payload = run_contract({
        "FIELD_STAGING_DATABASE_URL": "postgresql://u@prod-db.internal:5432/agroai",
        "PRODUCTION_DATABASE_HOST_FINGERPRINT": "prod-db.internal",
    })
    assert code == 1
    assert any("production database fingerprint" in f for f in payload["failures"])


def test_staging_bucket_cannot_equal_production_bucket():
    code, payload = run_contract({
        "FIELD_STAGING_OBJECT_BUCKET": "agroai-connectors-staging",
        "CONNECTOR_OBJECT_BUCKET": "agroai-connectors-staging",
    })
    assert code == 1
    assert any("equals the production bucket" in f for f in payload["failures"])
    code, payload = run_contract({"FIELD_STAGING_OBJECT_BUCKET": "agroai-connectors"})
    assert code == 1
    assert any("must contain 'staging'" in f for f in payload["failures"])


def test_release_state_general_is_always_refused():
    code, payload = run_contract({"FIELD_STAGING_RELEASE_STATE": "general"})
    assert code == 1
    assert any("'general' is refused" in f for f in payload["failures"])


def test_canary_requires_explicit_confirmation():
    code, payload = run_contract({"FIELD_STAGING_RELEASE_STATE": "canary"})
    assert code == 1
    code, payload = run_contract({"FIELD_STAGING_RELEASE_STATE": "canary",
                                  "FIELD_STAGING_CONFIRM_CANARY": "CONFIRM_STAGING_CANARY"})
    assert code == 0, payload


def test_production_r2_credentials_must_not_leak_into_staging():
    code, payload = run_contract({"CLOUDFLARE_R2_ACCESS_KEY_ID": "prod-key"})
    assert code == 1
    assert any("CLOUDFLARE_R2_ACCESS_KEY_ID must not be set" in f for f in payload["failures"])


def test_production_portal_project_is_refused():
    code, payload = run_contract({"FIELD_STAGING_PORTAL_PROJECT": "agroai-portal"})
    assert code == 1
    assert any("production portal project" in f for f in payload["failures"])


# --------------------------------------------------------------------------- #
# Staging workflow static contract
# --------------------------------------------------------------------------- #

def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_dispatch_only():
    text = _workflow_text()
    assert "workflow_dispatch:" in text
    lines = [line.strip() for line in text.splitlines()]
    trigger_index = lines.index("on:")
    trigger_block = "\n".join(lines[trigger_index:trigger_index + 30])
    assert "push:" not in trigger_block
    assert "pull_request:" not in trigger_block
    assert "schedule:" not in trigger_block


def test_workflow_requires_confirmation_and_exact_sha():
    text = _workflow_text()
    assert "STAGE_FIELD_INTELLIGENCE" in text
    assert "inputs.confirm != 'STAGE_FIELD_INTELLIGENCE'" in text
    assert "is not the ${STAGING_BRANCH} head" in text
    assert "Refusing: this staging workflow must not run from main" in text


def test_workflow_uses_protected_staging_environment_and_secrets():
    text = _workflow_text()
    assert "environment: field-intelligence-staging" in text
    # never the production environment or its secrets
    assert "environment: production" not in text
    for name in ("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}",
                 "secrets.QUEUE_PUBLISH_TOKEN", "secrets.EDGE_ORIGIN_AUTH_TOKEN"):
        assert name not in text


def test_workflow_refuses_production_targets_and_general_state():
    text = _workflow_text()
    assert 'Refusing: production API' in text
    assert 'Refusing: production upstream' in text
    assert '"agroai-portal"' in text and "Refusing: production portal project" in text
    assert 'general is never staged' in text
    assert "CONFIRM_STAGING_CANARY" in text


def test_workflow_smoke_is_manually_gated_and_evidence_uploaded():
    text = _workflow_text()
    assert "inputs.run_smoke == 'true'" in text
    assert "upload-artifact" in text
    assert "field-intelligence-staging-${{ needs.validate-source.outputs.sha }}" in text


def test_workflow_never_prints_secret_values():
    text = _workflow_text()
    # secrets are referenced only via env mapping, never echoed
    assert "echo ${{ secrets." not in text and "echo ${FIELD_STAGING_R2_SECRET" not in text


def test_staging_portal_build_cannot_target_production_api():
    text = _workflow_text()
    deploy_section = text[text.index("Deploy the staging portal"):]
    assert "api.agroai-pilot.com" in deploy_section  # present in the refusal case
    assert "exit 1" in deploy_section
    assert "VITE_DEPLOYMENT_ENVIRONMENT: staging" in text
