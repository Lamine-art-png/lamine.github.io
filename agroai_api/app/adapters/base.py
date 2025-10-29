"""Base adapter interfaces."""
from abc import ABC, abstractmethod
from typing import Dict, Optional
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
