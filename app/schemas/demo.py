from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any

SoilType = Literal["sand", "loam", "clay", "silt", "unknown"]
ModeType = Literal["real", "synthetic"]
ActionType = Literal["irrigate", "hold", "reduce"]
ConfidenceType = Literal["high", "medium", "low"]

class DemoBlock(BaseModel):
    id: str
    label: str
    lat: float
    lon: float
    crop: str
    acres: Optional[float] = None
    soil_type: Optional[str] = None
    region: Optional[str] = None

class Assumptions(BaseModel):
    root_depth_m: float = Field(0.9, ge=0.2, le=2.0)
    irrigation_efficiency: float = Field(0.85, ge=0.5, le=0.98)
    soil_type: SoilType = "loam"

class DemoRecommendationRequest(BaseModel):
    block_id: str
    mode: ModeType = "real"
    assumptions: Assumptions = Assumptions()

class RecommendationOut(BaseModel):
    action: ActionType
    amount_in: Optional[float] = None
    window: Optional[str] = None
    cadence: Optional[str] = None

class DemoRecommendationResponse(BaseModel):
    block: Dict[str, Any]
    recommendation: RecommendationOut
    drivers: Dict[str, Any]
    confidence: ConfidenceType
    notes: Optional[List[str]] = None
    soil_balance: Optional[List[float]] = None
    api_debug: Optional[Dict[str, Any]] = None

