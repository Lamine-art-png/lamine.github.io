import baseCatalog from "../../../shared/ui-catalog.en.json";
import literalCatalog1 from "../../../shared/ui-literals.en.1.json";
import literalCatalog2 from "../../../shared/ui-literals.en.2.json";
import literalCatalog3 from "../../../shared/ui-literals.en.3.json";
import literalCatalog4 from "../../../shared/ui-literals.en.4.json";
import literalCatalog5 from "../../../shared/ui-literals.en.5.json";
import literalCatalog6 from "../../../shared/ui-literals.en.6.json";
import literalCatalog7 from "../../../shared/ui-literals.en.7.json";
import dynamicCopyCatalog from "../../../shared/ui-dynamic-copy.en.json";
import commercialBoundaryCatalog from "../../../shared/ui-commercial-boundary.en.json";

const MAX_KEYS = 2_000;
const MAX_KEY_CHARS = 160;
const MAX_VALUE_CHARS = 2_000;
const MAX_SOURCE_CHARS = 200_000;

const CANONICAL_SOURCE: Record<string, string> = Object.assign(
  {},
  baseCatalog,
  literalCatalog1,
  literalCatalog2,
  literalCatalog3,
  literalCatalog4,
  literalCatalog5,
  literalCatalog6,
  literalCatalog7,
  dynamicCopyCatalog,
  commercialBoundaryCatalog,
);

export function canonicalRequestedSource(value: unknown): Record<string, string> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const entries = Object.entries(candidate);
  if (!entries.length || entries.length > MAX_KEYS) return null;

  let total = 0;
  const output: Record<string, string> = {};
  for (const [key, rawValue] of entries) {
    if (!key || key.length > MAX_KEY_CHARS || typeof rawValue !== "string" || rawValue.length > MAX_VALUE_CHARS) return null;
    if (!Object.prototype.hasOwnProperty.call(CANONICAL_SOURCE, key) || CANONICAL_SOURCE[key] !== rawValue) return null;
    total += key.length + rawValue.length;
    if (total > MAX_SOURCE_CHARS) return null;
    output[key] = rawValue;
  }
  return output;
}
