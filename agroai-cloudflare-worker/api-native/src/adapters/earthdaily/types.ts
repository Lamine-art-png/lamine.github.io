import type { EarthDailyRawInput } from "../../schemas/earthdaily";

export interface EarthDailyAdapterRequest {
  field_id?: string;
  mode?: "demo" | "live";
  raw?: EarthDailyRawInput;
}

export interface EarthDailyAdapterResult {
  input: EarthDailyRawInput;
  mode: "demo" | "live";
  usedFallback: boolean;
}

export interface EarthDailyLiveFetchOptions {
  field_id: string;
  collection?: string;
  datetime?: string;
  forecast_days?: number;
}

export interface EarthDailyTokenResponse {
  access_token: string;
  token_type?: string;
  expires_in?: number;
}

export interface EarthDailyStacItem {
  id: string;
  collection: string;
  datetime: string;
  assets?: Record<string, { href?: string }>;
  links?: Array<{ href?: string; rel?: string }>;
}

