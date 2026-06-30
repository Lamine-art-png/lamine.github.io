# PR summary

This branch fixes the actual runtime path behind the robotic chat response:

1. The AI gateway now treats router-provided model overrides as valid configuration.
2. The gateway normalizes OpenRouter base URLs.
3. Model routing uses verified OpenRouter ids.
4. The Ask AGRO-AI page no longer shows an internal “Brain” tag.
5. Safe-mode/fallback output is no longer rendered as a fake AI chat answer.
