import type { NormalizedSignalPack } from "../../schemas/signals";

export interface TimingWindow {
  recommended_window_start: string;
  recommended_window_end: string;
}

export function selectTimingWindow(pack: NormalizedSignalPack): TimingWindow {
  const offset = offsetForTimezone(pack.crop_context.timezone);
  for (let index = 0; index < Math.min(3, pack.weather_context.series.temperature_max.length); index += 1) {
    const temp = pack.weather_context.series.temperature_max[index]?.value ?? 99;
    const wind = pack.weather_context.series.wind_speed[index]?.value ?? 99;
    const precip = pack.weather_context.series.precipitation[index]?.value ?? 99;
    const date = pack.weather_context.series.temperature_max[index]?.date;
    if (date && temp < 32 && wind < 6 && precip < 5) {
      return {
        recommended_window_start: `${date}T06:00:00${offset}`,
        recommended_window_end: `${date}T18:00:00${offset}`,
      };
    }
  }

  const fallbackDate = pack.weather_context.series.temperature_max[0]?.date ?? new Date().toISOString().slice(0, 10);
  return {
    recommended_window_start: `${fallbackDate}T20:00:00${offset}`,
    recommended_window_end: nextDayIso(fallbackDate, offset),
  };
}

function offsetForTimezone(timezone: string): string {
  if (timezone === "America/Los_Angeles") return "-07:00";
  if (timezone === "America/Denver") return "-06:00";
  if (timezone === "America/Chicago") return "-05:00";
  if (timezone === "America/New_York") return "-04:00";
  return "Z";
}

function nextDayIso(date: string, offset: string): string {
  const next = new Date(`${date}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return `${next.toISOString().slice(0, 10)}T08:00:00${offset}`;
}

