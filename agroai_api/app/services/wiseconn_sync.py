"""WiseConn sync service — orchestrates discovery, ingestion, normalization,
and recommendation wiring.

This service is the bridge between the WiseConn adapter (HTTP client) and
AGRO-AI's domain models (Block, Telemetry, Recommendation, Schedule).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.adapters.wiseconn import WiseConnAdapter, WiseConnError
from app.models.block import Block
from app.models.schedule import Schedule
from app.models.telemetry import Telemetry
from app.models.tenant import Tenant
from app.schemas.wiseconn import (
    CanonicalDataPoint,
    CanonicalFarm,
    CanonicalIrrigation,
    CanonicalMeasure,
    CanonicalZone,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)

# Default tenant for demo operations
DEMO_TENANT_ID = "wiseconn-demo"


class WiseConnSyncService:
    """Orchestrates WiseConn data flow into AGRO-AI."""

    def __init__(self, adapter: WiseConnAdapter, db: Optional[Session] = None):
        self.adapter = adapter
        self.db = db

        # Cache for discovered entities (avoids repeated API calls)
        self._farms: List[CanonicalFarm] = []
        self._zones: Dict[str, List[CanonicalZone]] = {}  # farm_id -> zones
        self._measures: Dict[str, List[CanonicalMeasure]] = {}  # zone_id -> measures

    # ------------------------------------------------------------------
    # Phase 1: Discovery
    # ------------------------------------------------------------------

    async def discover_all(self) -> Dict[str, Any]:
        """Full discovery: farms → zones → measures.

        Returns a summary dict for reporting/validation.
        """
        summary: Dict[str, Any] = {
            "farms": [],
            "total_zones": 0,
            "total_measures": 0,
            "errors": [],
        }

        # Discover farms
        try:
            raw_farms = await self.adapter.list_farms()
            self._farms = [self.adapter.map_farm(f) for f in raw_farms]
            summary["farms"] = [
                {"id": f.provider_id, "name": f.name, "lat": f.latitude, "lng": f.longitude}
                for f in self._farms
            ]
        except WiseConnError as e:
            summary["errors"].append(f"Farm discovery failed: {e}")
            return summary

        # Discover zones per farm
        for farm in self._farms:
            try:
                raw_zones = await self.adapter.list_zones(farm.provider_id)
                zones = [self.adapter.map_zone(z, farm.provider_id) for z in raw_zones]
                self._zones[farm.provider_id] = zones
                summary["total_zones"] += len(zones)
            except WiseConnError as e:
                summary["errors"].append(
                    f"Zone discovery failed for farm {farm.name}: {e}"
                )

        # Discover measures per zone
        for farm_id, zones in self._zones.items():
            for zone in zones:
                try:
                    raw_measures = await self.adapter.list_measures(zone.provider_id)
                    measures = [
                        self.adapter.map_measure(m, zone.provider_id)
                        for m in raw_measures
                    ]
                    self._measures[zone.provider_id] = measures
                    summary["total_measures"] += len(measures)
                except WiseConnError as e:
                    summary["errors"].append(
                        f"Measure discovery failed for zone {zone.name}: {e}"
                    )

        logger.info(
            "WiseConn discovery complete: %d farms, %d zones, %d measures, %d errors",
            len(self._farms),
            summary["total_zones"],
            summary["total_measures"],
            len(summary["errors"]),
        )
        return summary

    # ------------------------------------------------------------------
    # Phase 2: Telemetry ingestion
    # ------------------------------------------------------------------

    async def ingest_telemetry(
        self,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Dict[str, Any]:
        """Ingest telemetry for a zone's measures into AGRO-AI Telemetry table.

        Returns ingestion summary.
        """
        result: Dict[str, Any] = {
            "zone_id": zone_id,
            "measures_processed": 0,
            "points_ingested": 0,
            "points_skipped": 0,
            "errors": [],
        }

        measures = self._measures.get(zone_id, [])
        if not measures:
            # Try to discover measures on the fly
            try:
                raw = await self.adapter.list_measures(zone_id)
                measures = [self.adapter.map_measure(m, zone_id) for m in raw]
                self._measures[zone_id] = measures
            except WiseConnError as e:
                result["errors"].append(f"Measure discovery failed: {e}")
                return result

        for measure in measures:
            try:
                raw_data = await self.adapter.get_measure_data(
                    measure.provider_id, start_time, end_time
                )
                points = self.adapter.map_data_points(raw_data, measure)
                result["measures_processed"] += 1

                if self.db:
                    ingested, skipped = self._persist_data_points(
                        points, zone_id, tenant_id
                    )
                    result["points_ingested"] += ingested
                    result["points_skipped"] += skipped
                else:
                    result["points_ingested"] += len(points)

            except WiseConnError as e:
                result["errors"].append(
                    f"Data fetch failed for measure {measure.name}: {e}"
                )

        logger.info(
            "Telemetry ingestion for zone %s: %d measures, %d points ingested, %d skipped",
            zone_id,
            result["measures_processed"],
            result["points_ingested"],
            result["points_skipped"],
        )
        return result

    async def ingest_current(
        self,
        zone_id: str,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Dict[str, Any]:
        """Ingest last 24h of data for a zone."""
        now = datetime.utcnow()
        return await self.ingest_telemetry(
            zone_id, now - timedelta(hours=24), now, tenant_id
        )

    async def ingest_historical(
        self,
        zone_id: str,
        days: int = 14,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Dict[str, Any]:
        """Ingest historical data (default: last 14 days)."""
        now = datetime.utcnow()
        return await self.ingest_telemetry(
            zone_id, now - timedelta(days=days), now, tenant_id
        )

    # ------------------------------------------------------------------
    # Phase 3: Irrigation history
    # ------------------------------------------------------------------

    async def ingest_irrigations(
        self,
        zone_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Dict[str, Any]:
        """Ingest irrigation events for a zone into AGRO-AI Schedule table."""
        if not start_time:
            start_time = datetime.utcnow() - timedelta(days=14)
        if not end_time:
            end_time = datetime.utcnow()

        result: Dict[str, Any] = {
            "zone_id": zone_id,
            "irrigations_found": 0,
            "irrigations_persisted": 0,
            "errors": [],
        }

        try:
            raw_irrigations = await self.adapter.list_irrigations(
                zone_id, start_time, end_time
            )
            irrigations = [
                self.adapter.map_irrigation(i, zone_id) for i in raw_irrigations
            ]
            result["irrigations_found"] = len(irrigations)

            if self.db:
                for irr in irrigations:
                    persisted = self._persist_irrigation(irr, zone_id, tenant_id)
                    if persisted:
                        result["irrigations_persisted"] += 1
            else:
                result["irrigations_persisted"] = len(irrigations)

        except WiseConnError as e:
            result["errors"].append(f"Irrigation fetch failed: {e}")

        return result

    # ------------------------------------------------------------------
    # Phase 4: Write path — create irrigation
    # ------------------------------------------------------------------

    async def create_test_irrigation(
        self,
        zone_id: str,
        duration_minutes: int = 1,
        start_offset_hours: int = 24,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Dict[str, Any]:
        """Create a minimal test irrigation in the demo environment.

        Defaults: 1 minute, 24 hours from now (minimally invasive).
        """
        start_time = datetime.utcnow() + timedelta(hours=start_offset_hours)

        result: Dict[str, Any] = {
            "zone_id": zone_id,
            "start_time": start_time.isoformat(),
            "duration_minutes": duration_minutes,
            "status": "pending",
            "provider_response": None,
            "verification": None,
        }

        try:
            # Create via adapter
            response = await self.adapter.create_irrigation(
                zone_id=zone_id,
                start_time=start_time,
                duration_minutes=duration_minutes,
                metadata={"source": "agro-ai-integration-test"},
            )
            result["provider_response"] = response
            result["status"] = "created"

            # Persist as Schedule
            if self.db:
                self._persist_schedule(
                    zone_id=zone_id,
                    start_time=start_time,
                    duration_min=duration_minutes,
                    provider_id=str(response.get("id", response.get("irrigationId", ""))),
                    tenant_id=tenant_id,
                    status="scheduled",
                )

            # Readback verification
            verification = await self._verify_irrigation(zone_id, start_time)
            result["verification"] = verification

        except WiseConnError as e:
            result["status"] = "failed"
            result["error"] = str(e)
            logger.error("Test irrigation creation failed: %s", e)

        return result

    async def _verify_irrigation(
        self, zone_id: str, expected_start: datetime
    ) -> Dict[str, Any]:
        """Verify the created irrigation appears in WiseConn."""
        try:
            # Query irrigations around the expected start time
            irrigations = await self.adapter.list_irrigations(
                zone_id,
                start_time=expected_start - timedelta(hours=1),
                end_time=expected_start + timedelta(hours=1),
            )
            found = len(irrigations) > 0
            return {
                "verified": found,
                "irrigations_in_window": len(irrigations),
                "raw": irrigations[:3] if irrigations else [],
            }
        except WiseConnError as e:
            return {"verified": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Phase 5: Map to AGRO-AI domain and wire recommendations
    # ------------------------------------------------------------------

    def _ensure_tenant_exists(self, tenant_id: str) -> None:
        """Ensure the tenant row exists (required by foreign key on blocks)."""
        if not self.db:
            return
        existing = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not existing:
            self.db.add(Tenant(
                id=tenant_id,
                name="WiseConn Demo",
                tier="standard",
                active=True,
            ))
            self.db.commit()
            logger.info("Created tenant: %s", tenant_id)

    def ensure_block_exists(
        self,
        zone: CanonicalZone,
        farm: CanonicalFarm,
        tenant_id: str = DEMO_TENANT_ID,
    ) -> Optional[str]:
        """Ensure an AGRO-AI Block exists for a WiseConn zone. Returns block_id."""
        if not self.db:
            return None

        self._ensure_tenant_exists(tenant_id)

        block_id = f"wc-{zone.provider_id}"
        existing = self.db.query(Block).filter(Block.id == block_id).first()
        if existing:
            return block_id

        block = Block(
            id=block_id,
            tenant_id=tenant_id,
            name=zone.name,
            area_ha=zone.area_ha or 0,
            crop_type=None,  # Will be enriched from farm metadata
            latitude=farm.latitude,
            longitude=farm.longitude,
            config={
                "provider": "wiseconn",
                "provider_zone_id": zone.provider_id,
                "provider_farm_id": farm.provider_id,
                "farm_name": farm.name,
            },
        )
        self.db.add(block)
        self.db.commit()
        logger.info("Created AGRO-AI block %s for WiseConn zone %s", block_id, zone.name)
        return block_id

    # ------------------------------------------------------------------
    # Full sync: end-to-end
    # ------------------------------------------------------------------

    async def full_sync(
        self,
        tenant_id: str = DEMO_TENANT_ID,
        days: int = 14,
    ) -> Dict[str, Any]:
        """Run a full sync: discover → ingest telemetry → ingest irrigations.

        Returns a comprehensive summary.
        """
        report: Dict[str, Any] = {
            "started_at": datetime.utcnow().isoformat(),
            "discovery": None,
            "blocks_created": [],
            "telemetry": [],
            "irrigations": [],
            "errors": [],
        }

        # Step 1: Discovery
        discovery = await self.discover_all()
        report["discovery"] = discovery
        if discovery["errors"]:
            report["errors"].extend(discovery["errors"])

        # Step 2: Ensure blocks exist and ingest per zone
        for farm in self._farms:
            zones = self._zones.get(farm.provider_id, [])
            for zone in zones:
                # Create/ensure block
                block_id = self.ensure_block_exists(zone, farm, tenant_id)
                if block_id:
                    report["blocks_created"].append(
                        {"block_id": block_id, "zone": zone.name}
                    )

                # Ingest telemetry
                telem = await self.ingest_historical(
                    zone.provider_id, days=days, tenant_id=tenant_id
                )
                report["telemetry"].append(telem)

                # Ingest irrigation history
                irr = await self.ingest_irrigations(
                    zone.provider_id, tenant_id=tenant_id
                )
                report["irrigations"].append(irr)

        report["completed_at"] = datetime.utcnow().isoformat()
        return report

    # ------------------------------------------------------------------
    # Persistence helpers (idempotent)
    # ------------------------------------------------------------------

    def _persist_data_points(
        self,
        points: List[CanonicalDataPoint],
        zone_id: str,
        tenant_id: str,
    ) -> Tuple[int, int]:
        """Persist data points to Telemetry table. Returns (ingested, skipped)."""
        if not self.db:
            return (0, 0)

        block_id = f"wc-{zone_id}"
        ingested = 0
        skipped = 0

        for pt in points:
            # Idempotency: hash of (block, type, variable, timestamp, depth)
            dedup_key = hashlib.sha256(
                f"{block_id}:{pt.variable}:{pt.timestamp.isoformat()}:{pt.depth_inches}".encode()
            ).hexdigest()[:16]

            telemetry_id = f"wc-{dedup_key}"
            existing = self.db.query(Telemetry).filter(Telemetry.id == telemetry_id).first()
            if existing:
                skipped += 1
                continue

            telemetry = Telemetry(
                id=telemetry_id,
                tenant_id=tenant_id,
                block_id=block_id,
                type=pt.variable,
                timestamp=pt.timestamp,
                value=pt.value,
                unit=pt.unit,
                source=f"wiseconn:{pt.source_measure_id}",
                meta_data={
                    "provider": "wiseconn",
                    "depth_inches": pt.depth_inches,
                    "measure_id": pt.source_measure_id,
                },
            )
            self.db.add(telemetry)
            ingested += 1

        if ingested > 0:
            self.db.commit()

        return (ingested, skipped)

    def _persist_irrigation(
        self,
        irrigation: CanonicalIrrigation,
        zone_id: str,
        tenant_id: str,
    ) -> bool:
        """Persist an irrigation event as a Schedule. Returns True if new."""
        if not self.db or not irrigation.provider_id:
            return False

        # Idempotency by provider_schedule_id
        existing = (
            self.db.query(Schedule)
            .filter(Schedule.provider_schedule_id == irrigation.provider_id)
            .first()
        )
        if existing:
            return False

        schedule = Schedule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            block_id=f"wc-{zone_id}",
            controller_id=zone_id,
            start_time=irrigation.start_time or datetime.utcnow(),
            duration_min=float(irrigation.duration_minutes or 0),
            status="completed" if irrigation.status == ExecutionStatus.APPLIED else "pending",
            provider="wiseconn",
            provider_schedule_id=irrigation.provider_id,
            meta_data={
                "program_name": irrigation.program_name,
                "source": "wiseconn-sync",
            },
        )
        self.db.add(schedule)
        self.db.commit()
        return True

    def _persist_schedule(
        self,
        zone_id: str,
        start_time: datetime,
        duration_min: float,
        provider_id: str,
        tenant_id: str,
        status: str = "scheduled",
    ) -> str:
        """Persist a newly created irrigation schedule. Returns schedule_id."""
        schedule_id = str(uuid.uuid4())
        if not self.db:
            return schedule_id

        schedule = Schedule(
            id=schedule_id,
            tenant_id=tenant_id,
            block_id=f"wc-{zone_id}",
            controller_id=zone_id,
            start_time=start_time,
            duration_min=duration_min,
            status=status,
            provider="wiseconn",
            provider_schedule_id=provider_id,
            meta_data={"source": "agro-ai-integration-test"},
        )
        self.db.add(schedule)
        self.db.commit()
        return schedule_id
