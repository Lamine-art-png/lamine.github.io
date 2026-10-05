"""Verified AWS purchase identities; resolving a token never grants access."""
from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, String
from app.db.base import Base


class AwsMarketplaceRegistration(Base):
    __tablename__ = "aws_marketplace_registrations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    license_arn = Column(String(1200), nullable=False, unique=True)
    customer_aws_account_id = Column(String(12), nullable=False)
    product_code = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending_license")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
