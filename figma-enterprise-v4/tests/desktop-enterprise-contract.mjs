import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const config = JSON.parse(read("src-tauri/tauri.conf.json"));
const capability = JSON.parse(read("src-tauri/capabilities/default.json"));
const cargo = read("src-tauri/Cargo.toml");
const rustRuntime = read("src-tauri/src/lib.rs");
const desktopRuntime = read("src/app/desktop/desktopRuntime.ts");
const main = read("src/main.tsx");
const serviceWorker = read("public/sw.js");

assert.equal(config.productName, "AGRO-AI Enterprise Portal");
assert.equal(config.identifier, "com.agroai.enterprise");
assert.equal(config.app.withGlobalTauri, true);
assert.equal(config.app.windows.length, 1);
assert.equal(config.app.windows[0].label, "main");
assert.equal(config.app.windows[0].useHttpsScheme, true, "Windows desktop origin must use HTTPS semantics");
assert.ok(config.app.windows[0].minWidth >= 1024);
assert.ok(config.app.windows[0].minHeight >= 720);
assert.deepEqual(config.plugins?.["deep-link"]?.desktop?.schemes, ["agroai"]);
assert.ok(Number.parseFloat(config.bundle?.macOS?.minimumSystemVersion) >= 12);
assert.equal(config.bundle?.windows?.nsis?.installMode, "currentUser");
assert.equal(config.bundle?.windows?.webviewInstallMode?.type, "downloadBootstrapper");
assert.deepEqual(config.bundle?.icon, [
  "icons/32x32.png",
  "icons/128x128.png",
  "icons/128x128@2x.png",
  "icons/icon.icns",
  "icons/icon.ico",
]);

assert.ok(capability.permissions.includes("core:default"));
assert.ok(capability.permissions.includes("deep-link:default"));
const httpPermission = capability.permissions.find((permission) => typeof permission === "object" && permission.identifier === "http:default");
assert.ok(httpPermission, "desktop native HTTP capability is required");
assert.deepEqual(httpPermission.allow, [{ url: "https://api.agroai-pilot.com/**" }]);
assert.equal(JSON.stringify(httpPermission).includes("*://*"), false, "native HTTP must never be globally scoped");

for (const dependency of [
  "tauri-plugin-deep-link",
  "tauri-plugin-http",
  "tauri-plugin-notification",
  "tauri-plugin-single-instance",
]) {
  assert.ok(cargo.includes(dependency), `missing ${dependency}`);
}
assert.match(cargo, /tauri-plugin-single-instance\s*=\s*\{[^\n]*features\s*=\s*\["deep-link"\]/);
assert.ok(rustRuntime.indexOf("tauri_plugin_single_instance::init") < rustRuntime.indexOf("tauri_plugin_deep_link::init"), "single-instance must be registered before deep-link");
assert.match(rustRuntime, /matches!\(parsed\.scheme\(\),\s*"https"\s*\|\s*"http"\s*\|\s*"mailto"\)/);
assert.ok(rustRuntime.includes('Builder::new("agroai-desktop-navigation-guard")'));
assert.ok(rustRuntime.includes('url.host_str() == Some("tauri.localhost")'));
assert.ok(rustRuntime.includes(".on_navigation("));
assert.ok(rustRuntime.includes("webbrowser::open(url.as_str())"));
assert.equal(rustRuntime.includes("shell::open"), false);

assert.ok(main.includes('import { installDesktopRuntime } from "./app/desktop/desktopRuntime"'));
assert.ok(main.includes("installDesktopRuntime();"));
assert.ok(desktopRuntime.includes('url.hostname === "api.agroai-pilot.com"'));
assert.ok(desktopRuntime.includes('url.protocol === "https:"'));
assert.ok(desktopRuntime.includes('parsed.protocol !== "agroai:" || parsed.hostname !== "open"'));
assert.ok(desktopRuntime.includes("desktopRouteAllowlist"));
assert.ok(desktopRuntime.includes("deepLink.getCurrent"));
assert.ok(desktopRuntime.includes("deepLink.onOpenUrl"));
assert.equal(desktopRuntime.includes("eval("), false, "desktop bridge must not inject runtime scripts");

assert.ok(serviceWorker.includes("/v1/"), "PWA service worker API exclusion contract must remain present");
assert.equal(capability.permissions.some((permission) => typeof permission === "string" && permission.startsWith("fs:")), false, "desktop does not receive filesystem access by default");

console.log("desktop enterprise contract: ok");
