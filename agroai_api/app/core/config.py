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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    OAUTH_STATE_SIGNING_KEY: str = ""
    OAUTH_STATE_TTL_SECONDS: int = 900
    CONNECTOR_CREDENTIAL_MASTER_KEY: str = ""
    CONNECTOR_CREDENTIAL_KEYS_JSON: str = ""
    CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION: str = "v1"
    ACCOUNT_VERIFICATION_MODE: str = "auto"
    AUTH_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_FAILURE_WINDOW_MINUTES: int = 15
    AUTH_LOCKOUT_MINUTES: int = 15

    # App
    APP_NAME: str = "AGRO-AI API"
    VERSION: str = "1.1.0"
    API_V1_PREFIX: str = "/v1"
    APP_ENV: str = "development"

    # Observability
    LOG_LEVEL: str = "INFO"
    ENABLE_METRICS: bool = True

    # Caching & Idempotency
    CACHE_TTL_HOURS: int = 6
    IDEMPOTENCY_TTL_HOURS: int = 24

    # Feature Flags
    ENABLE_WEBHOOKS: bool = True
    ENABLE_METERING: bool = True
    PLATFORM_API_ENABLED: bool = False
    PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED: bool = False
    PLATFORM_API_TEST_PROJECTS_ENABLED: bool = False
    PLATFORM_API_LIVE_PROJECTS_ENABLED: bool = False
    PLATFORM_API_WEBHOOK_DELIVERY_ENABLED: bool = False
    PLATFORM_API_PUBLIC_DOCS_ENABLED: bool = False
    PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED: bool = False
    PLATFORM_API_INTERNAL_TEST_ORG_ID: str = ""
    PLATFORM_API_KEY_PEPPER: str = ""
    PLATFORM_API_RATE_LIMIT_BACKEND: str = "memory"
    PLATFORM_API_REDIS_URL: str = ""
    PLATFORM_API_RATE_LIMIT_FAIL_OPEN: bool = False
    PLATFORM_API_REDIS_MAX_RETRIES: int = 1
    PLATFORM_API_REDIS_CONNECT_TIMEOUT_SECONDS: float = 2.0
    PLATFORM_API_REDIS_SOCKET_TIMEOUT_SECONDS: float = 2.0
    PLATFORM_API_TEST_BURST_LIMIT: int = 60
    PLATFORM_API_TEST_SUSTAINED_LIMIT: int = 600
    PLATFORM_API_LIVE_BURST_LIMIT: int = 600
    PLATFORM_API_LIVE_SUSTAINED_LIMIT: int = 6000
    PLATFORM_API_IDEMPOTENCY_TTL_HOURS: int = 24
    PLATFORM_API_EDGE_AUTH_SECRET: str = ""
    PLATFORM_API_WEBHOOK_SECRET_KEYS_JSON: str = ""
    PLATFORM_API_WEBHOOK_SECRET_ACTIVE_KEY_VERSION: str = "v1"
    PLATFORM_API_WEBHOOK_ALLOWED_PORTS: str = "443"
    PLATFORM_API_WEBHOOK_TIMEOUT_SECONDS: float = 10.0
    PLATFORM_API_WEBHOOK_MAX_RESPONSE_BYTES: int = 8192
    PLATFORM_API_WEBHOOK_MAX_ATTEMPTS: int = 6
    PLATFORM_API_WEBHOOK_SECRET_OVERLAP_MINUTES: int = 60
    EARTHDAILY_ADAPTER_ENABLED: bool = False
    VALLEY_IRRIGATION_ADAPTER_ENABLED: bool = False
    VALLEY_IRRIGATION_WRITE_CAPABILITY_ENABLED: bool = False
    PROVIDER_BASE_URL_ALLOWLIST: str = ""
    CALIFORNIA_COMPLIANCE_PACK_ENABLED: bool = False
    COMPLIANCE_DEMO_FIXTURES_ENABLED: bool = False
    COMPLIANCE_DEMO_TOKEN: str = ""
    COMPLIANCE_DEMO_TENANT_ID: str = "org-ca-vineyard-001"
    COMPLIANCE_ALLOW_BROWSER_TENANT_API_KEYS: bool = False
    COMPLIANCE_OBJECT_STORAGE_BACKEND: str = "disabled"

    # Scheduler
    SYNC_INTERVAL_MINUTES: int = 15
    SYNC_LOOKBACK_DAYS: int = 14
    ENABLE_SCHEDULER: bool = False

    # External Providers
    WISECONN_API_URL: str = "https://api.wiseconn.com"
    WISECONN_API_KEY: str = ""
    WISECONN_TIMEOUT_SECONDS: int = 30
    WISECONN_MAX_RETRIES: int = 3
    RAINBIRD_API_URL: str = "http://mock-rainbird"
    OPENET_API_URL: str = "https://openet-api.org"
    OPENET_TIMEOUT_SECONDS: int = 45

    TALGIL_API_URL: str = "https://external.talgil.com/v1"
    TALGIL_API_KEY: str = ""
    TALGIL_TIMEOUT_SECONDS: int = 30
    TALGIL_MAX_RETRIES: int = 3

    DEMO_API_KEY: str = "changeme-demo-key"

    # SaaS app + Stripe billing
    APP_URL: str = "https://app.agroai-pilot.com"
    API_URL: str = "https://api.agroai-pilot.com"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SUCCESS_URL: str = ""
    STRIPE_CANCEL_URL: str = ""

    # Server-authoritative non-customer access profiles.
    # Comma-separated verified account emails. Never expose these values to the browser.
    INTERNAL_FULL_ACCESS_EMAILS: str = ""
    DEMO_FULL_ACCESS_EMAILS: str = ""
    NON_CUSTOMER_ACCESS_PROVISIONING_TOKEN: str = ""

    # Fail-closed global customer observability. These verified accounts may
    # inspect platform-wide signup metadata; organization owners cannot.
    PLATFORM_ADMIN_EMAILS: str = ""

    # Optional idempotent demo-environment seed identities. Passwords are secrets.
    DEMO_AUTO_PROVISION: bool = False
    DEMO_FULL_EMAIL: str = ""
    DEMO_FULL_PASSWORD: str = ""
    DEMO_FREE_EMAIL: str = ""
    DEMO_FREE_PASSWORD: str = ""
    DEMO_FULL_ORGANIZATION_NAME: str = "AGRO-AI Demo Organization"
    DEMO_FREE_ORGANIZATION_NAME: str = "AGRO-AI Free Demo"

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
    RESEND_API_KEY: str = ""
    RESEND_APP_URL: str = ""
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
    EMAIL_ADMIN_TOKEN: str = ""

    # AI gateway
    AI_PROVIDER: str = ""
    AI_BASE_URL: str = ""
    AI_API_KEY: str = ""
    AI_MODEL: str = ""
    AI_FAST_MODEL: str = ""
    AI_REASONING_MODEL: str = ""
    AI_REPORT_MODEL: str = ""

    # Distinct inference lanes. Keep actual Mac Ollama and always-on edge AI
    # separate so an Ollama-compatible Worker can never be mislabeled as local.
    AI_LOCAL_BASE_URL: str = ""
    AI_LOCAL_MODEL: str = ""
    # Cloudflare Access service-token credentials for a public tunnel hostname.
    # Leave blank for loopback/private local development only.
    AI_LOCAL_CF_ACCESS_CLIENT_ID: str = ""
    AI_LOCAL_CF_ACCESS_CLIENT_SECRET: str = ""
    AI_EDGE_BASE_URL: str = ""
    AI_EDGE_MODEL: str = "@cf/zai-org/glm-4.7-flash"
    # Optional shared bearer secret for the Workers AI origin. Set the matching
    # Worker secret ORIGIN_TOKEN before enforcing it in production.
    AI_EDGE_AUTH_TOKEN: str = ""

    AI_CHALLENGER_MODEL: str = "deepseek/deepseek-v4-pro"
    AI_FREE_MODEL: str = ""
    AI_MODEL_FALLBACKS: str = "z-ai/glm-5.2,deepseek/deepseek-v4-pro,qwen/qwen3.5-flash-02-23,z-ai/glm-5-turbo,z-ai/glm-4.5-air"
    AI_ROUTING_MODE: str = "hybrid"
    AI_MODEL_TEST_COMMANDS_ENABLED: bool = False
    AI_LOCAL_NUM_CTX: int = 6144
    AI_LOCAL_MAX_TOKENS: int = 1200
    AI_LOCAL_TIMEOUT_SECONDS: int = 90
    AI_LOCAL_THINKING: bool = False
    AI_EDGE_TIMEOUT_SECONDS: int = 45
    AI_TIMEOUT_SECONDS: int = 30
    INTELLIGENCE_FRESHNESS_POLICY_JSON: str = ""

    # Connector ingestion / transient spool
    CONNECTOR_UPLOAD_DIR: str = "/tmp/agroai_uploads"
    CONNECTOR_MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    CONNECTOR_STREAM_CHUNK_BYTES: int = 1024 * 1024

    # Durable R2/S3-compatible object storage
    CONNECTOR_OBJECT_STORAGE_BACKEND: str = "disabled"
    CONNECTOR_OBJECT_BUCKET: str = ""
    CONNECTOR_OBJECT_PREFIX: str = "agroai"
    CONNECTOR_OBJECT_REGION: str = "auto"
    CONNECTOR_OBJECT_ENDPOINT_URL: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""

    # Durable external connector task plane
    TASK_QUEUE_BACKEND: str = "disabled"
    REDIS_URL: str = ""
    TASK_QUEUE_STREAM: str = "agroai:tasks"
    TASK_QUEUE_GROUP: str = "agroai-workers"
    TASK_QUEUE_STREAM_MAXLEN: int = 100000
    TASK_QUEUE_BLOCK_MS: int = 5000
    TASK_QUEUE_LEASE_SECONDS: int = 120
    TASK_QUEUE_MAX_ATTEMPTS: int = 5
    TASK_QUEUE_RETRY_BASE_SECONDS: int = 15
    CLOUDFLARE_QUEUE_PUBLISH_URL: str = ""
    CLOUDFLARE_QUEUE_PUBLISH_TOKEN: str = ""
    CLOUDFLARE_QUEUE_CONSUMER_TOKEN: str = ""

    # Connector provider setup
    DROPBOX_OAUTH_CLIENT_ID: str = ""
    BOX_OAUTH_CLIENT_ID: str = ""
    SLACK_OAUTH_CLIENT_ID: str = ""
    SALESFORCE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_EARTH_ENGINE_PROJECT_ID: str = ""
    GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON: str = ""

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
