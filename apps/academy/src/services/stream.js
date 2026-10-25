// Cloudflare Stream playback for protected lessons. Videos require signed URLs,
// so playback needs a short-lived token that only this Worker can mint, and
// only for a learner entitled to the lesson. The signing key lives in Worker
// secrets (STREAM_SIGNING_KEY_ID, STREAM_SIGNING_JWK: the base64 JWK returned
// by Stream's /stream/keys) and never reaches the browser, a log or a response.
// Without it, protected playback fails closed.
import { b64url } from "../lib/util.js";

export const STREAM_UID = /^[0-9a-f]{32}$/;
// Long enough to start and finish one lesson without a pause; the player
// asks for a fresh token when one expires mid-lesson.
export const TOKEN_TTL_SECONDS = 20 * 60;

export const isStreamVideo = (v) => Boolean(v && v.provider === "stream" && STREAM_UID.test(v.provider_ref || ""));

// Direct media URLs (hls_url/mp4_url) are public by nature: they play only in
// local development and tests. Deployed Academies play protected Stream
// uploads and nothing else.
export const directMediaAllowed = (env) => !["production", "staging"].includes(env?.ENVIRONMENT);

/** A video with something to play: a protected Stream upload, or (development and tests only) a direct source. */
export const hasMedia = (v, env) => Boolean(v && (isStreamVideo(v) || (v.provider !== "stream" && directMediaAllowed(env) && (v.hls_url || v.mp4_url))));

export function streamConfigured(env) {
  return Boolean(env.STREAM_SIGNING_KEY_ID && env.STREAM_SIGNING_JWK);
}

const keyCache = new Map();
async function signingKey(env) {
  const cached = keyCache.get(env.STREAM_SIGNING_KEY_ID);
  if (cached) return cached;
  const jwk = JSON.parse(atob(env.STREAM_SIGNING_JWK));
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  keyCache.set(env.STREAM_SIGNING_KEY_ID, key);
  return key;
}

const enc = new TextEncoder();
const part = (obj) => b64url(enc.encode(JSON.stringify(obj)));

/**
 * Signed playback token for one video, valid for TOKEN_TTL_SECONDS. Returns
 * null when signing is not configured (callers must then refuse playback).
 */
export async function playbackToken(env, uid, { now = Date.now(), ttl = TOKEN_TTL_SECONDS } = {}) {
  if (!streamConfigured(env) || !STREAM_UID.test(uid || "")) return null;
  const iat = Math.floor(now / 1000);
  const header = { alg: "RS256", kid: env.STREAM_SIGNING_KEY_ID };
  // nbf a little in the past absorbs clock skew between the Worker and Stream.
  const payload = { sub: uid, kid: env.STREAM_SIGNING_KEY_ID, nbf: iat - 30, exp: iat + ttl, downloadable: false };
  const unsigned = `${part(header)}.${part(payload)}`;
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", await signingKey(env), enc.encode(unsigned));
  return { token: `${unsigned}.${b64url(new Uint8Array(sig))}`, expiresAt: new Date((iat + ttl) * 1000).toISOString() };
}

/** Origin of the player iframe: the account's customer subdomain when known. */
export function streamOrigin(env) {
  const code = String(env.STREAM_CUSTOMER_CODE || "");
  return /^[a-z0-9]{8,40}$/.test(code) ? `https://customer-${code}.cloudflarestream.com` : "https://iframe.videodelivery.net";
}

export function iframeUrl(env, token, { poster } = {}) {
  const origin = streamOrigin(env);
  const base = origin === "https://iframe.videodelivery.net" ? `${origin}/${token}` : `${origin}/${token}/iframe`;
  const q = new URLSearchParams({ preload: "metadata", letterboxColor: "transparent" });
  if (poster) q.set("poster", poster);
  return `${base}?${q}`;
}

export const STREAM_FRAME_ORIGINS = ["https://iframe.videodelivery.net", "https://*.cloudflarestream.com"];
export const STREAM_SDK = "https://embed.cloudflarestream.com/embed/sdk.latest.js";
export const STREAM_SDK_ORIGIN = "https://embed.cloudflarestream.com";
// Internal marker from a page that embeds the Stream player; finalize() strips
// it and widens that page's CSP (and only that page's) for the player SDK.
export const STREAM_PAGE_HEADER = "x-academy-stream-player";
