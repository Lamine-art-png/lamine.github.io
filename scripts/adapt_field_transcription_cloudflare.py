from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch marker: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# First-class Cloudflare Workers AI transcription provider.
# ---------------------------------------------------------------------------
path = "agroai_api/app/services/field_transcription.py"
text = read(path)
text = replace_once(text, "import time\n", "import base64\nimport time\n", "base64 import")
text = replace_once(
    text,
    "from typing import Protocol\n",
    "from typing import Protocol\nfrom urllib.parse import urlparse\n",
    "urlparse import",
)

cloudflare_provider = r'''

class CloudflareWorkersAITranscriptionProvider:
    """Cloudflare Workers AI speech-to-text via the Execute AI Model REST API.

    The provider sends Base64 JSON to Cloudflare's account-scoped ``ai/run``
    endpoint. The API token is never sent anywhere except ``api.cloudflare.com``;
    endpoint and model agreement is checked before any network request.
    """

    name = "cloudflare_workers_ai"
    default_model = "@cf/openai/whisper-large-v3-turbo"

    def available(self) -> bool:
        return bool(
            str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
            and str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        )

    @classmethod
    def endpoint_valid(cls, endpoint: str, model: str) -> bool:
        try:
            parsed = urlparse(endpoint)
        except ValueError:
            return False
        normalized_model = (model or cls.default_model).strip()
        expected_suffix = f"/ai/run/{normalized_model}"
        path = (parsed.path or "").rstrip("/")
        return bool(
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == "api.cloudflare.com"
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and path.startswith("/client/v4/accounts/")
            and path.endswith(expected_suffix)
        )

    @staticmethod
    def _envelope_retryable(errors: object) -> bool:
        text = str(errors or "").lower()
        return any(
            token in text
            for token in (
                "rate limit", "too many requests", "temporar", "timeout",
                "unavailable", "overload", "internal error", "try again",
            )
        )

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        started = time.monotonic()
        if not self.available():
            return TranscriptionResult(
                provider=self.name,
                status="unavailable",
                error="transcription_provider_not_configured",
                language=language,
            )
        bound = _input_bound_error(self.name, audio, language)
        if bound is not None:
            return bound

        endpoint = str(settings.FIELD_TRANSCRIPTION_ENDPOINT).strip()
        api_key = str(settings.FIELD_TRANSCRIPTION_API_KEY).strip()
        model = (
            str(getattr(settings, "FIELD_TRANSCRIPTION_MODEL", "") or "").strip()
            or self.default_model
        )
        if not self.endpoint_valid(endpoint, model):
            return TranscriptionResult(
                provider=self.name,
                status="failed",
                model=model,
                language=language,
                latency_ms=int((time.monotonic() - started) * 1000),
                error="invalid_cloudflare_workers_ai_endpoint",
                retryable=False,
            )

        request_payload: dict = {
            "audio": base64.b64encode(audio or b"").decode("ascii"),
            "task": "transcribe",
            "vad_filter": True,
            # Avoid conditioning loops in noisy field recordings.
            "condition_on_previous_text": False,
        }
        if language:
            request_payload["language"] = language

        try:
            import httpx

            with httpx.Client(timeout=_provider_timeout()) as http:
                response = http.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
            latency = int((time.monotonic() - started) * 1000)
            if response.status_code >= 400:
                return TranscriptionResult(
                    provider=self.name,
                    status="failed",
                    model=model,
                    language=language,
                    latency_ms=latency,
                    error=f"provider_http_{response.status_code}",
                    retryable=response.status_code in _RETRYABLE_HTTP,
                )
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001 - stable error, no response body leakage
                return TranscriptionResult(
                    provider=self.name,
                    status="failed",
                    model=model,
                    language=language,
                    latency_ms=latency,
                    error="provider_invalid_json",
                    retryable=True,
                )
            if not isinstance(payload, dict):
                return TranscriptionResult(
                    provider=self.name,
                    status="failed",
                    model=model,
                    language=language,
                    latency_ms=latency,
                    error="provider_invalid_response",
                    retryable=False,
                )
            if payload.get("success") is False:
                errors = payload.get("errors") or []
                return TranscriptionResult(
                    provider=self.name,
                    status="failed",
                    model=model,
                    language=language,
                    latency_ms=latency,
                    error="provider_envelope_error",
                    retryable=self._envelope_retryable(errors),
                    metadata={"provider_error_count": len(errors) if isinstance(errors, list) else 1},
                )

            result_payload = payload.get("result", payload)
            if isinstance(result_payload, str):
                transcript = result_payload.strip()
                result_payload = {}
            elif isinstance(result_payload, dict):
                info = result_payload.get("transcription_info")
                info = info if isinstance(info, dict) else {}
                transcript = str(
                    result_payload.get("text")
                    or result_payload.get("transcript")
                    or info.get("text")
                    or ""
                ).strip()
            else:
                transcript = ""
                result_payload = {}
                info = {}

            if not transcript:
                return TranscriptionResult(
                    provider=self.name,
                    status="failed",
                    model=model,
                    language=language,
                    latency_ms=latency,
                    error="provider_returned_empty_transcript",
                    retryable=False,
                )

            info = result_payload.get("transcription_info")
            info = info if isinstance(info, dict) else {}
            detected = str(
                result_payload.get("language")
                or info.get("language")
                or info.get("detected_language")
                or ""
            ).strip() or None
            word_count = result_payload.get("word_count")
            if word_count is None:
                word_count = info.get("word_count")
            segments = result_payload.get("segments")
            metadata = {
                "detected_language": detected,
                "language_hint": language,
                "audio_bytes": len(audio or b""),
                "word_count": word_count,
                "segment_count": len(segments) if isinstance(segments, list) else None,
                "vtt_available": bool(result_payload.get("vtt")),
                "transport": "cloudflare_workers_ai_json_base64",
            }
            return TranscriptionResult(
                provider=self.name,
                status="completed",
                transcript=transcript,
                model=model,
                language=detected or language,
                latency_ms=latency,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 - surface failure truthfully
            name = exc.__class__.__name__.lower()
            transient = any(
                token in name
                for token in ("timeout", "connect", "network", "pool", "protocol", "read")
            )
            return TranscriptionResult(
                provider=self.name,
                status="failed",
                model=model,
                language=language,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=exc.__class__.__name__,
                retryable=transient,
            )
'''
text = replace_once(
    text,
    "\n\nclass HttpTranscriptionProvider:",
    cloudflare_provider + "\n\nclass HttpTranscriptionProvider:",
    "Cloudflare provider insertion",
)
text = replace_once(
    text,
    "    if mode in {\"openai_whisper\", \"whisper\"}:\n        whisper = OpenAIWhisperTranscriptionProvider()\n        return whisper if whisper.available() else DisabledTranscriptionProvider()\n",
    "    if mode in {\"cloudflare_workers_ai\", \"workers_ai\", \"cloudflare_whisper\"}:\n"
    "        cloudflare = CloudflareWorkersAITranscriptionProvider()\n"
    "        return cloudflare if cloudflare.available() else DisabledTranscriptionProvider()\n"
    "    if mode in {\"openai_whisper\", \"whisper\"}:\n"
    "        whisper = OpenAIWhisperTranscriptionProvider()\n"
    "        return whisper if whisper.available() else DisabledTranscriptionProvider()\n",
    "provider selection",
)
write(path, text)


# Settings documentation.
path = "agroai_api/app/core/config.py"
text = read(path)
text = replace_once(
    text,
    '    FIELD_TRANSCRIPTION_PROVIDER: str = ""  # "", fake, fake_fail, http/configured\n',
    '    FIELD_TRANSCRIPTION_PROVIDER: str = ""  # cloudflare_workers_ai | openai_whisper | http | fake (dev only)\n',
    "settings provider comment",
)
write(path, text)


# Production readiness: accept Cloudflare only with its official HTTPS account endpoint.
path = "agroai_api/app/services/production_readiness.py"
text = read(path)
text = replace_once(
    text,
    '    elif provider in {"http", "configured", "production", "openai_whisper", "whisper"}:\n',
    '    elif provider in {\n'
    '        "http", "configured", "production", "openai_whisper", "whisper",\n'
    '        "cloudflare_workers_ai", "workers_ai", "cloudflare_whisper",\n'
    '    }:\n',
    "readiness provider allowlist",
)
credential_block = '''        if not _setting(settings, "FIELD_TRANSCRIPTION_ENDPOINT") or not _setting(settings, "FIELD_TRANSCRIPTION_API_KEY"):
            blockers.append(ReadinessFinding(
                "field_intelligence.transcription_credentials_missing", "blocker", "field_intelligence",
                "The transcription provider requires both endpoint and API key.",
            ))
'''
endpoint_block = credential_block + '''        if provider in {"cloudflare_workers_ai", "workers_ai", "cloudflare_whisper"}:
            endpoint = urlparse(_setting(settings, "FIELD_TRANSCRIPTION_ENDPOINT"))
            model = _setting(settings, "FIELD_TRANSCRIPTION_MODEL", "@cf/openai/whisper-large-v3-turbo")
            expected_suffix = f"/ai/run/{model}"
            path = (endpoint.path or "").rstrip("/")
            if not (
                endpoint.scheme == "https"
                and (endpoint.hostname or "").lower() == "api.cloudflare.com"
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.query
                and not endpoint.fragment
                and path.startswith("/client/v4/accounts/")
                and path.endswith(expected_suffix)
            ):
                blockers.append(ReadinessFinding(
                    "field_intelligence.transcription_endpoint_invalid", "blocker", "field_intelligence",
                    "Cloudflare Workers AI transcription requires the official account-scoped HTTPS ai/run endpoint matching the configured model.",
                ))
'''
text = replace_once(text, credential_block, endpoint_block, "readiness endpoint validation")
write(path, text)


# Staging contract: Cloudflare is real, but only on the official endpoint and matching model.
path = "agroai_api/scripts/field_intelligence_staging_contract.py"
text = read(path)
text = replace_once(
    text,
    'REAL_TRANSCRIPTION_PROVIDERS = {\n    "openai_whisper",\n',
    'REAL_TRANSCRIPTION_PROVIDERS = {\n    "cloudflare_workers_ai",\n    "workers_ai",\n    "cloudflare_whisper",\n    "openai_whisper",\n',
    "staging provider allowlist",
)
provider_check = '''    if not values["FIELD_STAGING_TRANSCRIPTION_MODEL"]:
        failures.append("real staging transcription requires a model")
    report["checks"]["transcription_provider"] = transcription_provider or None
'''
provider_check_new = '''    if not values["FIELD_STAGING_TRANSCRIPTION_MODEL"]:
        failures.append("real staging transcription requires a model")
    if transcription_provider in {"cloudflare_workers_ai", "workers_ai", "cloudflare_whisper"}:
        endpoint = urlparse(values["FIELD_STAGING_TRANSCRIPTION_ENDPOINT"])
        model = values["FIELD_STAGING_TRANSCRIPTION_MODEL"]
        endpoint_path = (endpoint.path or "").rstrip("/")
        if not (
            endpoint.scheme == "https"
            and (endpoint.hostname or "").lower() == "api.cloudflare.com"
            and endpoint.username is None
            and endpoint.password is None
            and not endpoint.query
            and not endpoint.fragment
            and endpoint_path.startswith("/client/v4/accounts/")
            and endpoint_path.endswith(f"/ai/run/{model}")
        ):
            failures.append("Cloudflare Workers AI transcription endpoint must be the official account-scoped ai/run URL matching the model")
    report["checks"]["transcription_provider"] = transcription_provider or None
'''
text = replace_once(text, provider_check, provider_check_new, "staging Cloudflare endpoint validation")
write(path, text)


# Operator environment template.
path = "agroai_api/.env.example"
text = read(path)
text = replace_once(
    text,
    "# Transcription: openai_whisper (multipart, OpenAI-compatible) | http | fake (dev only)\n"
    "FIELD_TRANSCRIPTION_PROVIDER=\n"
    "FIELD_TRANSCRIPTION_ENDPOINT=\n"
    "FIELD_TRANSCRIPTION_API_KEY=\n"
    "FIELD_TRANSCRIPTION_MODEL=\n",
    "# Transcription providers:\n"
    "# - cloudflare_workers_ai: JSON/Base64 Workers AI Execute Model API\n"
    "# - openai_whisper: multipart OpenAI-compatible /audio/transcriptions API\n"
    "# - http: provider-neutral raw-audio adapter; fake is development/test only\n"
    "FIELD_TRANSCRIPTION_PROVIDER=\n"
    "# Cloudflare example:\n"
    "# https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/run/@cf/openai/whisper-large-v3-turbo\n"
    "FIELD_TRANSCRIPTION_ENDPOINT=\n"
    "FIELD_TRANSCRIPTION_API_KEY=\n"
    "FIELD_TRANSCRIPTION_MODEL=\n",
    "environment provider documentation",
)
write(path, text)


# Provider behavior and production-readiness tests.
path = "agroai_api/tests/unit/test_field_intelligence_launch.py"
text = read(path)
text = replace_once(text, "import json\n", "import base64\nimport json\n", "test base64 import")
text = replace_once(
    text,
    "from app.services.field_transcription import (\n    OpenAIWhisperTranscriptionProvider,\n",
    "from app.services.field_transcription import (\n    CloudflareWorkersAITranscriptionProvider,\n    OpenAIWhisperTranscriptionProvider,\n",
    "Cloudflare test import",
)
cloudflare_tests = r'''


def _configure_cloudflare_transcription(monkeypatch):
    model = "@cf/openai/whisper-large-v3-turbo"
    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/stage-account-123/ai/run/"
        + model
    )
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "cloudflare_workers_ai")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", endpoint)
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "cf-staging-token")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MODEL", model)
    return endpoint, model


def test_cloudflare_workers_ai_provider_selected_and_bounded(monkeypatch):
    _configure_cloudflare_transcription(monkeypatch)
    provider = get_transcription_provider()
    assert provider.name == "cloudflare_workers_ai"
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MAX_BYTES", 10)
    result = provider.transcribe_bytes(audio=b"x" * 11, content_type="audio/wav", language=None)
    assert result.status == "failed" and result.retryable is False
    assert result.error == "audio_exceeds_provider_input_bound"


def test_cloudflare_workers_ai_json_base64_and_response_provenance(monkeypatch):
    endpoint, model = _configure_cloudflare_transcription(monkeypatch)

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "success": True,
                "errors": [],
                "messages": [],
                "result": {
                    "text": "irrigation ran forty five minutes on Block A",
                    "transcription_info": {"language": "en", "word_count": 8},
                    "segments": [{"start": 0.0, "end": 2.0}],
                    "vtt": "WEBVTT",
                },
            }

    class _Client:
        def __init__(self, timeout=None):
            _Client.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            _Client.seen = {"url": url, "headers": headers, "json": json}
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    audio = b"RIFF" + b"field-audio"
    result = CloudflareWorkersAITranscriptionProvider().transcribe_bytes(
        audio=audio, content_type="audio/wav", language=None
    )
    assert result.succeeded and result.model == model and result.language == "en"
    assert result.metadata["transport"] == "cloudflare_workers_ai_json_base64"
    assert result.metadata["word_count"] == 8
    assert result.metadata["segment_count"] == 1
    assert result.metadata["vtt_available"] is True
    assert _Client.seen["url"] == endpoint
    assert _Client.seen["headers"]["Authorization"] == "Bearer cf-staging-token"
    assert base64.b64decode(_Client.seen["json"]["audio"]) == audio
    assert _Client.seen["json"]["task"] == "transcribe"
    assert _Client.seen["json"]["vad_filter"] is True
    assert _Client.seen["json"]["condition_on_previous_text"] is False
    assert "language" not in _Client.seen["json"]


def test_cloudflare_workers_ai_language_hint_endpoint_guard_and_retry(monkeypatch):
    endpoint, _model = _configure_cloudflare_transcription(monkeypatch)

    class _EnvelopeError:
        status_code = 200

        @staticmethod
        def json():
            return {"success": False, "errors": [{"message": "rate limit exceeded"}]}

    class _Client:
        calls = 0

        def __init__(self, timeout=None): ...
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def post(self, url, headers=None, json=None):
            _Client.calls += 1
            assert url == endpoint and json["language"] == "fr"
            return _EnvelopeError()

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)
    provider = CloudflareWorkersAITranscriptionProvider()
    result = provider.transcribe_bytes(audio=b"audio", content_type="audio/wav", language="fr")
    assert result.status == "failed" and result.error == "provider_envelope_error"
    assert result.retryable is True and _Client.calls == 1

    monkeypatch.setattr(
        "app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT",
        "https://evil.example/client/v4/accounts/x/ai/run/@cf/openai/whisper-large-v3-turbo",
    )
    blocked = provider.transcribe_bytes(audio=b"audio", content_type="audio/wav", language=None)
    assert blocked.error == "invalid_cloudflare_workers_ai_endpoint"
    assert blocked.retryable is False and _Client.calls == 1


def test_cloudflare_workers_ai_readiness_requires_official_matching_endpoint(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        FIELD_INTELLIGENCE_RELEASE_STATE="internal",
        FIELD_TRANSCRIPTION_PROVIDER="cloudflare_workers_ai",
        FIELD_TRANSCRIPTION_ENDPOINT="https://evil.example/ai/run/@cf/openai/whisper-large-v3-turbo",
        FIELD_TRANSCRIPTION_API_KEY="configured",
        FIELD_TRANSCRIPTION_MODEL="@cf/openai/whisper-large-v3-turbo",
    )
    assert "field_intelligence.transcription_endpoint_invalid" in codes
'''
text = replace_once(
    text,
    "\n\n# --------------------------------------------------------------------------- #\n# Metrics / logging redaction\n",
    cloudflare_tests + "\n\n# --------------------------------------------------------------------------- #\n# Metrics / logging redaction\n",
    "Cloudflare tests insertion",
)
write(path, text)


# The staging contract's default valid fixture now exercises Cloudflare directly.
path = "agroai_api/tests/unit/test_field_intelligence_staging_contract.py"
text = read(path)
text = replace_once(
    text,
    '    "FIELD_STAGING_TRANSCRIPTION_PROVIDER": "openai_whisper",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://stt-staging.example/v1/audio/transcriptions",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_API_KEY": "staging-stt-key",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_MODEL": "whisper-1",\n',
    '    "FIELD_STAGING_TRANSCRIPTION_PROVIDER": "cloudflare_workers_ai",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://api.cloudflare.com/client/v4/accounts/stageacct123/ai/run/@cf/openai/whisper-large-v3-turbo",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_API_KEY": "staging-workers-ai-key",\n'
    '    "FIELD_STAGING_TRANSCRIPTION_MODEL": "@cf/openai/whisper-large-v3-turbo",\n',
    "staging Cloudflare fixture",
)
additional_staging_test = '''


def test_cloudflare_transcription_endpoint_is_account_scoped_and_model_matched():
    code, payload = run_contract({
        "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://evil.example/client/v4/accounts/x/ai/run/@cf/openai/whisper-large-v3-turbo",
    })
    assert code == 1
    assert any("official account-scoped ai/run URL" in item for item in payload["failures"])

    code, payload = run_contract({
        "FIELD_STAGING_TRANSCRIPTION_ENDPOINT": "https://api.cloudflare.com/client/v4/accounts/stageacct123/ai/run/@cf/openai/whisper",
    })
    assert code == 1
    assert any("matching the model" in item for item in payload["failures"])
'''
text = replace_once(
    text,
    "\n\ndef test_release_state_general_is_refused_and_canary_is_double_confirmed():",
    additional_staging_test + "\n\ndef test_release_state_general_is_refused_and_canary_is_double_confirmed():",
    "staging endpoint tests",
)
write(path, text)

print("Cloudflare Workers AI transcription adaptation applied")
