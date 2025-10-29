"""Structured JSON logging configuration."""
import logging
import sys
from pythonjsonlogger import jsonlogger
from contextvars import ContextVar

from app.core.config import settings

# Context variable for request ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with request ID."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record['request_id'] = request_id_var.get()
        log_record['service'] = 'agroai-api'


def setup_logging():
    """Configure structured logging."""
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


def set_request_id(request_id: str):
    """Set request ID in context."""
    request_id_var.set(request_id)


def get_request_id() -> str:
    """Get current request ID."""
    return request_id_var.get()
