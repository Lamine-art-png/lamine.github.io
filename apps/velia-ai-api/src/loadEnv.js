// Optional dotenv loader — keeps the fallback server bootable when node_modules are absent.
// Exported for unit testing with a mock importFn; the default uses the real dynamic import.

export async function loadDotenv(importFn = async (specifier) => import(specifier)) {
  try {
    await importFn("dotenv/config");
  } catch (err) {
    // MODULE_NOT_FOUND  — CJS resolution (Node ≤18 compat)
    // ERR_MODULE_NOT_FOUND — ESM resolution (Node 20+)
    if (err?.code === "MODULE_NOT_FOUND" || err?.code === "ERR_MODULE_NOT_FOUND") return;
    throw err;
  }
}

// Run at module evaluation so env vars are populated before any config property is accessed.
await loadDotenv();
