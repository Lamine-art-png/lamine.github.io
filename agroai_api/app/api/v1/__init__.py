from fastapi import APIRouter

from . import health

api_router = APIRouter()

# All v1 endpoints (health + demo) are in health.py for now
api_router.include_router(health.router, tags=["v1"])

