// Tiny method + path router with :params and a trailing * wildcard.

export class Router {
  constructor() {
    this.routes = [];
  }
  add(method, pattern, handler, opts = {}) {
    const keys = [];
    const re = new RegExp(
      "^" +
        pattern
          .replace(/\/$/, "")
          .replace(/[.]/g, "\\.")
          .replace(/:(\w+)/g, (_, k) => {
            keys.push(k);
            return "([^/]+)";
          })
          .replace(/\*$/, "(.*)") +
        "/?$",
    );
    this.routes.push({ method, re, keys, handler, opts, pattern });
    return this;
  }
  get(p, h, o) {
    return this.add("GET", p, h, o);
  }
  post(p, h, o) {
    return this.add("POST", p, h, o);
  }
  match(method, path) {
    let allowed = false;
    for (const r of this.routes) {
      const m = r.re.exec(path);
      if (!m) continue;
      if (r.method !== method && !(method === "HEAD" && r.method === "GET")) {
        allowed = true;
        continue;
      }
      const params = {};
      r.keys.forEach((k, i) => {
        try {
          params[k] = decodeURIComponent(m[i + 1]);
        } catch {
          params[k] = m[i + 1];
        }
      });
      return { route: r, params };
    }
    return allowed ? { methodNotAllowed: true } : null;
  }
}
