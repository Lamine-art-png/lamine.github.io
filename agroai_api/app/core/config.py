from pydantic import field_validator
try:
    from pydantic_settings import BaseSettings
except ModuleNotFoundError:  # pragma: no cover - local minimal env fallback
    from pydantic import BaseModel

    class BaseSettings(BaseModel):
        def __init__(self, **values):
            import os
            annotations = getattr(self.__class__, "__annotations__", {})
            env_values = {name: os.getenv(name) for name in annotations if os.getenv(name) is not None}
            values = {**env_values, **values}
            super().__init__(**values)
from typing import Optional


class Settings(BaseSettings):
    """Application settings."""

    # Database
    DATABASE_URL: str = "sqlite:///./agroai.db"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars"
    WEBHOOK_SECRET: str = "dev-webhook-secret-change-in-production"
    ALGORITHM: str = "HS256"
    # Internal pilots need stable sessions while validating connector uploads and sync.
    # Override in production with a stricter value once refresh-token auth is added.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    # App
    APP_NAME: str = "AGRO-AI API"
    VERSION: str = "1.1.0"
    API_V1_PREFIX: str = "/v1"

    # Observability
    LOG_LEVEL: str = "INFO"
    ENABLE_METRICS: bool = True

    # Caching & Idempotency
    CACHE_TTL_HOURS: int = 6
    IDEMPOTENCY_TTL_HOURS: int = 24

    # Feature Flags
    ENABLE_WEBHOOKS: bool = True
    ENABLE_METERING: bool = True
    CALIFORNIA_COMPLIANCE_PACK_ENABLED: bool = False
    COMPLIANCE_DEMO_FIXTURES_ENABLED: bool = False
    COMPLIANCE_DEMO_TOKEN: str = ""
    COMPLIANCE_DEMO_TENANT_ID: str = "org-ca-vineyard-001"
    COMPLIANCE_ALLOW_BROWSER_TENANT_API_KEYS: bool = False
    COMPLIANCE_OBJECT_STORAGE_BACKEND: str = "disabled"

    # Scheduler
    SYNC_INTERVAL_MINUTES: int = 15  # How often to run WiseConn sync
    SYNC_LOOKBACK_DAYS: int = 14  # How many days of history to sync
    ENABLE_SCHEDULER: bool = True  # Set False to disable background sync

    # External Providers
    WISECONN_API_URL: str = "https://api.wiseconn.com"
    WISECONN_API_KEY: str = ""  # Set via env var WISECONN_API_KEY
    WISECONN_TIMEOUT_SECONDS: int = 30
    WISECONN_MAX_RETRIES: int = 3
    RAINBIRD_API_URL: str = "http://mock-rainbird"
    OPENET_API_URL: str = "http://mock-openet"

    TALGIL_API_URL: str = "https://external.talgil.com/v1"
    TALGIL_API_KEY: str = ""  # Set via env var TALGIL_API_KEY
    TALGIL_TIMEOUT_SECONDS: int = 30
    TALGIL_MAX_RETRIES: int = 3

    DEMO_API_KEY: str = "changeme-demo-key"  # override via env in prod

    # SaaS app + Stripe billing
    APP_URL: str = "https://app.agroai-pilot.com"
    API_URL: str = "https://api.agroai-pilot.com"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SUCCESS_URL: str = ""
    STRIPE_CANCEL_URL: str = ""

    # Current AGRO-AI commercial offers
    STRIPE_PRICE_ASSURANCE_AUDIT_FARM: str = ""
    STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK: str = ""
    STRIPE_PRICE_WATEROPS_MONTHLY: str = ""
    STRIPE_PRICE_ASSURANCE_MONTHLY: str = ""
    STRIPE_PRICE_PRO_MONTHLY: str = ""
    STRIPE_PRICE_PRO_ANNUAL: str = ""
    STRIPE_PRICE_TEAM_MONTHLY: str = ""
    STRIPE_PRICE_TEAM_ANNUAL: str = ""
    STRIPE_PRICE_NETWORK_MONTHLY: str = ""
    STRIPE_PRICE_NETWORK_ANNUAL: str = ""

    # Legacy names kept for backwards compatibility with older frontends/tests.
    STRIPE_PRICE_PILOT: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""

    # Email delivery and verification operations.
    # RESEND_APP_URL is intentionally separate from APP_URL so verification
    # links can be routed without disturbing other portal/runtime config.
    RESEND_API_KEY: str = ""
    RESEND_APP_URL: str = ""
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
    EMAIL_ADMIN_TOKEN: str = ""

    # AI gateway. Leave unset to keep startup safe and return deterministic
    # unavailable responses instead of fabricated model output.
    AI_PROVIDER: str = ""
    AI_BASE_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL: str = ""
    AI_FAST_MODEL: str = ""
    AI_REASONING_MODEL: str = ""
    AI_REPORT_MODEL: str = ""
    AI_LOCAL_MODEL: str = ""
    # Comma-separated OpenAI-compatible backup models. Used when the primary
    # hosted model is rejected/unavailable, so AGRO-AI does not silently fall
    # into deterministic fallback because of one bad model id.
    AI_MODEL_FALLBACKS: str = "z-ai/glm-5.2,z-ai/glm-4.5,qwen/qwen3-max,deepseek/deepseek-r1-0528"
    AI_TIMEOUT_SECONDS: int = 30

    # Connector ingestion / uploaded evidence storage.
    # Render free instances have ephemeral disk; use a Render Disk/R2/S3 later
    # for production retention. This makes uploads functional immediately.
    CONNECTOR_UPLOAD_DIR: str = "/tmp/agroai_uploads"
    DROPBOX_OAUTH_CLIENT_ID: str = ""
    BOX_OAUTH_CLIENT_ID: str = ""
    SLACK_OAUTH_CLIENT_ID: str = ""
    SALESFORCE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_EARTH_ENGINE_PROJECT_ID: str = ""
    GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON: str = ""

    # Strip whitespace/tabs from env vars that may be copy-pasted with junk
    @field_validator("*", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
