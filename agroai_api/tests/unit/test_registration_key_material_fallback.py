from app.core.config import settings
from app.services.identity_vault import decrypt_phone, encrypt_phone
from app.services.security_audit import privacy_hash


def test_identity_vault_works_with_secret_key_only(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "production-signing-secret-with-sufficient-length")
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "")

    protected = encrypt_phone(
        "+1 415 555 0199",
        organization_id="org-registration-fallback",
        profile_id="profile-registration-fallback",
    )

    assert protected["algorithm"] == "AES-256-GCM"
    assert protected["key_version"] == "derived-identity-secret-key-v1"
    assert protected["last4"] == "0199"
    assert decrypt_phone(
        ciphertext_b64=protected["ciphertext_b64"],
        nonce_b64=protected["nonce_b64"],
        organization_id="org-registration-fallback",
        profile_id="profile-registration-fallback",
        key_version=protected["key_version"],
    ) == "+14155550199"


def test_security_audit_hash_works_with_secret_key_only(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "production-signing-secret-with-sufficient-length")
    monkeypatch.setattr(settings, "WEBHOOK_SECRET", "")

    first = privacy_hash("Owner@Example.com", "subject")
    second = privacy_hash("owner@example.com", "subject")

    assert first
    assert first == second
    assert "owner@example.com" not in first
