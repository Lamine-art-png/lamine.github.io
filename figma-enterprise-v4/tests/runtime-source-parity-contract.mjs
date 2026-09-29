// The deterministic catalogs are generated from shared/localization/source.json.
// A locale can activate only if its catalog covers the English source the
// running portal actually requires. This contract bundles the real runtime
// source (same side-effect imports as src/main.tsx) and requires exact parity,
// so a new or runtime-injected English string can never silently block or
// English-fallback an advertised locale.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { build } from "esbuild";

const root = path.resolve(process.cwd(), "..");
const app = path.join(root, "figma-enterprise-v4/src/app");
const entry = `
import "./commercialBoundaryConversionLabels";
import { runtimeFullEnglishSource } from "./dynamicLocaleCatalog";
globalThis.__runtimeSource = runtimeFullEnglishSource();
`;
const bundled = await build({
  stdin: { contents: entry, resolveDir: app, loader: "ts" },
  bundle: true, write: false, platform: "node", format: "cjs", logLevel: "silent",
  define: { "import.meta.env": "{}" },
  plugins: [{
    // Vite-only import.meta.glob loader: the parity check needs no catalogs.
    name: "stub-bundled-catalogs",
    setup(pluginBuild) {
      pluginBuild.onResolve({ filter: /\/bundledLocaleCatalogs$/ }, () => ({ path: "bundled-stub", namespace: "stub" }));
      pluginBuild.onLoad({ filter: /.*/, namespace: "stub" }, () => ({
        contents: "export const BUNDLED_LOCALE_CODES=[];export const hasBundledLocale=()=>false;export const loadBundledLocaleCatalog=async()=>null;export const loadedBundledLocaleCatalog=()=>null;",
        loader: "js",
      }));
    },
  }],
});
const storage = { getItem: () => null, setItem() {}, removeItem() {}, key: () => null, length: 0 };
const sandbox = {
  localStorage: storage, sessionStorage: storage, console, URL, URLSearchParams, setTimeout, clearTimeout,
  navigator: { language: "en-US" },
  window: { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { search: "", pathname: "/", hostname: "localhost" }, localStorage: storage },
  CustomEvent: class {}, Event: class {}, AbortController, fetch: async () => { throw new Error("offline"); },
};
vm.runInNewContext(bundled.outputFiles[0].text, sandbox);
const runtime = sandbox.__runtimeSource;
const source = JSON.parse(fs.readFileSync(path.join(root, "shared/localization/source.json"), "utf8")).catalog;

const missing = Object.keys(runtime).filter((key) => !(key in source));
const drift = Object.keys(runtime).filter((key) => key in source && source[key] !== runtime[key]);
if (missing.length || drift.length) {
  throw new Error(`runtime English source diverges from shared/localization/source.json (run node scripts/i18n-build-source.mjs): missing=${missing.slice(0, 10).join(",")} drift=${drift.slice(0, 10).join(",")}`);
}
console.log(JSON.stringify({ status: "ok", runtimeKeys: Object.keys(runtime).length, sourceKeys: Object.keys(source).length }));
