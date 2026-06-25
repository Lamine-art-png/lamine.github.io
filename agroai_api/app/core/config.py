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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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

<<<<<<< ours
    # SaaS app + Stripe billing
    APP_URL: str = "https://app.agroai-pilot.com"
    API_URL: str = "https://api.agroai-pilot.com"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Current AGRO-AI commercial offers
    STRIPE_PRICE_ASSURANCE_AUDIT_FARM: str = ""
    STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK: str = ""
    STRIPE_PRICE_WATEROPS_MONTHLY: str = ""
    STRIPE_PRICE_ASSURANCE_MONTHLY: str = ""

    # Legacy names kept for backwards compatibility with older frontends/tests.
    STRIPE_PRICE_PILOT: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""
=======
    # AI gateway. Leave unset to keep startup safe and return deterministic
    # unavailable responses instead of fabricated model output.
    AI_PROVIDER: str = ""
    AI_BASE_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL: str = ""
    AI_TIMEOUT_SECONDS: int = 30
>>>>>>> theirs

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
