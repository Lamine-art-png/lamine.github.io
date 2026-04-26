export function requestLogger(req, _res, next) {
  req.requestId = `req-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
  console.log(JSON.stringify({ level: "info", requestId: req.requestId, method: req.method, path: req.path }));
  next();
}

export function safeErrorHandler(err, req, res, _next) {
  console.error(JSON.stringify({ level: "error", requestId: req.requestId, message: err.message }));
  res.status(err.statusCode || 500).json({ error: "Request failed", requestId: req.requestId });
}
