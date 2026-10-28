// Language behavior: a page is always marked and laid out in the language it is
// actually written in, the learner's choice is remembered everywhere, and
// untranslated languages fall back to English plainly and coherently.
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeEnv, Client, registeredLearner, publishCourse, ORIGIN } from "../helpers.js";
import { queueEmail } from "../../src/services/email.js";

const COURSE = "/courses/introduction-to-ai-in-agriculture";

test("an untranslated right-to-left language falls back to English laid out left-to-right, with Gregorian English dates", async () => {
  const env = makeEnv();
  const r = await new Client(env).get(`${COURSE}?lang=fa`);
  assert.match(r.text, /<html lang="en" dir="ltr"/, "English text must not be laid out right-to-left");
  assert.match(r.text, /Persian isn(?:'|&#39;)t translated yet, so the Academy is shown in English for now/);
  assert.match(r.text, /<option value="fa" lang="fa" dir="rtl" selected>/, "the choice stays selected");
  assert.match(r.text, /Coming soon/);
  assert.doesNotMatch(r.text, /Opens October 29, 2026/);
  assert.doesNotMatch(r.text, /[۰-۹]/, "no Persian digits or calendar in an English page");
  // The fallback notice no longer claims dates and direction follow the language.
  assert.doesNotMatch(r.text, /text direction follow/);
});

test("a translated right-to-left page marks English curriculum text as English, left-to-right", async () => {
  const env = makeEnv();
  const r = await new Client(env).get(`${COURSE}?lang=ar`);
  assert.match(r.text, /<html lang="ar" dir="rtl"/);
  assert.match(r.text, /<h1 class="display-sm" lang="en" dir="ltr">Introduction to Artificial Intelligence in Agriculture<\/h1>/);
  assert.match(r.text, /<div class="prose" lang="en" dir="ltr">/);
  assert.match(r.text, /أكتوبر/, "Gregorian month names in Arabic");
  // English pages carry no redundant markers.
  const en = await new Client(env).get(`${COURSE}?lang=en`);
  assert.match(en.text, /<h1 class="display-sm">Introduction to Artificial Intelligence in Agriculture<\/h1>/);
});

test("a reviewed course translation is marked with its language inside an English page", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('course','crs_a1','title','de','Einführung in KI in der Landwirtschaft','reviewed',?)").bind(now).run();
  const r = await new Client(env).get(`${COURSE}?lang=de`);
  assert.match(r.text, /<html lang="en" dir="ltr"/);
  assert.match(r.text, /<h1 class="display-sm" lang="de" dir="ltr">Einführung in KI in der Landwirtschaft<\/h1>/);
});

test("partly translated content is marked field by field, and machine translations are disclosed on English-fallback pages", async () => {
  const env = makeEnv();
  await publishCourse(env, "crs_a1");
  const now = new Date().toISOString();
  // Only the title is translated: the subtitle stays English and must be marked as such.
  await env.DB.prepare("INSERT INTO content_translations (entity_type, entity_id, field, locale, value, status, updated_at) VALUES ('course','crs_a1','title','ar','مقدمة في الذكاء الاصطناعي في الزراعة','reviewed',?), ('course','crs_a1','title','de','Einführung in KI','machine',?)").bind(now, now).run();
  let r = await new Client(env).get(`${COURSE}?lang=ar`);
  assert.match(r.text, /<h1 class="display-sm">مقدمة في الذكاء الاصطناعي في الزراعة<\/h1>/, "translated field: no marker in an Arabic page");
  assert.match(r.text, /<p class="lead" lang="en" dir="ltr">What AI is/, "untranslated field stays marked as English");
  // German has no interface catalog: the page is English, the title a machine translation that must be disclosed.
  r = await new Client(env).get(`${COURSE}?lang=de`);
  assert.match(r.text, /<h1 class="display-sm" lang="de" dir="ltr">Einführung in KI<\/h1>/);
  assert.match(r.text, /<p class="lead">What AI is/, "English subtitle in an English page needs no marker");
  assert.match(r.text, /class="translation-note"[^<]*<svg[^]*?Machine-translated — not yet reviewed/, "machine translation disclosed");
});

test("a language picked in the header is saved to the profile and follows the learner to another device", async () => {
  const env = makeEnv();
  const learner = await registeredLearner(env, { email: "lang@academy.test" });
  await learner.get("/dashboard?lang=fr-FR");
  assert.equal((await env.DB.prepare("SELECT locale FROM users WHERE email = 'lang@academy.test'").first()).locale, "fr-FR");
  const other = new Client(env);
  await other.get("/login");
  const login = await other.post("/login", { email: "lang@academy.test", password: learner.password });
  assert.equal(login.status, 303);
  const r = await other.get("/dashboard");
  assert.match(r.text, /<html lang="fr-FR" dir="ltr"/, "no cookie on the new device: the profile language applies");
});

test("emails use the learner's language when translated, otherwise English laid out left-to-right", async () => {
  const env = makeEnv();
  const cfg = { origin: ORIGIN, supportEmail: "contact@academy.test", environment: "test", emailEnabled: false };
  const row = async (locale, email) => {
    await queueEmail(env, cfg, { user: { id: null, email, display_name: "Learner", locale }, template: "password_changed", vars: { url: `${ORIGIN}/login` } });
    return env.DB.prepare("SELECT locale, html FROM email_outbox WHERE to_email = ?").bind(email).first();
  };
  const fa = await row("fa", "fa@academy.test");
  assert.equal(fa.locale, "en");
  assert.match(fa.html, /<html lang="en" dir="ltr">/);
  const ar = await row("ar", "ar@academy.test");
  assert.equal(ar.locale, "ar");
  assert.match(ar.html, /<html lang="ar" dir="rtl">/);
  // Branded with the official lockup, which stays readable when images are blocked.
  assert.match(ar.html, /<img src="https:\/\/academy\.test\/static\/brand\/email-lockup\.png"[^>]*alt="AGRO-AI Academy"/);
});

test("only translated languages are advertised as alternates; the staff console stays English left-to-right", async () => {
  const env = makeEnv();
  const r = await new Client(env).get("/courses");
  const alternates = r.text.match(/<link rel="alternate" hreflang="(?!x-default)[^"]+"/g) || [];
  assert.equal(alternates.length, 6, "English + the five translated catalogs");
  assert.doesNotMatch(r.text, /hreflang="de"/);
  const founder = await registeredLearner(env, { email: "founder@academy.test" });
  const admin = await founder.get("/admin?lang=ar");
  assert.match(admin.text, /<html lang="ar" dir="rtl"/);
  assert.match(admin.text, /<div class="admin" lang="en" dir="ltr">/);
});

test("brand assets are served and referenced: lockup, icons, social card, font", async () => {
  const env = makeEnv();
  const anon = new Client(env);
  const r = await anon.get("/");
  assert.match(r.text, /<img class="logo logo-on-light" src="\/static\/brand\/academy-lockup-h\.webp\?v=[^"]+"[^>]*alt="AGRO-AI Academy"/);
  assert.match(r.text, /<meta property="og:image" content="https:\/\/academy\.test\/static\/brand\/og-academy\.png\?v=/);
  assert.match(r.text, /<link rel="stylesheet" href="https:\/\/fonts\.cdnfonts\.com\/css\/glacial-indifference-2" media="print" data-brand-font>/);
  assert.match(r.headers.get("content-security-policy"), /font-src 'self' https:\/\/fonts\.cdnfonts\.com/);
  for (const path of ["/static/brand/og-academy.png", "/static/brand/academy-lockup-h.webp", "/static/brand/email-lockup.png", "/static/brand/academy-mark-512.png", "/apple-touch-icon.png", "/favicon.ico"]) {
    assert.equal((await anon.get(path)).status, 200, path);
  }
});
