import test from "node:test";
import assert from "node:assert/strict";
import { modelRouter } from "../ai/modelRouter.js";

test("model router maps reasoning/fast/translation", () => {
  assert.equal(modelRouter.route("reasoning").id, "reasoningModel");
  assert.equal(modelRouter.route("fast").id, "fastModel");
  assert.equal(modelRouter.route("translate").id, "translationModel");
});

test("llm provider falls back when no key exists", async () => {
  const llm = modelRouter.llmProvider();
  const result = await llm.generate("hello", { task: "reasoning", model: modelRouter.modelFor("reasoning") });
  assert.ok(result.text);
});
