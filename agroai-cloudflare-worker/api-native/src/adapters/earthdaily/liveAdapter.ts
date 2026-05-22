import type { Env } from "../../lib/cloudflare/env";
import { EarthDailyLiveError, EarthDailyUnavailableError, type EarthDailyRawInput } from "../../schemas/earthdaily";
import { buildDemoEarthDailyInput } from "./demoAdapter";
import type { EarthDailyLiveFetchOptions, EarthDailyStacItem, EarthDailyTokenResponse } from "./types";

export const EDS_ENDPOINTS = {
  token_cache_key: "eds:token",
  auth_token: "/oauth/token",
  stac_search: "/stac/search",
  vegetation_time_series: "/agriculture/vegetation/time-series",
  weather_indicators: "/agriculture/weather/indicators",
  change_detection: "/agriculture/change-detection",
} as const;

export function hasLiveEarthDailyCredentials(env: Env): boolean {
  return Boolean(env.EARTHDAILY_CLIENT_ID && env.EARTHDAILY_SECRET && env.EARTHDAILY_AUTH_URL && env.EARTHDAILY_API_URL);
}

export async function fetchLiveEarthDailyInput(env: Env, options: EarthDailyLiveFetchOptions): Promise<EarthDailyRawInput> {
  if (!hasLiveEarthDailyCredentials(env)) {
    throw new EarthDailyUnavailableError("EarthDaily live credentials are not configured.");
  }
  const token = await authenticate(env);
  const seed = buildDemoEarthDailyInput(options.field_id);
  const [stac, vegetation, weather, change] = await Promise.all([
    stacSearch(env, token, {
      collection: options.collection ?? "sentinel-2-l2a",
      intersects: seed.field.geometry,
      datetime: options.datetime ?? "P30D",
    }),
    vegetationTimeSeries(env, token, {
      field_id: options.field_id,
      indices: ["ndvi", "ndmi", "evi", "ndre"],
      date_range: options.datetime ?? "P30D",
    }),
    weatherIndicators(env, token, {
      field_id: options.field_id,
      forecast_days: options.forecast_days ?? 7,
    }),
    changeDetection(env, token, {
      field_id: options.field_id,
      window: options.datetime ?? "P30D",
    }),
  ]);
  return normalizeToRawInput(seed, { stac, vegetation, weather, change });
}

export async function authenticate(env: Env): Promise<string> {
  if (!hasLiveEarthDailyCredentials(env)) {
    throw new EarthDailyUnavailableError("EarthDaily live credentials are not configured.");
  }
  const cached = await env.EDS_TOKEN_CACHE?.get(EDS_ENDPOINTS.token_cache_key);
  if (cached) return cached;

  const response = await fetch(env.EARTHDAILY_AUTH_URL!, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: env.EARTHDAILY_CLIENT_ID!,
      client_secret: env.EARTHDAILY_SECRET!,
    }),
  });

  const payload = await parseJsonResponse<EarthDailyTokenResponse>(response, "auth_token");
  if (!payload.access_token) {
    throw new EarthDailyLiveError("EarthDaily auth response did not include an access token.", response.status);
  }
  const ttl = Math.max((payload.expires_in ?? 3600) - 60, 60);
  await env.EDS_TOKEN_CACHE?.put(EDS_ENDPOINTS.token_cache_key, payload.access_token, { expirationTtl: ttl });
  return payload.access_token;
}

export async function stacSearch(
  env: Env,
  token: string,
  body: { collection: string; intersects: EarthDailyRawInput["field"]["geometry"]; datetime: string },
): Promise<{ items: EarthDailyStacItem[] }> {
  return postJson(env, token, EDS_ENDPOINTS.stac_search, {
    collections: [body.collection],
    intersects: body.intersects,
    datetime: body.datetime,
    limit: 10,
  }, "stac_search");
}

export async function vegetationTimeSeries(
  env: Env,
  token: string,
  body: { field_id: string; indices: string[]; date_range: string },
): Promise<unknown> {
  return postJson(env, token, EDS_ENDPOINTS.vegetation_time_series, body, "vegetation_time_series");
}

export async function weatherIndicators(
  env: Env,
  token: string,
  body: { field_id: string; forecast_days: number },
): Promise<unknown> {
  return postJson(env, token, EDS_ENDPOINTS.weather_indicators, body, "weather_indicators");
}

export async function changeDetection(
  env: Env,
  token: string,
  body: { field_id: string; window: string },
): Promise<unknown> {
  return postJson(env, token, EDS_ENDPOINTS.change_detection, body, "change_detection");
}

export function normalizeToRawInput(
  seed: EarthDailyRawInput,
  data: { stac: { items?: EarthDailyStacItem[] }; vegetation: unknown; weather: unknown; change: unknown },
): EarthDailyRawInput {
  const stacItems = (data.stac.items ?? []).map((item) => ({
    id: item.id,
    collection: item.collection,
    datetime: item.datetime,
    href: item.links?.find((link) => link.rel === "self")?.href ?? item.assets?.visual?.href ?? "",
  }));
  return {
    ...seed,
    mode: "live",
    imagery: {
      ...seed.imagery,
      stac_items: stacItems.length ? stacItems : seed.imagery.stac_items,
    },
    metadata: {
      ...seed.metadata,
      source: "earthdaily-live-rest",
      retrieved_at: new Date().toISOString(),
      quality_flags: seed.metadata.quality_flags.filter((flag) => flag !== "demo_fixture"),
    },
  };
}

async function postJson<T>(env: Env, token: string, path: string, body: unknown, label: string): Promise<T> {
  const response = await fetch(`${env.EARTHDAILY_API_URL}${path}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  return parseJsonResponse<T>(response, label);
}

async function parseJsonResponse<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) {
    throw new EarthDailyLiveError(`EarthDaily ${label} request failed.`, response.status);
  }
  return response.json() as Promise<T>;
}

