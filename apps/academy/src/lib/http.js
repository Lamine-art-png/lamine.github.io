// HTTP helpers: cookies, responses, security headers and request body parsing.
import { fontOrigin } from "../brand.js";
import { STREAM_SDK_ORIGIN, STREAM_FRAME_ORIGINS } from "../services/stream.js";

export class HttpError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message || code);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

export function parseCookies(header) {
  const out = {};
  for (const part of String(header || "").split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const k = part.slice(0, idx).trim();
    if (!k || k in out) continue;
    try {
      out[k] = decodeURIComponent(part.slice(idx + 1).trim());
    } catch {
      out[k] = part.slice(idx + 1).trim();
    }
  }
  return out;
}

export function serializeCookie(name, value, opts = {}) {
  let s = `${name}=${encodeURIComponent(value)}; Path=${opts.path || "/"}`;
  if (opts.maxAge != null) s += `; Max-Age=${Math.floor(opts.maxAge)}`;
  if (opts.httpOnly !== false) s += "; HttpOnly";
  if (opts.secure) s += "; Secure";
  s += `; SameSite=${opts.sameSite || "Lax"}`;
  return s;
}

export function securityHeaders(headers, { isHtml, secure, streamPlayer = false }) {
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Cross-Origin-Opener-Policy", "same-origin");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");
  if (secure) headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  if (isHtml) {
    headers.set(
      "Content-Security-Policy",
      [
        "default-src 'self'",
        `script-src 'self'${streamPlayer ? ` ${STREAM_SDK_ORIGIN}` : ""}`,
        `style-src 'self'${fontOrigin ? ` ${fontOrigin}` : ""}`,
        "img-src 'self' data: https:",
        "media-src 'self' https: blob:",
        `font-src 'self'${fontOrigin ? ` ${fontOrigin}` : ""}`,
        "connect-src 'self'",
        `frame-src ${STREAM_FRAME_ORIGINS.join(" ")}`,
        "frame-ancestors 'none'",
        "form-action 'self' https://accounts.google.com",
        "base-uri 'none'",
        "object-src 'none'",
        secure ? "upgrade-insecure-requests" : "",
      ]
        .filter(Boolean)
        .join("; "),
    );
  }
  return headers;
}

export function redirect(location, status = 303) {
  return new Response(null, { status, headers: { Location: location } });
}

export function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
  });
}

/** Parse a form or JSON body into a plain object, with a size ceiling. */
export async function readBody(req, maxBytes = 256 * 1024) {
  const len = Number(req.headers.get("content-length") || 0);
  if (len > maxBytes) throw new HttpError(413, "payload_too_large");
  const type = req.headers.get("content-type") || "";
  const text = await req.text();
  if (text.length > maxBytes) throw new HttpError(413, "payload_too_large");
  if (type.includes("application/json")) {
    try {
      const v = JSON.parse(text || "{}");
      return v && typeof v === "object" ? v : {};
    } catch {
      throw new HttpError(400, "invalid_json");
    }
  }
  const params = new URLSearchParams(text);
  const out = {};
  for (const [k, v] of params) {
    if (k in out) out[k] = [].concat(out[k], v);
    else out[k] = v;
  }
  return out;
}

export function clientIp(req) {
  return req.headers.get("cf-connecting-ip") || req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
}
