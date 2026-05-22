import type { Env } from "../../lib/cloudflare/env";
import { EarthDailyUnavailableError, type EarthDailyRawInput } from "../../schemas/earthdaily";
import { buildDemoEarthDailyInput } from "./demoAdapter";
import { fetchLiveEarthDailyInput, hasLiveEarthDailyCredentials } from "./liveAdapter";
import type { EarthDailyAdapterRequest, EarthDailyAdapterResult } from "./types";

export async function loadEarthDailyInput(
  env: Env,
  req: EarthDailyAdapterRequest,
): Promise<EarthDailyAdapterResult> {
  if (req.raw) {
    return { input: req.raw, mode: req.raw.mode, usedFallback: false };
  }

  if (env.LIVE_EARTHDAILY_ENABLED === "true" && hasLiveEarthDailyCredentials(env)) {
    try {
      const input = await fetchLiveEarthDailyInput(env, {
        field_id: req.field_id ?? "madera-almonds-block-12",
        forecast_days: 7,
      });
      return { input, mode: "live", usedFallback: false };
    } catch (error) {
      if (env.DEMO_MODE === "true") {
        return {
          input: buildDemoEarthDailyInput(req.field_id),
          mode: "demo",
          usedFallback: true,
        };
      }
      throw error;
    }
  }

  if (env.DEMO_MODE === "true" || env.DEMO_MODE === undefined) {
    return {
      input: buildDemoEarthDailyInput(req.field_id),
      mode: "demo",
      usedFallback: false,
    };
  }

  throw new EarthDailyUnavailableError();
}

