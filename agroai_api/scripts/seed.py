"""Seed script to create demo tenant and block."""
import sys
import os
from datetime import datetime, timedelta
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.base import SessionLocal, init_db
from app.models.tenant import Tenant
from app.models.client import Client
from app.models.block import Block
from app.models.telemetry import Telemetry


def seed_data():
    """Seed demo data."""
    print("Initializing database...")
    init_db()

    db = SessionLocal()

    try:
        # Create demo tenant
        tenant_id = "demo-tenant"
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        if not tenant:
            tenant = Tenant(
                id=tenant_id,
                name="Demo Tenant",
                email="demo@agro-ai.com",
                tier="enterprise",
                active=True,
            )
            db.add(tenant)
            print(f"✓ Created tenant: {tenant_id}")
        else:
            print(f"✓ Tenant already exists: {tenant_id}")

        # Create demo client
        client_id = "demo-client"
        client = db.query(Client).filter(Client.id == client_id).first()

        if not client:
            client = Client(
                id=client_id,
                tenant_id=tenant_id,
                client_secret_hash="demo-secret-hash",
                name="Demo Client",
                active=True,
            )
            db.add(client)
            print(f"✓ Created client: {client_id}")
        else:
            print(f"✓ Client already exists: {client_id}")

        # Create demo blocks
        blocks_data = [
            {
                "id": "block-001",
                "name": "North Field - Corn",
                "area_ha": 25.5,
                "crop_type": "corn",
                "soil_type": "loam",
                "latitude": 37.7749,
                "longitude": -122.4194,
                "water_budget_allocated": 5000.0,
            },
            {
                "id": "block-002",
                "name": "South Field - Wheat",
                "area_ha": 18.2,
                "crop_type": "wheat",
                "soil_type": "clay",
                "latitude": 37.7849,
                "longitude": -122.4294,
                "water_budget_allocated": 3500.0,
            },
        ]

        for block_data in blocks_data:
            block = db.query(Block).filter(Block.id == block_data["id"]).first()

            if not block:
                block = Block(
                    tenant_id=tenant_id,
                    **block_data
                )
                db.add(block)
                print(f"✓ Created block: {block_data['id']} - {block_data['name']}")

                # Add sample telemetry
                now = datetime.utcnow()

                # Soil VWC readings (last 7 days)
                for i in range(7):
                    telemetry = Telemetry(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        block_id=block_data["id"],
                        type="soil_vwc",
                        timestamp=now - timedelta(days=i),
                        value=0.28 + (i * 0.01),  # Decreasing moisture
                        unit="m3/m3",
                        source="sensor-01",
                    )
                    db.add(telemetry)

                # ET0 readings
                for i in range(7):
                    telemetry = Telemetry(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        block_id=block_data["id"],
                        type="et0",
                        timestamp=now - timedelta(days=i),
                        value=5.5 + (i * 0.2),  # ET varies 5-6 mm/day
                        unit="mm/day",
                        source="weather-api",
                    )
                    db.add(telemetry)

                print(f"  ✓ Added sample telemetry for {block_data['id']}")
            else:
                print(f"✓ Block already exists: {block_data['id']}")

        db.commit()
        print("\n" + "="*60)
        print("✓ Database seeded successfully!")
        print("="*60)
        print("\nDemo credentials:")
        print(f"  Tenant ID:  {tenant_id}")
        print(f"  Client ID:  {client_id}")
        print(f"  Secret:     demo-secret")
        print("\nDemo blocks:")
        for block_data in blocks_data:
            print(f"  - {block_data['id']}: {block_data['name']}")
        print("\nTo test the API, use the demo tenant in your requests.")
        print("Authentication is stubbed - it will use 'demo-tenant' by default.\n")

    except Exception as e:
        print(f"✗ Error seeding database: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
