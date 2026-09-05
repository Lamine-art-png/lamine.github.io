"""Database configuration and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Create engine with appropriate settings per database type
_is_sqlite = "sqlite" in settings.DATABASE_URL

_engine_kwargs = {
    "pool_pre_ping": True,
}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Production requests must fail fast instead of sitting on a depleted pool
    # for tens of seconds. Keep the values environment-tunable so the pool can
    # be sized to the actual Render/PostgreSQL instance without code changes.
    _engine_kwargs["pool_size"] = max(1, int(settings.DB_POOL_SIZE))
    _engine_kwargs["max_overflow"] = max(0, int(settings.DB_MAX_OVERFLOW))
    _engine_kwargs["pool_timeout"] = max(1, int(settings.DB_POOL_TIMEOUT_SECONDS))
    _engine_kwargs["pool_recycle"] = max(60, int(settings.DB_POOL_RECYCLE_SECONDS))
    _engine_kwargs["pool_use_lifo"] = True
    _engine_kwargs["connect_args"] = {
        "connect_timeout": max(1, int(settings.DB_CONNECT_TIMEOUT_SECONDS)),
    }

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Refuse runtime schema creation.

    Database schema is owned by Alembic migrations. This function remains only
    as a compatibility tripwire for old local scripts.
    """
    raise RuntimeError("Runtime schema creation is disabled. Run `alembic upgrade head` instead.")
