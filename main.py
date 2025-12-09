from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import demo router (you will create this file)
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

@app.get("/v1/health")
def health():
    return {"status": "ok", "version": app.version}

app.include_router(demo_router, prefix="/v1/demo", tags=["demo"])

