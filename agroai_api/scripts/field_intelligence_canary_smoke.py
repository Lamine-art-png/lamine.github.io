"""Manually-gated deployed-environment smoke for Field Intelligence.

Runs the full capture → durability → processing → intelligence → deletion →
audit journey against a *deployed* environment as a real signed-in user.
It never runs automatically: it requires explicit environment configuration
and an operator-provided bearer token for a canary organization account.

    FIELD_SMOKE_BASE_URL=https://api.example.com \
    FIELD_SMOKE_TOKEN=<bearer for a canary-org user> \
    FIELD_SMOKE_RESTRICTED_TOKEN=<bearer for a restricted user, optional> \
    python scripts/field_intelligence_canary_smoke.py

Every step prints PASS/FAIL; exit code is nonzero on any failure. No step
fabricates success: durability, processing and deletion are verified by
reading state back from the API.
"""
from __future__ import annotations

import io
import json
import os
import struct
import zlib
from pathlib import Path
import sys
import time
import uuid

import httpx

BASE = os.environ.get("FIELD_SMOKE_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("FIELD_SMOKE_TOKEN", "")
RESTRICTED_TOKEN = os.environ.get("FIELD_SMOKE_RESTRICTED_TOKEN", "")
TIMEOUT = float(os.environ.get("FIELD_SMOKE_TIMEOUT_SECONDS", "30"))
PROCESS_WAIT = float(os.environ.get("FIELD_SMOKE_PROCESS_WAIT_SECONDS", "120"))

_results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        finish()


def finish() -> None:
    failed = [name for name, ok, _ in _results if not ok]
    print(json.dumps({
        "smoke": "field_intelligence_canary",
        "steps": len(_results),
        "failed": failed,
    }, indent=2))
    sys.exit(1 if failed else 0)


def _png() -> bytes:
    """Return a structurally valid 1x1 RGB PNG, not a magic-byte stub."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    scanline = b"\x00\x2c\x7a\x3f"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(scanline)) + chunk(b"IEND", b"")


def _speech_audio() -> tuple[bytes, str, str]:
    raw_path = (os.environ.get("FIELD_SMOKE_AUDIO_PATH") or "").strip()
    if not raw_path:
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH is required for a real transcription smoke")
    path = Path(raw_path)
    if not path.is_file():
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH does not reference a file")
    payload = path.read_bytes()
    if len(payload) < 44 or not payload.startswith(b"RIFF") or payload[8:12] != b"WAVE":
        raise RuntimeError("FIELD_SMOKE_AUDIO_PATH is not a valid WAV container")
    return payload, path.name or "field-smoke.wav", (os.environ.get("FIELD_SMOKE_AUDIO_CONTENT_TYPE") or "audio/wav").strip()


def main() -> None:
    if not BASE or not TOKEN:
        print("FIELD_SMOKE_BASE_URL and FIELD_SMOKE_TOKEN are required — this smoke is manually gated.")
        sys.exit(2)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    http = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    run_id = uuid.uuid4().hex[:10]

    # 1. Signed-in authorized user
    me = http.get("/v1/field-intelligence/observations?limit=1", headers=auth)
    step("authorized user can reach field intelligence", me.status_code == 200, f"http {me.status_code}")

    # 2. Create typed capture
    cap = http.post("/v1/field-intelligence/captures/initiate", headers=auth, json={
        "client_capture_id": f"smoke-{run_id}", "idempotency_key": f"smoke-{run_id}",
        "capture_source": "voice",
        "note_text": f"Canary smoke {run_id}: irrigation ran 45 minutes on Block A, 1200 gallons applied.",
        "field_name": "Canary Ranch", "block_name": "Block A", "crop": "Almonds",
    })
    step("capture initiated", cap.status_code == 200, f"http {cap.status_code}")
    capture_id = cap.json()["capture"]["id"]

    # 3. Upload real small audio + photo evidence
    audio, audio_filename, audio_content_type = _speech_audio()
    up_audio = http.post(f"/v1/field-intelligence/captures/{capture_id}/assets", headers=auth,
                         data={"client_asset_id": f"aud-{run_id}", "kind": "audio"},
                         files={"file": (audio_filename, io.BytesIO(audio), audio_content_type)})
    step("audio evidence uploaded", up_audio.status_code == 200, up_audio.text[:120])
    up_photo = http.post(f"/v1/field-intelligence/captures/{capture_id}/assets", headers=auth,
                         data={"client_asset_id": f"pic-{run_id}", "kind": "photo"},
                         files={"file": ("smoke.png", io.BytesIO(_png()), "image/png")})
    step("photo evidence uploaded", up_photo.status_code == 200, up_photo.text[:120])
    audio_asset = up_audio.json()["asset"]

    # 4. Confirm R2 durability (authorized read-back of the stored bytes)
    content = http.get(f"/v1/field-intelligence/assets/{audio_asset['id']}/content", headers=auth)
    step("durable object readable", content.status_code == 200 and content.content == audio,
         f"{len(content.content)} bytes")

    # 5-6. Complete capture -> 202 processing
    done = http.post(f"/v1/field-intelligence/captures/{capture_id}/complete", headers=auth, json={})
    step("capture completed with 202 processing", done.status_code == 202, f"http {done.status_code}")
    observation_id = done.json()["observation"]["id"]

    # 7-10. Worker processes: transcription, extraction, correlation
    deadline = time.monotonic() + PROCESS_WAIT
    observation = None
    while time.monotonic() < deadline:
        response = http.get(f"/v1/field-intelligence/observations/{observation_id}", headers=auth)
        if response.status_code == 200:
            observation = response.json()["observation"]
            if observation.get("status") in {"completed", "needs_review", "failed"}:
                break
        time.sleep(3)
    step("worker processed the job", bool(observation) and observation.get("status") in {"completed", "needs_review"},
         f"status={observation and observation.get('status')}")
    provenance = (observation or {}).get("provenance") or {}
    transcript = str((observation or {}).get("transcript") or "").strip()
    step("real transcription completed", provenance.get("transcription_status") == "completed" and bool(transcript),
         f"status={provenance.get('transcription_status')} transcript_chars={len(transcript)}")
    step("extraction present", bool((observation or {}).get("structured")), "")
    step("correlation present", isinstance((observation or {}).get("correlation"), dict), "")

    # 11. Observation retrieval (list view)
    listing = http.get("/v1/field-intelligence/observations?limit=5", headers=auth)
    listed = [o["id"] for o in listing.json().get("observations", [])]
    step("observation retrievable in list", observation_id in listed, "")

    # 12-13. Evidence graph + Ask AGRO-AI context (evidence ids present)
    step("evidence graph entry", bool((observation or {}).get("evidence_ids")), "")

    # 14. Create task
    task = http.post(f"/v1/field-intelligence/observations/{observation_id}/tasks", headers=auth,
                     json={"title": f"Canary follow-up {run_id}"})
    step("task created", task.status_code == 200, f"http {task.status_code}")

    # 15. Range retrieval
    ranged = http.get(f"/v1/field-intelligence/assets/{audio_asset['id']}/content",
                      headers={**auth, "Range": "bytes=0-15"})
    step("range retrieval honored", ranged.status_code == 206 and len(ranged.content) == 16,
         f"http {ranged.status_code}")

    # 16-18. Delete observation -> retrieval blocked -> object physically deleted
    deleted = http.delete(f"/v1/field-intelligence/observations/{observation_id}", headers=auth)
    step("observation deleted", deleted.status_code == 200, f"http {deleted.status_code}")
    blocked = http.get(f"/v1/field-intelligence/observations/{observation_id}", headers=auth)
    step("retrieval blocked after deletion", blocked.status_code == 404, f"http {blocked.status_code}")
    deadline = time.monotonic() + PROCESS_WAIT
    gone = False
    while time.monotonic() < deadline:
        content = http.get(f"/v1/field-intelligence/assets/{audio_asset['id']}/content", headers=auth)
        if content.status_code in {404, 410}:
            gone = True
            break
        time.sleep(3)
    step("object physically deleted by worker", gone, "")

    # 19. The append-only audit row survives the observation soft deletion.
    audit = http.get("/v1/field-intelligence/admin/audit",
                     params={"observation_id": observation_id, "limit": 100}, headers=auth)
    audit_actions = {event.get("action") for event in (audit.json().get("events", []) if audit.status_code == 200 else [])}
    step("audit provenance recorded", audit.status_code == 200 and "observation_deleted" in audit_actions,
         f"http {audit.status_code}; actions={sorted(action for action in audit_actions if action)}")

    # 20. Restricted user remains blocked
    if RESTRICTED_TOKEN:
        blocked = http.get("/v1/field-intelligence/observations",
                           headers={"Authorization": f"Bearer {RESTRICTED_TOKEN}"})
        step("restricted user blocked", blocked.status_code == 403, f"http {blocked.status_code}")
    else:
        step("restricted user blocked", True, "skipped: FIELD_SMOKE_RESTRICTED_TOKEN not provided")

    finish()


if __name__ == "__main__":
    main()
