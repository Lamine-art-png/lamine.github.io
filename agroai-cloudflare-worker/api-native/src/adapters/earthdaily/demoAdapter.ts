import type { EarthDailyRawInput, TimeSeriesPoint } from "../../schemas/earthdaily";
import { SAMPLE_FIELD } from "../demo/sampleField";

const START = "2026-04-22T00:00:00-07:00";

export function buildDemoEarthDailyInput(fieldId = SAMPLE_FIELD.field_id): EarthDailyRawInput {
  const field = { ...SAMPLE_FIELD, field_id: fieldId || SAMPLE_FIELD.field_id };
  const dates = buildDateSeries(START, 30);
  const forecastDates = buildDateSeries("2026-05-22T00:00:00-07:00", 7);

  return {
    provider: "earthdaily",
    mode: "demo",
    field,
    imagery: {
      stac_items: [
        {
          id: "S2A_MSIL2A_20260521T184921_N0511_R070_T10SGF_20260521T231024",
          collection: "sentinel-2-l2a",
          datetime: "2026-05-21T18:49:21Z",
          href: "https://example.earthdaily.ag/stac/sentinel-2-l2a/madera-almonds-20260521.json",
        },
        {
          id: "S2B_MSIL2A_20260516T184919_N0511_R070_T10SGF_20260516T224442",
          collection: "sentinel-2-l2a",
          datetime: "2026-05-16T18:49:19Z",
          href: "https://example.earthdaily.ag/stac/sentinel-2-l2a/madera-almonds-20260516.json",
        },
      ],
      acquisition_date: "2026-05-21",
      cloud_cover: 0.08,
      asset_links: {
        visual: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/visual.tif",
        nir: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/nir.tif",
        swir: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/swir.tif",
      },
      index_maps: {
        ndvi: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/ndvi.tif",
        ndmi: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/ndmi.tif",
        evi: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/evi.tif",
        ndre: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/ndre.tif",
      },
      vegetation_indices: {
        ndvi_mean: 0.74,
        ndre_mean: 0.42,
        evi_mean: 0.51,
        ndmi_mean: 0.29,
      },
      anomaly_layers: [
        {
          id: "madera-almonds-hotspot-west-row-20260521",
          type: "low_ndmi_patch",
          severity: 0.58,
          href: "https://example.earthdaily.ag/assets/madera-almonds/2026-05-21/anomaly-low-ndmi-west.tif",
        },
      ],
    },
    time_series: {
      ndvi: values(dates, 0.78, -0.0014, 0.012),
      ndmi: values(dates, 0.37, -0.0031, 0.009),
      evi: values(dates, 0.54, -0.001, 0.008),
      ndre: values(dates, 0.45, -0.0012, 0.006),
      lai: values(dates, 3.2, 0.008, 0.04),
      biomass: values(dates, 7.8, 0.035, 0.08),
      fapar: values(dates, 0.71, 0.001, 0.006),
      fcover: values(dates, 0.68, 0.0015, 0.006),
    },
    weather: {
      forecast_days: 7,
      precipitation: series(forecastDates, [0, 0, 0, 0, 1.2, 0, 0]),
      temperature_min: series(forecastDates, [16.2, 17.1, 19.5, 20.1, 18.2, 16.9, 16.4]),
      temperature_max: series(forecastDates, [30.4, 31.2, 36.6, 37.1, 33.4, 29.8, 28.9]),
      humidity: series(forecastDates, [43, 39, 31, 29, 36, 42, 46]),
      wind_speed: series(forecastDates, [3.1, 4.4, 5.7, 5.2, 4.1, 3.6, 3.2]),
      gdd: series(forecastDates, [16.8, 17.5, 20.9, 21.4, 18.9, 16.7, 16.1]),
      et0: series(dates.slice(-7), [5.4, 5.6, 5.9, 6.1, 5.8, 5.7, 5.9]),
      et_forecast: series(forecastDates, [6.2, 6.4, 7.3, 7.6, 6.8, 5.9, 5.7]),
    },
    water_context: {
      soil_moisture_surface: 0.21,
      soil_moisture_rootzone: 0.235,
      estimated_depletion: 47,
      water_stress_index: 0.48,
      irrigation_history: [
        { date: "2026-05-04", volume_mm: 18, method: "drip" },
        { date: "2026-05-11", volume_mm: 16, method: "drip" },
        { date: "2026-05-18", volume_mm: 14, method: "drip" },
      ],
      applied_water_actuals: [
        { date: "2026-05-04", volume_mm: 17.4 },
        { date: "2026-05-11", volume_mm: 15.7 },
        { date: "2026-05-18", volume_mm: 13.8 },
      ],
    },
    agronomic_events: {
      emergence: "2026-03-18",
      peak_growth: "2026-06-18",
      senescence: "2026-09-08",
      change_detection: [
        { date: "2026-05-19", type: "canopy_moisture_decline", magnitude: 0.34 },
      ],
      hotspot_alerts: [
        {
          date: "2026-05-21",
          type: "localized_water_stress",
          severity: 0.62,
          bbox: [-120.1328, 36.9461, -120.1287, 36.9493],
        },
      ],
    },
    metadata: {
      source: "agroai-demo-fixture",
      retrieved_at: "2026-05-22T15:00:00-07:00",
      data_freshness: "8h",
      missing_fields: [],
      quality_flags: ["demo_fixture", "clear_scene", "localized_hotspot"],
    },
  };
}

function buildDateSeries(start: string, count: number): string[] {
  const startDate = new Date(start);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(startDate.getTime() + index * 86_400_000);
    return date.toISOString().slice(0, 10);
  });
}

function values(dates: string[], base: number, slope: number, amplitude: number): TimeSeriesPoint[] {
  return dates.map((date, index) => ({
    date,
    value: round(base + slope * index + Math.sin(index / 2.8) * amplitude, 3),
    quality: index % 11 === 0 ? "interpolated" : "observed",
  }));
}

function series(dates: string[], nums: number[]): TimeSeriesPoint[] {
  return dates.map((date, index) => ({
    date,
    value: nums[index] ?? nums[nums.length - 1],
    quality: "forecast",
  }));
}

function round(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

