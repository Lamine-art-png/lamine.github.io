"""Test configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import uuid

from app.main import app
from app.db.base import Base, get_db
from app.models import Tenant, Client, Block, Telemetry


# Test database
TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    """Create test database and session."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create test client with database override."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_tenant(db):
    """Create test tenant."""
    tenant = Tenant(
        id="test-tenant",
        name="Test Tenant",
        email="test@test.com",
        tier="enterprise",
        active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def test_block(db, test_tenant):
    """Create test block."""
    block = Block(
        id="test-block-001",
        tenant_id=test_tenant.id,
        name="Test Field",
        area_ha=10.0,
        crop_type="corn",
        soil_type="loam",
        latitude=37.7749,
        longitude=-122.4194,
        water_budget_allocated=1000.0,
        water_budget_used=0.0,
    )
    db.add(block)
    db.commit()
    db.refresh(block)

    # Add sample telemetry
    now = datetime.utcnow()

    # Soil VWC
    for i in range(3):
        telemetry = Telemetry(
            id=str(uuid.uuid4()),
            tenant_id=test_tenant.id,
            block_id=block.id,
            type="soil_vwc",
            timestamp=now - timedelta(days=i),
            value=0.30,
            unit="m3/m3",
            source="test-sensor",
        )
        db.add(telemetry)

    # ET0
    for i in range(3):
        telemetry = Telemetry(
            id=str(uuid.uuid4()),
            tenant_id=test_tenant.id,
            block_id=block.id,
            type="et0",
            timestamp=now - timedelta(days=i),
            value=5.0,
            unit="mm/day",
            source="test-api",
        )
        db.add(telemetry)

    db.commit()

    return block


@pytest.fixture
def auth_headers():
    """Mock authentication headers."""
    return {}  # Auth is stubbed in test mode
