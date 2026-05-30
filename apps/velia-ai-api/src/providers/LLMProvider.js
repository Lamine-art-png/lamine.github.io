export class LLMProvider {
  constructor(name = "mock", options = {}) {
    this.name = name;
    this.model = options.model || name;
    this.mode = options.mode || "mock";
    this.fallbackReason = options.fallbackReason || null;
  }

  isConfigured() {
    return this.mode === "live";
  }

  async generate(_prompt, _options = {}) { throw new Error("LLMProvider.generate not implemented"); }
}
