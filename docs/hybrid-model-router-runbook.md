# AGRO-AI Hybrid Model Router Runbook

## Purpose

Run Ask AGRO-AI behind one stable customer-facing API while keeping four inference lanes explicit and truthful:

- **Hosted frontier**: OpenRouter primary / challenger / fast models
- **Always-on edge**: Cloudflare Workers AI Ollama-compatible origin
- **Actual local**: Mac-hosted Ollama through a distinct, Access-protected Cloudflare Tunnel hostname
- **Optional zero-price hosted test**: a time-bounded free OpenRouter route

## Production topology truth

These origins are **not the same thing**:

```text
https://local-ai.agroai-pilot.com
    -> Cloudflare Worker `agroai-local-ai-origin`
    -> optional ORIGIN_TOKEN bearer gate
    -> Workers AI model `@cf/zai-org/glm-4.7-flash`

https://ollama.agroai-pilot.com
    -> Cloudflare Access Service Auth
    -> named Cloudflare Tunnel `agroai-local-ai`
    -> Mac localhost:11434
    -> actual Ollama model `qwen3.5:4b`
```

Do not point `AI_LOCAL_BASE_URL` at `local-ai.agroai-pilot.com`. That hostname is the edge Worker, not the Mac.

Do not expose raw Ollama publicly without Access. The backend intentionally fails closed for a public local hostname unless both Cloudflare Access service-token credentials are configured.

## Recommended Render environment

```text
AI_PROVIDER=ollama

# Backwards-compatible structured / translation gateway. This is EDGE, not Mac Ollama.
AI_BASE_URL=https://local-ai.agroai-pilot.com

# Explicit always-on edge lane.
AI_EDGE_BASE_URL=https://local-ai.agroai-pilot.com
AI_EDGE_MODEL=@cf/zai-org/glm-4.7-flash
AI_EDGE_AUTH_TOKEN=<same-random-secret-as-worker-ORIGIN_TOKEN>
AI_EDGE_TIMEOUT_SECONDS=45

# Explicit real Mac Ollama lane. Add only after tunnel + Access are live.
AI_LOCAL_BASE_URL=https://ollama.agroai-pilot.com
AI_LOCAL_MODEL=qwen3.5:4b
AI_LOCAL_CF_ACCESS_CLIENT_ID=<cloudflare-service-token-client-id>
AI_LOCAL_CF_ACCESS_CLIENT_SECRET=<cloudflare-service-token-client-secret>
AI_LOCAL_NUM_CTX=6144
AI_LOCAL_MAX_TOKENS=1200
AI_LOCAL_TIMEOUT_SECONDS=90
AI_LOCAL_THINKING=false

# Hosted frontier / challenger lanes.
AI_REASONING_MODEL=z-ai/glm-5.2
AI_REPORT_MODEL=z-ai/glm-5.2
AI_FAST_MODEL=qwen/qwen3.5-flash-02-23
AI_CHALLENGER_MODEL=deepseek/deepseek-v4-pro

# Optional, volatile free test lane. Revalidate before each rollout.
AI_FREE_MODEL=tencent/hy3:free
AI_MODEL_FALLBACKS=z-ai/glm-5.2,deepseek/deepseek-v4-pro,tencent/hy3:free,qwen/qwen3.5-flash-02-23,z-ai/glm-5-turbo,z-ai/glm-4.5-air

AI_ROUTING_MODE=hybrid
AI_MODEL_TEST_COMMANDS_ENABLED=true
AI_TIMEOUT_SECONDS=60
```

Also configure a valid hosted-provider secret:

```text
OPENROUTER_API_KEY=<secret>
```

Do not commit any key, Access client secret, edge token, or provider credential.

`AI_FREE_MODEL` is intentionally environment-controlled because zero-price hosted routes can expire or disappear.

## Local Mac preparation

Keep the current model installed during rollout. Pull the new candidate alongside it:

```bash
ollama pull qwen3.5:4b
ollama ls
```

Local smoke:

```bash
curl -s http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen3.5:4b",
    "messages":[{"role":"user","content":"Reply exactly: QWEN35 ONLINE"}],
    "stream":false,
    "think":false,
    "options":{"num_predict":40,"num_ctx":4096}
  }'
```

## Cloudflare edge origin: add bearer auth without cutting traffic

Do **not** delete or repoint the existing Worker route for `local-ai.agroai-pilot.com`.

The Worker accepts an optional secret named:

```text
ORIGIN_TOKEN
```

When that secret is absent, the route remains backward-compatible. When it is present, POST `/api/chat` requires:

```text
Authorization: Bearer <ORIGIN_TOKEN>
```

The health route remains public.

### Safe rollout order

1. Deploy backend code that knows how to send `AI_EDGE_AUTH_TOKEN`.
2. Generate one high-entropy random secret.
3. Put that value in Render as `AI_EDGE_AUTH_TOKEN` and redeploy the API.
4. Put the identical value in the Worker as `ORIGIN_TOKEN`.
5. Verify `/edge`, structured AI calls, and UI translation.

Do not set the Worker secret first; old backend instances would receive 401 until they know the token.

Wrangler example:

```bash
npx wrangler secret put ORIGIN_TOKEN --config wrangler.local-ai.toml
```

Then paste the same value already stored in Render as `AI_EDGE_AUTH_TOKEN`.

Authenticated edge smoke:

```bash
curl -s https://local-ai.agroai-pilot.com/api/chat \
  -H "Authorization: Bearer $AI_EDGE_AUTH_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"@cf/zai-org/glm-4.7-flash",
    "messages":[{"role":"user","content":"Reply exactly: EDGE ONLINE"}],
    "stream":false
  }'
```

A POST without the bearer header should return 401 after `ORIGIN_TOKEN` is configured.

## Cloudflare: add a distinct secured real-Ollama hostname

Reuse the existing named tunnel `agroai-local-ai` for the Mac and create a separate hostname:

```bash
cloudflared tunnel route dns agroai-local-ai ollama.agroai-pilot.com
```

The tunnel ingress must send that hostname to Ollama:

```yaml
ingress:
  - hostname: ollama.agroai-pilot.com
    service: http://127.0.0.1:11434
  - service: http_status:404
```

Then run the tunnel from its existing config. When installing it as a system service, remember: the service removes the need to keep a Terminal window open, but the Mac itself must still be powered on and connected.

### Protect the hostname with Cloudflare Access

Create a self-hosted Access application for:

```text
ollama.agroai-pilot.com
```

Create a dedicated service token for the Render backend, then create an Access policy with action:

```text
Service Auth
```

Allow only that service token. Store its generated Client ID and Client Secret in Render as:

```text
AI_LOCAL_CF_ACCESS_CLIENT_ID
AI_LOCAL_CF_ACCESS_CLIENT_SECRET
```

The backend sends them on every real-Ollama request using:

```text
CF-Access-Client-Id
CF-Access-Client-Secret
```

Do not add a broad public Allow policy to the Ollama hostname.

Access-protected real-Ollama smoke:

```bash
curl -s https://ollama.agroai-pilot.com/api/tags \
  -H "CF-Access-Client-Id: $AI_LOCAL_CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $AI_LOCAL_CF_ACCESS_CLIENT_SECRET"
```

A request without those headers should be denied after Access is configured.

Edge health smoke remains separate:

```bash
curl -s https://local-ai.agroai-pilot.com/health
```

Expected edge identity:

```json
{"status":"ok","provider":"cloudflare-workers-ai","model":"@cf/zai-org/glm-4.7-flash"}
```

## Portal tests

With `AI_MODEL_TEST_COMMANDS_ENABLED=true`, ask the same question with each prefix:

```text
/local What should I do with my data?
/edge What should I do with my data?
/glm What should I do with my data?
/deepseek What should I do with my data?
/free What should I do with my data?
/auto What should I do with my data?
```

Forced routes are isolated. They do not silently switch to a different model.

## Normal hybrid behavior

- quick/fast profile: edge -> actual local -> hosted remote
- standard reasoning: hosted remote -> edge -> actual local
- reports: hosted remote -> edge -> actual local
- deep analysis: hosted remote -> edge -> actual local

A 401/402/403 from the hosted account fails fast instead of wasting latency retrying every hosted model; the router then proceeds to edge/local fallbacks.

## Runtime verification

Check the secret-free lane endpoint:

```text
GET /v1/runtime/ai-router-status
```

The model-router status must distinguish hosted, edge, and local lane configuration. Never accept a status payload or trace that calls `local-ai.agroai-pilot.com` a Mac Ollama model.

For a public local hostname, the local lane is considered configured only when the Access service-token credentials are present. The endpoint reports booleans only; it never returns the service-token values or edge bearer secret.

## Rollback

Fast rollback that keeps the always-on edge lane:

```text
AI_ROUTING_MODE=edge_only
AI_MODEL_TEST_COMMANDS_ENABLED=false
```

To return to the old Mac model without deleting `qwen3.5:4b`:

```text
AI_LOCAL_MODEL=qwen3:1.7b
AI_ROUTING_MODE=local_first
AI_MODEL_TEST_COMMANDS_ENABLED=false
```

If edge bearer auth causes a rollout issue, remove `ORIGIN_TOKEN` from the Worker first so older API instances can talk to it again, then clear `AI_EDGE_AUTH_TOKEN` from Render.

No model deletion, Worker-route deletion, or tunnel replacement is required.
