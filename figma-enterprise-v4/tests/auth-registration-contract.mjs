import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

const flows = [
  ["Enterprise Portal", read("../src/app/components/AuthScreen.tsx")],
  ["Platform API", read("../src/app/components/PlatformAuthScreen.tsx")],
];

for (const [name, source] of flows) {
  assert.match(source, /function advanceRegisterStep\(form\?: HTMLFormElement \| null\)/, `${name}: Continue must validate the active form`);
  assert.match(source, /explainRegistrationError\(/, `${name}: server rejection reason codes must map to the correct signup step`);
  assert.match(source, /translatePortalLiteral\(issue\.message, legalLocale\)/, `${name}: error guidance must use the active locale`);
  assert.match(source, /minLength=\{12\}/, `${name}: concise use-case requirement must match the backend`);
  assert.match(source, /Request access<\/a>/, `${name}: legitimate organizations need an alternate verification route`);

  assert.match(source, /registerForm\.password\.length < 12/, `${name}: 12-character password policy must be explicit before advancing`);
  assert.match(source, /registerForm\.password\.toLowerCase\(\)\.includes\(emailName\)/, `${name}: frontend password validation must mirror the backend email-name rule`);
  assert.match(source, /form && !form\.reportValidity\(\)/, `${name}: browser email and URL validity must run on Continue`);
  assert.match(source, /onClick=\{\(event\) => advanceRegisterStep\(event\.currentTarget\.form\)\}/, `${name}: Continue must pass its form to the step validator`);

  const stepOneStart = source.indexOf("{registerStep === 1 ? <>");
  const stepTwoStart = source.indexOf("{registerStep === 2 ? <>");
  assert.ok(stepOneStart >= 0 && stepTwoStart > stepOneStart, `${name}: registration step boundaries are missing`);
  const stepOne = source.slice(stepOneStart, stepTwoStart);
  assert.match(stepOne, /type="checkbox"/, `${name}: legal clickwrap must be visible on the account-creation step`);
  // Legal links may be inline or rendered through the localized clickwrap
  // template; either way they must be on step one, and hoisted links must
  // open the customer's language version of the canonical document.
  const inlineTerms = /https:\/\/agroai-pilot\.com\/terms-of-service/.test(stepOne);
  const inlinePrivacy = /https:\/\/agroai-pilot\.com\/privacy-policy/.test(stepOne);
  const templated = /values=\{\{\s*terms: termsLink, privacy: privacyLink\s*\}\}/.test(stepOne);
  if (templated) {
    assert.match(source, /const termsUrl = `https:\/\/agroai-pilot\.com\/terms-of-service\?lang=\$\{legalLang\}`;/, `${name}: templated Terms link must carry the locale`);
    assert.match(source, /const privacyUrl = `https:\/\/agroai-pilot\.com\/privacy-policy\?lang=\$\{legalLang\}`;/, `${name}: templated Privacy link must carry the locale`);
    assert.match(source, /const termsLink = <a href=\{termsUrl\}/, `${name}: Terms link must use the localized Terms URL`);
    assert.match(source, /const privacyLink = <a href=\{privacyUrl\}/, `${name}: Privacy link must use the localized Privacy URL`);
  }
  assert.ok(inlineTerms || templated, `${name}: Terms of Service link must be present on step one`);
  assert.ok(inlinePrivacy || templated, `${name}: Privacy Policy link must be present on step one`);
  assert.match(stepOne, /terms_accepted: event\.target\.checked, authority_confirmed: event\.target\.checked/, `${name}: clickwrap must set both legal acceptance flags`);

  const stepThreeStart = source.indexOf("{registerStep === 3 ? <>");
  const controlsStart = source.indexOf('<div className="flex gap-3">', stepThreeStart);
  assert.ok(stepThreeStart >= 0 && controlsStart > stepThreeStart, `${name}: third-step boundary is missing`);
  const stepThree = source.slice(stepThreeStart, controlsStart);
  assert.doesNotMatch(stepThree, /terms-of-service/, `${name}: legal clickwrap must not be hidden until step three`);
}

console.log("Auth registration contract passed.");
