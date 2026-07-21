"""Transcription provider abstraction for Field Intelligence.

Selection lives here, never in routes. Providers operate on durable audio
bytes retrieved from the authorized object store (never on client-supplied
references). A failed run is reported as failed — we never claim a successful
transcript for failed or absent audio.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from app.core.config import settings


@dataclass
class TranscriptionResult:
    provider: str
    status: str  # completed | failed | unavailable | skipped
    transcript: str | None = None
    model: str | None = None
    language: str | None = None
    duration_seconds: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    # True => a transient provider error (429/5xx/timeout/network); the durable
    # job should retry with backoff. False => terminal (invalid audio, 4xx).
    retryable: bool = False
    attempt_count: int = 1
    metadata: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.transcript)


# HTTP status codes / error classes that warrant a durable retry.
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class RetryableTranscriptionError(Exception):
    """Raised by callers to force durable job retry on a transient failure.

    ``provenance`` carries the attempted run's provider/model/classification/
    latency so the durable plane can persist attempt provenance even though the
    pipeline transaction rolls back.
    """

    def __init__(self, message: str, *, provenance: dict | None = None):
        super().__init__(message)
        self.provenance = provenance or {}


def classify_transcription_error(error: str | None) -> str:
    """Map a provider error string onto a stable HTTP/transport classification."""
    text = (error or "").strip().lower()
    if not text:
        return "unclassified"
    import re as _re

    match = _re.search(r"(?:http[_ ]?|_)(\d{3})\b", text)
    if match:
        code = int(match.group(1))
        if code in _RETRYABLE_HTTP:
            return f"http_{code}_retryable"
        return f"http_{code}"
    if any(tok in text for tok in ("timeout", "connect", "network", "pool", "protocol", "read")):
        return "transport_transient"
    return "unclassified"


class TranscriptionProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def transcribe_bytes(
        self, *, audio: bytes, content_type: str | None, language: str | None
    ) -> TranscriptionResult: ...


class TypedNoteFallbackProvider:
    """Used when there is no audio to transcribe.

    A typed note is authoritative text, not a transcript, so it is surfaced as a
    ``skipped`` transcription with the typed content preserved downstream.
    """

    name = "typed_note"

    def available(self) -> bool:
        return True

    def transcribe_typed(self, *, note_text: str | None, language: str | None) -> TranscriptionResult:
        return TranscriptionResult(
            provider=self.name,
            status="skipped",
            transcript=(note_text or "").strip() or None,
            language=language,
            metadata={"reason": "typed_note_no_audio"},
        )


class DisabledTranscriptionProvider:
    """Selected when audio exists but no provider is configured.

    Truthful: audio is present but cannot be transcribed here, so the run is
    reported ``unavailable`` rather than fabricating a transcript.
    """

    name = "disabled"

    def available(self) -> bool:
        return False

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        return TranscriptionResult(
            provider=self.name,
            status="unavailable",
            transcript=None,
            language=language,
            error="transcription_provider_not_configured",
            metadata={"audio_bytes": len(audio or b"")},
        )


class FakeTranscriptionProvider:
    """Deterministic provider for tests and demos.

    Produces a stable, non-fabricated marker transcript derived from the audio
    length so pipelines can be exercised without an external dependency.
    """

    name = "fake"

    def __init__(self, *, fail: bool = False):
        self._fail = fail

    def available(self) -> bool:
        return True

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        started = time.monotonic()
        if self._fail:
            return TranscriptionResult(
                provider=self.name,
                status="failed",
                model="fake-1",
                language=language or "en",
                error="synthetic_transcription_failure",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        transcript = f"[fake transcript of {len(audio or b'')} audio bytes]"
        return TranscriptionResult(
            provider=self.name,
            status="completed",
            transcript=transcript,
            model="fake-1",
            language=language or "en",
            latency_ms=int((time.monotonic() - started) * 1000),
            metadata={"audio_bytes": len(audio or b"")},
        )


def _provider_timeout() -> float:
    try:
        return max(1.0, float(getattr(settings, "FIELD_TRANSCRIPTION_TIMEOUT_SECONDS", 60.0)))
    except (TypeError, ValueError):
        return 60.0


def _input_bound_error(provider_name: str, audio: bytes | None, language: str | None) -> TranscriptionResult | None:
    """Terminal (non-retryable) rejection for provider input beyond the bound."""
    limit = int(getattr(settings, "FIELD_TRANSCRIPTION_MAX_BYTES", 26214400) or 26214400)
    if audio is not None and len(audio) > limit:
        return TranscriptionResult(
            provider=provider_name, status="failed", language=language,
            error="audio_exceeds_provider_input_bound", retryable=False,
            metadata={"audio_bytes": len(audio), "limit_bytes": limit},
        )
    return None


class OpenAIWhisperTranscriptionProvider:
    """Production speech-to-text via an OpenAI-compatible transcription API.

    Posts multipart ``file`` + ``model`` (+ optional ``language``) to the
    configured ``/audio/transcriptions``-style endpoint. Multilingual by
    default: when no language hint is supplied the provider detects it, and
    the detected language is preserved as provenance. Credentials come from
    settings and are never logged or echoed.
    """

    name = "openai_whisper"

    _EXTENSIONS = {
        "audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg",
        "audio/mpeg": "mp3", "audio/mp4": "m4a", "video/mp4": "mp4",
        "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac",
    }

    def available(self) -> bool:
        return bool(
            str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
            and str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        )

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        started = time.monotonic()
        if not self.available():
            return TranscriptionResult(
                provider=self.name, status="unavailable",
                error="transcription_provider_not_configured", language=language,
            )
        bound = _input_bound_error(self.name, audio, language)
        if bound is not None:
            return bound
        endpoint = str(settings.FIELD_TRANSCRIPTION_ENDPOINT).strip()
        api_key = str(settings.FIELD_TRANSCRIPTION_API_KEY).strip()
        model = str(getattr(settings, "FIELD_TRANSCRIPTION_MODEL", "") or "").strip() or "whisper-1"
        extension = self._EXTENSIONS.get((content_type or "").split(";")[0].strip().lower(), "webm")
        try:
            import httpx

            data: dict = {"model": model, "response_format": "json"}
            if language:
                data["language"] = language  # hint only; detection otherwise
            files = {"file": (f"audio.{extension}", audio, content_type or "application/octet-stream")}
            with httpx.Client(timeout=_provider_timeout()) as http:
                response = http.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files=files,
                )
            latency = int((time.monotonic() - started) * 1000)
            if response.status_code >= 400:
                return TranscriptionResult(
                    provider=self.name, status="failed", model=model, language=language,
                    latency_ms=latency, error=f"provider_http_{response.status_code}",
                    retryable=response.status_code in _RETRYABLE_HTTP,
                )
            payload = response.json()
            transcript = str(payload.get("text") or "").strip()
            if not transcript:
                return TranscriptionResult(
                    provider=self.name, status="failed", model=model, language=language,
                    latency_ms=latency, error="provider_returned_empty_transcript", retryable=False,
                )
            detected = str(payload.get("language") or "").strip() or None
            return TranscriptionResult(
                provider=self.name, status="completed", transcript=transcript, model=model,
                language=detected or language, latency_ms=latency,
                metadata={"detected_language": detected, "language_hint": language,
                          "audio_bytes": len(audio or b"")},
            )
        except Exception as exc:  # noqa: BLE001 - surface failure truthfully
            name = exc.__class__.__name__.lower()
            transient = any(tok in name for tok in ("timeout", "connect", "network", "pool", "protocol", "read"))
            return TranscriptionResult(
                provider=self.name, status="failed", model=model, language=language,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=exc.__class__.__name__, retryable=transient,
            )


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


class HttpTranscriptionProvider:
    """Real, configured speech-to-text adapter (provider-neutral HTTP).

    Reads endpoint + API key from settings and posts the audio bytes. If the
    required configuration is absent it reports ``unavailable`` (fail closed);
    request failures report ``failed``. Provider-specific wiring stays here, out
    of routes. Credentials are never logged or echoed back to callers.
    """

    name = "http"

    def available(self) -> bool:
        return bool(
            str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
            and str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        )

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        started = time.monotonic()
        if not self.available():
            return TranscriptionResult(
                provider=self.name, status="unavailable",
                error="transcription_provider_not_configured", language=language,
            )
        bound = _input_bound_error(self.name, audio, language)
        if bound is not None:
            return bound
        endpoint = str(settings.FIELD_TRANSCRIPTION_ENDPOINT).strip()
        api_key = str(settings.FIELD_TRANSCRIPTION_API_KEY).strip()
        model = str(getattr(settings, "FIELD_TRANSCRIPTION_MODEL", "") or "").strip() or None
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": content_type or "application/octet-stream",
            }
            params = {"language": language or "en"}
            if model:
                params["model"] = model
            with httpx.Client(timeout=_provider_timeout()) as http:
                response = http.post(endpoint, content=audio, headers=headers, params=params)
            latency = int((time.monotonic() - started) * 1000)
            if response.status_code >= 400:
                return TranscriptionResult(
                    provider=self.name, status="failed", model=model, language=language,
                    latency_ms=latency, error=f"provider_http_{response.status_code}",
                    retryable=response.status_code in _RETRYABLE_HTTP,
                )
            payload = response.json()
            transcript = (payload.get("text") or payload.get("transcript") or "").strip()
            if not transcript:
                # Empty transcript from a 2xx is treated as terminal (no text).
                return TranscriptionResult(
                    provider=self.name, status="failed", model=model, language=language,
                    latency_ms=latency, error="provider_returned_empty_transcript", retryable=False,
                )
            return TranscriptionResult(
                provider=self.name, status="completed", transcript=transcript, model=model,
                language=payload.get("language") or language, latency_ms=latency,
            )
        except Exception as exc:  # noqa: BLE001 - surface failure truthfully
            # Timeouts and network/connection errors are transient -> retryable.
            name = exc.__class__.__name__.lower()
            transient = any(tok in name for tok in ("timeout", "connect", "network", "pool", "protocol", "read"))
            return TranscriptionResult(
                provider=self.name, status="failed", model=model, language=language,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=exc.__class__.__name__, retryable=transient,
            )


# Process-local counter so the retry provider can fail transiently a bounded
# number of times before succeeding, exercising durable auto-retry.
_FAKE_RETRY_ATTEMPTS = {"n": 0}


class FakeRetryTranscriptionProvider:
    """Fails with a retryable error for the first N attempts, then succeeds."""

    name = "fake_retry"

    def __init__(self, fail_times: int = 1):
        self._fail_times = fail_times

    def available(self) -> bool:
        return True

    def transcribe_bytes(self, *, audio, content_type, language) -> TranscriptionResult:
        _FAKE_RETRY_ATTEMPTS["n"] += 1
        if _FAKE_RETRY_ATTEMPTS["n"] <= self._fail_times:
            return TranscriptionResult(
                provider=self.name, status="failed", model="fake-retry", language=language or "en",
                error="synthetic_transient_503", retryable=True,
            )
        return TranscriptionResult(
            provider=self.name, status="completed", model="fake-retry", language=language or "en",
            transcript=f"[fake retry transcript of {len(audio or b'')} audio bytes]",
        )


def reset_fake_retry_state() -> None:
    _FAKE_RETRY_ATTEMPTS["n"] = 0


def get_transcription_provider() -> TranscriptionProvider:
    """Resolve the configured provider without importing provider SDKs eagerly."""
    mode = str(getattr(settings, "FIELD_TRANSCRIPTION_PROVIDER", "") or "").strip().lower()
    if mode in {"fake", "test"}:
        return FakeTranscriptionProvider()
    if mode in {"fake_fail", "test_fail"}:
        return FakeTranscriptionProvider(fail=True)
    if mode in {"fake_retry", "test_retry"}:
        return FakeRetryTranscriptionProvider(int(getattr(settings, "FIELD_TRANSCRIPTION_FAKE_RETRY_FAILS", 1) or 1))
    if mode in {"cloudflare_workers_ai", "workers_ai", "cloudflare_whisper"}:
        cloudflare = CloudflareWorkersAITranscriptionProvider()
        return cloudflare if cloudflare.available() else DisabledTranscriptionProvider()
    if mode in {"openai_whisper", "whisper"}:
        whisper = OpenAIWhisperTranscriptionProvider()
        return whisper if whisper.available() else DisabledTranscriptionProvider()
    if mode in {"http", "configured", "production"}:
        provider = HttpTranscriptionProvider()
        return provider if provider.available() else DisabledTranscriptionProvider()
    return DisabledTranscriptionProvider()


def transcribe_audio(*, audio: bytes | None, content_type: str | None, language: str | None,
                     note_text: str | None) -> TranscriptionResult:
    """Public entrypoint: choose typed fallback vs provider based on real audio."""
    if not audio:
        return TypedNoteFallbackProvider().transcribe_typed(note_text=note_text, language=language)
    provider = get_transcription_provider()
    if hasattr(provider, "transcribe_bytes"):
        return provider.transcribe_bytes(audio=audio, content_type=content_type, language=language)
    return DisabledTranscriptionProvider().transcribe_bytes(audio=audio, content_type=content_type, language=language)
