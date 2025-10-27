"""Report schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import date


class ROIReportResponse(BaseModel):
    """ROI report response."""
    block_id: Optional[str] = None
    period_start: date
    period_end: date
    water_saved_m3: float
    energy_saved_kwh: float
    cost_saved_usd: float
    yield_delta_pct: Optional[float] = None
    baseline_method: str = "historical_average"


class WaterBudgetResponse(BaseModel):
    """Water budget response."""
    block_id: str
    allocated_m3: float
    used_m3: float
    remaining_m3: float
    utilization_pct: float
    period: str = "current_season"
