export class LLMProvider {
  constructor(name = "mock") { this.name = name; }
  async generate(_prompt, _options = {}) { throw new Error("LLMProvider.generate not implemented"); }
}
