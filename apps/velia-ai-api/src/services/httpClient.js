const TRANSIENT_STATUSES = new Set([408, 409, 425, 429, 500, 502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeFetchError(error) {
  if (error?.name === "AbortError") {
    const timeoutError = new Error("Provider request timed out");
    timeoutError.transient = true;
    timeoutError.code = "TIMEOUT";
    return timeoutError;
  }
  return error;
}

export async function fetchJsonWithRetry(url, options = {}) {
  const {
    timeoutMs = 12000,
    retries = 2,
    retryDelayMs = 350,
    fetchImpl = globalThis.fetch,
    transientStatuses = TRANSIENT_STATUSES,
    ...fetchOptions
  } = options;

  if (typeof fetchImpl !== "function") throw new Error("fetch is not available in this runtime");

  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(url, { ...fetchOptions, signal: controller.signal });
      const text = await response.text();
      let body = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = { raw: text };
        }
      }

      if (!response.ok) {
        const error = new Error(`Provider HTTP ${response.status}`);
        error.status = response.status;
        error.body = body;
        error.transient = transientStatuses.has(response.status);
        throw error;
      }

      return body;
    } catch (error) {
      lastError = normalizeFetchError(error);
      if (!lastError.transient || attempt === retries) break;
      await sleep(retryDelayMs * (attempt + 1));
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError;
}
