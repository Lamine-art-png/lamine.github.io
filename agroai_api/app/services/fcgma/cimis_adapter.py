"""CIMIS Live Weather adapter for the FCGMA Water Intelligence Copilot.

Uses the official California DWR CIMIS REST API.
Reference: https://et.water.ca.gov/Rest/Index

Environment variable required: CIMIS_APP_KEY
If absent, the adapter returns a clear unavailable state.

IMPORTANT: CIMIS data is weather context only. It must NOT silently alter
groundwater-meter calculations or extraction totals.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

CIMIS_BASE_URL = "https://et.water.ca.gov/api/data"

# Ventura County CIMIS stations (configurable via CIMIS_TARGET env)
# Station 152 = Camarillo (Ventura County)
# Station 232 = Somis (near Fox Canyon management area)
DEFAULT_TARGET = os.getenv("CIMIS_TARGET", "Cimis Station 152")

# Data items: reference ET, precipitation, air temp, dew point, wind speed
DATA_ITEMS = "day-eto,day-precip,day-air-tmp-max,day-air-tmp-min,day-wind-spd"


def _api_key() -> str | None:
    return os.getenv("CIMIS_APP_KEY", "").strip() or None


def get_status() -> dict[str, Any]:
    key = _api_key()
    return {
        "provider": "cimis_live_weather",
        "available": bool(key),
        "message": (
            "CIMIS weather context connected."
            if key
            else "Live source unavailable — configure authorized access. Set CIMIS_APP_KEY environment variable."
        ),
        "target": DEFAULT_TARGET,
        "note": "CIMIS data is weather context only. It does not alter groundwater-meter calculations.",
        "source_url": "https://et.water.ca.gov/Rest/Index",
    }


async def fetch_daily_data(
    days: int = 7,
    target: str | None = None,
) -> dict[str, Any]:
    """Fetch recent daily CIMIS data. Returns unavailable state if no key."""
    key = _api_key()
    if not key:
        return {
            "available": False,
            "provider": "cimis_live_weather",
            "message": "Live source unavailable — configure authorized access. Set CIMIS_APP_KEY environment variable.",
            "data": [],
        }

    try:
        import httpx
    except ImportError:
        return {
            "available": False,
            "provider": "cimis_live_weather",
            "message": "httpx not available. Install httpx to enable CIMIS integration.",
            "data": [],
        }

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    tgt = target or DEFAULT_TARGET

    params = {
        "appKey": key,
        "targets": tgt,
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "dataItems": DATA_ITEMS,
        "unitOfMeasure": "E",  # English units
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(CIMIS_BASE_URL, params=params)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as exc:
        logger.warning("CIMIS fetch failed: %s", exc)
        return {
            "available": False,
            "provider": "cimis_live_weather",
            "message": f"CIMIS API call failed: {exc}. Retry or check CIMIS_APP_KEY validity.",
            "data": [],
        }

    records = _parse_cimis_response(raw, tgt)
    return {
        "available": True,
        "provider": "cimis_live_weather",
        "target": tgt,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "record_count": len(records),
        "data": records,
        "note": "CIMIS data is weather context only. It does not alter groundwater-meter calculations.",
        "source_url": "https://et.water.ca.gov/Rest/Index",
    }


def _parse_cimis_response(raw: dict[str, Any], target: str) -> list[dict[str, Any]]:
    """Parse CIMIS API response into normalized weather records."""
    records: list[dict[str, Any]] = []
    try:
        data = raw.get("Data", {})
        providers = data.get("Providers", [])
        for provider in providers:
            records_raw = provider.get("Records", [])
            for rec in records_raw:
                parsed = {
                    "id": f"cimis-{rec.get('Date', 'unknown')}-{target.replace(' ', '-')}",
                    "evidence_class": "weather_context",
                    "provider": "cimis_live_weather",
                    "target": target,
                    "date": rec.get("Date"),
                    "station_number": rec.get("Station", {}).get("StationNbr"),
                    "station_name": rec.get("Station", {}).get("Name"),
                    "eto_inches": _val(rec, "DayEto"),
                    "precip_inches": _val(rec, "DayPrecip"),
                    "air_tmp_max_f": _val(rec, "DayAirTmpMax"),
                    "air_tmp_min_f": _val(rec, "DayAirTmpMin"),
                    "wind_spd_mph": _val(rec, "DayWindSpd"),
                    "source_url": "https://et.water.ca.gov/Rest/Index",
                    "note": "Reference ET context. Does not replace flowmeter records.",
                }
                records.append(parsed)
    except Exception as exc:
        logger.warning("CIMIS parse failed: %s", exc)

    return records


def _val(rec: dict[str, Any], key: str) -> float | None:
    item = rec.get(key, {})
    if isinstance(item, dict):
        v = item.get("Value")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None
