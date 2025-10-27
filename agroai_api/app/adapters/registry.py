"""Adapter registry for managing provider adapters."""
from typing import Dict, Optional
from app.adapters.base import ControllerAdapter
from app.adapters.wiseconn import WiseConnAdapter
from app.adapters.rainbird import RainBirdAdapter
from app.core.config import settings


class AdapterRegistry:
    """Registry for controller adapters."""

    _adapters: Dict[str, ControllerAdapter] = {}

    @classmethod
    def initialize(cls):
        """Initialize adapters."""
        cls._adapters["wiseconn"] = WiseConnAdapter(settings.WISECONN_API_URL)
        cls._adapters["rainbird"] = RainBirdAdapter(settings.RAINBIRD_API_URL)

    @classmethod
    def get_adapter(cls, provider: str) -> Optional[ControllerAdapter]:
        """Get adapter by provider name."""
        if not cls._adapters:
            cls.initialize()

        return cls._adapters.get(provider.lower())


# Initialize on import
AdapterRegistry.initialize()
