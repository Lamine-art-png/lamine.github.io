# AGRO-AI Platform Python SDK

Private, unpublished package for server-side test and partner integrations.
Set `AGROAI_API_KEY` and use `AgroAIPlatformClient` or
`AsyncAgroAIPlatformClient`. Never embed an API key in browser code.

`ApiResponse.request_id` is the server-generated response identifier.
`ApiResponse.client_correlation_id` is the bounded optional value sent as
`X-Request-Id`; it is correlation metadata only and is never a billing or
idempotency identity. Writes use the separate `Idempotency-Key` option.

See `examples/` and the repository release runbook. Publishing is deliberately
out of scope until the SDK-download and public-documentation gates are approved.

## AGRO-AI Intelligence

```python
from agroai import AgroAI

client = AgroAI()  # AGROAI_API_KEY
result = client.intelligence.run(
    "Why are the lower leaves yellowing?",
    task="field_diagnosis",
    context={"crop": {"name": "tomato", "growth_stage": "fruit set"}},
    response_format="diagnosis",
)
print(result.structured_output)
```

Jobs (`client.intelligence.jobs.create/wait`), streaming (`client.intelligence.stream`),
sessions, files, knowledge and tools are documented in
[docs/INTELLIGENCE_PLATFORM_V1.md](../../docs/INTELLIGENCE_PLATFORM_V1.md).
