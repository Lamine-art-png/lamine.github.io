import express from "express";
import cors from "cors";
import { config } from "./config.js";
import { decisionsRouter } from "./routes/decisions.js";
import { assistantRouter } from "./routes/assistant.js";
import { voiceRouter } from "./routes/voice.js";
import { weatherRouter } from "./routes/weather.js";
import { memoryRouter } from "./routes/memory.js";
import { evaluationRouter } from "./routes/evaluation.js";
import { requestLogger, safeErrorHandler } from "./services/logger.js";
import { rateLimitPlaceholder } from "./services/rateLimit.js";

export const app = express();
app.use(cors({ origin: config.corsOrigin }));
app.use(express.json({ limit: "1mb" }));
app.use(requestLogger);
app.use(rateLimitPlaceholder);

app.get("/health", (_req, res) => res.json({ ok: true, service: "velia-ai-api" }));
app.use("/v1/decisions", decisionsRouter);
app.use("/v1/assistant", assistantRouter);
app.use("/v1/voice", voiceRouter);
app.use("/v1/weather", weatherRouter);
app.use("/v1/memory", memoryRouter);
app.use("/v1/evaluation", evaluationRouter);
app.use(safeErrorHandler);

if (process.env.NODE_ENV !== "test") {
  app.listen(config.port, () => {
    console.log(JSON.stringify({ level: "info", msg: "velia-ai-api started", port: config.port }));
  });
}
