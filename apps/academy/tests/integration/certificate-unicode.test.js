// End to end over HTTP: learners with names in different writing systems
// download certificate PDFs that print their names as written.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, registeredLearner, publishCourse, completeA1 } from "../helpers.js";

async function certified(name) {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const learner = await registeredLearner(env, { email: `u${Math.random().toString(36).slice(2, 8)}@academy.test`, name });
  const { cert } = await completeA1(env, learner);
  assert.ok(cert, `certificate issued for ${name}`);
  assert.equal(cert.credential_name, name);
  return { env, learner, cert };
}

for (const [label, name] of [
  ["Arabic", "فاطمة الزهراء"],
  ["Chinese", "陳美玲"],
  ["Hindi", "श्रीनिवास राव"],
  ["accented Latin", "Đặng Thùy Trâm"],
]) {
  test(`${label} name: PDF download prints the name with an embedded font`, async () => {
    const { learner, cert } = await certified(name);
    const page = await learner.get(`/certificates/${cert.credential_id}`);
    assert.match(page.text, /\/pdf" download/, "download offered");
    assert.doesNotMatch(page.text, /can(?:'|&#39;)t yet print names/);
    const r = await learner.get(`/certificates/${cert.credential_id}/pdf`);
    assert.equal(r.status, 200);
    assert.equal(r.headers.get("content-type"), "application/pdf");
    const s = new TextDecoder("latin1").decode(new Uint8Array(await r.res.arrayBuffer()));
    assert.match(s, /\/Subtype \/Type0/);
    assert.match(s, /\/FontFile2/);
  });
}

test("a name in a writing system without a font gets an explanation, not a broken PDF", async () => {
  const { learner, cert } = await certified("వెంకటేశ్వర రావు");
  let page = await learner.get(`/certificates/${cert.credential_id}`);
  assert.doesNotMatch(page.text, /\/pdf" download/, "no download button");
  assert.match(page.text, /can(?:'|&#39;)t yet print names in this writing system/);
  const r = await learner.get(`/certificates/${cert.credential_id}/pdf`);
  assert.equal(r.status, 303);
  assert.match(r.location, /\?pdf=unsupported$/);
  // The web certificate and public verification still show the name as written.
  page = await learner.get(`/verify/${cert.credential_id}`);
  assert.match(page.text, /వెంకటేశ్వర రావు/);
});
