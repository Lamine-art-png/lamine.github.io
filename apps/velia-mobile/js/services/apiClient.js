const DEFAULT_BASE_URL = (globalThis?.localStorage?.getItem("veliaApiBaseUrl") || "http://localhost:4310").replace(/\/$/, "");

async function post(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4500);
  try {
    const response = await fetch(`${DEFAULT_BASE_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

export const apiClient = {
  async getDailyDecision(payload) { return post("/v1/decisions/daily", payload); },
  async queryAssistant(payload) { return post("/v1/assistant/query", payload); },
  async interpretVoice(payload) { return post("/v1/voice/interpret", payload); },
  async getWeatherContext(payload) { return post("/v1/weather/context", payload); },
  async updateMemory(payload) { return post("/v1/memory/update", payload); },
};
