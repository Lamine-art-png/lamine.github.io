import test from "node:test";
import assert from "node:assert/strict";
import { LLMProvider } from "../providers/LLMProvider.js";
import { FailoverLLMProvider } from "../providers/FailoverLLMProvider.js";

class TestProvider extends LLMProvider {
  constructor(name, behavior) {
    super(name, { model: name + "-model", mode: "live" });
    this.behavior = behavior;
    this.calls = 0;
  }

  async generate() {
    this.calls += 1;
    if (this.behavior === "fail") throw new Error(this.name + " unavailable");
    return { text: this.name + " answer", provider: this.name, model: this.model, mode: "live" };
  }
}

test("Terris failover keeps Terris Core primary when healthy", async () => {
  const terris = new TestProvider("terris", "ok");
  const frontier = new TestProvider("openai", "ok");
  const provider = new FailoverLLMProvider(terris, frontier);
  const result = await provider.generate("hello");
  assert.equal(result.provider, "terris");
  assert.equal(result.failoverUsed, false);
  assert.equal(frontier.calls, 0);
});

test("Terris failover uses configured frontier only on operational failure", async () => {
  const terris = new TestProvider("terris", "fail");
  const frontier = new TestProvider("openai", "ok");
  const provider = new FailoverLLMProvider(terris, frontier);
  const result = await provider.generate("hello");
  assert.equal(result.provider, "openai");
  assert.equal(result.failoverUsed, true);
  assert.match(result.failoverReason, /terris unavailable/);
  assert.equal(terris.calls, 1);
  assert.equal(frontier.calls, 1);
});
