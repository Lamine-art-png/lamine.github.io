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
    VERSION: str = "1.0.0"
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

    # External Providers
    WISECONN_API_URL: str = "http://mock-wiseconn"
    RAINBIRD_API_URL: str = "http://mock-rainbird"
    OPENET_API_URL: str = "http://mock-openet"

    class Config:
        env_file = ".env"
        case_sensitive = True

   DEMO_API_KEY: str = "changeme-demo-key"  # override via env in prod

settings = Settings()
