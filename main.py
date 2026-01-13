from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agroai.routers.health import router as health_router

# Demo router import — keep whichever path matches your repo
from app.routers.demo import router as demo_router
# If your demo router is actually under agroai/, use this instead:
# from agroai.routers.demo import router as demo_router

app = FastAPI(title="AGRO-AI API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agroai-pilot.com",
        "https://www.agroai-pilot.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Health endpoints (provides GET /v1/health with ok/ts/build)
app.include_router(health_router)

# ✅ Demo endpoints (mounted under /v1/demo/...)
app.include_router(demo_router, prefix="/v1/demo", tags=["demo"])

