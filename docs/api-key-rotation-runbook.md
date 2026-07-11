# API Key Rotation Runbook

1. Create a replacement key for the same service account and scopes.
2. Show the plaintext key once.
3. Configure the client with the replacement.
4. Observe successful requests and usage events.
5. Revoke the old key after the overlap window.

Never send full keys in tickets, logs, screenshots, PRs, or chat.
