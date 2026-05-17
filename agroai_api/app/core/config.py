from pydantic import field_validator
from pydantic_settings import BaseSettings
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
