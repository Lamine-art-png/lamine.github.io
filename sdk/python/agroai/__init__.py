"""AGRO-AI Intelligence SDK.

    from agroai import AgroAI

    client = AgroAI(api_key="agro_live_...")
    result = client.intelligence.run(
        "Why are the lower leaves yellowing?",
        task="field_diagnosis",
        context={"crop": {"name": "tomato", "growth_stage": "fruit set"}},
        response_format="diagnosis",
    )
    print(result.structured_output)
"""
from ._client import AgroAI, APIObject, AsyncAgroAI, SDK_VERSION as __version__
from ._errors import (
    AgroAIError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InsufficientBalanceError,
    InternalServerError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
    UnsupportedMediaTypeError,
)

__all__ = [
    "AgroAI",
    "AsyncAgroAI",
    "APIObject",
    "AgroAIError",
    "APIConnectionError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "InsufficientBalanceError",
    "InternalServerError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
    "UnsupportedMediaTypeError",
    "__version__",
]
