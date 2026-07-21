from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing replacement marker: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Backend provider: direct Cloudflare in staging, protected edge binding in prod.
# ---------------------------------------------------------------------------
path = "agroai_api/app/services/field_transcription.py"
text = read(path)

old_available = '''    def available(self) -> bool:
        return bool(
            str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
            and str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        )
'''
new_available = '''    @staticmethod
    def _internal_edge_endpoint() -> str:
        api_url = str(getattr(settings, "API_URL", "") or "").strip().rstrip("/")
        return f"{api_url}/v1/internal/edge/field-transcription" if api_url else ""

    @staticmethod
    def _resolved_endpoint() -> str:
        explicit = str(getattr(settings, "FIELD_TRANSCRIPTION_ENDPOINT", "") or "").strip()
        if explicit:
            return explicit
        if str(getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "") or "").strip():
            return CloudflareWorkersAITranscriptionProvider._internal_edge_endpoint()
        return ""

    @staticmethod
    def _resolved_api_key() -> str:
        explicit = str(getattr(settings, "FIELD_TRANSCRIPTION_API_KEY", "") or "").strip()
        if explicit:
            return explicit
        return str(getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "") or "").strip()

    @classmethod
    def uses_internal_edge(cls, endpoint: str | None = None) -> bool:
        candidate = (endpoint or cls._resolved_endpoint()).rstrip("/")
        internal = cls._internal_edge_endpoint().rstrip("/")
        return bool(candidate and internal and candidate == internal)

    def available(self) -> bool:
        return bool(self._resolved_endpoint() and self._resolved_api_key())
'''
# Replace only the Cloudflare provider's available block, not earlier providers.
cloudflare_start = text.index("class CloudflareWorkersAITranscriptionProvider:")
prefix, cloudflare = text[:cloudflare_start], text[cloudflare_start:]
cloudflare = replace_once(cloudflare, old_available, new_available, "cloudflare available resolver")
text = prefix + cloudflare

pattern = re.compile(
    r'''    @classmethod\n    def endpoint_valid\(cls, endpoint: str, model: str\) -> bool:\n.*?\n\n    @staticmethod\n    def _envelope_retryable''',
    re.S,
)
new_endpoint_guard = '''    @classmethod
    def endpoint_valid(cls, endpoint: str, model: str) -> bool:
        try:
            parsed = urlparse(endpoint)
        except ValueError:
            return False
        normalized_model = (model or cls.default_model).strip()
        path = (parsed.path or "").rstrip("/")
        clean_https = bool(
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        if not clean_https:
            return False
        if (parsed.hostname or "").lower() == "api.cloudflare.com":
            return bool(
                path.startswith("/client/v4/accounts/")
                and path.endswith(f"/ai/run/{normalized_model}")
            )
        internal = urlparse(cls._internal_edge_endpoint())
        return bool(
            normalized_model == cls.default_model
            and parsed.netloc.lower() == internal.netloc.lower()
            and path == (internal.path or "").rstrip("/")
        )

    @staticmethod
    def _envelope_retryable'''
text, count = pattern.subn(new_endpoint_guard, text, count=1)
if count != 1:
    raise SystemExit("missing Cloudflare endpoint guard")

text = replace_once(
    text,
    '''        endpoint = str(settings.FIELD_TRANSCRIPTION_ENDPOINT).strip()
        api_key = str(settings.FIELD_TRANSCRIPTION_API_KEY).strip()
        model = (
            str(getattr(settings, "FIELD_TRANSCRIPTION_MODEL", "") or "").strip()
            or self.default_model
        )
''',
    '''        endpoint = self._resolved_endpoint()
        api_key = self._resolved_api_key()
        model = (
            str(getattr(settings, "FIELD_TRANSCRIPTION_MODEL", "") or "").strip()
            or self.default_model
        )
''',
    "resolved Cloudflare credentials",
)
text = replace_once(
    text,
    '''        if language:
            request_payload["language"] = language

        try:
''',
    '''        if language:
            request_payload["language"] = language
        if self.uses_internal_edge(endpoint):
            request_payload["model"] = model

        try:
''',
    "internal edge model payload",
)
text = replace_once(
    text,
    '''                "transport": "cloudflare_workers_ai_json_base64",
''',
    '''                "transport": (
                    "agroai_edge_workers_ai_json_base64"
                    if self.uses_internal_edge(endpoint)
                    else "cloudflare_workers_ai_json_base64"
                ),
''',
    "provider transport provenance",
)
text = replace_once(
    text,
    '''    mode = str(getattr(settings, "FIELD_TRANSCRIPTION_PROVIDER", "") or "").strip().lower()
    if mode in {"fake", "test"}:
''',
    '''    mode = str(getattr(settings, "FIELD_TRANSCRIPTION_PROVIDER", "") or "").strip().lower()
    if not mode:
        environment = str(getattr(settings, "APP_ENV", "development") or "development").strip().lower()
        cloudflare = CloudflareWorkersAITranscriptionProvider()
        if environment in {"production", "staging"} and cloudflare.available() and cloudflare.uses_internal_edge():
            return cloudflare
    if mode in {"fake", "test"}:
''',
    "automatic production edge provider selection",
)
write(path, text)


# ---------------------------------------------------------------------------
# Production readiness recognizes the same fail-closed edge bridge.
# ---------------------------------------------------------------------------
path = "agroai_api/app/services/production_readiness.py"
text = read(path)
text = replace_once(
    text,
    '''    release_state = _setting(settings, "FIELD_INTELLIGENCE_RELEASE_STATE").lower()
    if release_state in {"", "disabled"}:
        return  # not activating: no additional launch requirements
''',
    '''    release_state = _setting(settings, "FIELD_INTELLIGENCE_RELEASE_STATE").lower()
    if not release_state:
        internal_operators = bool(
            _setting(settings, "PLATFORM_ADMIN_EMAILS")
            or _setting(settings, "INTERNAL_FULL_ACCESS_EMAILS")
        )
        if _setting(settings, "APP_ENV").lower() in {"production", "staging"} and internal_operators:
            release_state = "internal"
    if release_state in {"", "disabled"}:
        return  # not activating: no additional launch requirements
''',
    "effective internal release readiness",
)
old_provider = '''    provider = _setting(settings, "FIELD_TRANSCRIPTION_PROVIDER").lower()
    if provider in {"", "disabled"}:
        blockers.append(ReadinessFinding(
            "field_intelligence.transcription_provider_missing", "blocker", "field_intelligence",
            "Field Intelligence activation requires a configured transcription provider (voice capture fails closed without one).",
        ))
'''
new_provider = '''    provider = _setting(settings, "FIELD_TRANSCRIPTION_PROVIDER").lower()
    edge_transcription = bool(
        not provider
        and _setting(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN")
        and _setting(settings, "API_URL").startswith("https://")
    )
    if edge_transcription:
        provider = "cloudflare_workers_ai"
    if provider in {"", "disabled"}:
        blockers.append(ReadinessFinding(
            "field_intelligence.transcription_provider_missing", "blocker", "field_intelligence",
            "Field Intelligence activation requires a configured transcription provider (voice capture fails closed without one).",
        ))
'''
text = replace_once(text, old_provider, new_provider, "edge provider readiness selection")
text = replace_once(
    text,
    '''        if not _setting(settings, "FIELD_TRANSCRIPTION_ENDPOINT") or not _setting(settings, "FIELD_TRANSCRIPTION_API_KEY"):
            blockers.append(ReadinessFinding(
                "field_intelligence.transcription_credentials_missing", "blocker", "field_intelligence",
                "The transcription provider requires both endpoint and API key.",
            ))
        if provider in {"cloudflare_workers_ai", "workers_ai", "cloudflare_whisper"}:
            endpoint = urlparse(_setting(settings, "FIELD_TRANSCRIPTION_ENDPOINT"))
''',
    '''        endpoint_value = _setting(settings, "FIELD_TRANSCRIPTION_ENDPOINT")
        api_key_value = _setting(settings, "FIELD_TRANSCRIPTION_API_KEY")
        if edge_transcription:
            endpoint_value = _setting(settings, "API_URL").rstrip("/") + "/v1/internal/edge/field-transcription"
            api_key_value = _setting(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN")
        if not endpoint_value or not api_key_value:
            blockers.append(ReadinessFinding(
                "field_intelligence.transcription_credentials_missing", "blocker", "field_intelligence",
                "The transcription provider requires both endpoint and API key.",
            ))
        if provider in {"cloudflare_workers_ai", "workers_ai", "cloudflare_whisper"}:
            endpoint = urlparse(endpoint_value)
''',
    "resolved readiness credentials",
)
old_guard = '''            if not (
                endpoint.scheme == "https"
                and (endpoint.hostname or "").lower() == "api.cloudflare.com"
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.query
                and not endpoint.fragment
                and path.startswith("/client/v4/accounts/")
                and path.endswith(expected_suffix)
            ):
'''
new_guard = '''            official_direct = bool(
                endpoint.scheme == "https"
                and (endpoint.hostname or "").lower() == "api.cloudflare.com"
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.query
                and not endpoint.fragment
                and path.startswith("/client/v4/accounts/")
                and path.endswith(expected_suffix)
            )
            internal_edge = bool(
                edge_transcription
                and endpoint.scheme == "https"
                and endpoint.netloc == urlparse(_setting(settings, "API_URL")).netloc
                and path == "/v1/internal/edge/field-transcription"
                and model == "@cf/openai/whisper-large-v3-turbo"
            )
            if not (official_direct or internal_edge):
'''
text = replace_once(text, old_guard, new_guard, "readiness endpoint guard")
text = text.replace(
    "Cloudflare Workers AI transcription requires the official account-scoped HTTPS ai/run endpoint matching the configured model.",
    "Cloudflare Workers AI transcription requires either the official account-scoped ai/run endpoint or the protected AGRO-AI edge bridge matching the approved model.",
    1,
)
write(path, text)


# ---------------------------------------------------------------------------
# Tests: internal launch, portal device policy, edge-provider fallback/readiness.
# ---------------------------------------------------------------------------
path = "agroai_api/tests/unit/test_field_intelligence_launch.py"
text = read(path)
text = replace_once(
    text,
    '''def test_default_state_is_disabled_in_production(monkeypatch, db):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    _set_state(monkeypatch, "")
    assert rollout.configured_release_state() == "disabled"
    assert rollout.effective_release_state(db) == "disabled"
''',
    '''def test_default_state_is_disabled_in_production(monkeypatch, db):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "")
    monkeypatch.setattr("app.core.config.settings.INTERNAL_FULL_ACCESS_EMAILS", "")
    _set_state(monkeypatch, "")
    assert rollout.configured_release_state() == "disabled"
    assert rollout.effective_release_state(db) == "disabled"


def test_configured_platform_admin_organization_gets_internal_launch(client, db, monkeypatch):
    _auth(db)
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ADMIN_EMAILS", "fi@example.com")
    monkeypatch.setattr("app.core.config.settings.INTERNAL_FULL_ACCESS_EMAILS", "")
    _set_state(monkeypatch, "")
    headers = _auth_headers_for_existing_user(db, "fi@example.com")
    assert rollout.configured_release_state() == "internal"
    result = _initiate(client, headers, client_capture_id="internal-live", idempotency_key="internal-live")
    assert result.status_code == 200, result.text
''',
    "production internal launch test",
)
# Add a small helper without duplicating the fixture records.
text = replace_once(
    text,
    '''def _set_state(monkeypatch, value):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", value)
''',
    '''def _set_state(monkeypatch, value):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", value)


def _auth_headers_for_existing_user(db, email: str):
    from app.core.security import create_access_token
    from app.models.saas import OrganizationMembership, User

    user = db.query(User).filter(User.email == email).one()
    membership = db.query(OrganizationMembership).filter(OrganizationMembership.user_id == user.id).one()
    token = create_access_token({
        "sub": user.id,
        "tenant_id": membership.organization_id,
        "org_id": membership.organization_id,
        "role": membership.role,
    })
    return {"Authorization": f"Bearer {token}"}
''',
    "existing-user auth helper",
)
append = '''


def test_cloudflare_workers_ai_production_edge_fallback(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.API_URL", "https://api.agroai-pilot.com")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_ENDPOINT", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_API_KEY", "")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_MODEL", "")
    monkeypatch.setattr("app.core.config.settings.CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "edge-consumer-secret")
    provider = get_transcription_provider()
    assert provider.name == "cloudflare_workers_ai"
    assert provider.available() is True
    assert provider.uses_internal_edge() is True
    assert provider._resolved_endpoint() == "https://api.agroai-pilot.com/v1/internal/edge/field-transcription"
    assert provider._resolved_api_key() == "edge-consumer-secret"


def test_internal_launch_readiness_accepts_protected_edge_transcription(monkeypatch):
    codes = _readiness_codes(
        monkeypatch,
        APP_ENV="production",
        FIELD_INTELLIGENCE_RELEASE_STATE="",
        PLATFORM_ADMIN_EMAILS="fi@example.com",
        INTERNAL_FULL_ACCESS_EMAILS="",
        FIELD_TRANSCRIPTION_PROVIDER="",
        FIELD_TRANSCRIPTION_ENDPOINT="",
        FIELD_TRANSCRIPTION_API_KEY="",
        FIELD_TRANSCRIPTION_MODEL="",
        API_URL="https://api.agroai-pilot.com",
        CLOUDFLARE_QUEUE_CONSUMER_TOKEN="edge-consumer-secret",
        CONNECTOR_OBJECT_STORAGE_BACKEND="r2",
        CONNECTOR_OBJECT_BUCKET="agroai-connector-objects-prod",
    )
    assert "field_intelligence.transcription_provider_missing" not in codes
    assert "field_intelligence.transcription_credentials_missing" not in codes
    assert "field_intelligence.transcription_endpoint_invalid" not in codes


def test_portal_allows_first_party_field_capture_devices():
    headers_path = Path(__file__).resolve().parents[3] / "figma-enterprise-v4" / "public" / "_headers"
    headers = headers_path.read_text(encoding="utf-8")
    assert "microphone=(self)" in headers
    assert "geolocation=(self)" in headers
    assert "microphone=()" not in headers
    assert "geolocation=()" not in headers
'''
# Path is needed only for the new portal contract.
text = replace_once(text, "import os\n", "import os\nfrom pathlib import Path\n", "Path import")
if "test_cloudflare_workers_ai_production_edge_fallback" not in text:
    marker = "\n\n# --------------------------------------------------------------------------- #\n# Metrics / logging redaction\n"
    text = replace_once(text, marker, append + marker, "production launch test insertion")
write(path, text)

print("production Field Intelligence launch patch applied")
