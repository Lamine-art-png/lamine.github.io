export class WeatherProvider {
  constructor(name = "mock", options = {}) {
    this.name = name;
    this.mode = options.mode || "mock";
    this.fallbackReason = options.fallbackReason || null;
  }

  isConfigured() {
    return this.mode === "live";
  }

  async getContext(_location) { throw new Error("WeatherProvider.getContext not implemented"); }
}
