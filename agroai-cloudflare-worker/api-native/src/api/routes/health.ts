export interface HealthEnv {
  ENVIRONMENT?: string;
  AGROAI_ENV?: string;
  AGROAI_API_VERSION?: string;
}

export function handleHealth(env: HealthEnv) {
  return {
    status: "ok",
    version: env.AGROAI_API_VERSION ?? "v1",
    build_ts: new Date().toISOString(),
    environment: env.AGROAI_ENV ?? env.ENVIRONMENT ?? "unknown",
    modules: ["earthdaily", "talgil"],
  };
}

