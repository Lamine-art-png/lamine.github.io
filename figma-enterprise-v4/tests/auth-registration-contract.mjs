import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

const flows = [
  ["Enterprise Portal", read("../src/app/components/AuthScreen.tsx")],
  ["Platform API", read("../src/app/components/PlatformAuthScreen.tsx")],
];

for (const [name, source] of flows) {
  assert.match(source, /function advanceRegisterStep\(form\?: HTMLFormElement \| null\)/, `${name}: Continue must validate the active form`);
  assert.match(source, /registerForm\.password\.length < 12/, `${name}: 12-character password policy must be explicit before advancing`);
  assert.match(source, /registerForm\.password\.toLowerCase\(\)\.includes\(emailName\)/, `${name}: frontend password validation must mirror the backend email-name rule`);
  assert.match(source, /form && !form\.reportValidity\(\)/, `${name}: browser email and URL validity must run on Continue`);
  assert.match(source, /onClick=\{\(event\) => advanceRegisterStep\(event\.currentTarget\.form\)\}/, `${name}: Continue must pass its form to the step validator`);

  const stepOneStart = source.indexOf("{registerStep === 1 ? <>");
  const stepTwoStart = source.indexOf("{registerStep === 2 ? <>");
  assert.ok(stepOneStart >= 0 && stepTwoStart > stepOneStart, `${name}: registration step boundaries are missing`);
  const stepOne = source.slice(stepOneStart, stepTwoStart);
  assert.match(stepOne, /type="checkbox"/, `${name}: legal clickwrap must be visible on the account-creation step`);
  assert.match(stepOne, /https:\/\/agroai-pilot\.com\/terms-of-service/, `${name}: Terms of Service link must be present on step one`);
  assert.match(stepOne, /https:\/\/agroai-pilot\.com\/privacy-policy/, `${name}: Privacy Policy link must be present on step one`);
  assert.match(stepOne, /terms_accepted: event\.target\.checked, authority_confirmed: event\.target\.checked/, `${name}: clickwrap must set both legal acceptance flags`);

  const stepThreeStart = source.indexOf("{registerStep === 3 ? <>");
  const controlsStart = source.indexOf('<div className="flex gap-3">', stepThreeStart);
  assert.ok(stepThreeStart >= 0 && controlsStart > stepThreeStart, `${name}: third-step boundary is missing`);
  const stepThree = source.slice(stepThreeStart, controlsStart);
  assert.doesNotMatch(stepThree, /terms-of-service/, `${name}: legal clickwrap must not be hidden until step three`);
}

console.log("Auth registration contract passed.");
