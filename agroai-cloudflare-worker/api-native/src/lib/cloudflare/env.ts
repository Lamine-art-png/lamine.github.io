import type { Env as TalgilEnv } from "../../sync/TalgilSyncDO";

export interface Env extends TalgilEnv {
  ENVIRONMENT?: string;
  EARTHDAILY_CLIENT_ID?: string;
  EARTHDAILY_SECRET?: string;
  EARTHDAILY_AUTH_URL?: string;
  EARTHDAILY_API_URL?: string;
  AGROAI_LLM_API_KEY?: string;
  AGROAI_LLM_MODEL?: string;
  DEMO_MODE?: string;
  LIVE_EARTHDAILY_ENABLED?: string;
  AGROAI_ENV?: string;
  AGROAI_API_VERSION?: string;
  ALLOWED_ORIGINS?: string;
  EDS_TOKEN_CACHE: KVNamespace;
}

