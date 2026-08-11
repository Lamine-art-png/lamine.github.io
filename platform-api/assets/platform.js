/* ============================================================================
   AGRO-AI Platform API — shared UI behaviour
   No external dependencies. No secrets. Progressive enhancement only:
   every page is fully readable with JS disabled.
   ========================================================================== */
(function () {
  "use strict";

  /* ---------- Theme (persisted, respects system default) ---------- */
  var STORAGE_KEY = "agroai-platform-theme";
  var root = document.documentElement;

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") {
      root.setAttribute("data-theme", theme);
    } else {
      root.removeAttribute("data-theme");
    }
  }

  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved) applyTheme(saved);
  } catch (e) {
    /* storage unavailable — fall back to system preference */
  }

  function currentTheme() {
    var attr = root.getAttribute("data-theme");
    if (attr) return attr;
    return window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function initThemeToggle() {
    var btn = document.querySelector(".theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) {
        /* ignore */
      }
      btn.setAttribute(
        "aria-label",
        next === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
    });
  }

  /* ---------- Mobile nav ---------- */
  function initNav() {
    var toggle = document.querySelector(".nav-toggle");
    var nav = document.querySelector(".nav");
    if (!toggle || !nav) return;
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.closest("a")) {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  /* ---------- Copy-to-clipboard for code blocks ---------- */
  function initCopy() {
    document.querySelectorAll(".code").forEach(function (block) {
      var head = block.querySelector(".code-head");
      var pre = block.querySelector("pre");
      if (!pre) return;
      var btn = block.querySelector(".code-copy");
      if (!btn) {
        btn = document.createElement("button");
        btn.className = "code-copy";
        btn.type = "button";
        btn.textContent = "Copy";
        if (head) head.appendChild(btn);
        else block.insertBefore(btn, pre);
      }
      btn.addEventListener("click", function () {
        var text = pre.innerText;
        var done = function () {
          var prev = btn.textContent;
          btn.textContent = "Copied";
          setTimeout(function () {
            btn.textContent = prev;
          }, 1400);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, fallback);
        } else {
          fallback();
        }
        function fallback() {
          var ta = document.createElement("textarea");
          ta.value = text;
          ta.setAttribute("readonly", "");
          ta.style.position = "absolute";
          ta.style.left = "-9999px";
          document.body.appendChild(ta);
          ta.select();
          try {
            document.execCommand("copy");
            done();
          } catch (e) {
            /* ignore */
          }
          document.body.removeChild(ta);
        }
      });
    });
  }

  /* ---------- Lightweight syntax highlighting ----------
     Deliberately small + safe: escapes text first, then tokenises.
     Supports the languages we actually show (bash, json, http, js, py). */
  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function highlight(code, lang) {
    var src = escapeHtml(code);
    if (lang === "json" || lang === "http") {
      src = src
        .replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)/g,
          '<span class="tok-prop">$1</span>$2')
        .replace(/(:\s*)(&quot;(?:[^&]|&(?!quot;))*?&quot;)/g,
          '$1<span class="tok-str">$2</span>')
        .replace(/\b(-?\d+\.?\d*)\b/g, '<span class="tok-num">$1</span>')
        .replace(/\b(true|false|null)\b/g, '<span class="tok-key">$1</span>')
        .replace(/^(GET|POST|PUT|PATCH|DELETE)\b/gm,
          '<span class="tok-key">$1</span>');
    } else if (lang === "bash" || lang === "sh" || lang === "shell") {
      src = src
        .replace(/(#.*)$/gm, '<span class="tok-com">$1</span>')
        .replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g,
          '<span class="tok-str">$1</span>')
        .replace(/\b(curl|export|npm|pip|node|python|echo)\b/g,
          '<span class="tok-key">$1</span>')
        .replace(/(\s)(-{1,2}[a-zA-Z][\w-]*)/g,
          '$1<span class="tok-num">$2</span>');
    } else if (lang === "python" || lang === "py") {
      src = src
        .replace(/(#.*)$/gm, '<span class="tok-com">$1</span>')
        .replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g,
          '<span class="tok-str">$1</span>')
        .replace(
          /\b(import|from|def|return|for|in|if|else|with|as|class|print)\b/g,
          '<span class="tok-key">$1</span>'
        );
    } else if (lang === "javascript" || lang === "js") {
      src = src
        .replace(/(\/\/.*)$/gm, '<span class="tok-com">$1</span>')
        .replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;|`[^`]*?`)/g,
          '<span class="tok-str">$1</span>')
        .replace(
          /\b(const|let|var|function|return|await|async|for|of|if|else|new|import|from|export)\b/g,
          '<span class="tok-key">$1</span>'
        );
    }
    return src;
  }

  function initHighlight() {
    document.querySelectorAll("pre code[data-lang]").forEach(function (el) {
      if (el.dataset.highlighted) return;
      var lang = el.getAttribute("data-lang");
      el.innerHTML = highlight(el.textContent, lang);
      el.dataset.highlighted = "1";
    });
  }

  /* ---------- Heading anchors + TOC scroll-spy (docs) ---------- */
  function initDocsEnhancements() {
    var content = document.querySelector(".docs-content");
    if (!content) return;

    content.querySelectorAll("h2[id], h3[id]").forEach(function (h) {
      if (h.querySelector(".anchor")) return;
      var a = document.createElement("a");
      a.className = "anchor";
      a.href = "#" + h.id;
      a.textContent = "#";
      a.setAttribute("aria-label", "Link to this section");
      h.appendChild(a);
    });

    var links = Array.prototype.slice.call(
      document.querySelectorAll(".toc a[href^='#']")
    );
    if (!links.length || !("IntersectionObserver" in window)) return;
    var map = {};
    links.forEach(function (l) {
      map[l.getAttribute("href").slice(1)] = l;
    });
    var visible = new Set();
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        });
        links.forEach(function (l) {
          l.classList.remove("active");
        });
        var first = content.querySelector("h2[id], h3[id]");
        for (var i = 0; i < links.length; i++) {
          var id = links[i].getAttribute("href").slice(1);
          if (visible.has(id)) {
            links[i].classList.add("active");
            return;
          }
        }
        if (first && map[first.id]) map[first.id].classList.add("active");
      },
      { rootMargin: "-70px 0px -70% 0px", threshold: 0 }
    );
    content.querySelectorAll("h2[id], h3[id]").forEach(function (h) {
      observer.observe(h);
    });
  }

  /* ---------- Tabbed panels (e.g. language samples) ---------- */
  function initTabs() {
    document.querySelectorAll("[data-tabs]").forEach(function (group) {
      var tabs = Array.prototype.slice.call(
        group.querySelectorAll("[role='tab']")
      );
      var panels = Array.prototype.slice.call(
        group.querySelectorAll("[role='tabpanel']")
      );
      if (!tabs.length) return;
      function select(idx) {
        tabs.forEach(function (t, i) {
          var on = i === idx;
          t.setAttribute("aria-selected", on ? "true" : "false");
          t.tabIndex = on ? 0 : -1;
        });
        panels.forEach(function (p, i) {
          p.hidden = i !== idx;
        });
      }
      tabs.forEach(function (tab, i) {
        tab.addEventListener("click", function () {
          select(i);
        });
        tab.addEventListener("keydown", function (e) {
          var n = null;
          if (e.key === "ArrowRight") n = (i + 1) % tabs.length;
          else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length;
          if (n !== null) {
            e.preventDefault();
            tabs[n].focus();
            select(n);
          }
        });
      });
      select(0);
    });
  }

  /* ---------- Year stamp ---------- */
  function initYear() {
    document.querySelectorAll("[data-year]").forEach(function (el) {
      el.textContent = String(new Date().getFullYear());
    });
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    initThemeToggle();
    initNav();
    initHighlight();
    initCopy();
    initTabs();
    initDocsEnhancements();
    initYear();
  });

  /* Re-process content injected at runtime (reference, explorer). */
  document.addEventListener("agroai:content-updated", function () {
    initHighlight();
    initCopy();
    initTabs();
  });
})();
