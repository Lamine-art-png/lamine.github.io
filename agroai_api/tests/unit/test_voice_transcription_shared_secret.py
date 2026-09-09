from app.core.config import settings
from app.services.field_transcription import (
    OpenAIWhisperTranscriptionProvider,
    _openai_transcription_api_key,
    _openai_transcription_endpoint,
    _openai_transcription_model,
)


def test_openai_transcription_reuses_realtime_secret(monkeypatch):
    monkeypatch.setattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "")
    monkeypatch.setattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "")
    monkeypatch.setattr(settings, "FIELD_TRANSCRIPTION_MODEL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGROAI_REALTIME_API_KEY", "shared-voice-secret")

    assert _openai_transcription_api_key() == "shared-voice-secret"
    assert _openai_transcription_endpoint() == "https://api.openai.com/v1/audio/transcriptions"
    assert _openai_transcription_model() == "gpt-transcribe"
    assert OpenAIWhisperTranscriptionProvider().available() is True


def test_field_transcription_secret_still_has_precedence(monkeypatch):
    monkeypatch.setattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "field-secret")
    monkeypatch.setenv("AGROAI_REALTIME_API_KEY", "shared-voice-secret")

    assert _openai_transcription_api_key() == "field-secret"
