# ADR 003: API Key Hashing And Verification

Decision: Platform API keys use `agro_test_` and `agro_live_` prefixes, one-time plaintext display, and HMAC-SHA256 storage with server-side pepper.

Verification is read-oriented and does not update usage fields or commit on the auth hot path.
