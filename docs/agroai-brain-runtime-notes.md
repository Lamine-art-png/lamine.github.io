# AGRO-AI Brain runtime diagnosis

The June 30 screen recording showed the chat rendering the safe-mode sentence: live model reasoning did not complete. That is not a frontend tone issue. It means the deployed route returned fallback instead of a live model result.

Fixes in this branch:

- The AI gateway now accepts model overrides as a valid configured model. Previously, a deployment with provider/base/key but no AI_MODEL could still fall back even though the router selected a model at runtime.
- The gateway normalizes AI_BASE_URL if the full `/chat/completions` URL was pasted into Render.
- The gateway accepts `OPENROUTER_API_KEY` as an alias through the process environment.
- Model routing now uses verified OpenRouter ids.
- The chat UI no longer brands the page as “AGRO-AI Brain”.
- The UI no longer renders safe-mode fallback as if it were an AI answer. If live inference is not connected, it shows an explicit connection error instead of fake analysis.
