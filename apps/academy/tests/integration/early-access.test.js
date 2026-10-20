// Early-access registrants (agroai-pilot.com/academy/early-access): imported
// without creating accounts, linked only after the person proves the mailbox,
// invited at most once, and never emailed from a non-production copy.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, registeredLearner, lastEmail, tokenFrom } from "../helpers.js";
import { parseRegistrants } from "../../src/services/earlyAccess.js";

const CSV = [
  "source_id,email,name,language,role,email_opt_in,registered_at",
  "req_1,Ana.Grower@Example.org,Ana Grower,pt-BR,grower,true,2026-10-16T10:00:00Z",
  'req_2,"chef@example.org","Jean, Chef",fr,manager,true,2026-10-17T09:30:00Z',
  "req_3,quiet@example.org,Quiet Person,es,student,false,2026-10-17T11:00:00Z",
  "req_4,contact@agroai-pilot.com,AGRO-AI Academy Diagnostic,en,other,true,2026-10-18T08:00:00Z",
  "req_5,not-an-email,Broken,en,other,true,2026-10-18T08:00:00Z",
  "req_6,ana.grower@example.org,Ana Again,en,other,true,2026-10-19T08:00:00Z",
].join("\n");

async function founder(env) {
  return registeredLearner(env, { email: "founder@academy.test", name: "Founder" });
}
const rows = (env) => env.DB.prepare("SELECT * FROM early_access_registrants ORDER BY email").all().then((r) => r.results);

test("the export parser keeps consent and language, maps roles, skips internal test rows and rejects bad rows", () => {
  const { records, rejected, internal } = parseRegistrants(CSV);
  assert.equal(internal, 1);
  assert.deepEqual(rejected, [{ line: 6, reason: "invalid email" }]);
  const ana = records.find((r) => r.source_id === "req_1");
  assert.deepEqual(
    { email: ana.email, locale: ana.locale, role: ana.professional_role, optIn: ana.email_opt_in },
    { email: "ana.grower@example.org", locale: "pt-BR", role: "grower", optIn: 1 },
  );
  const chef = records.find((r) => r.source_id === "req_2");
  assert.equal(chef.name, "Jean, Chef", "quoted CSV fields");
  assert.equal(chef.locale, "fr-FR");
  assert.equal(chef.professional_role, "farm_manager");
  assert.equal(records.find((r) => r.source_id === "req_3").email_opt_in, 0);
  // JSON exports work the same way.
  assert.equal(parseRegistrants(JSON.stringify([{ email: "x@example.org", registered_at: "2026-10-16T00:00:00Z", email_opt_in: true }])).records.length, 1);
});

test("import is previewed first, creates no accounts and sends nothing; repeating it changes nothing", async () => {
  const env = makeEnv();
  const admin = await founder(env);
  const before = await env.DB.prepare("SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM email_outbox) AS mail").first();
  let r = await admin.post("/admin/early-access/import", { data: CSV });
  assert.equal(r.status, 200);
  assert.match(r.text, /4 valid row\(s\): 4 new/);
  assert.equal((await rows(env)).length, 0, "the preview writes nothing");
  r = await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  assert.equal(r.status, 303);
  const imported = await rows(env);
  assert.equal(imported.length, 3, "one row per address (duplicate merged), internal and invalid rows skipped");
  const ana = imported.find((x) => x.email === "ana.grower@example.org");
  assert.equal(ana.registered_at, "2026-10-16T10:00:00.000Z", "the earliest registration is kept");
  assert.equal(ana.locale, "pt-BR", "the first recorded language is kept");
  assert.ok(imported.every((x) => x.status === "pending"));
  const after = await env.DB.prepare("SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM email_outbox) AS mail").first();
  assert.deepEqual({ ...after }, { ...before }, "no accounts created, no email queued");
  await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  assert.deepEqual(await rows(env), imported, "re-importing is idempotent");
});

test("only super administrators can see or use early-access tools", async () => {
  const env = makeEnv();
  await founder(env);
  const staff = await registeredLearner(env, { email: "staff@academy.test" });
  const id = (await env.DB.prepare("SELECT id FROM users WHERE email = 'staff@academy.test'").first()).id;
  await env.DB.prepare("INSERT INTO user_roles (user_id, role, granted_at) VALUES (?, 'academy_admin', ?)").bind(id, new Date().toISOString()).run();
  assert.equal((await staff.get("/admin/early-access")).status, 403);
  assert.equal((await staff.post("/admin/early-access/import", { data: CSV, mode: "import" })).status, 403);
  assert.equal((await staff.post("/admin/early-access/invite", { expected: "1", confirm: "send 1 invitations" })).status, 403);
  assert.equal((await rows(env)).length, 0);
});

test("a registrant is linked only after proving the mailbox, never on registration alone", async () => {
  const env = makeEnv();
  const admin = await founder(env);
  await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  const u = await registeredLearner(env, { email: "chef@example.org", verify: false });
  let row = await env.DB.prepare("SELECT * FROM early_access_registrants WHERE email = 'chef@example.org'").first();
  assert.equal(row.status, "pending", "registering with the address proves nothing");
  const user = await env.DB.prepare("SELECT * FROM users WHERE email = 'chef@example.org'").first();
  assert.equal(user.email_verified_at, null, "the import never marks an address verified");
  const tok = tokenFrom(await lastEmail(env, "chef@example.org", "verify_email"), "/verify-email");
  await u.get(`/verify-email?token=${tok}`);
  await u.post("/verify-email", { token: tok });
  row = await env.DB.prepare("SELECT * FROM early_access_registrants WHERE email = 'chef@example.org'").first();
  assert.equal(row.status, "activated");
  assert.equal(row.activated_user_id, user.id);
  // Someone who already had a verified account is linked when imported.
  const env2 = makeEnv();
  const admin2 = await founder(env2);
  await registeredLearner(env2, { email: "quiet@example.org" });
  await admin2.post("/admin/early-access/import", { data: CSV, mode: "import" });
  assert.equal((await env2.DB.prepare("SELECT status FROM early_access_registrants WHERE email = 'quiet@example.org'").first()).status, "activated");
});

test("invitations: consent required, existing accounts excluded, confirmed batch, at most once each", async () => {
  const env = makeEnv({ ENVIRONMENT: "production" });
  const admin = await founder(env);
  await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  await registeredLearner(env, { email: "chef@example.org", verify: false }); // has an account, not yet verified
  let page = await admin.get("/admin/early-access");
  assert.match(page.text, /1 registrant\(s\) consented, have no Academy account/, "Ana only: Quiet did not consent, Chef has an account");
  // A wrong confirmation phrase sends nothing.
  let r = await admin.post("/admin/early-access/invite", { expected: "1", confirm: "yes" });
  assert.match(decodeURIComponent(r.location), /confirmation phrase/);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM email_outbox WHERE template = 'early_access_invite'").first()).n, 0);
  // A stale confirmed count sends nothing either.
  r = await admin.post("/admin/early-access/invite", { expected: "2", confirm: "send 2 invitations" });
  assert.match(decodeURIComponent(r.location), /changed \(now 1\)/);
  r = await admin.post("/admin/early-access/invite", { expected: "1", confirm: "send 1 invitations" });
  assert.match(decodeURIComponent(r.location), /invited:1/);
  const mail = (await env.DB.prepare("SELECT * FROM email_outbox WHERE template = 'early_access_invite'").all()).results;
  assert.equal(mail.length, 1);
  assert.equal(mail[0].to_email, "ana.grower@example.org");
  assert.equal(mail[0].locale, "pt-BR", "invited in the registration language");
  assert.match(mail[0].text, /\/register\?lang=pt-BR/);
  assert.equal((await env.DB.prepare("SELECT status FROM early_access_registrants WHERE email = 'ana.grower@example.org'").first()).status, "invited");
  // Repeating the send (or re-importing) never invites anyone again.
  await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  r = await admin.post("/admin/early-access/invite", { expected: "1", confirm: "send 1 invitations" });
  assert.match(decodeURIComponent(r.location), /changed \(now 0\)/);
  assert.equal((await env.DB.prepare("SELECT COUNT(*) AS n FROM email_outbox WHERE template = 'early_access_invite'").first()).n, 1);
});

test("outside production, only synthetic staging test addresses can ever be invited", async () => {
  const env = makeEnv({ ENVIRONMENT: "staging" });
  const admin = await founder(env);
  const csv = CSV + "\nreq_9,probe@academy-staging-test.invalid,Synthetic Probe,en,other,true,2026-10-19T09:00:00Z";
  await admin.post("/admin/early-access/import", { data: csv, mode: "import" });
  const page = await admin.get("/admin/early-access");
  assert.match(page.text, /1 registrant\(s\) consented/);
  await admin.post("/admin/early-access/invite", { expected: "1", confirm: "send 1 invitations" });
  const sent = (await env.DB.prepare("SELECT to_email, status FROM email_outbox WHERE template = 'early_access_invite'").all()).results;
  assert.deepEqual(sent.map((m) => m.to_email), ["probe@academy-staging-test.invalid"]);
  assert.equal(sent[0].status, "suppressed");
});

test("deleting the account also erases the early-access registration", async () => {
  const env = makeEnv();
  const admin = await founder(env);
  await admin.post("/admin/early-access/import", { data: CSV, mode: "import" });
  const u = await registeredLearner(env, { email: "chef@example.org" });
  assert.equal((await env.DB.prepare("SELECT status FROM early_access_registrants WHERE email = 'chef@example.org'").first()).status, "activated");
  await u.get("/account");
  const r = await u.post("/account/delete", { confirm: "DELETE", password: u.password });
  assert.equal(r.status, 303);
  assert.equal(await env.DB.prepare("SELECT 1 FROM early_access_registrants WHERE email = 'chef@example.org'").first(), null);
});
