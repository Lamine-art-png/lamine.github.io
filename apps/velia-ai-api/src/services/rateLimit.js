const hits = new Map();

export function rateLimitPlaceholder(req, res, next) {
  const key = req.ip || "local";
  const now = Date.now();
  const entry = hits.get(key) || { count: 0, ts: now };
  if (now - entry.ts > 60_000) {
    entry.count = 0;
    entry.ts = now;
  }
  entry.count += 1;
  hits.set(key, entry);

  if (entry.count > 600) {
    return res.status(429).json({ error: "Rate limit exceeded" });
  }

  return next();
}
