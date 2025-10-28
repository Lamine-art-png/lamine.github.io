from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, Literal

app = FastAPI()

class TenantRole(BaseModel):
    tenant_id: str
    role: Literal["owner", "analyst"]

# Replace with DB/JWT in production; demo map:
TOKENS = {
    # "api_key_value": {"tenant_id":"t_123", "role":"owner"}
}

def get_identity(api_key: Optional[str] = Header(None, alias="x-api-key")) -> TenantRole:
    if not api_key or api_key not in TOKENS:
        raise HTTPException(status_code=401, detail="invalid api key")
    return TenantRole(**TOKENS[api_key])

def require_role(required: str):
    def checker(id: TenantRole = Depends(get_identity)):
        rank = {"analyst": 0, "owner": 1}
        if rank[id.role] < rank[required]:
            raise HTTPException(status_code=403, detail="forbidden")
        return id
    return checker

@app.get("/v1/tenant/{tenant_id}/kpis")
def kpis(tenant_id: str, id: TenantRole = Depends(require_role("analyst"))):
    if id.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="cross-tenant forbidden")
    return {"tenant_id": tenant_id, "water_saved_af": 3.2}

@app.post("/v1/tenant/{tenant_id}/secrets/rotate")
def rotate_secret(tenant_id: str, id: TenantRole = Depends(require_role("owner"))):
    if id.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="cross-tenant forbidden")
    return {"status": "rotation_scheduled"}
