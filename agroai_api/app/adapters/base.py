"""Base adapter interfaces."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime


class ControllerAdapter(ABC):
    """Base interface for irrigation controller adapters."""

    @abstractmethod
    async def apply_schedule(
        self,
        controller_id: str,
        start_time: datetime,
        duration_min: float,
        zone_ids: Optional[list] = None,
        metadata: Optional[dict] = None,
    ) -> Dict:
        """
        Apply irrigation schedule to controller.

        Returns: {
            "provider_schedule_id": str,
            "status": str
        }
        """
        pass

    @abstractmethod
    async def cancel_schedule(self, controller_id: str, provider_schedule_id: str) -> bool:
        """Cancel a schedule."""
        pass


class DataProviderAdapter(ABC):
    """Base interface for data provider adapters (read + write path)."""

    @abstractmethod
    async def check_auth(self) -> bool:
        """Verify authentication is valid."""
        pass

    @abstractmethod
    async def list_farms(self) -> List[Dict[str, Any]]:
        """Discover farms accessible to this account."""
        pass

    @abstractmethod
    async def list_zones(self, farm_id: str) -> List[Dict[str, Any]]:
        """List zones/management units within a farm."""
        pass

    @abstractmethod
    async def list_measures(self, zone_id: str) -> List[Dict[str, Any]]:
        """List available measurement sources for a zone."""
        pass

    @abstractmethod
    async def get_measure_data(
        self,
        measure_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Get time-series data for a measure within a date range."""
        pass

    @abstractmethod
    async def create_irrigation(
        self,
        zone_id: str,
        start_time: datetime,
        duration_minutes: int,
        metadata: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Create an irrigation action. Returns provider response with ID."""
        pass

    @abstractmethod
    async def list_irrigations(
        self,
        zone_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List irrigation events for a zone."""
        pass


class WeatherAdapter(ABC):
    """Base interface for weather/ET data providers."""

    @abstractmethod
    async def get_et0_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 7,
    ) -> list:
        """Get ET0 forecast."""
        pass
