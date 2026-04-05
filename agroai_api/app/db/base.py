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
    # PostgreSQL connection pool settings for production
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10
    _engine_kwargs["pool_timeout"] = 30
    _engine_kwargs["pool_recycle"] = 300  # Recycle connections every 5 min (Neon compat)

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


def init_db():
    """Initialize database - create all tables and add new columns."""
    from app.models import (
        tenant, client, block, telemetry, event,
        recommendation, schedule, webhook, usage_metering, audit_log
    )
    Base.metadata.create_all(bind=engine)

    # Add columns to existing tables that create_all() won't handle.
    # Each ALTER is idempotent (IF NOT EXISTS or caught exception).
    _migrate_columns()


def _migrate_columns():
    """Add new columns to existing tables. Safe to run repeatedly."""
    import logging
    logger = logging.getLogger(__name__)

    migrations = [
        # Schedule table — Phase 2 additions
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS decision_run_id VARCHAR",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS actual_duration_min FLOAT",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS actual_volume_m3 FLOAT",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS actual_start TIMESTAMP",
        "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        # Recommendation table — Phase 2 addition
        "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS decision_run_id VARCHAR",
        # Decision run table — Phase 3 additions
        "ALTER TABLE decision_runs ADD COLUMN IF NOT EXISTS match_confidence FLOAT",
        "ALTER TABLE decision_runs ADD COLUMN IF NOT EXISTS match_method VARCHAR",
        "ALTER TABLE decision_runs ADD COLUMN IF NOT EXISTS match_reason VARCHAR",
        "ALTER TABLE decision_runs ADD COLUMN IF NOT EXISTS matched_at TIMESTAMP",
    ]

    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(sql))
            except Exception as e:
                # Table might not exist yet (create_all handles it), or column already exists
                logger.debug("Migration skipped: %s — %s", sql.split("ADD COLUMN")[-1].strip(), e)
        conn.commit()
    logger.info("Column migrations complete")
