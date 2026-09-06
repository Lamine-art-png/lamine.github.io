import { LLMProvider } from "./LLMProvider.js";

export class FailoverLLMProvider extends LLMProvider {
  constructor(primary, fallback = null) {
    super(primary?.name || "terris", {
      model: primary?.model || "terris-core-v0",
      mode: primary?.mode || "mock",
      fallbackReason: primary?.fallbackReason || null,
    });
    this.primary = primary;
    this.fallback = fallback?.isConfigured?.() ? fallback : null;
  }

  isConfigured() {
    return Boolean(this.primary?.isConfigured?.() || this.fallback?.isConfigured?.());
  }

  async generate(prompt, options = {}) {
    if (this.primary?.isConfigured?.()) {
      try {
        const result = await this.primary.generate(prompt, options);
        return { ...result, failoverUsed: false, failoverReason: null };
      } catch (error) {
        if (!this.fallback) throw error;
        const result = await this.fallback.generate(prompt, options);
        return {
          ...result,
          failoverUsed: true,
          failoverReason: error.message,
          primaryProvider: this.primary.name,
          primaryModel: this.primary.model,
        };
      }
    }

    if (this.fallback) {
      const result = await this.fallback.generate(prompt, options);
      return {
        ...result,
        failoverUsed: true,
        failoverReason: this.primary?.fallbackReason || "Terris Core unavailable",
        primaryProvider: this.primary?.name || "terris",
        primaryModel: this.primary?.model || null,
      };
    }

    throw new Error(this.primary?.fallbackReason || "No configured reasoning provider");
  }
}
