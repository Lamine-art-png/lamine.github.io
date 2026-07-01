# Local AI repetition diagnosis

The June 30 recordings showed local Ask AGRO-AI returning the same fallback answer for unrelated questions.

Root cause:

- `qwen3:1.7b` is a thinking model and often returns empty `message.content` through Ollama while using its token budget in the thinking channel.
- The backend then replaced empty content with the same generic fallback sentence.
- The local route also buried the user's question inside a compact JSON object instead of putting the question first in the prompt.

Fix direction:

- Use a direct local prompt with `User question:` first.
- Add `think: false` to Ollama requests where supported.
- Keep local output small and warm with `num_predict` around 80, `num_ctx` around 1024, and `keep_alive`.
- If the model still returns empty content, fallback should be question-aware instead of repeating the same generic sentence.
