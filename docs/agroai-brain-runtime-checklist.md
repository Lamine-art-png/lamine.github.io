# AGRO-AI Brain runtime checklist

Required Render variables for live OpenRouter inference:

- `AI_PROVIDER=openrouter` or `AI_PROVIDER=openai_compatible`
- `AI_BASE_URL=https://openrouter.ai/api/v1` 
  - The gateway now also normalizes `https://openrouter.ai/api/v1/chat/completions` if that was pasted by mistake.
- `AI_API_KEY=<OpenRouter key>` or `OPENROUTER_API_KEY=<OpenRouter key>`
- Optional: `AI_REASONING_MODEL=z-ai/glm-5.2`
- Optional: `AI_MODEL_FALLBACKS=z-ai/glm-5.2,z-ai/glm-5-turbo,qwen/qwen3-max-thinking,qwen/qwen3-max,qwen/qwen3-coder-plus,qwen/qwen3-next-80b-a3b-instruct,z-ai/glm-4.5,z-ai/glm-4.5-air,deepseek/deepseek-v3.1-terminus`

How to know it is actually fixed:

- The Ask AGRO-AI page should not show the “AGRO-AI Brain” chip.
- A normal prompt should return a natural answer, not the safe-mode sentence.
- If the provider is still not reachable, the UI should show a connection error rather than a fake assistant response.
