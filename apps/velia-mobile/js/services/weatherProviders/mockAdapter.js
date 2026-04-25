import { WeatherProviderAdapter } from "./baseAdapter.js";

export class MockWeatherAdapter extends WeatherProviderAdapter {
  constructor() {
    super("mock");
  }

  async getCurrentWeather(location = "unknown") {
    const hour = new Date().getHours();
    const temperature = hour > 13 ? 34 : 27;
    const rainChance = 18;
    const rainfallForecastMm = rainChance > 40 ? 8 : 1;
    const humidity = 38;
    const wind = 15;
    const evapotranspiration = 5.4;
    const heatRisk = temperature >= 33 ? "elevated" : "low";
    const frostRisk = temperature <= 3 ? "elevated" : "low";

    return {
      location,
      temperature,
      rainChance,
      rainfallForecastMm,
      wind,
      humidity,
      evapotranspiration,
      heatRisk,
      frostRisk,
      forecastSummary: heatRisk === "elevated" ? "Hot and dry with low chance of rain." : "Stable weather expected.",
      lastUpdated: new Date().toISOString(),
      source: this.name,
    };
  }
}
