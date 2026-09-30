// Release catalog identity: the stamped catalogSha256 must equal the identity
// recomputed by the production verifier's implementation, and any
// translation-only change (English source untouched) must change it, so an
// older deployed translation can never satisfy production verification.
import fs from "node:fs";
import path from "node:path";
import { catalogSha256 } from "../../scripts/i18n-catalog-identity.mjs";

const dir = path.resolve(process.cwd(), "..", "shared", "localization", "catalogs");
const files = fs.readdirSync(dir).filter((name) => name.endsWith(".json"));
if (files.length < 59) throw new Error(`expected every release catalog, found ${files.length}`);
const seen = new Set();
for (const file of files) {
  const envelope = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
  const identity = catalogSha256(envelope);
  if (envelope.catalogSha256 !== identity) throw new Error(`${file}: stamped catalogSha256 does not match content (run python3 scripts/i18n_catalog_identity.py --stamp)`);
  if (seen.has(identity)) throw new Error(`${file}: duplicate catalog identity`);
  seen.add(identity);
  const [key] = Object.keys(envelope.catalog);
  const mutated = { ...envelope, catalog: { ...envelope.catalog, [key]: `${envelope.catalog[key]} ` } };
  if (catalogSha256(mutated) === identity) throw new Error(`${file}: translation-only change did not change the identity`);
  if (mutated.sourceFingerprint !== envelope.sourceFingerprint) throw new Error("mutation must leave the English source fingerprint unchanged");
}
console.log(JSON.stringify({ status: "ok", catalogs: files.length, identities: seen.size }));
