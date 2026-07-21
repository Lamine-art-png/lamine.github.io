/* ============================================================================
   AGRO-AI Platform API — interactive API Explorer.

   Security posture (see also docs/authentication.html):
     • The API key you enter stays in this browser. It is held in memory and,
       only if you opt in, in sessionStorage (cleared when the tab closes).
       It is never written to localStorage and never sent to AGRO-AI web
       servers — this page is static. In "Live" mode the key is sent only to
       the API base URL you explicitly select, as a bearer token.
     • The default mode is "Sample response": it returns the documented example
       with no network request and no key, so nothing can leak by accident.
     • The generated cURL uses the $AGROAI_API_KEY placeholder, never the raw
       key, so copying a snippet never copies your secret.
   ========================================================================== */
(function () {
  "use strict";

  var SESSION_KEY = "agroai-explorer-key";
  var state = {
    spec: null,
    ep: null,
    mode: "sample", // "sample" | "live"
    server: null,
    apiKey: "",
    remember: false,
    params: {},
    body: "",
  };

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  /* ---------- Request construction ---------- */
  function resolvedPath() {
    var p = state.ep.path;
    (state.ep.params || [])
      .filter(function (x) {
        return x.in === "path";
      })
      .forEach(function (x) {
        var v = state.params[x.name] || "{" + x.name + "}";
        p = p.replace("{" + x.name + "}", encodeURIComponent(v));
      });
    return p;
  }
  function queryString() {
    var qs = (state.ep.params || [])
      .filter(function (x) {
        return x.in === "query" && state.params[x.name];
      })
      .map(function (x) {
        return encodeURIComponent(x.name) + "=" + encodeURIComponent(state.params[x.name]);
      });
    return qs.length ? "?" + qs.join("&") : "";
  }
  function fullUrl() {
    return state.server.url + resolvedPath() + queryString();
  }
  function curlSnippet() {
    var lines = ["curl"];
    if (state.ep.method !== "GET") lines.push("-X " + state.ep.method);
    lines.push('"' + fullUrl() + '"');
    lines.push('-H "Authorization: Bearer $AGROAI_API_KEY"');
    if (state.ep.body) {
      lines.push('-H "Content-Type: application/json"');
      lines.push("-d '" + (state.body || "{}") + "'");
    }
    return lines.join(" \\\n  ");
  }

  /* ---------- Rendering ---------- */
  function renderEndpointList() {
    var list = $("#exp-list");
    list.innerHTML = "";
    state.spec.tags.forEach(function (tag) {
      var eps = state.spec.endpoints.filter(function (e) {
        return e.tag === tag.id;
      });
      if (!eps.length) return;
      var group = el('<nav class="docs-nav-group"><h5>' + esc(tag.name) + "</h5></nav>");
      eps.forEach(function (e) {
        var a = el(
          '<a href="#' +
            esc(e.id) +
            '" data-ep="' +
            esc(e.id) +
            '"><span class="method ' +
            e.method.toLowerCase() +
            '" style="font-size:.6rem;padding:.1rem .3rem;margin-right:.4rem">' +
            esc(e.method) +
            "</span>" +
            esc(e.summary) +
            "</a>"
        );
        if (state.ep && state.ep.id === e.id) a.setAttribute("aria-current", "page");
        a.addEventListener("click", function (evt) {
          evt.preventDefault();
          selectEndpoint(e.id);
          history.replaceState(null, "", "#" + e.id);
        });
        group.appendChild(a);
      });
      list.appendChild(group);
    });
  }

  function paramField(p) {
    var id = "pf-" + p.name;
    var val = state.params[p.name] != null ? state.params[p.name] : (p.default != null ? p.default : "");
    return (
      '<label class="exp-field"><span class="exp-label">' +
      esc(p.name) +
      (p.required ? ' <span class="req">*</span>' : "") +
      ' <em class="text-faint">' +
      esc(p.in) +
      " · " +
      esc(p.type) +
      "</em></span>" +
      '<input id="' +
      id +
      '" data-param="' +
      esc(p.name) +
      '" value="' +
      esc(val) +
      '" placeholder="' +
      esc(p.description || "") +
      '" autocomplete="off" /></label>'
    );
  }

  function renderRequest() {
    var host = $("#exp-request");
    if (!state.ep) {
      host.innerHTML = '<p class="text-muted">Select an endpoint to begin.</p>';
      return;
    }
    var e = state.ep;
    var serverOpts = state.spec.info.servers
      .map(function (s) {
        return (
          '<option value="' +
          esc(s.url) +
          '"' +
          (state.server && state.server.url === s.url ? " selected" : "") +
          ">" +
          esc(s.label) +
          " — " +
          esc(s.url) +
          "</option>"
        );
      })
      .join("");

    var paramsHtml = (e.params || []).map(paramField).join("");
    var bodyHtml = e.body
      ? '<div class="exp-block"><h4>Request body</h4><textarea id="exp-body" rows="10" spellcheck="false" aria-label="Request body JSON">' +
        esc(state.body) +
        "</textarea></div>"
      : "";

    host.innerHTML =
      '<div class="flex items-center gap-3 wrap"><span class="method ' +
      e.method.toLowerCase() +
      '">' +
      esc(e.method) +
      '</span><code style="font-size:1rem">' +
      esc(e.path) +
      "</code></div>" +
      '<p class="text-muted">' +
      esc(e.description) +
      "</p>" +
      '<div class="exp-controls">' +
      '<label class="exp-field"><span class="exp-label">Environment</span><select id="exp-server">' +
      serverOpts +
      "</select></label>" +
      '<label class="exp-field"><span class="exp-label">API key <em class="text-faint">held in this browser only</em></span>' +
      '<input id="exp-key" type="password" value="' +
      esc(state.apiKey) +
      '" placeholder="sk_test_… (optional for Sample mode)" autocomplete="off" /></label>' +
      "</div>" +
      '<div class="exp-modes" role="radiogroup" aria-label="Request mode">' +
      '<label class="exp-mode"><input type="radio" name="exp-mode" value="sample"' +
      (state.mode === "sample" ? " checked" : "") +
      "> Sample response <em class=\"text-faint\">(no network, no key)</em></label>" +
      '<label class="exp-mode"><input type="radio" name="exp-mode" value="live"' +
      (state.mode === "live" ? " checked" : "") +
      "> Live request <em class=\"text-faint\">(sends your key to the selected host)</em></label>" +
      '<label class="exp-remember"><input type="checkbox" id="exp-remember"' +
      (state.remember ? " checked" : "") +
      "> Remember key for this tab</label>" +
      "</div>" +
      (paramsHtml ? '<div class="exp-block"><h4>Parameters</h4><div class="exp-grid">' + paramsHtml + "</div></div>" : "") +
      bodyHtml +
      '<div class="flex gap-3 wrap" style="margin-top:1rem"><button id="exp-send" class="btn btn-primary">Send request</button>' +
      '<button id="exp-clear-key" class="btn btn-ghost" type="button">Clear key</button></div>' +
      '<div class="exp-block"><h4>cURL</h4><div class="code" id="exp-curl-wrap"><div class="code-head"><span class="code-lang">bash</span></div><pre><code data-lang="bash" id="exp-curl"></code></pre></div></div>' +
      '<div class="exp-block"><h4>Response</h4><div id="exp-response" class="exp-response" aria-live="polite"><p class="text-muted">No request sent yet.</p></div></div>';

    wireRequest();
    updateCurl();
  }

  function updateCurl() {
    var node = $("#exp-curl");
    if (node) {
      node.textContent = curlSnippet();
      node.removeAttribute("data-highlighted");
      document.dispatchEvent(new CustomEvent("agroai:content-updated"));
    }
  }

  function setResponse(html) {
    $("#exp-response").innerHTML = html;
    document.dispatchEvent(new CustomEvent("agroai:content-updated"));
  }

  function wireRequest() {
    $("#exp-server").addEventListener("change", function () {
      var url = this.value;
      state.server = state.spec.info.servers.filter(function (s) {
        return s.url === url;
      })[0];
      updateCurl();
    });
    var keyInput = $("#exp-key");
    keyInput.addEventListener("input", function () {
      state.apiKey = this.value;
      persistKey();
    });
    $("#exp-remember").addEventListener("change", function () {
      state.remember = this.checked;
      persistKey();
    });
    $("#exp-clear-key").addEventListener("click", function () {
      state.apiKey = "";
      keyInput.value = "";
      try {
        sessionStorage.removeItem(SESSION_KEY);
      } catch (e) {}
    });
    document.querySelectorAll("input[name='exp-mode']").forEach(function (r) {
      r.addEventListener("change", function () {
        state.mode = this.value;
      });
    });
    document.querySelectorAll("[data-param]").forEach(function (input) {
      input.addEventListener("input", function () {
        state.params[this.getAttribute("data-param")] = this.value;
        updateCurl();
      });
    });
    var bodyEl = $("#exp-body");
    if (bodyEl) {
      bodyEl.addEventListener("input", function () {
        state.body = this.value;
        updateCurl();
      });
    }
    $("#exp-send").addEventListener("click", send);
  }

  function persistKey() {
    try {
      if (state.remember && state.apiKey) {
        sessionStorage.setItem(SESSION_KEY, state.apiKey);
      } else {
        sessionStorage.removeItem(SESSION_KEY);
      }
    } catch (e) {
      /* storage blocked — key simply stays in memory */
    }
  }

  function validateParams() {
    var missing = (state.ep.params || [])
      .filter(function (p) {
        return p.required && !state.params[p.name];
      })
      .map(function (p) {
        return p.name;
      });
    return missing;
  }

  function renderResponseBlock(status, statusText, ms, bodyText, note) {
    var ok = status >= 200 && status < 300;
    return (
      '<div class="exp-status ' +
      (ok ? "ok" : "err") +
      '"><span class="dot" style="background:' +
      (ok ? "var(--success)" : "var(--danger)") +
      '"></span> ' +
      esc(status) +
      " " +
      esc(statusText) +
      (ms != null ? ' <span class="text-faint">· ' + ms + " ms</span>" : "") +
      "</div>" +
      (note ? '<p class="text-muted" style="font-size:.85rem">' + esc(note) + "</p>" : "") +
      '<div class="code"><div class="code-head"><span class="code-lang">application/json</span></div><pre><code data-lang="json">' +
      esc(bodyText) +
      "</code></pre></div>"
    );
  }

  function send() {
    var missing = validateParams();
    if (missing.length) {
      setResponse(
        '<div class="callout callout-warn"><p>Fill required parameter(s): <code>' +
          missing.map(esc).join("</code>, <code>") +
          "</code></p></div>"
      );
      return;
    }

    if (state.mode === "sample") {
      var ex = state.ep.response ? state.ep.response.example : {};
      var st = state.ep.response ? state.ep.response.status : 200;
      setResponse(
        renderResponseBlock(
          st,
          "Sample",
          null,
          JSON.stringify(ex, null, 2),
          "Documented example response — no network request was made."
        )
      );
      return;
    }

    // Live mode
    if (!state.apiKey) {
      setResponse(
        '<div class="callout callout-warn"><p>Live mode needs an API key. Enter a sandbox key (<code>sk_test_…</code>) above, or switch to Sample response.</p></div>'
      );
      return;
    }
    var body = null;
    if (state.ep.body) {
      try {
        body = JSON.stringify(JSON.parse(state.body || "{}"));
      } catch (e) {
        setResponse('<div class="callout callout-danger"><p>Request body is not valid JSON: ' + esc(e.message) + "</p></div>");
        return;
      }
    }
    setResponse('<p class="text-muted">Sending…</p>');
    var headers = { Authorization: "Bearer " + state.apiKey };
    if (body) headers["Content-Type"] = "application/json";
    var t0 = performance.now();
    fetch(fullUrl(), { method: state.ep.method, headers: headers, body: body })
      .then(function (res) {
        return res.text().then(function (text) {
          var ms = Math.round(performance.now() - t0);
          var pretty = text;
          try {
            pretty = JSON.stringify(JSON.parse(text), null, 2);
          } catch (e) {}
          setResponse(renderResponseBlock(res.status, res.statusText || "", ms, pretty));
        });
      })
      .catch(function (err) {
        setResponse(
          '<div class="callout callout-danger"><p><strong>Request failed:</strong> ' +
            esc(err.message) +
            ". This is often a browser CORS restriction when calling the API directly from a web page, or the sandbox host being unreachable. Use the cURL snippet from your server instead.</p></div>"
        );
      });
  }

  /* ---------- Endpoint selection ---------- */
  function selectEndpoint(id) {
    var e = state.spec.endpoints.filter(function (x) {
      return x.id === id;
    })[0];
    if (!e) e = state.spec.endpoints[0];
    state.ep = e;
    state.params = {};
    (e.params || []).forEach(function (p) {
      if (p.default != null) state.params[p.name] = p.default;
    });
    state.body = e.body ? JSON.stringify(e.body.example, null, 2) : "";
    renderEndpointList();
    renderRequest();
  }

  function boot() {
    try {
      var saved = sessionStorage.getItem(SESSION_KEY);
      if (saved) {
        state.apiKey = saved;
        state.remember = true;
      }
    } catch (e) {}

    fetch("/platform-api/assets/openapi.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("spec " + r.status);
        return r.json();
      })
      .then(function (spec) {
        state.spec = spec;
        state.server = spec.info.servers[spec.info.servers.length - 1]; // default: sandbox
        var hash = (location.hash || "").slice(1);
        selectEndpoint(hash);
      })
      .catch(function (err) {
        $("#exp-request").innerHTML =
          '<div class="callout callout-danger"><p>Could not load the API spec (' +
          esc(err.message) +
          "). Refresh to try again.</p></div>";
      });
  }

  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
