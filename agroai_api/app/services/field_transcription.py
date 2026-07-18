"""Transcription provider abstraction for Field Intelligence.

The application must stay functional when no transcription provider is
configured. Provider selection lives here, never in routes. A failed run is
reported as failed — we never claim a successful transcript for failed audio.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

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
    attempt_count: int = 1
    metadata: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and bool(self.transcript)


class TranscriptionProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def transcribe(self, *, audio_ref: str | None, language: str | None, note_text: str | None) -> TranscriptionResult: ...


class TypedNoteFallbackProvider:
    """Deterministic fallback used when there is no audio to transcribe.

    A typed note is authoritative text, not a transcript, so it is surfaced as a
    ``skipped`` transcription with the typed content preserved downstream.
    """

    name = "typed_note"

    def available(self) -> bool:
        return True

    def transcribe(self, *, audio_ref, language, note_text) -> TranscriptionResult:
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

    def transcribe(self, *, audio_ref, language, note_text) -> TranscriptionResult:
        return TranscriptionResult(
            provider=self.name,
            status="unavailable",
            transcript=(note_text or "").strip() or None,
            language=language,
            error="transcription_provider_not_configured",
            metadata={"audio_ref_present": bool(audio_ref)},
        )


class FakeTranscriptionProvider:
    """Deterministic provider for tests and demos.

    Produces a stable, non-fabricated marker transcript so pipelines can be
    exercised end to end without an external dependency.
    """

    name = "fake"

    def __init__(self, *, fail: bool = False):
        self._fail = fail

    def available(self) -> bool:
        return True

    def transcribe(self, *, audio_ref, language, note_text) -> TranscriptionResult:
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
        base = (note_text or "").strip()
        transcript = base or f"[fake transcript for {audio_ref or 'audio'}]"
        return TranscriptionResult(
            provider=self.name,
            status="completed",
            transcript=transcript,
            model="fake-1",
            language=language or "en",
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def get_transcription_provider() -> TranscriptionProvider:
    """Resolve the configured provider without importing provider SDKs eagerly."""
    mode = str(getattr(settings, "FIELD_TRANSCRIPTION_PROVIDER", "") or "").strip().lower()
    if mode in {"fake", "test"}:
        return FakeTranscriptionProvider()
    if mode in {"fake_fail", "test_fail"}:
        return FakeTranscriptionProvider(fail=True)
    # A real provider (e.g. a hosted speech-to-text service) would be
    # constructed here from settings. Until one is configured we fail closed to
    # the disabled provider so audio is never silently dropped or faked.
    return DisabledTranscriptionProvider()


def transcribe_capture(*, audio_ref: str | None, language: str | None, note_text: str | None) -> TranscriptionResult:
    """Public entrypoint: choose fallback vs provider based on available media."""
    if not audio_ref:
        return TypedNoteFallbackProvider().transcribe(audio_ref=None, language=language, note_text=note_text)
    provider = get_transcription_provider()
    return provider.transcribe(audio_ref=audio_ref, language=language, note_text=note_text)
