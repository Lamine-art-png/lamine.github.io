import { normalizeEarthDailyInput } from "../../core/normalization/normalize";
import { validateEarthDailyRawInput } from "../../schemas/earthdaily";

export function handleEarthDailyNormalize(body: unknown) {
  const validation = validateEarthDailyRawInput(body);
  if (!validation.ok || !validation.value) {
    throw routeError(validation.issues[0]?.code ?? "invalid_payload", "EarthDaily payload failed validation.", 400, validation.issues);
  }
  return normalizeEarthDailyInput(validation.value);
}

function routeError(code: string, message: string, status: number, details?: unknown): Error {
  return Object.assign(new Error(message), { code, status, details });
}

