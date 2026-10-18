// Cookie- and CSRF-aware HTTP client for testing a deployed Academy over the network.
export class RemoteClient {
  constructor(base) {
    this.base = base.replace(/\/$/, "");
    this.jar = new Map();
    this.csrf = null;
  }
  async request(method, path, { form, headers = {} } = {}) {
    const h = new Headers({ "user-agent": "agroai-academy-staging-test", origin: this.base, ...headers });
    if (this.jar.size) h.set("cookie", [...this.jar].map(([k, v]) => `${k}=${v}`).join("; "));
    let body;
    if (form) {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(form)) for (const item of [].concat(v)) p.append(k, item);
      if (this.csrf && !p.has("_csrf")) p.set("_csrf", this.csrf);
      h.set("content-type", "application/x-www-form-urlencoded");
      body = p.toString();
    }
    const res = await fetch(this.base + path, { method, headers: h, body, redirect: "manual" });
    for (const sc of res.headers.getSetCookie()) {
      const [pair, ...attrs] = sc.split(";");
      const i = pair.indexOf("=");
      const k = pair.slice(0, i).trim();
      const v = pair.slice(i + 1).trim();
      if (attrs.some((a) => /max-age=0/i.test(a)) || v === "") this.jar.delete(k);
      else this.jar.set(k, v);
    }
    const type = res.headers.get("content-type") || "";
    const text = type.includes("pdf") ? null : await res.text();
    const m = text && /<meta name="csrf-token" content="([^"]+)"/.exec(text);
    if (m) this.csrf = m[1];
    return { status: res.status, text, headers: res.headers, location: res.headers.get("location") };
  }
  get(path, opts) {
    return this.request("GET", path, opts);
  }
  post(path, form, opts = {}) {
    return this.request("POST", path, { form, ...opts });
  }
}
