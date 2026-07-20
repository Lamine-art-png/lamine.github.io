from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_required(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"missing replacement marker in {path}: {old!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Staging workflow: the storage probe must consume the effective staging
# prefix, and the optional live smoke must use a real spoken-audio fixture.
# ---------------------------------------------------------------------------
workflow_path = ".github/workflows/field-intelligence-staging.yml"
workflow = read(workflow_path)
replace_required(
    workflow_path,
    "          CONNECTOR_OBJECT_PREFIX: ${{ vars.FIELD_STAGING_OBJECT_PREFIX }}",
    "          CONNECTOR_OBJECT_PREFIX: ${{ env.FIELD_STAGING_OBJECT_PREFIX }}",
)
workflow = read(workflow_path)
smoke_old = '''        run: |
          set -o pipefail
          python -m pip install -q httpx
          python scripts/field_intelligence_canary_smoke.py 2>&1 | tee ../staging-smoke.log
'''
smoke_new = '''        run: |
          set -euo pipefail
          python -m pip install -q httpx
          sudo apt-get update -q
          sudo apt-get install -y -q espeak-ng
          speech_fixture="$(mktemp --suffix=.wav)"
          trap 'rm -f "$speech_fixture"' EXIT
          espeak-ng -s 150 -w "$speech_fixture" \
            "Irrigation ran forty five minutes on Block A. One thousand two hundred gallons applied."
          FIELD_SMOKE_AUDIO_PATH="$speech_fixture" \
          FIELD_SMOKE_AUDIO_CONTENT_TYPE="audio/wav" \
            python scripts/field_intelligence_canary_smoke.py 2>&1 | tee ../staging-smoke.log
'''
if smoke_old not in workflow:
    raise SystemExit("staging smoke step marker missing")
write(workflow_path, workflow.replace(smoke_old, smoke_new, 1))


# ---------------------------------------------------------------------------
# Platform-admin audit readback. This is intentionally observation-scoped,
# bounded and metadata-only; it cannot enumerate content or bypass auth.
# ---------------------------------------------------------------------------
admin_path = "agroai_api/app/api/v1/field_intelligence_admin.py"
admin = read(admin_path)
admin = admin.replace(
    "from fastapi import APIRouter, Depends, HTTPException, status",
    "from fastapi import APIRouter, Depends, HTTPException, Query, status",
    1,
)
admin = admin.replace(
    "    FieldObservation,\n    FieldObservationAsset,",
    "    FieldObservation,\n    FieldObservationAsset,\n    FieldObservationAuditEvent,",
    1,
)
audit_endpoint = '''

@router.get("/audit")
def get_observation_audit(
    observation_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=100, ge=1, le=200),
    ctx: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Read bounded append-only audit metadata for one observation.

    The route is platform-admin only and requires an exact observation id, so it
    cannot be used to enumerate tenants or retrieve customer media/transcripts.
    """
    rows = (
        db.query(FieldObservationAuditEvent)
        .filter(FieldObservationAuditEvent.observation_id == observation_id)
        .order_by(FieldObservationAuditEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    return {
        "status": "ok",
        "observation_id": observation_id,
        "count": len(rows),
        "events": [
            {
                "id": row.id,
                "action": row.action,
                "actor_type": row.actor_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }
'''
if '@router.get("/audit")' not in admin:
    marker = '\n\n@router.get("/operations")\n'
    if marker not in admin:
        raise SystemExit("admin operations marker missing")
    admin = admin.replace(marker, audit_endpoint + marker, 1)
write(admin_path, admin)


# ---------------------------------------------------------------------------
# Live deployed-environment smoke: real speech fixture, valid PNG, actual
# transcript assertion, and authoritative audit readback after deletion.
# ---------------------------------------------------------------------------
smoke_path = "agroai_api/scripts/field_intelligence_canary_smoke.py"
smoke = read(smoke_path)
smoke = smoke.replace(
    '"""Manually-gated production canary smoke for Field Intelligence.',
    '"""Manually-gated deployed-environment smoke for Field Intelligence.',
    1,
)
smoke = smoke.replace("import struct\n", "import struct\nimport zlib\nfrom pathlib import Path\n", 1)
fixtures_pattern = re.compile(r"def _png\(\) -> bytes:.*?(?=\n\ndef main\(\) -> None:)", re.S)
fixtures = '''def _png() -> bytes:
    """Return a structurally valid 1x1 RGB PNG, not a magic-byte stub."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    scanline = b"\\x00\\x2c\\x7a\\x3f"
    return b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(scanline)) + chunk(b"IEND", b"")


def _speech_audio() -> tuple[bytes, str, str]:
    """Read the real speech fixture generated by the protected staging job."""
    raw_path = (os.environ.get("FIELD_SMOKE_AUDIO_PATH") or "").strip()
    if not raw_path:
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH is required for a real transcription smoke")
    path = Path(raw_path)
    if not path.is_file():
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH does not reference a file")
    payload = path.read_bytes()
    if len(payload) < 44 or not payload.startswith(b"RIFF") or payload[8:12] != b"WAVE":
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH is not a valid WAV container")
    content_type = (os.environ.get("FIELD_SMOKE_AUDIO_CONTENT_TYPE") or "audio/wav").strip()
    return payload, path.name or "field-smoke.wav", content_type
'''
smoke, count = fixtures_pattern.subn(fixtures, smoke, count=1)
if count != 1:
    raise SystemExit("smoke media fixture block not found")
smoke = smoke.replace(
    "    audio = _ogg_opus()\n    up_audio = http.post(f\"/v1/field-intelligence/captures/{capture_id}/assets\", headers=auth,\n                         data={\"client_asset_id\": f\"aud-{run_id}\", \"kind\": \"audio\"},\n                         files={\"file\": (\"smoke.ogg\", io.BytesIO(audio), \"audio/ogg\")})",
    "    audio, audio_filename, audio_content_type = _speech_audio()\n    up_audio = http.post(f\"/v1/field-intelligence/captures/{capture_id}/assets\", headers=auth,\n                         data={\"client_asset_id\": f\"aud-{run_id}\", \"kind\": \"audio\"},\n                         files={\"file\": (audio_filename, io.BytesIO(audio), audio_content_type)})",
    1,
)
smoke = smoke.replace(
    '    step("transcription ran", provenance.get("transcription_status") in {"completed", "skipped"},\n         str(provenance.get("transcription_status")))',
    '    transcript = str((observation or {}).get("transcript") or "").strip()\n'
    '    step("real transcription completed", provenance.get("transcription_status") == "completed" and bool(transcript),\n'
    '         f"status={provenance.get(\'transcription_status\')} transcript_chars={len(transcript)}")',
    1,
)
smoke = smoke.replace(
    '    # 19. Audit provenance survives deletion (capture remains queryable? audit is server-side)\n'
    '    step("audit provenance recorded", True, "verified via observation provenance before deletion")',
    '    # 19. The append-only audit row survives the observation soft deletion.\n'
    '    audit = http.get("/v1/field-intelligence/admin/audit",\n'
    '                     params={"observation_id": observation_id, "limit": 100}, headers=auth)\n'
    '    audit_actions = {event.get("action") for event in (audit.json().get("events", []) if audit.status_code == 200 else [])}\n'
    '    step("audit provenance recorded", audit.status_code == 200 and "observation_deleted" in audit_actions,\n'
    '         f"http {audit.status_code}; actions={sorted(action for action in audit_actions if action)}")',
    1,
)
write(smoke_path, smoke)


# ---------------------------------------------------------------------------
# Regression contracts for the new operational proof surfaces.
# ---------------------------------------------------------------------------
staging_test_path = "agroai_api/tests/unit/test_field_intelligence_staging_contract.py"
staging_tests = read(staging_test_path)
new_staging_tests = '''


def test_storage_probe_uses_the_effective_staging_prefix():
    text = _workflow_text()
    assert "FIELD_STAGING_OBJECT_PREFIX: ${{ vars.FIELD_STAGING_OBJECT_PREFIX || 'staging/field-intelligence' }}" in text
    assert "CONNECTOR_OBJECT_PREFIX: ${{ env.FIELD_STAGING_OBJECT_PREFIX }}" in text
    assert "CONNECTOR_OBJECT_PREFIX: ${{ vars.FIELD_STAGING_OBJECT_PREFIX }}" not in text


def test_live_smoke_uses_real_speech_and_reads_append_only_audit():
    smoke = (REPO / "agroai_api" / "scripts" / "field_intelligence_canary_smoke.py").read_text(encoding="utf-8")
    workflow = _workflow_text()
    assert "FIELD_SMOKE_AUDIO_PATH" in smoke
    assert "valid WAV container" in smoke
    assert "real transcription completed" in smoke
    assert "/v1/field-intelligence/admin/audit" in smoke
    assert 'step("audit provenance recorded", True' not in smoke
    assert "espeak-ng" in workflow and "FIELD_SMOKE_AUDIO_PATH" in workflow
'''
if "test_storage_probe_uses_the_effective_staging_prefix" not in staging_tests:
    staging_tests += new_staging_tests
write(staging_test_path, staging_tests)

launch_test_path = "agroai_api/tests/unit/test_field_intelligence_launch.py"
launch_tests = read(launch_test_path)
launch_tests = launch_tests.replace(
    "from tests.unit.test_field_intelligence import _auth, _initiate",
    "from tests.unit.test_field_intelligence import _auth, _initiate",
    1,
)
admin_audit_test = '''


def test_admin_audit_is_platform_admin_only_bounded_and_metadata_only(client, db, monkeypatch):
    from app.models.field_intelligence import FieldObservationAuditEvent

    org, _, headers = _auth(db)
    db.add(FieldObservationAuditEvent(
        id="audit-proof-1",
        tenant_id=org.id,
        observation_id="obs-audit-proof",
        action="observation_deleted",
        actor="sensitive-actor-id",
        actor_type="user",
        details_json={"private_detail": "must-not-leak"},
    ))
    db.commit()

    path = "/v1/field-intelligence/admin/audit?observation_id=obs-audit-proof&limit=10"
    assert client.get(path, headers=headers).status_code == 403

    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["action"] == "observation_deleted"
    assert set(payload["events"][0]) == {"id", "action", "actor_type", "created_at"}
    assert "sensitive-actor-id" not in response.text
    assert "private_detail" not in response.text
'''
marker = "\n\n# --------------------------------------------------------------------------- #\n# Worker topology\n"
if "test_admin_audit_is_platform_admin_only_bounded_and_metadata_only" not in launch_tests:
    if marker not in launch_tests:
        raise SystemExit("launch test worker section marker missing")
    launch_tests = launch_tests.replace(marker, admin_audit_test + marker, 1)
write(launch_test_path, launch_tests)

print("Field Intelligence staging smoke hardening applied")
