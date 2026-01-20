from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import demo

app = FastAPI(title="AGRO-AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep both for compatibility
app.include_router(demo.router, prefix="/demo", tags=["demo"])
app.include_router(demo.router, prefix="/v1/demo", tags=["demo"])

@app.get("/health")
def health():
    return {"ok": True}
