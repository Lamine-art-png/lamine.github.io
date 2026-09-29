import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd(), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "shared/supported-locales.json"), "utf8"));
const sourceEnvelope = JSON.parse(fs.readFileSync(path.join(root, "shared/localization/source.json"), "utf8"));
const catalogDir = path.join(root, "shared/localization/catalogs");

function assert(condition, message) {
  if (!condition) throw new Error(`static locale contract failed: ${message}`);
}

function tokens(value) {
  return (String(value).match(/\{[A-Za-z_][A-Za-z0-9_]*\}/g) || []).sort();
}

const advertised = manifest.enabledUiLocales.filter((code) => code !== "auto");
const complete = manifest.catalogCompleteLocales || [];

assert(advertised.includes("en"), "English must remain available");
const target = manifest.targetUiLocales || manifest.enabledUiLocales;
assert(target.includes("pt-BR"), "Brazilian Portuguese must be a first-class production target");
assert(!target.includes("pt"), "generic pt must not replace the Brazilian production target");
assert(manifest.uiTranslationPolicy === "versioned-static-complete-catalogs", "production must use deterministic static catalogs");
assert(Array.isArray(manifest.dynamicCatalogLocales) && manifest.dynamicCatalogLocales.length === 0, "advertised locales must not depend on runtime generation");
assert(JSON.stringify([...advertised].sort()) === JSON.stringify([...complete].sort()), "every advertised locale must be catalog-complete");

const source = sourceEnvelope.catalog;
const sourceKeys = Object.keys(source).sort();
assert(sourceKeys.length >= 2500, `canonical source unexpectedly small: ${sourceKeys.length}`);

for (const locale of advertised) {
  if (locale === "en") continue;
  const file = path.join(catalogDir, `${locale}.json`);
  assert(fs.existsSync(file), `missing bundled catalog for ${locale}`);
  const envelope = JSON.parse(fs.readFileSync(file, "utf8"));
  assert(envelope.schemaVersion === 2, `${locale} schema version`);
  assert(envelope.locale === locale, `${locale} envelope locale`);
  assert(envelope.status === "complete-generated", `${locale} incomplete status`);
  assert(envelope.sourceFingerprint === sourceEnvelope.sourceFingerprint, `${locale} source fingerprint drift`);
  const catalog = envelope.catalog || {};
  const keys = Object.keys(catalog).sort();
  assert(JSON.stringify(keys) === JSON.stringify(sourceKeys), `${locale} exact-key parity failed`);

  let changed = 0;
  for (const key of sourceKeys) {
    const value = catalog[key];
    assert(typeof value === "string" && value.trim(), `${locale} empty ${key}`);
    assert(value.trim().toLowerCase() !== "[object object]", `${locale} serialization artifact ${key}`);
    assert(!value.includes("\ufffd"), `${locale} replacement character ${key}`);
    assert(JSON.stringify(tokens(value)) === JSON.stringify(tokens(source[key])), `${locale} placeholder mismatch ${key}`);
    if (value.trim() !== source[key].trim()) changed += 1;
  }
  assert(changed >= Math.max(25, Math.floor(sourceKeys.length / 20)), `${locale} made too little translation progress: ${changed}`);
}

console.log(JSON.stringify({
  status: "ok",
  advertisedLocales: advertised.length,
  sourceKeys: sourceKeys.length,
  sourceFingerprint: sourceEnvelope.sourceFingerprint,
}));
