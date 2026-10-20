// Every repository file outside apps/academy that the Academy imports must
// trigger Academy CI (push and pull request) and the staging deployment.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const app = join(dirname(fileURLToPath(import.meta.url)), "../..");
const repo = resolve(app, "../..");

function sources(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? sources(p) : p.endsWith(".js") ? [p] : [];
  });
}

/** Path filters of one trigger (push / pull_request) in a workflow file. */
function pathsOf(workflow, trigger) {
  const text = readFileSync(join(repo, ".github/workflows", workflow), "utf8");
  const block = new RegExp(`\\n  ${trigger}:\\n(?:    .*\\n)*?    paths:\\n((?:      - .*\\n)+)`).exec(text);
  assert.ok(block, `${workflow} has a ${trigger} path filter`);
  return block[1].split("\n").map((l) => l.trim().replace(/^- "?|"$/g, "")).filter(Boolean);
}

test("imported shared files trigger Academy CI and the staging deployment", () => {
  const external = new Set();
  for (const file of sources(join(app, "src"))) {
    for (const m of readFileSync(file, "utf8").matchAll(/from\s+"(\.\.\/[^"]+)"/g)) {
      const target = relative(repo, resolve(dirname(file), m[1]));
      if (!target.startsWith("apps/academy/")) external.add(target);
    }
  }
  assert.ok(external.has("shared/registries/countries.json"));
  assert.ok(external.has("shared/supported-locales.json"));
  for (const [workflow, trigger] of [["academy-ci.yml", "push"], ["academy-ci.yml", "pull_request"], ["academy-deploy.yml", "push"]]) {
    const paths = pathsOf(workflow, trigger);
    for (const f of external) assert.ok(paths.includes(f), `${workflow} ${trigger} watches ${f}`);
    assert.ok(paths.includes("apps/academy/**"));
  }
  assert.ok(pathsOf("academy-deploy.yml", "push").includes(".github/workflows/academy-ci.yml"), "the deploy reruns when its CI gate changes");
});
