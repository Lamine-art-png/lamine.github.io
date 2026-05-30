export function requestLogger(req, _res, next) {
  req.requestId = `req-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  console.log(JSON.stringify({ level: "info", requestId: req.requestId, method: req.method, path: req.path }));
  next();
}

const loggedModes = new Set();

export function logProviderMode(kind, details = {}) {
  const key = `${kind}:${details.provider}:${details.mode}:${details.model || ""}`;
  if (loggedModes.has(key)) return;
  loggedModes.add(key);
  console.log(JSON.stringify({
    level: "info",
    kind,
    provider: details.provider,
    mode: details.mode,
    model: details.model || null,
    fallbackReason: details.fallbackReason || null,
  }));
}

export function safeErrorHandler(err, req, res, _next) {
  console.error(JSON.stringify({ level: "error", requestId: req.requestId, message: err.message }));
  res.status(err.statusCode || 500).json({ error: "Request failed", requestId: req.requestId });
}
