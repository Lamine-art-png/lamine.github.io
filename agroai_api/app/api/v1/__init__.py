from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()

# All v1 endpoints currently live in health.py
api_router.include_router(
    health.router,
    tags=["v1"],
)

