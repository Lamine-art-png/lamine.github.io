"""Tests for WiseConn integration — critical path coverage.

Tests the adapter, canonical mapping, sync service, and API endpoints
using mocked HTTP responses (no live API calls).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.wiseconn import WiseConnAdapter, WiseConnAuthError
from app.schemas.wiseconn import (
    CanonicalFarm,
    CanonicalMeasure,
    CanonicalZone,
    ExecutionStatus,
    WCDataPointRaw,
    WCFarmRaw,
    normalize_unit,
    normalize_variable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    """Create a WiseConn adapter for testing."""
    return WiseConnAdapter(
        api_url="https://api.wiseconn.com",
        api_key="test-key-12345",
        timeout=5,
    )


@pytest.fixture
def sample_farm_raw():
    return {
        "id": 42,
        "name": "Demo Ferti and Flush",
        "lat": 36.7378,
        "lng": -119.7871,
        "timezone": "America/Los_Angeles",
    }


@pytest.fixture
def sample_zone_raw():
    return {
        "id": 101,
        "name": "Zone 1",
        "farmId": 42,
        "type": "irrigation",
        "area": 140.0,
    }


@pytest.fixture
def sample_measure_raw():
    return {
        "id": 201,
        "name": "Soil Moisture",
        "unit": "%",
        "sensorType": "soil_moisture",
        "depth": 12.0,
        "zoneId": 101,
        "nodeId": 301,
    }


@pytest.fixture
def sample_data_points():
    return [
        {"time": "2024-03-15T10:00:00", "value": "35.2"},
        {"time": "2024-03-15T11:00:00", "value": "34.8"},
        {"time": "2024-03-15T12:00:00", "value": ""},
        {"time": "2024-03-15T13:00:00", "value": "33.5"},
        {"time": "2024-03-15T14:00:00", "value": None},
    ]


@pytest.fixture
def sample_irrigation_raw():
    return {
        "id": 501,
        "zoneId": 101,
        "status": "Executed OK",
        "initTime": "2024-03-15T06:00:00.000Z",
        "endTime": "2024-03-15T06:30:00.000Z",
        "durationMinutes": 30,
        "programName": "Morning Cycle",
        "volume": {"value": 10000, "unitAbrev": "gal"},
    }


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    """Test WiseConn raw schema validation."""

    def test_farm_raw_parsing(self, sample_farm_raw):
        farm = WCFarmRaw.model_validate(sample_farm_raw)
        assert farm.id == 42
        assert farm.name == "Demo Ferti and Flush"
        assert farm.latitude == 36.7378
        assert farm.longitude == -119.7871

    def test_farm_raw_with_alias(self):
        """Test that lat/lng aliases work."""
        data = {"id": 1, "lat": 36.0, "lng": -120.0}
        farm = WCFarmRaw.model_validate(data)
        assert farm.latitude == 36.0
        assert farm.longitude == -120.0

    def test_farm_raw_extra_fields_preserved(self):
        """Extra fields from API should not cause validation errors."""
        data = {"id": 1, "name": "Test", "unknownField": "value"}
        farm = WCFarmRaw.model_validate(data)
        assert farm.id == 1

    def test_data_point_value_coercion(self):
        """Test that string values are coerced to float."""
        dp = WCDataPointRaw.model_validate({"time": 1710500000000, "value": "35.2"})
        assert dp.value == 35.2

    def test_data_point_null_value(self):
        dp = WCDataPointRaw.model_validate({"time": 1710500000000, "value": None})
        assert dp.value is None

    def test_data_point_empty_string(self):
        dp = WCDataPointRaw.model_validate({"time": 1710500000000, "value": ""})
        assert dp.value is None


# ---------------------------------------------------------------------------
# Variable and unit normalization tests
# ---------------------------------------------------------------------------

class TestNormalization:
    """Test variable and unit normalization."""

    def test_soil_moisture_variants(self):
        assert normalize_variable("Soil Moisture") == "soil_vwc"
        assert normalize_variable("soil_moisture") == "soil_vwc"
        assert normalize_variable("VWC") == "soil_vwc"
        assert normalize_variable("Volumetric Water Content") == "soil_vwc"

    def test_weather_variables(self):
        assert normalize_variable("Temperature") == "temperature"
        assert normalize_variable("Humidity") == "humidity"
        assert normalize_variable("Wind Speed") == "wind_speed"
        assert normalize_variable("Rainfall") == "rainfall"
        assert normalize_variable("ET0") == "et0"

    def test_unknown_variable(self):
        assert normalize_variable("Battery Level") == "battery_level"

    def test_unit_normalization(self):
        assert normalize_unit("%") == "percent"
        assert normalize_unit("°C") == "celsius"
        assert normalize_unit("mm") == "mm"
        assert normalize_unit("W/m²") == "w_per_m2"

    def test_unit_passthrough(self):
        assert normalize_unit("custom_unit") == "custom_unit"

    def test_none_handling(self):
        assert normalize_variable(None) == "unknown"
        assert normalize_unit(None) == "unknown"


# ---------------------------------------------------------------------------
# Canonical mapping tests
# ---------------------------------------------------------------------------

class TestCanonicalMapping:
    """Test raw → canonical mapping via adapter methods."""

    def test_map_farm(self, adapter, sample_farm_raw):
        farm = adapter.map_farm(sample_farm_raw)
        assert isinstance(farm, CanonicalFarm)
        assert farm.provider == "wiseconn"
        assert farm.provider_id == "42"
        assert farm.name == "Demo Ferti and Flush"
        assert farm.latitude == 36.7378
        assert farm.raw == sample_farm_raw

    def test_map_zone(self, adapter, sample_zone_raw):
        zone = adapter.map_zone(sample_zone_raw, farm_id="42")
        assert isinstance(zone, CanonicalZone)
        assert zone.provider_id == "101"
        assert zone.name == "Zone 1"
        assert zone.farm_provider_id == "42"
        # 140 acres → ~56.66 ha
        assert zone.area_ha is not None
        assert abs(zone.area_ha - 56.656) < 0.1

    def test_map_measure(self, adapter, sample_measure_raw):
        measure = adapter.map_measure(sample_measure_raw, zone_id="101")
        assert isinstance(measure, CanonicalMeasure)
        assert measure.variable == "soil_vwc"
        assert measure.unit == "percent"
        assert measure.depth_inches == 12.0
        assert measure.zone_provider_id == "101"

    def test_map_data_points(self, adapter, sample_measure_raw, sample_data_points):
        measure = adapter.map_measure(sample_measure_raw, zone_id="101")
        points = adapter.map_data_points(sample_data_points, measure)
        # Should skip None and empty values → 3 valid points
        assert len(points) == 3
        assert points[0].value == 35.2
        assert points[0].variable == "soil_vwc"
        assert points[0].unit == "percent"
        assert points[0].depth_inches == 12.0

    def test_map_irrigation(self, adapter, sample_irrigation_raw):
        irr = adapter.map_irrigation(sample_irrigation_raw, zone_id="101")
        assert irr.provider_id == "501"
        assert irr.zone_provider_id == "101"
        assert irr.duration_minutes == 30
        assert irr.status == ExecutionStatus.APPLIED
        assert irr.program_name == "Morning Cycle"
        assert irr.start_time is not None


# ---------------------------------------------------------------------------
# Timestamp parsing tests
# ---------------------------------------------------------------------------

class TestTimestampParsing:
    """Test the adapter's timestamp parsing."""

    def test_iso_format(self, adapter):
        ts = adapter._parse_timestamp("2024-03-15T10:00:00")
        assert ts == datetime(2024, 3, 15, 10, 0, 0)

    def test_iso_with_z(self, adapter):
        ts = adapter._parse_timestamp("2024-03-15T10:00:00Z")
        assert ts is not None
        assert ts.year == 2024

    def test_epoch_milliseconds(self, adapter):
        # 2024-03-15 10:00:00 UTC in ms
        ts = adapter._parse_timestamp(1710500400000)
        assert ts is not None
        assert ts.year == 2024

    def test_epoch_seconds(self, adapter):
        ts = adapter._parse_timestamp(1710500400)
        assert ts is not None

    def test_wiseconn_format(self, adapter):
        ts = adapter._parse_timestamp("2024/03/15 10:00")
        assert ts == datetime(2024, 3, 15, 10, 0)

    def test_none_returns_none(self, adapter):
        assert adapter._parse_timestamp(None) is None

    def test_invalid_returns_none(self, adapter):
        assert adapter._parse_timestamp("not-a-date") is None


# ---------------------------------------------------------------------------
# HTTP client tests (mocked)
# ---------------------------------------------------------------------------

class TestHTTPClient:
    """Test adapter HTTP methods with mocked responses."""

    @pytest.mark.asyncio
    async def test_list_farms_success(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'[{"id":1,"name":"Test Farm"}]'
        mock_response.json.return_value = [{"id": 1, "name": "Test Farm"}]

        with patch.object(adapter, "_get_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            farms = await adapter.list_farms()
            assert len(farms) == 1
            assert farms[0]["name"] == "Test Farm"

    @pytest.mark.asyncio
    async def test_auth_failure_raises(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(adapter, "_get_client") as mock_client:
            client = AsyncMock()
            client.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            with pytest.raises(WiseConnAuthError):
                await adapter._get("/farms")

    @pytest.mark.asyncio
    async def test_create_irrigation(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id":999,"status":"created"}'
        mock_response.json.return_value = {"id": 999, "status": "created"}

        with patch.object(adapter, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            result = await adapter.create_irrigation(
                zone_id="101",
                start_time=datetime.utcnow() + timedelta(hours=24),
                duration_minutes=1,
            )
            assert result["id"] == 999

    @pytest.mark.asyncio
    async def test_apply_schedule_maps_to_irrigation(self, adapter):
        """Test that ControllerAdapter.apply_schedule maps correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id":888}'
        mock_response.json.return_value = {"id": 888}

        with patch.object(adapter, "_get_client") as mock_client:
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            result = await adapter.apply_schedule(
                controller_id="101",
                start_time=datetime.utcnow() + timedelta(hours=24),
                duration_min=5,
            )
            assert result["provider_schedule_id"] == "888"
            assert result["status"] == "accepted"


# ---------------------------------------------------------------------------
# Integration-level test (all layers, mocked HTTP)
# ---------------------------------------------------------------------------

class TestEndToEndMocked:
    """Test the full flow with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_discover_and_map(self, adapter):
        """Test discovery maps raw responses to canonical models."""
        farm_data = [{"id": 42, "name": "Demo Ferti and Flush", "lat": 36.7, "lng": -119.8}]
        zone_data = [{"id": 101, "name": "Zone 1", "farmId": 42}]
        measure_data = [
            {"id": 201, "name": "Soil Moisture", "unit": "%", "depth": 12},
            {"id": 202, "name": "Temperature", "unit": "°C"},
        ]

        async def mock_get(path, params=None):
            if path == "/farms":
                return farm_data
            if path.endswith("/measures"):
                return measure_data
            if path.endswith("/zones"):
                return zone_data
            return []

        adapter._get = mock_get

        farms = await adapter.list_farms()
        assert len(farms) == 1
        canonical = adapter.map_farm(farms[0])
        assert canonical.name == "Demo Ferti and Flush"
        assert canonical.provider == "wiseconn"

        zones = await adapter.list_zones("42")
        assert len(zones) == 1
        cz = adapter.map_zone(zones[0], "42")
        assert cz.name == "Zone 1"

        measures = await adapter.list_measures("101")
        assert len(measures) == 2
        cm = adapter.map_measure(measures[0], "101")
        assert cm.variable == "soil_vwc"
