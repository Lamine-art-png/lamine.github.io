# Local AI stabilization notes

This note documents the stabilization target for local Ollama mode:

- Local mode should answer the actual user question, not repeat fallback text.
- The prompt should put the user question first, not bury it in JSON.
- The model request should disable or minimize thinking where supported.
- If the local model returns empty content, the fallback must be question-aware.
