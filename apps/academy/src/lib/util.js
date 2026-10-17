// Small, dependency-free primitives shared across the Worker.

const enc = new TextEncoder();

export const nowIso = () => new Date().toISOString();

export function addSeconds(iso, seconds) {
  return new Date(new Date(iso).getTime() + seconds * 1000).toISOString();
}

export function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlDecode(str) {
  const s = str.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((str.length + 3) % 4);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function randomBytes(n) {
  const b = new Uint8Array(n);
  crypto.getRandomValues(b);
  return b;
}

export const randomToken = (n = 32) => b64url(randomBytes(n));

/** Short, sortable-enough random identifier for primary keys. */
export const newId = (prefix = "") => prefix + randomToken(12);

// Crockford base32 without ambiguous characters, used for public credential IDs.
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export function credentialId() {
  const bytes = randomBytes(12);
  let out = "";
  for (const b of bytes) out += CROCKFORD[b & 31];
  return `AGA-${out.slice(0, 4)}-${out.slice(4, 8)}-${out.slice(8, 12)}`;
}

export async function sha256Hex(input) {
  const d = await crypto.subtle.digest("SHA-256", typeof input === "string" ? enc.encode(input) : input);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export async function hmacHex(secret, message) {
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Constant-time string comparison. */
export function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export function parseJson(text, fallback) {
  if (text == null || text === "") return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

export const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

export function slugify(s) {
  return String(s)
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

/** Unbiased Fisher–Yates shuffle using the CSPRNG. */
export function shuffle(list) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) {
    const buf = new Uint32Array(1);
    const limit = Math.floor(0x100000000 / (i + 1)) * (i + 1);
    let r;
    do {
      crypto.getRandomValues(buf);
      r = buf[0];
    } while (r >= limit);
    const j = r % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function chunk(list, size) {
  const out = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

export function formatDuration(minutes, t) {
  const m = Math.max(0, Math.round(minutes || 0));
  if (m < 60) return t("duration.minutes", { n: m });
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? t("duration.hours_minutes", { h, m: r }) : t("duration.hours", { h });
}
