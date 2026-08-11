import { createRequire } from "module";

// Two-step design:
//   resolveFn — checks whether dotenv/config itself exists; MODULE_NOT_FOUND here means dotenv is absent.
//   importFn  — executes the resolved module; any error here (transitive deps, eval failures) propagates.
// Does not auto-run; server.js awaits loadDotenv() explicitly before importing config-dependent modules.
const _defaultResolve = createRequire(import.meta.url).resolve;

export async function loadDotenv({
  resolveFn = (s) => _defaultResolve(s),
  importFn = async (url) => import(url),
} = {}) {
  let resolved;
  try {
    resolved = resolveFn("dotenv/config");
  } catch (err) {
    // MODULE_NOT_FOUND  — CJS resolver (Node ≤18 compat, require.resolve)
    // ERR_MODULE_NOT_FOUND — ESM resolver (Node 20+, import.meta.resolve)
    // Both mean dotenv/config itself is absent — tolerated gracefully.
    if (err?.code === "MODULE_NOT_FOUND" || err?.code === "ERR_MODULE_NOT_FOUND") return;
    throw err;
  }
  // dotenv/config is present — execute it. Transitive MODULE_NOT_FOUND and eval errors propagate.
  await importFn(resolved);
}
