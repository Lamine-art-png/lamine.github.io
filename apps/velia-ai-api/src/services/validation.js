export function requireFields(payload, fields) {
  const missing = fields.filter((field) => payload[field] === undefined || payload[field] === null);
  return { ok: missing.length === 0, missing };
}

export function badRequest(res, missing) {
  return res.status(400).json({ error: "Invalid request", missing });
}
