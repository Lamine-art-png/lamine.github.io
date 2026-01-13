from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agroai.routers.health import router as health_router
from app.routers.demo import router as demo_router

app = FastAPI(title="AGRO-AI API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agroai-pilot.com",
        "https://www.agroai-pilot.com",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Health (includes build SHA)
app.include_router(health_router)

# ✅ Demo endpoints
app.include_router(demo_router, prefix="/v1/demo", tags=["demo"])

