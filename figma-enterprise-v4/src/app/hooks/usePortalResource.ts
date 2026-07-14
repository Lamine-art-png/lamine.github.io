import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

type RefreshOptions = {
  silent?: boolean;
};

type ResourceState<T> = {
  data: T | null;
  error: string;
  isLoading: boolean;
  isUnavailable: boolean;
  refresh: (options?: RefreshOptions) => Promise<void>;
};

export function usePortalResource<T>(
  loader: () => Promise<T>,
  options: { enabled?: boolean } = {},
): ResourceState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(Boolean(options.enabled ?? true));
  const [isUnavailable, setIsUnavailable] = useState(false);
  const enabled = options.enabled ?? true;

  const refresh = useCallback(async (refreshOptions: RefreshOptions = {}) => {
    if (!enabled) return;
    const silent = Boolean(refreshOptions.silent);

    if (!silent) setIsLoading(true);
    setError("");
    setIsUnavailable(false);

    try {
      setData(await loader());
    } catch (err) {
      const apiError = err as ApiError;
      if (!silent) setData(null);
      setIsUnavailable(apiError.status === 404 || apiError.status === 405);
      setError(apiError.message || "Backend unavailable. Retry.");
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [enabled, loader]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, error, isLoading, isUnavailable, refresh };
}

export function arrayFromUnknown<T>(value: unknown, keys: string[] = []) {
  if (Array.isArray(value)) return value as T[];
  if (!value || typeof value !== "object") return [];

  for (const key of keys) {
    const nested = (value as Record<string, unknown>)[key];
    if (Array.isArray(nested)) return nested as T[];
  }

  return [];
}

export function canUseEntitlement(entitlements: Record<string, unknown>, keys: string[]) {
  if (entitlements.internal_testing === true || entitlements.all_features === true) return true;
  return keys.some((key) => entitlements[key] === true);
}
