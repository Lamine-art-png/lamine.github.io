export class WeatherProviderAdapter {
  constructor(name) {
    this.name = name;
  }

  async getCurrentWeather(_location) {
    throw new Error("getCurrentWeather not implemented");
  }
}
