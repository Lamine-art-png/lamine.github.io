from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.saas import User
from app.services.account_recovery import GENERIC_RECOVERY_MESSAGE, consume_recovery_token, create_recovery_token, send_recovery_email
from app.services.password_policy import password_policy_error

router = APIRouter(prefix="/account-recovery", tags=["account-recovery"])
logger = logging.getLogger(__name__)


class StartRecovery(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email required")
        return value


class CompleteRecovery(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    replacement_credential: str = Field(min_length=12, max_length=128)


def _deliver(email: str, token: str) -> None:
    try:
        send_recovery_email(SimpleNamespace(email=email), token)
    except Exception:
        logger.exception("Account recovery delivery failed")


@router.post("/start")
def start(payload: StartRecovery, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> dict:
    try:
        user = db.query(User).filter(User.email == payload.email).first()
        if user and user.is_active and user.password_hash:
            token = create_recovery_token(db, user)
            if token:
                email = str(user.email)
                db.commit()
                background_tasks.add_task(_deliver, email, token)
            else:
                db.rollback()
    except Exception:
        db.rollback()
        logger.exception("Account recovery request failed")
    return {"message": GENERIC_RECOVERY_MESSAGE}


@router.post("/complete")
def complete(payload: CompleteRecovery, db: Session = Depends(get_db)) -> dict:
    policy_error = password_policy_error(payload.replacement_credential)
    if policy_error:
        raise HTTPException(status_code=422, detail=policy_error)
    try:
        user = consume_recovery_token(db, payload.token, payload.replacement_credential)
    except Exception:
        db.rollback()
        logger.exception("Account recovery completion failed")
        user = None
    if not user:
        raise HTTPException(status_code=400, detail="Recovery link is invalid or expired")
    return {"status": "recovered", "message": "Account access updated. Sign in with your new credential."}
