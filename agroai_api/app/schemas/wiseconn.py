"""WiseConn API response schemas and canonical mapping models.

These schemas validate inbound WiseConn API payloads and define the
canonical AGRO-AI representations for WiseConn entities.

ASSUMPTIONS (isolated here, derived from wiseconn-node library and
common ag-IoT REST patterns):
- API returns JSON with camelCase keys
- Farms have id, name, lat/lng, timezone
- Zones belong to farms, have id, name, type
- Measures belong to zones, have id, name, unit, depth
- Data points have time (ISO or epoch) and value
- Irrigations have id, zone, start/end times, status
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# WiseConn raw API response models (inbound validation)
# ---------------------------------------------------------------------------

class WCFarmRaw(BaseModel):
    """Raw farm object from WiseConn API."""
    id: Any  # WiseConn may use int or str IDs
    name: Optional[str] = None
    latitude: Optional[float] = Field(None, alias="lat")
    longitude: Optional[float] = Field(None, alias="lng")
    timezone: Optional[str] = None
    account: Optional[Any] = None  # parent account reference

    class Config:
        populate_by_name = True
        extra = "allow"  # preserve unknown fields


class WCZoneRaw(BaseModel):
    """Raw zone object from WiseConn API."""
    id: Any
    name: Optional[str] = None
    farm_id: Optional[Any] = Field(None, alias="farmId")
    type: Optional[Any] = None  # Can be str or list (e.g. ['Soil', 'Irrigation'])
    area: Optional[float] = None  # area in provider units

    class Config:
        populate_by_name = True
        extra = "allow"


class WCMeasureRaw(BaseModel):
    """Raw measure/sensor definition from WiseConn API."""
    id: Any
    name: Optional[str] = None
    unit: Optional[str] = None
    sensor_type: Optional[str] = Field(None, alias="sensorType")
    depth: Optional[float] = None  # depth in provider units (inches or cm)
    zone_id: Optional[Any] = Field(None, alias="zoneId")
    node_id: Optional[Any] = Field(None, alias="nodeId")

    class Config:
        populate_by_name = True
        extra = "allow"


class WCDataPointRaw(BaseModel):
    """Raw data point from WiseConn API."""
    time: Any  # epoch ms, ISO string, or datetime
    value: Any  # string or float

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value(cls, v: Any) -> Optional[float]:
        if v is None or v == "" or v == "null":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None


class WCIrrigationRaw(BaseModel):
    """Raw irrigation event from WiseConn API."""
    id: Optional[Any] = None
    zone_id: Optional[Any] = Field(None, alias="zoneId")
    status: Optional[str] = None
    # WiseConn uses initTime/endTime (not start/end)
    init_time: Optional[str] = Field(None, alias="initTime")
    end_time: Optional[str] = Field(None, alias="endTime")
    duration_minutes: Optional[int] = Field(None, alias="durationMinutes")
    volume: Optional[Any] = None  # Can be float or dict {'value': float, 'unitAbrev': str}
    program_name: Optional[str] = Field(None, alias="programName")

    @property
    def volume_value(self) -> Optional[float]:
        """Extract numeric volume regardless of format."""
        if self.volume is None:
            return None
        if isinstance(self.volume, (int, float)):
            return float(self.volume)
        if isinstance(self.volume, dict):
            return float(self.volume.get("value", 0))
        return None

    @property
    def volume_unit(self) -> Optional[str]:
        """Extract volume unit if available."""
        if isinstance(self.volume, dict):
            return self.volume.get("unitAbrev") or self.volume.get("unit")
        return None

    class Config:
        populate_by_name = True
        extra = "allow"


# ---------------------------------------------------------------------------
# AGRO-AI canonical models (normalized from any provider)
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    """Lifecycle status for irrigation actions."""
    RECOMMENDED = "recommended"
    SCHEDULED = "scheduled"
    APPLIED = "applied"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CanonicalFarm(BaseModel):
    """AGRO-AI canonical farm representation."""
    provider: str = "wiseconn"
    provider_id: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    area_acres: Optional[float] = None
    crops: Optional[List[str]] = None
    raw: Optional[Dict[str, Any]] = None  # preserve full provider payload


class CanonicalZone(BaseModel):
    """AGRO-AI canonical zone / management unit."""
    provider: str = "wiseconn"
    provider_id: str
    farm_provider_id: str
    name: str
    zone_type: Optional[str] = None
    area_ha: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


class CanonicalMeasure(BaseModel):
    """AGRO-AI canonical sensor / measurement source."""
    provider: str = "wiseconn"
    provider_id: str
    zone_provider_id: str
    name: str
    variable: str  # normalized: soil_vwc, temperature, humidity, etc.
    unit: str  # normalized unit
    depth_inches: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None


class CanonicalDataPoint(BaseModel):
    """AGRO-AI canonical time series data point."""
    timestamp: datetime
    value: Optional[float] = None
    unit: str
    variable: str
    depth_inches: Optional[float] = None
    source_measure_id: str
    provider: str = "wiseconn"


class CanonicalIrrigation(BaseModel):
    """AGRO-AI canonical irrigation event."""
    provider: str = "wiseconn"
    provider_id: Optional[str] = None
    zone_provider_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    volume_m3: Optional[float] = None
    status: ExecutionStatus = ExecutionStatus.APPLIED
    program_name: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# WiseConn sensor type / unit -> AGRO-AI variable name
VARIABLE_MAP: Dict[str, str] = {
    "soil moisture": "soil_vwc",
    "soil_moisture": "soil_vwc",
    "vwc": "soil_vwc",
    "volumetric water content": "soil_vwc",
    "temperature": "temperature",
    "air temperature": "temperature",
    "humidity": "humidity",
    "relative humidity": "humidity",
    "wind speed": "wind_speed",
    "wind": "wind_speed",
    "solar radiation": "solar_radiation",
    "radiation": "solar_radiation",
    "rain": "rainfall",
    "rainfall": "rainfall",
    "precipitation": "rainfall",
    "et0": "et0",
    "evapotranspiration": "et0",
    "eto": "et0",
    "flow": "flow",
    "pressure": "pressure",
    "ec": "electrical_conductivity",
    "electrical conductivity": "electrical_conductivity",
    "salinity": "salinity",
}

UNIT_NORMALIZATION: Dict[str, str] = {
    "%": "percent",
    "cb": "cbar",
    "°c": "celsius",
    "°f": "fahrenheit",
    "mm": "mm",
    "in": "inches",
    "m/s": "m_per_s",
    "km/h": "km_per_h",
    "w/m2": "w_per_m2",
    "w/m²": "w_per_m2",
    "l": "liters",
    "gal": "gallons",
    "m3": "m3",
    "m³": "m3",
    "ds/m": "ds_per_m",
    "ms/cm": "ms_per_cm",
}


def normalize_variable(raw_name: Optional[str], raw_unit: Optional[str] = None) -> str:
    """Map a WiseConn sensor/variable name to AGRO-AI canonical variable."""
    if not raw_name:
        return "unknown"
    key = raw_name.strip().lower()
    if key in VARIABLE_MAP:
        return VARIABLE_MAP[key]
    # Fallback: check if unit gives us a hint
    if raw_unit:
        unit_lower = raw_unit.strip().lower()
        if unit_lower in ("%", "cb", "cbar"):
            return "soil_vwc"
    return key.replace(" ", "_")


def normalize_unit(raw_unit: Optional[str]) -> str:
    """Normalize a WiseConn unit string."""
    if not raw_unit:
        return "unknown"
    key = raw_unit.strip().lower()
    return UNIT_NORMALIZATION.get(key, key)
