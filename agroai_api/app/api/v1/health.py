from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        database="ok",
        version=settings.VERSION,  # <- reads from config instead of hard-coded "1.0.0"
    )

