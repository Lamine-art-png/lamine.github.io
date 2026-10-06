# AGRO-AI Platform TypeScript SDK

Private, unpublished server-runtime SDK. API keys are machine credentials; the
package deliberately refuses to construct a client in a browser runtime.

`ApiResponse.requestId` is the server-generated response identifier.
`ApiResponse.clientCorrelationId` is the bounded optional value sent as
`X-Request-Id`; it is correlation metadata only and is never a billing or
idempotency identity. Writes use the separate `idempotencyKey` option.

## AGRO-AI Intelligence

```ts
import { AgroAI } from "@agro-ai/platform";

const client = new AgroAI(); // AGROAI_API_KEY, server-side only
const result = await client.intelligence.run({
  question: "Why are the lower leaves yellowing?",
  task: "field_diagnosis",
  context: { crop: { name: "tomato", growth_stage: "fruit set" } },
  responseFormat: "diagnosis",
});
for await (const event of client.intelligence.stream({ question: "Plan irrigation for B7" })) console.log(event.event);
```

See [docs/INTELLIGENCE_PLATFORM_V1.md](../../docs/INTELLIGENCE_PLATFORM_V1.md).
