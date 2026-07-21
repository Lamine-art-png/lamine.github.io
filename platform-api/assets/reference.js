/* ============================================================================
   AGRO-AI Platform API — API reference renderer.
   Reads the public spec (openapi.json) and renders a static-feeling reference.
   All spec text is escaped before insertion.
   ========================================================================== */
(function () {
  "use strict";

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function pretty(obj) {
    return esc(JSON.stringify(obj, null, 2));
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  function paramRows(params) {
    return params
      .map(function (p) {
        var req = p.required
          ? '<span class="req" title="required">required</span>'
          : '<span class="text-faint">optional</span>';
        var def =
          p.default !== undefined
            ? " Defaults to <code>" + esc(p.default) + "</code>."
            : "";
        return (
          "<tr><td><code>" +
          esc(p.name) +
          "</code></td><td>" +
          esc(p.type) +
          "</td><td>" +
          req +
          "</td><td>" +
          esc(p.description || "") +
          def +
          "</td></tr>"
        );
      })
      .join("");
  }

  function endpointCard(ep) {
    var m = ep.method.toLowerCase();
    var card = el('<article class="card" id="' + esc(ep.id) + '" style="scroll-margin-top: 84px; margin-bottom: 1.5rem"></article>');

    card.appendChild(
      el(
        '<div class="flex items-center gap-3 wrap"><span class="method ' +
          m +
          '">' +
          esc(ep.method) +
          '</span><code style="font-size: 1rem; white-space: nowrap">' +
          esc(ep.path) +
          "</code></div>"
      )
    );
    card.appendChild(el('<h3 style="margin-top: .75rem">' + esc(ep.summary) + "</h3>"));
    card.appendChild(el("<p class=\"text-muted\">" + esc(ep.description) + "</p>"));

    if (ep.params && ep.params.length) {
      card.appendChild(el('<h4 style="margin: 1rem 0 .4rem; font-size: .95rem">Parameters</h4>'));
      card.appendChild(
        el(
          '<div class="table-wrap"><table class="data"><thead><tr><th>Name</th><th>Type</th><th></th><th>Description</th></tr></thead><tbody>' +
            paramRows(ep.params) +
            "</tbody></table></div>"
        )
      );
    }

    if (ep.body) {
      card.appendChild(el('<h4 style="margin: 1rem 0 .4rem; font-size: .95rem">Request body</h4>'));
      if (ep.body.fields) {
        card.appendChild(
          el(
            '<div class="table-wrap"><table class="data"><thead><tr><th>Field</th><th>Type</th><th></th><th>Description</th></tr></thead><tbody>' +
              paramRows(ep.body.fields) +
              "</tbody></table></div>"
          )
        );
      }
      card.appendChild(
        el(
          '<div class="code"><div class="code-head"><span class="code-lang">Example body</span></div><pre><code data-lang="json">' +
            pretty(ep.body.example) +
            "</code></pre></div>"
        )
      );
    }

    if (ep.response) {
      card.appendChild(el('<h4 style="margin: 1rem 0 .4rem; font-size: .95rem">Response</h4>'));
      card.appendChild(
        el(
          '<div class="code"><div class="code-head"><span class="code-lang">' +
            esc(ep.response.status) +
            ' · application/json</span></div><pre><code data-lang="json">' +
            pretty(ep.response.example) +
            "</code></pre></div>"
        )
      );
    }

    var tryLink = el(
      '<a class="btn btn-ghost" style="margin-top: .5rem" href="/platform-api/explorer.html#' +
        esc(ep.id) +
        '">Try it in the Explorer →</a>'
    );
    card.appendChild(tryLink);
    return card;
  }

  function render(spec) {
    var side = document.getElementById("ref-sidebar");
    var overview = document.getElementById("ref-overview");
    var main = document.getElementById("ref-endpoints");
    if (!side || !main || !overview) return;

    var version = document.getElementById("ref-version");
    if (version) version.textContent = spec.info.version;

    var servers = spec.info.servers
      .map(function (s) {
        return (
          "<tr><td>" + esc(s.label) + "</td><td><code>" + esc(s.url) + "</code></td></tr>"
        );
      })
      .join("");
    overview.innerHTML =
      '<h2 style="scroll-margin-top:84px">Base URL</h2><div class="table-wrap"><table class="data"><thead><tr><th>Environment</th><th>URL</th></tr></thead><tbody>' +
      servers +
      "</tbody></table></div>" +
      "<h2 style=\"scroll-margin-top:84px\">Authentication</h2><p>Send your API key as a bearer token. See <a href=\"/platform-api/docs/authentication.html\">Authentication</a>.</p>" +
      '<div class="code"><div class="code-head"><span class="code-lang">http</span></div><pre><code data-lang="http">' +
      esc(spec.info.auth.format) +
      "</code></pre></div>";

    spec.tags.forEach(function (tag) {
      var eps = spec.endpoints.filter(function (e) {
        return e.tag === tag.id;
      });
      if (!eps.length) return;

      // sidebar group
      var group = el('<nav class="docs-nav-group"><h5>' + esc(tag.name) + "</h5></nav>");
      eps.forEach(function (e) {
        group.appendChild(
          el(
            '<a href="#' +
              esc(e.id) +
              '"><span class="method ' +
              e.method.toLowerCase() +
              '" style="font-size:.6rem; padding:.1rem .3rem; margin-right:.4rem">' +
              esc(e.method) +
              "</span>" +
              esc(e.summary) +
              "</a>"
          )
        );
      });
      side.appendChild(group);

      // content section
      main.appendChild(
        el(
          '<section style="margin-top: 2.5rem"><h2 id="tag-' +
            esc(tag.id) +
            '" style="scroll-margin-top: 84px">' +
            esc(tag.name) +
            "</h2><p class=\"text-muted\">" +
            esc(tag.description) +
            "</p></section>"
        )
      );
      eps.forEach(function (e) {
        main.appendChild(endpointCard(e));
      });
    });

    // let the shared highlighter tokenise the code we just injected
    document.dispatchEvent(new CustomEvent("agroai:content-updated"));
  }

  function boot() {
    fetch("/platform-api/assets/openapi.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("spec " + r.status);
        return r.json();
      })
      .then(render)
      .catch(function (err) {
        var main = document.getElementById("ref-content");
        if (main) {
          main.appendChild(
            el(
              '<div class="callout callout-danger"><p>Could not load the API spec (' +
                esc(err.message) +
                "). Refresh to try again.</p></div>"
            )
          );
        }
      });
  }

  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
