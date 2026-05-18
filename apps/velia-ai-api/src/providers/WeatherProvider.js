export class WeatherProvider {
  constructor(name = "mock") { this.name = name; }
  async getContext(_location) { throw new Error("WeatherProvider.getContext not implemented"); }
}
