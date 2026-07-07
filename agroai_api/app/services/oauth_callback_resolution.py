"""Compatibility import for deterministic one-time callback resolution.

The active implementation lives in ``oauth_callback_resolution_v2`` and resolves
exactly one callback URL from the provider identity already protected by signed
state before invoking the existing single-use nonce consumer.
"""
from app.services.oauth_callback_resolution_v2 import (
    consume_state_for_signed_provider_redirect,
    install_exact_oauth_callback_resolution,
)

__all__ = [
    "consume_state_for_signed_provider_redirect",
    "install_exact_oauth_callback_resolution",
]
