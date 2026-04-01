#!/usr/bin/env python3
"""WiseConn integration validation script.

Run this to prove the end-to-end integration works against the demo environment.

Usage:
    # Set credentials first
    export WISECONN_API_KEY="your-api-key"
    export WISECONN_API_URL="https://api.wiseconn.com"  # or actual base URL

    # Run validation
    python -m scripts.wiseconn_demo

    # Or with options
    python -m scripts.wiseconn_demo --skip-write  # read-only mode
    python -m scripts.wiseconn_demo --days 7      # last 7 days of data
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.wiseconn import WiseConnAdapter, WiseConnError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wiseconn_demo")


def mask(s: str, show: int = 4) -> str:
    """Mask a string for safe display."""
    if len(s) <= show:
        return "****"
    return s[:show] + "*" * (len(s) - show)


async def run_validation(args: argparse.Namespace) -> dict:
    """Run the full validation pipeline."""
    api_url = os.environ.get("WISECONN_API_URL", "https://api.wiseconn.com")
    api_key = os.environ.get("WISECONN_API_KEY", "")

    if not api_key:
        logger.error("WISECONN_API_KEY not set. Exiting.")
        return {"status": "error", "message": "WISECONN_API_KEY not set"}

    logger.info("Connecting to %s (key: %s)", api_url, mask(api_key))

    adapter = WiseConnAdapter(api_url=api_url, api_key=api_key)
    report: dict = {
        "timestamp": datetime.utcnow().isoformat(),
        "api_url": api_url,
        "steps": {},
    }

    try:
        # Step 1: Auth check
        logger.info("=" * 60)
        logger.info("STEP 1: Authentication check")
        auth_ok = await adapter.check_auth()
        report["steps"]["auth"] = {"ok": auth_ok}
        if not auth_ok:
            logger.error("AUTH FAILED. Check WISECONN_API_KEY and WISECONN_API_URL.")
            report["status"] = "auth_failed"
            return report
        logger.info("AUTH OK")

        # Step 2: Discover farms
        logger.info("=" * 60)
        logger.info("STEP 2: Farm discovery")
        raw_farms = await adapter.list_farms()
        farms = [adapter.map_farm(f) for f in raw_farms]
        report["steps"]["farms"] = {
            "count": len(farms),
            "farms": [
                {"id": f.provider_id, "name": f.name, "lat": f.latitude, "lng": f.longitude}
                for f in farms
            ],
        }
        logger.info("Found %d farm(s):", len(farms))
        for f in farms:
            logger.info("  - %s (id=%s, lat=%s, lng=%s)", f.name, f.provider_id, f.latitude, f.longitude)

        if not farms:
            logger.warning("No farms found. Integration may not have access.")
            report["status"] = "no_farms"
            return report

        # Step 3: Discover zones for first farm
        logger.info("=" * 60)
        logger.info("STEP 3: Zone discovery for farm '%s'", farms[0].name)
        target_farm = farms[0]
        raw_zones = await adapter.list_zones(target_farm.provider_id)
        zones = [adapter.map_zone(z, target_farm.provider_id) for z in raw_zones]
        report["steps"]["zones"] = {
            "farm_id": target_farm.provider_id,
            "count": len(zones),
            "zones": [
                {"id": z.provider_id, "name": z.name, "type": z.zone_type}
                for z in zones
            ],
        }
        logger.info("Found %d zone(s):", len(zones))
        for z in zones:
            logger.info("  - %s (id=%s, type=%s)", z.name, z.provider_id, z.zone_type)

        if not zones:
            logger.warning("No zones found for farm %s", target_farm.name)
            report["status"] = "no_zones"
            return report

        # Step 4: Discover measures for first zone
        logger.info("=" * 60)
        target_zone = zones[0]
        logger.info("STEP 4: Measure discovery for zone '%s'", target_zone.name)
        raw_measures = await adapter.list_measures(target_zone.provider_id)
        measures = [adapter.map_measure(m, target_zone.provider_id) for m in raw_measures]
        report["steps"]["measures"] = {
            "zone_id": target_zone.provider_id,
            "count": len(measures),
            "measures": [
                {
                    "id": m.provider_id,
                    "name": m.name,
                    "variable": m.variable,
                    "unit": m.unit,
                    "depth_inches": m.depth_inches,
                }
                for m in measures
            ],
        }
        logger.info("Found %d measure(s):", len(measures))
        for m in measures:
            logger.info(
                "  - %s → %s (%s, depth=%s)",
                m.name, m.variable, m.unit, m.depth_inches,
            )

        # Step 5: Fetch telemetry data
        logger.info("=" * 60)
        logger.info("STEP 5: Telemetry data (last %d days)", args.days)
        now = datetime.utcnow()
        start = now - timedelta(days=args.days)
        telemetry_results = []

        for measure in measures[:5]:  # Limit to first 5 measures for speed
            try:
                raw_data = await adapter.get_measure_data(
                    measure.provider_id, start, now
                )
                points = adapter.map_data_points(raw_data, measure)
                summary = {
                    "measure": measure.name,
                    "variable": measure.variable,
                    "raw_count": len(raw_data),
                    "valid_points": len(points),
                    "first": points[0].model_dump() if points else None,
                    "last": points[-1].model_dump() if points else None,
                }
                telemetry_results.append(summary)
                logger.info(
                    "  %s: %d raw → %d valid points",
                    measure.name, len(raw_data), len(points),
                )
                if points:
                    logger.info(
                        "    range: %s to %s",
                        points[0].timestamp.isoformat(),
                        points[-1].timestamp.isoformat(),
                    )
            except WiseConnError as e:
                logger.warning("  %s: error fetching data: %s", measure.name, e)
                telemetry_results.append(
                    {"measure": measure.name, "error": str(e)}
                )

        report["steps"]["telemetry"] = telemetry_results

        # Step 6: Fetch irrigation history
        logger.info("=" * 60)
        logger.info("STEP 6: Irrigation history for zone '%s'", target_zone.name)
        try:
            raw_irrigations = await adapter.list_irrigations(
                target_zone.provider_id, start, now
            )
            irrigations = [
                adapter.map_irrigation(i, target_zone.provider_id)
                for i in raw_irrigations
            ]
            report["steps"]["irrigations_read"] = {
                "zone_id": target_zone.provider_id,
                "count": len(irrigations),
                "sample": [i.model_dump() for i in irrigations[:3]],
            }
            logger.info("Found %d irrigation event(s)", len(irrigations))
            for i in irrigations[:3]:
                logger.info(
                    "  - %s: start=%s dur=%smin status=%s",
                    i.provider_id, i.start_time, i.duration_minutes, i.status.value,
                )
        except WiseConnError as e:
            logger.warning("Irrigation history fetch failed: %s", e)
            report["steps"]["irrigations_read"] = {"error": str(e)}

        # Step 7: Write path (create test irrigation)
        if args.skip_write:
            logger.info("=" * 60)
            logger.info("STEP 7: SKIPPED (--skip-write)")
            report["steps"]["irrigation_write"] = {"skipped": True}
        else:
            logger.info("=" * 60)
            logger.info("STEP 7: Create test irrigation (1 min, +24h)")
            try:
                test_start = now + timedelta(hours=24)
                create_result = await adapter.create_irrigation(
                    zone_id=target_zone.provider_id,
                    start_time=test_start,
                    duration_minutes=1,
                    metadata={"source": "agro-ai-validation"},
                )
                report["steps"]["irrigation_write"] = {
                    "status": "created",
                    "response": create_result,
                }
                logger.info("Irrigation created: %s", json.dumps(create_result, default=str))

                # Readback verification
                logger.info("Verifying via readback...")
                verify_irrigations = await adapter.list_irrigations(
                    target_zone.provider_id,
                    start_time=test_start - timedelta(hours=1),
                    end_time=test_start + timedelta(hours=1),
                )
                report["steps"]["irrigation_verify"] = {
                    "found": len(verify_irrigations),
                    "sample": verify_irrigations[:2],
                }
                if verify_irrigations:
                    logger.info("VERIFIED: found %d irrigation(s) in time window", len(verify_irrigations))
                else:
                    logger.warning("Could not verify irrigation via readback")

            except WiseConnError as e:
                logger.error("Write path failed: %s", e)
                report["steps"]["irrigation_write"] = {
                    "status": "failed",
                    "error": str(e),
                }

        report["status"] = "success"
        return report

    except Exception as e:
        logger.error("Validation failed: %s", e, exc_info=True)
        report["status"] = "error"
        report["error"] = str(e)
        return report

    finally:
        await adapter.close()


def main():
    parser = argparse.ArgumentParser(description="WiseConn integration validation")
    parser.add_argument("--skip-write", action="store_true", help="Skip write path")
    parser.add_argument("--days", type=int, default=14, help="Days of historical data")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    args = parser.parse_args()

    result = asyncio.run(run_validation(args))

    # Print summary
    print("\n" + "=" * 60)
    print("VALIDATION RESULT:", result.get("status", "unknown").upper())
    print("=" * 60)

    # Serialize (handle datetime objects)
    def default_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    output = json.dumps(result, indent=2, default=default_serializer)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Full report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
