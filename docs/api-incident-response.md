# Platform API Incident Response

For suspected key or credential exposure:

1. Do not print the secret.
2. Record affected file, route, or system and the secret type.
3. Revoke or rotate the secret immediately.
4. Disable affected project/service account if needed.
5. Check usage events, request IDs, and webhook deliveries.
6. Prepare history-purge steps if the secret entered Git history.
7. Document residual risk and customer communication needs.
