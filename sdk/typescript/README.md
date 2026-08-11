# AGRO-AI Platform TypeScript SDK

Private, unpublished server-runtime SDK. API keys are machine credentials; the
package deliberately refuses to construct a client in a browser runtime.

`ApiResponse.requestId` is the server-generated response identifier.
`ApiResponse.clientCorrelationId` is the bounded optional value sent as
`X-Request-Id`; it is correlation metadata only and is never a billing or
idempotency identity. Writes use the separate `idempotencyKey` option.
