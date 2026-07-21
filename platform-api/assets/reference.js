/* ============================================================================
   AGRO-AI Platform API — reference renderer.

   Renders the REAL curated contract (platform-api/contract/platform_api_openapi
   .json), which is generated only from the backend. This file never invents
   endpoints, schemas, or key prefixes. It has no request-execution / API-key
   input: authenticated calls are made from the console, and try-it lives in the
   server-mediated Playground, never with a browser-held key.
   ========================================================================== */
(function () {
  "use strict";

  var CONTRACT_URL = "/platform-api/contract/platform_api_openapi.json";
  var SURFACE_LABELS = {
    public_metadata: "Metadata",
    platform_api_partner: "Partner",
    platform_api_resource: "Resources",
  };
  var SURFACE_ORDER = ["public_metadata", "platform_api_partner", "platform_api_resource"];

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }
  function slug(method, path) {
    return (method + "-" + path).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  var spec = null;
  function resolveRef(ref) {
    if (!ref || ref[0] !== "#") return null;
    var parts = ref.slice(2).split("/");
    var node = spec;
    for (var i = 0; i < parts.length; i++) {
      node = node && node[parts[i]];
    }
    return node || null;
  }

  function typeLabel(schema) {
    if (!schema) return "";
    if (schema.$ref) {
      var name = schema.$ref.split("/").pop();
      return '<a href="#schema-' + esc(name.toLowerCase()) + '"><code>' + esc(name) + "</code></a>";
    }
    if (schema.type === "array") {
      return "array&lt;" + typeLabel(schema.items) + "&gt;";
    }
    var t = schema.type || "object";
    var extra = [];
    if (schema.enum) extra.push("enum");
    if (schema.format) extra.push(esc(schema.format));
    if (schema.minimum !== undefined) extra.push("min " + schema.minimum);
    if (schema.maximum !== undefined) extra.push("max " + schema.maximum);
    if (schema.maxLength !== undefined) extra.push("≤" + schema.maxLength + " chars");
    if (schema.default !== undefined) extra.push("default " + JSON.stringify(schema.default));
    return "<code>" + esc(t) + "</code>" + (extra.length ? ' <span class="text-faint">(' + extra.join(", ") + ")</span>" : "");
  }

  function schemaTable(schema) {
    var resolved = schema && schema.$ref ? resolveRef(schema.$ref) : schema;
    if (!resolved) return "";
    if (resolved.type === "array") {
      return '<p class="text-muted">Array of ' + typeLabel(resolved.items) + ".</p>" +
        schemaTable(resolved.items);
    }
    var props = resolved.properties;
    if (!props) {
      if (resolved.enum) {
        return '<p class="text-muted">One of: ' +
          resolved.enum.map(function (v) { return "<code>" + esc(v) + "</code>"; }).join(", ") + ".</p>";
      }
      return "";
    }
    var required = resolved.required || [];
    var rows = Object.keys(props).map(function (name) {
      var p = props[name];
      var req = required.indexOf(name) >= 0
        ? '<span class="req">required</span>'
        : '<span class="text-faint">optional</span>';
      return "<tr><td><code>" + esc(name) + "</code></td><td>" + typeLabel(p) +
        "</td><td>" + req + "</td><td>" + esc(p.description || "") + "</td></tr>";
    }).join("");
    return '<div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Type</th><th></th><th>Description</th></tr></thead><tbody>' +
      rows + "</tbody></table></div>";
  }

  function paramTable(params) {
    if (!params || !params.length) return "";
    var rows = params.map(function (p) {
      var req = p.required ? '<span class="req">required</span>' : '<span class="text-faint">optional</span>';
      return "<tr><td><code>" + esc(p.name) + "</code></td><td>" + esc(p.in) +
        "</td><td>" + typeLabel(p.schema) + "</td><td>" + req + "</td><td>" +
        esc(p.description || "") + "</td></tr>";
    }).join("");
    return '<div class="table-wrap"><table class="data"><thead><tr><th>Name</th><th>In</th><th>Type</th><th></th><th>Description</th></tr></thead><tbody>' +
      rows + "</tbody></table></div>";
  }

  function operationCard(method, path, op) {
    var id = slug(method, path);
    var m = method.toLowerCase();
    var card = el('<article class="card" id="' + esc(id) + '" style="scroll-margin-top:84px;margin-bottom:1.5rem"></article>');
    card.appendChild(el(
      '<div class="flex items-center gap-3 wrap"><span class="method ' + m + '">' + esc(method) +
      '</span><code style="font-size:1rem">/v1' + esc(path) + "</code></div>"
    ));
    if (op.summary) card.appendChild(el('<p class="text-muted" style="margin-top:.6rem">' + esc(op.summary) + "</p>"));

    // auth + scopes (truthful, from x-agroai extensions)
    var auth = op["x-agroai-authentication"];
    var scopes = op["x-agroai-required-scopes"] || [];
    var authHtml = '<div class="flex gap-2 wrap" style="margin:.5rem 0">';
    if (auth) {
      authHtml += '<span class="badge">' + (auth === "anonymous" ? "No auth" : esc(auth)) + "</span>";
    }
    scopes.forEach(function (s) { authHtml += '<span class="badge badge-accent">' + esc(s) + "</span>"; });
    authHtml += "</div>";
    card.appendChild(el(authHtml));

    if (op.parameters && op.parameters.length) {
      card.appendChild(el('<h4 style="margin:1rem 0 .4rem;font-size:.95rem">Parameters</h4>'));
      card.appendChild(el(paramTable(op.parameters)));
    }
    if (op.requestBody) {
      var rb = op.requestBody.content && op.requestBody.content["application/json"];
      if (rb && rb.schema) {
        card.appendChild(el('<h4 style="margin:1rem 0 .4rem;font-size:.95rem">Request body</h4>'));
        card.appendChild(el(schemaTable(rb.schema) || "<p></p>"));
      }
    }
    // responses
    card.appendChild(el('<h4 style="margin:1rem 0 .4rem;font-size:.95rem">Responses</h4>'));
    var respRows = Object.keys(op.responses || {}).map(function (code) {
      var r = op.responses[code];
      var resolved = r.$ref ? resolveRef(r.$ref) : r;
      var desc = (resolved && resolved.description) || (r.$ref ? r.$ref.split("/").pop() : "");
      var schemaName = "";
      var sc = resolved && resolved.content && resolved.content["application/json"];
      if (sc && sc.schema && sc.schema.$ref) schemaName = typeLabel(sc.schema);
      return "<tr><td><code>" + esc(code) + "</code></td><td>" + esc(desc) + "</td><td>" + schemaName + "</td></tr>";
    }).join("");
    card.appendChild(el('<div class="table-wrap"><table class="data"><thead><tr><th>Status</th><th>Description</th><th>Schema</th></tr></thead><tbody>' +
      respRows + "</tbody></table></div>"));
    return card;
  }

  function render() {
    var side = document.getElementById("ref-sidebar");
    var overview = document.getElementById("ref-overview");
    var main = document.getElementById("ref-endpoints");
    if (!side || !overview || !main) return;

    var info = spec.info || {};
    var v = document.getElementById("ref-version");
    if (v) v.textContent = info.version || "";

    // Overview: truthful private-beta note, base path, auth, key prefixes, readiness
    var sec = (spec.components && spec.components.securitySchemes && spec.components.securitySchemes.PlatformApiKey) || {};
    var readiness = spec["x-agroai-provider-readiness"] || {};
    var readinessRows = Object.keys(readiness).map(function (k) {
      return "<tr><td><code>" + esc(k) + "</code></td><td>" + esc(readiness[k]) + "</td></tr>";
    }).join("");
    overview.innerHTML =
      (info.description ? '<div class="callout callout-warn"><span class="callout-icon warn" aria-hidden="true">●</span><p>' + esc(info.description) + "</p></div>" : "") +
      '<h2 id="ref-base" style="scroll-margin-top:84px">Base path &amp; authentication</h2>' +
      '<p>All routes are under the <code>/v1</code> base path. Authenticate with a Platform API key issued from your project in the authenticated console — send it as a bearer token:</p>' +
      '<div class="code"><div class="code-head"><span class="code-lang">http</span></div><pre><code data-lang="http">Authorization: Bearer ' + esc(sec.bearerFormat || "agro_test_... or agro_live_...") + "</code></pre></div>" +
      '<p class="text-muted">Keys are created and rotated in the console. They are never entered into this website. See <a href="/platform-api/docs/authentication.html">Authentication</a>.</p>' +
      (readinessRows ? '<h2 id="ref-readiness" style="scroll-margin-top:84px">Provider readiness</h2><div class="table-wrap"><table class="data"><thead><tr><th>Provider</th><th>Status</th></tr></thead><tbody>' + readinessRows + "</tbody></table></div>" : "");

    // group operations by surface
    var groups = {};
    Object.keys(spec.paths).forEach(function (path) {
      var methods = spec.paths[path];
      Object.keys(methods).forEach(function (method) {
        if (["get", "post", "put", "patch", "delete"].indexOf(method) < 0) return;
        var op = methods[method];
        var surface = op["x-agroai-surface"] || "platform_api_resource";
        (groups[surface] = groups[surface] || []).push({ method: method.toUpperCase(), path: path, op: op });
      });
    });

    SURFACE_ORDER.forEach(function (surface) {
      var ops = groups[surface];
      if (!ops || !ops.length) return;
      var label = SURFACE_LABELS[surface] || surface;
      var group = el('<nav class="docs-nav-group"><h5>' + esc(label) + "</h5></nav>");
      ops.forEach(function (o) {
        group.appendChild(el('<a href="#' + slug(o.method, o.path) + '"><span class="method ' +
          o.method.toLowerCase() + '" style="font-size:.6rem;padding:.1rem .3rem;margin-right:.4rem">' +
          esc(o.method) + "</span>" + esc(o.path.replace("/platform/", "")) + "</a>"));
      });
      side.appendChild(group);

      main.appendChild(el('<section style="margin-top:2.5rem"><h2 id="surface-' + esc(surface) +
        '" style="scroll-margin-top:84px">' + esc(label) + "</h2></section>"));
      ops.forEach(function (o) { main.appendChild(operationCard(o.method, o.path, o.op)); });
    });

    document.dispatchEvent(new CustomEvent("agroai:content-updated"));
  }

  fetch(CONTRACT_URL, { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("contract " + r.status); return r.json(); })
    .then(function (data) { spec = data; render(); })
    .catch(function (err) {
      var main = document.getElementById("ref-endpoints");
      if (main) main.appendChild(el('<div class="callout callout-danger"><p>Could not load the contract (' + esc(err.message) + ").</p></div>"));
    });
})();
