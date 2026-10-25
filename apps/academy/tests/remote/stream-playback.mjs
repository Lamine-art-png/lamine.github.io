// Protected video playback on staging with a real Course A1 upload, run by
// the deploy workflow after the deploy's Stream step has verified every
// upload private:
//   STAGING_TEST_INBOX_TOKEN=… node tests/remote/stream-playback.mjs https://academy-staging.agroai-pilot.com
// A synthetic learner (mail suppressed) enrolls in the staging-only probe
// course, whose optional video lesson uses one verified upload through its
// own asset record (nothing in Course A1 is approved by this). It checks that
// the page carries only a short-lived, non-downloadable signed token; that
// the token plays (manifest, rendition and a real media segment); that the
// bare id and anonymous visitors get nothing; that renewal works for the
// learner; and that a real browser plays the video in Stream's player. The
// learner is deleted at the end. Every check is mandatory.
import { RemoteClient } from "./client.mjs";

const BASE = process.argv[2];
const TOKEN = process.env.STAGING_TEST_INBOX_TOKEN || "";
if (!BASE || !TOKEN) {
  console.error("usage: STAGING_TEST_INBOX_TOKEN=… stream-playback.mjs <base-url>");
  process.exit(2);
}
const expect = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

async function inbox(to, template) {
  for (let i = 0; i < 10; i++) {
    const r = await fetch(`${BASE}/__staging/inbox?to=${encodeURIComponent(to)}`, { headers: { authorization: `Bearer ${TOKEN}` } });
    if (r.ok) {
      const { message } = await r.json();
      if (message.template === template) return message;
    }
    await new Promise((res) => setTimeout(res, 1000));
  }
  throw new Error(`no ${template} message for the synthetic learner`);
}

async function playback(learner, probe) {
  expect(probe.protectedVideo, "no Stream upload verified private in the last day (the deploy's Stream step must run first)");
  const page = await learner.get(`/learn/${probe.slug}/${probe.videoLessonSlug}`);
  expect(page.status === 200, `video lesson returned ${page.status}`);
  expect(page.headers.get("cache-control") === "private, no-store", "lesson page may be cached");
  const src = /<iframe src="(https:\/\/customer-[a-z0-9]+\.cloudflarestream\.com\/([\w-]+\.[\w-]+\.[\w-]+)\/iframe[^"]*)"/.exec(page.text);
  expect(src, "no signed Stream player on the lesson page");
  const origin = new URL(src[1].replace(/&amp;/g, "&")).origin;
  const claims = JSON.parse(Buffer.from(src[2].split(".")[1], "base64url").toString());
  expect(claims.exp - Date.now() / 1000 <= 20 * 60 + 5 && claims.downloadable === false, "token is not short-lived and non-downloadable");
  expect(!page.text.includes(claims.sub), "the bare video id appears in the page");
  expect(!/\.m3u8|\.mp4|\/downloads\//.test(page.text), "a media URL appears in the page");
  // The signed manifest, a rendition and a real media segment play.
  const get = (u) => fetch(u, { headers: { referer: `${BASE}/` } });
  const manifest = await get(`${origin}/${src[2]}/manifest/video.m3u8`);
  const master = await manifest.text();
  expect(manifest.status === 200 && master.startsWith("#EXTM3U"), `signed manifest returned ${manifest.status}`);
  const variantUrl = new URL(master.split("\n").find((l) => l && !l.startsWith("#")), manifest.url);
  const variant = await get(variantUrl);
  const playlist = await variant.text();
  expect(variant.status === 200, `rendition playlist returned ${variant.status}`);
  const segment = await get(new URL(playlist.split("\n").find((l) => l && !l.startsWith("#")), variant.url));
  const bytes = (await segment.arrayBuffer()).byteLength;
  expect(segment.status === 200 && bytes > 1000, `media segment returned ${segment.status} (${bytes} bytes)`);
  // Without a token: refused.
  const bare = await fetch(`${origin}/${claims.sub}/manifest/video.m3u8`);
  expect(bare.status === 401 || bare.status === 403, `bare id manifest returned ${bare.status}`);
  // Renewal: a fresh token for the enrolled learner, none for an anonymous visitor.
  const cookie = [...learner.jar].map(([k, v]) => `${k}=${v}`).join("; ");
  const renew = await fetch(`${BASE}/api/video-token`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json", "x-csrf-token": learner.csrf, origin: BASE, cookie },
    body: JSON.stringify({ lessonId: "les_staging_probe_video" }),
  });
  expect(renew.status === 200 && renew.headers.get("cache-control") === "private, no-store", `token renewal returned ${renew.status}`);
  const anonLesson = await new RemoteClient(BASE).get(`/learn/${probe.slug}/${probe.videoLessonSlug}`);
  expect(anonLesson.status === 303 && /\/login/.test(anonLesson.location || ""), `anonymous lesson request returned ${anonLesson.status}`);
  const anonToken = await fetch(`${BASE}/api/video-token`, { method: "POST", headers: { "content-type": "application/json", origin: BASE }, body: "{}" });
  expect(anonToken.status !== 200, "an anonymous visitor received a token");
  // A real browser, signed in as the learner, plays the video in Stream's player.
  const { chromium } = await import("playwright");
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    await context.addCookies([...learner.jar].map(([name, value]) => ({ name, value, url: BASE, secure: true, httpOnly: true, sameSite: "Lax" })));
    const tab = await context.newPage();
    await tab.goto(`${BASE}/learn/${probe.slug}/${probe.videoLessonSlug}`);
    await tab.waitForSelector("[data-player] iframe");
    const played = await tab.evaluate(
      () =>
        new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("playback did not start within 45 s")), 45000);
          const wait = () => (typeof window.Stream === "function" ? start() : setTimeout(wait, 200));
          const start = () => {
            const p = window.Stream(document.querySelector("[data-player] iframe"));
            p.muted = true;
            p.addEventListener("timeupdate", () => {
              if (p.currentTime > 2) {
                clearTimeout(timer);
                resolve({ t: p.currentTime, duration: p.duration });
              }
            });
            p.play();
          };
          wait();
        }),
    );
    expect(played.duration > 10, `player reported duration ${played.duration}`);
    return `segment ${bytes} bytes; browser played ${played.t.toFixed(1)} s of ${Math.round(played.duration)} s; bare id ${bare.status}`;
  } finally {
    await browser.close();
  }
}

async function main() {
  const health = await (await fetch(`${BASE}/healthz`)).json();
  expect(health.environment === "staging", `refusing to run against environment "${health.environment}"`);
  const r = await fetch(`${BASE}/__staging/probe-course`, { method: "POST", headers: { authorization: `Bearer ${TOKEN}` } });
  expect(r.status === 200, `probe-course returned ${r.status}`);
  const { probe } = await r.json();
  const learner = new RemoteClient(BASE);
  const email = `stream-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}@academy-staging-test.invalid`;
  const password = `staging only ${Math.random().toString(36).slice(2)} passphrase`;
  await learner.get("/register");
  let res = await learner.post("/register", { display_name: "Staging Playback Learner", email, password, locale: "en", accept_terms: "1" });
  expect(res.status === 303, `register returned ${res.status}`);
  try {
    const tok = new RegExp("/verify-email\\?token=([A-Za-z0-9_-]+)").exec((await inbox(email, "verify_email")).text)?.[1];
    expect(tok, "no verification link");
    await learner.get(`/verify-email?token=${tok}`);
    res = await learner.post("/verify-email", { token: tok });
    expect(res.status === 303, `verify returned ${res.status}`);
    res = await learner.post(`/courses/${probe.slug}/enroll`, {});
    expect(res.status === 303, `enroll returned ${res.status}`);
    return await playback(learner, probe);
  } finally {
    await learner.get("/account");
    const del = await learner.post("/account/delete", { password, confirm: "DELETE" });
    if (del.status !== 303) console.error(`could not delete the synthetic learner (${del.status})`);
  }
}

main().then(
  (note) => {
    console.log(`✔ protected Stream playback of a real A1 video — ${note}`);
    console.log("Stream playback test passed");
  },
  (e) => {
    console.log(`✖ protected Stream playback of a real A1 video — ${e.message}`);
    console.log("Stream playback test FAILED");
    process.exit(1);
  },
);
