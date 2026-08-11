export async function verifyWebhookSignature(options: {
  secret: string;
  body: string | Uint8Array;
  timestamp: string;
  signature: string;
  toleranceSeconds?: number;
  nowSeconds?: number;
}): Promise<boolean> {
  const sentAt = Number(options.timestamp);
  if (!Number.isInteger(sentAt)) return false;
  const now = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (Math.abs(now - sentAt) > (options.toleranceSeconds ?? 300)) return false;
  const encoder = new TextEncoder();
  const body = typeof options.body === "string" ? encoder.encode(options.body) : options.body;
  const prefix = encoder.encode(`${options.timestamp}.`);
  const signed = new Uint8Array(prefix.length + body.length);
  signed.set(prefix);
  signed.set(body, prefix.length);
  const key = await crypto.subtle.importKey("raw", encoder.encode(options.secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, signed));
  const expected = [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const candidate = options.signature.replace(/^v1=/, "");
  if (candidate.length !== expected.length) return false;
  let mismatch = 0;
  for (let index = 0; index < expected.length; index += 1) mismatch |= expected.charCodeAt(index) ^ candidate.charCodeAt(index);
  return mismatch === 0;
}
