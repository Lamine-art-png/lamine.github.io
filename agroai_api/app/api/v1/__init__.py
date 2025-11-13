# app/api/v1/__init__.py
from fastapi import APIRouter
from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["v1"])

