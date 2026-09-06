import test from "node:test";
import assert from "node:assert/strict";
import { TerrisCoreProvider } from "../providers/TerrisCoreProvider.js";
import { modelRouter } from "../ai/modelRouter.js";

test("Terris Core provider is disabled unless explicitly enabled", () => {
  const provider = new TerrisCoreProvider({ enabled: false, baseUrl: "http://localhost:8008" });
  assert.equal(provider.name, "terris");
  assert.equal(provider.mode, "mock");
  assert.equal(provider.isConfigured(), false);
});

test("Terris Core provider sends an OpenAI-compatible request", async () => {
  let request;
  const provider = new TerrisCoreProvider({
    enabled: true,
    baseUrl: "http://terris-core.test/",
    model: "terris-core-v0-test",
    fetchImpl: async (url, options) => {
      request = { url, options };
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({
          id: "terris-test-1",
          model: "terris-core-v0-test",
          choices: [{ message: { content: "{\"action\":\"monitor\"}" } }],
        }),
      };
    },
  });

  const result = await provider.generate("Return a decision", {
    system: "Use field facts.",
    schema: { type: "object", properties: { action: { type: "string" } } },
  });

  assert.equal(request.url, "http://terris-core.test/v1/chat/completions");
  const body = JSON.parse(request.options.body);
  assert.equal(body.model, "terris-core-v0-test");
  assert.ok(body.messages[0].content.includes("Preserve truth labels"));
  assert.ok(body.messages[0].content.includes("Return valid JSON"));
  assert.equal(result.provider, "terris");
  assert.equal(result.mode, "live");
  assert.equal(result.text, "{\"action\":\"monitor\"}");
});

test("model router can select Terris Core behind the explicit feature flag", () => {
  process.env.LLM_PROVIDER = "terris";
  process.env.TERRIS_CORE_ENABLED = "true";
  process.env.TERRIS_CORE_BASE_URL = "http://127.0.0.1:8008";
  process.env.TERRIS_CORE_MODEL = "terris-core-v0-test";
  try {
    const provider = modelRouter.llmProvider();
    assert.equal(provider.name, "terris");
    assert.equal(provider.mode, "live");
    assert.equal(provider.model, "terris-core-v0-test");
  } finally {
    delete process.env.LLM_PROVIDER;
    delete process.env.TERRIS_CORE_ENABLED;
    delete process.env.TERRIS_CORE_BASE_URL;
    delete process.env.TERRIS_CORE_MODEL;
  }
});
