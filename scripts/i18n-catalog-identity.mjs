// Same canonical identity as scripts/i18n_catalog_identity.py:
// sha256(JSON of {catalog, locale, sourceFingerprint} with sorted keys).
import { createHash } from "node:crypto";

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function catalogSha256(envelope) {
  const identity = { catalog: envelope.catalog || {}, locale: envelope.locale, sourceFingerprint: envelope.sourceFingerprint };
  return createHash("sha256").update(canonical(identity), "utf8").digest("hex");
}
