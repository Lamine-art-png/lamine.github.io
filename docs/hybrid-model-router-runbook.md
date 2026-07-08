# AGRO-AI Hybrid Model Router Runbook

## Purpose

Run Ask AGRO-AI with one stable customer-facing API while routing work across:

- local Ollama fallback/fast lane
- primary hosted frontier lane
- hosted challenger lane
- optional zero-price hosted test lane

The working public local origin remains `https://local-ai.agroai-pilot.com`.

## Recommended Render environment

```text
AI_PROVIDER=ollama
AI_BASE_URL=https://local-ai.agroai-pilot.com
AI_LOCAL_MODEL=qwen3.5:4b
AI_ROUTING_MODE=hybrid
AI_MODEL_TEST_COMMANDS_ENABLED=true

AI_REASONING_MODEL=z-ai/glm-5.2
AI_REPORT_MODEL=z-ai/glm-5.2
AI_FAST_MODEL=qwen/qwen3.5-flash-02-23
AI_CHALLENGER_MODEL=deepseek/deepseek-v4-pro
AI_FREE_MODEL=tencent/hy3:free
AI_MODEL_FALLBACKS=z-ai/glm-5.2,deepseek/deepseek-v4-pro,tencent/hy3:free,qwen/qwen3.5-flash-02-23,z-ai/glm-5-turbo,z-ai/glm-4.5-air

AI_LOCAL_NUM_CTX=6144
AI_LOCAL_MAX_TOKENS=1200
AI_LOCAL_TIMEOUT_SECONDS=90
AI_LOCAL_THINKING=false
AI_TIMEOUT_SECONDS=60
```

Also configure a valid secret:

```text
OPENROUTER_API_KEY=<secret>
```

Do not commit the key.

`AI_FREE_MODEL` is intentionally environment-controlled because zero-price hosted routes can disappear or expire. Revalidate the provider catalog before relying on it.

## Local Mac preparation

Keep the current model installed during the rollout. Pull the new local candidate alongside it:

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

Public-origin smoke:

```bash
curl -s https://local-ai.agroai-pilot.com/api/tags
```

Do not change Cloudflare DNS or the named tunnel for this rollout while the existing origin is healthy.

## Portal tests

With `AI_MODEL_TEST_COMMANDS_ENABLED=true`, ask the same question with each prefix:

```text
/local What should I do with my data?
/glm What should I do with my data?
/deepseek What should I do with my data?
/free What should I do with my data?
/auto What should I do with my data?
```

Forced routes are isolated: they do not silently switch to a different model.

## Normal hybrid behavior

- quick/fast profile: local first, remote fallback
- standard reasoning: remote first, local fallback
- reports: remote first, local fallback
- deep analysis: remote first, local fallback

## Rollback

The code rollout is environment-driven. Immediate safe rollback:

```text
AI_LOCAL_MODEL=qwen3:1.7b
AI_ROUTING_MODE=local_only
AI_MODEL_TEST_COMMANDS_ENABLED=false
```

No model deletion, DNS change, or tunnel replacement is required.
