import http from "http";
import { config } from "./config.js";
import { aiOrchestrator } from "./ai/aiOrchestrator.js";
import { memoryStore } from "./ai/memoryStore.js";
import { evaluateDecision, scenarios } from "./ai/evaluationHarness.js";
import { detectIntent } from "./services/voiceIntent.js";
import { normalizeWeatherContext } from "./services/weatherNormalizer.js";
import { createWeatherProvider } from "./services/weatherProviderFactory.js";

async function createExpressApp() {
  const [{ default: express }, { default: cors }] = await Promise.all([
    import("express"),
    import("cors"),
  ]);
  const { decisionsRouter } = await import("./routes/decisions.js");
  const { assistantRouter } = await import("./routes/assistant.js");
  const { voiceRouter } = await import("./routes/voice.js");
  const { weatherRouter } = await import("./routes/weather.js");
  const { memoryRouter } = await import("./routes/memory.js");
  const { evaluationRouter } = await import("./routes/evaluation.js");
  const { requestLogger, safeErrorHandler } = await import("./services/logger.js");
  const { rateLimitPlaceholder } = await import("./services/rateLimit.js");

  const expressApp = express();
  expressApp.use(cors({ origin: config.corsOrigin }));
  expressApp.use(express.json({ limit: "1mb" }));
  expressApp.use(requestLogger);
  expressApp.use(rateLimitPlaceholder);

  expressApp.get("/health", (_req, res) => res.json({ ok: true, service: "terris-ai-api" }));
  expressApp.use("/v1/decisions", decisionsRouter);
  expressApp.use("/v1/assistant", assistantRouter);
  expressApp.use("/v1/voice", voiceRouter);
  expressApp.use("/v1/weather", weatherRouter);
  expressApp.use("/v1/memory", memoryRouter);
  expressApp.use("/v1/evaluation", evaluationRouter);
  expressApp.use(safeErrorHandler);
  return expressApp;
}

function sendJson(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json",
    "access-control-allow-origin": config.corsOrigin,
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET,POST,OPTIONS",
  });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    req.on("end", () => {
      if (!raw) return resolve({});
      try {
        return resolve(JSON.parse(raw));
      } catch (error) {
        return reject(error);
      }
    });
    req.on("error", reject);
  });
}

function createFallbackApp() {
  return async function fallbackApp(req, res) {
    const requestId = `req-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const url = new URL(req.url, "http://localhost");
    console.log(JSON.stringify({ level: "info", requestId, method: req.method, path: url.pathname, runtime: "node-fallback" }));
    if (req.method === "OPTIONS") return sendJson(res, 204, {});

    try {
      if (req.method === "GET" && url.pathname === "/health") {
        return sendJson(res, 200, { ok: true, service: "terris-ai-api", runtime: "node-fallback" });
      }

      const body = req.method === "POST" ? await readJson(req) : {};

      if (req.method === "POST" && url.pathname === "/v1/decisions/daily") {
        if (!body.field) return sendJson(res, 400, { error: "Missing required fields", missing: ["field"] });
        const result = await aiOrchestrator.run("daily irrigation decision", {
          field: body.field,
          weather: body.weather || null,
          location: body.location || null,
          logs: body.logs || [],
          observations: body.observations || [],
          language: body.language || "en",
        });
        return sendJson(res, 200, result);
      }

      if (req.method === "POST" && url.pathname === "/v1/assistant/query") {
        const result = await aiOrchestrator.run("assistant query", {
          query: body.query || body.question || "Why?",
          fieldId: body.fieldId,
          field: body.field,
          decision: body.decision,
          verification: body.verification,
          recommendationHistory: body.recommendationHistory || [],
          language: body.language || "en",
        });
        return sendJson(res, 200, result);
      }

      if (req.method === "POST" && url.pathname === "/v1/voice/interpret") {
        const transcript = String(body.transcript || "");
        const fieldId = body.fieldId || null;
        const intent = detectIntent(transcript);
        return sendJson(res, 200, {
          type: "voice_intent",
          transcript,
          intent,
          action: {
            type: intent === "LOG_IRRIGATION" ? "log_irrigation" : intent === "UPDATE_CONDITION" ? "update_condition" : "noop",
            payload: { fieldId, source: "voice" },
          },
        });
      }

      if (req.method === "POST" && url.pathname === "/v1/weather/context") {
        const location = normalizeWeatherContext(body);
        const weatherProvider = createWeatherProvider();
        const weather = await weatherProvider.getContext({
          location: body.location || location.location || "farm",
          lat: body.lat ?? body.latitude ?? body.coordinates?.lat,
          lon: body.lon ?? body.longitude ?? body.coordinates?.lon,
          coordinates: body.coordinates,
        });
        return sendJson(res, 200, { ...location, ...weather });
      }

      if (req.method === "POST" && url.pathname === "/v1/memory/update") {
        if (!body.fieldId || !body.event) return sendJson(res, 400, { error: "Missing required fields", missing: ["fieldId", "event"].filter((key) => !body[key]) });
        const updated = memoryStore.updateFieldMemory(body.fieldId, body.event);
        return sendJson(res, 200, { ok: true, fieldId: body.fieldId, summary: memoryStore.summarizeFieldMemory(body.fieldId), eventCount: (updated.events || []).length });
      }

      if (req.method === "POST" && url.pathname === "/v1/evaluation/run") {
        const decision = body.decision || {};
        return sendJson(res, 200, {
          scenarioCount: scenarios.length,
          scenarios,
          evaluation: evaluateDecision(decision),
        });
      }

      return sendJson(res, 404, { error: "Not found", requestId });
    } catch (error) {
      console.error(JSON.stringify({ level: "error", requestId, message: error.message }));
      return sendJson(res, 500, { error: "Request failed", requestId });
    }
  };
}

async function createApp() {
  try {
    return await createExpressApp();
  } catch (error) {
    console.warn(JSON.stringify({ level: "warn", msg: "Express dependencies unavailable; using Node fallback app", reason: error.code || error.message }));
    return createFallbackApp();
  }
}

export const app = await createApp();

if (process.env.NODE_ENV !== "test") {
  http.createServer(app).listen(config.port, () => {
    console.log(JSON.stringify({ level: "info", msg: "terris-ai-api started", port: config.port }));
  });
}
