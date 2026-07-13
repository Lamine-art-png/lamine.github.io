import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

const shell = read("../src/app/components/MainLayout.tsx");
const statusBar = read("../src/app/components/OperatingStatusBar.tsx");
const sources = read("../src/app/components/Sources.tsx");
const evidence = read("../src/app/components/Evidence.tsx");
const overview = read("../src/app/components/Overview.tsx");
const operations = read("../src/app/components/Operations.tsx");
const intelligence = read("../src/app/components/intelligence/IntelligenceView.tsx");
const globals = read("../src/styles/globals.css");
const styleEntry = read("../src/styles/index.css");
const htmlEntry = read("../index.html");

assert.match(shell, /h-\[100dvh\]/, "portal shell must use dynamic viewport height");
assert.match(shell, /<aside[\s\S]*?hidden[\s\S]*?md:flex/, "desktop sidebar must be hidden on phones");
assert.match(shell, /data-desktop-sidebar/, "desktop sidebar contract missing");
assert.match(shell, /transition-\[width\]/, "desktop sidebar must animate width changes");
assert.match(shell, /agroai_sidebar_collapsed_v1/, "desktop sidebar collapse preference must persist");
assert.match(shell, /data-mobile-portal-header/, "mobile header contract missing");
assert.match(shell, /data-mobile-navigation/, "mobile overlay navigation missing");
assert.match(shell, /w-\[min\(86vw,320px\)\]/, "mobile navigation must be viewport-bounded");
assert.match(shell, /overflow-x-hidden overflow-y-auto/, "content canvas must prevent horizontal overlap");
assert.match(shell, /env\(safe-area-inset-top\)/, "mobile drawer must respect safe area");

assert.match(statusBar, /sm:hidden/, "status bar needs a compact mobile control");
assert.match(statusBar, /w-full overflow-y-auto shadow-2xl sm:w-\[560px\]/, "brain drawer must become full-width on mobile");

assert.match(sources, /md:hidden/, "Sources must provide a mobile card view");
assert.match(sources, /hidden md:block/, "Sources desktop table must not crush into mobile width");
assert.match(sources, /grid-cols-2 gap-3 lg:grid-cols-4/, "Sources metrics must adapt to viewport width");

assert.match(evidence, /md:hidden/, "Evidence must provide a mobile record view");
assert.match(evidence, /hidden md:block/, "Evidence desktop table must be isolated from mobile");
assert.match(evidence, /w-full cursor-pointer.*sm:min-w-\[260px\]/s, "Evidence upload target must fit phone width");

assert.match(overview, /grid-cols-1 gap-3 min-\[420px\]:grid-cols-2 xl:grid-cols-5/, "Command Center metrics must stack responsively");
assert.match(overview, /xl:grid-cols-\[1\.2fr_0\.8fr\]/, "Command Center split panels must wait for wide screens");
assert.match(operations, /grid-cols-2 gap-3 lg:grid-cols-4/, "Decision cards must adapt on mobile");

assert.match(intelligence, /fixed inset-0 z-\[80\] lg:hidden/, "Ask AGRO-AI history must become a mobile overlay");
assert.match(intelligence, /hidden w-\[300px\].*lg:flex/s, "Ask AGRO-AI desktop history rail must not render as a phone column");
assert.match(intelligence, /max-w-\[90%\] sm:max-w-\[72%\]/, "chat messages need mobile width limits");
assert.match(intelligence, /text-\[16px\].*sm:text-\[14px\]/s, "mobile composer must avoid iOS focus zoom");

assert.match(globals, /@media \(max-width: 767px\)/, "mobile layout baseline missing");
assert.match(globals, /\[data-portal-content\] \[style\*="grid-template-columns"\]/, "legacy fixed grids need a mobile fallback");
assert.match(globals, /overflow-x: hidden/, "global horizontal overflow guard missing");
assert.match(styleEntry, /@import '\.\/globals\.css';/, "production stylesheet must load the mobile baseline");
assert.match(htmlEntry, /viewport-fit=cover/, "iPhone safe-area viewport support missing");
assert.match(htmlEntry, /interactive-widget=resizes-content/, "mobile keyboard must resize the content viewport");

console.log("Mobile portal responsive contract passed.");
