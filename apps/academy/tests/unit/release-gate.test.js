// The staging write-path test is a hard gate for production: it runs in the
// staging job, cannot be skipped or soft-failed, and production needs staging.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const wf = readFileSync(join(root, ".github/workflows/academy-deploy.yml"), "utf8");
const job = (name) => {
  const start = wf.indexOf(`\n  ${name}:\n`);
  assert.ok(start >= 0, `job ${name} exists`);
  const rest = wf.slice(start + 1);
  const next = rest.slice(3).search(/\n  [a-z_-]+:\n/);
  return next < 0 ? rest : rest.slice(0, next + 3);
};

test("production deploys only after the staging job, which runs the write-path test", () => {
  const staging = job("staging");
  const production = job("production");
  assert.match(production, /needs: staging/);
  assert.match(staging, /run: node tests\/remote\/staging\.mjs https:\/\/academy-staging\.agroai-pilot\.com/);
  // A configured token is used; otherwise the run generates one. Either way the test must run.
  assert.match(staging, /CONFIGURED_STAGING_TEST_INBOX_TOKEN: \$\{\{ secrets\.ACADEMY_STAGING_TEST_INBOX_TOKEN \}\}/);
  assert.match(staging, /openssl rand -hex 32[\s\S]*::add-mask::[\s\S]*STAGING_TEST_INBOX_TOKEN=\$token" >> "\$GITHUB_ENV"/);
  assert.match(staging, /Require staging test credentials[\s\S]*exit 1/);
  for (const j of [staging, production]) {
    assert.doesNotMatch(j, /continue-on-error/, "no soft-failing steps");
    assert.doesNotMatch(j, /\|\| true/, "no ignored failures");
  }
  assert.doesNotMatch(production, /if: .*always\(\)/, "production never runs when staging failed");
});

test("the staging test has no silent skip paths", () => {
  const src = readFileSync(join(root, "apps/academy/tests/remote/staging.mjs"), "utf8");
  assert.doesNotMatch(src, /::warning::/);
  assert.doesNotMatch(src, /skipped/);
});


test("official Academy jobs explicitly opt into A1 machine draft import", () => {
  for (const name of ["staging", "production"]) {
    const releaseJob = job(name);
    assert.ok(releaseJob.includes('ACADEMY_IMPORT_A1_MACHINE_TRANSLATIONS: "1"'),
      name + " must generate guarded machine translations on deployment");
  }
  const deploy = readFileSync(join(root, "apps/academy/scripts/deploy.sh"), "utf8");
  assert.ok(deploy.includes('if [ "${ACADEMY_IMPORT_A1_MACHINE_TRANSLATIONS:-0}" = "1" ]; then'));
});
