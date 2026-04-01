"""Adapter registry for managing provider adapters."""
from typing import Dict, Optional
from app.adapters.base import ControllerAdapter, DataProviderAdapter
from app.adapters.wiseconn import WiseConnAdapter
from app.adapters.rainbird import RainBirdAdapter
from app.core.config import settings


class AdapterRegistry:
    """Registry for controller and data provider adapters."""

    _adapters: Dict[str, ControllerAdapter] = {}
    _data_adapters: Dict[str, DataProviderAdapter] = {}

    @classmethod
    def initialize(cls):
        """Initialize adapters from settings."""
        wiseconn = WiseConnAdapter(
            api_url=settings.WISECONN_API_URL,
            api_key=settings.WISECONN_API_KEY,
            timeout=settings.WISECONN_TIMEOUT_SECONDS,
            max_retries=settings.WISECONN_MAX_RETRIES,
        )
        cls._adapters["wiseconn"] = wiseconn
        cls._data_adapters["wiseconn"] = wiseconn

        cls._adapters["rainbird"] = RainBirdAdapter(settings.RAINBIRD_API_URL)

    @classmethod
    def get_adapter(cls, provider: str) -> Optional[ControllerAdapter]:
        """Get controller adapter by provider name."""
        if not cls._adapters:
            cls.initialize()
        return cls._adapters.get(provider.lower())

    @classmethod
    def get_data_adapter(cls, provider: str) -> Optional[DataProviderAdapter]:
        """Get data provider adapter by name."""
        if not cls._data_adapters:
            cls.initialize()
        return cls._data_adapters.get(provider.lower())

    @classmethod
    def get_wiseconn(cls) -> WiseConnAdapter:
        """Convenience: get the WiseConn adapter with full type."""
        if not cls._adapters:
            cls.initialize()
        return cls._adapters["wiseconn"]  # type: ignore


# Initialize on import
AdapterRegistry.initialize()
