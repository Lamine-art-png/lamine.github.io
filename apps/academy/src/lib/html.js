// Escape-by-default HTML templating. Every interpolated value is escaped unless
// it was produced by html`` or explicitly wrapped with raw() by trusted code.

class SafeHtml {
  constructor(value) {
    this.value = value;
  }
  toString() {
    return this.value;
  }
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export const escapeHtml = (s) => String(s).replace(/[&<>"'`]/g, (c) => ESC[c]);

function render(value) {
  if (value == null || value === false || value === true) return "";
  if (value instanceof SafeHtml) return value.value;
  if (Array.isArray(value)) return value.map(render).join("");
  return escapeHtml(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) out += render(values[i]) + strings[i + 1];
  return new SafeHtml(out);
}

/** Mark a string as trusted HTML. Only use for content this codebase generated. */
export const raw = (s) => new SafeHtml(String(s ?? ""));

export const isSafe = (v) => v instanceof SafeHtml;

/** Serialize JSON for embedding inside <script type="application/ld+json">. */
export function jsonScript(obj) {
  return raw(JSON.stringify(obj).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026"));
}

/** Allow only http(s), mailto and same-origin relative URLs in links. */
export function safeUrl(url) {
  const s = String(url ?? "").trim();
  if (s.startsWith("/") && !s.startsWith("//")) return s;
  if (/^https?:\/\//i.test(s) || /^mailto:/i.test(s)) return s;
  return "#";
}
