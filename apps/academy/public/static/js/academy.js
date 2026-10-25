// AGRO-AI Academy progressive enhancement. Every feature here layers on top of
// server-rendered HTML that already works without JavaScript.
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const csrf = () => $('meta[name="csrf-token"]')?.content || "";
  const store = {
    get(k, d) {
      try {
        const v = localStorage.getItem(k);
        return v == null ? d : JSON.parse(v);
      } catch {
        return d;
      }
    },
    set(k, v) {
      try {
        localStorage.setItem(k, JSON.stringify(v));
      } catch {
        /* storage unavailable: features degrade gracefully */
      }
    },
  };

  function toast(msg) {
    const el = $("[data-toast]");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => (el.hidden = true), 2600);
  }

  async function post(url, data, { json = true, keepalive = false } = {}) {
    const body = json ? JSON.stringify(data) : data;
    const res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      keepalive,
      headers: { Accept: "application/json", "X-CSRF-Token": csrf(), ...(json ? { "Content-Type": "application/json" } : { "Content-Type": "application/x-www-form-urlencoded" }) },
      body,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json().catch(() => ({}));
  }

  // ───── Generic behaviors ─────
  // The brand typeface loads without blocking the first paint (it comes from a
  // font CDN); system fonts show until it arrives, or if it never does.
  $$("link[data-brand-font]").forEach((l) => {
    const use = () => (l.media = "all");
    if (l.sheet) use();
    else l.addEventListener("load", use, { once: true });
  });
  $$("form[data-autosubmit] select").forEach((s) => s.addEventListener("change", () => s.form.submit()));
  $$("[data-autosubmit-change]").forEach((el) => {
    const form = el.tagName === "FORM" ? el : el.form;
    el.addEventListener("change", () => form && form.submit());
  });
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const trigger = e.submitter;
    const msg = trigger?.dataset.confirm || form.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });
  $$("[data-theme-toggle]").forEach((btn) =>
    btn.form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const theme = btn.form.theme.value;
      document.documentElement.dataset.theme = theme;
      btn.form.theme.value = theme === "dark" ? "light" : "dark";
      try {
        await post("/preferences/theme", new URLSearchParams({ theme, _csrf: csrf() }).toString(), { json: false });
      } catch {
        /* the cookie update will be retried on the next toggle */
      }
    }),
  );
  $$("[data-copy]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(b.dataset.copy);
        toast(b.dataset.copied || "Copied");
      } catch {
        prompt("", b.dataset.copy);
      }
    }),
  );
  $$("[data-share]").forEach((b) => {
    if (!navigator.share) return;
    b.hidden = false;
    b.addEventListener("click", () => navigator.share({ title: b.dataset.shareTitle, text: b.dataset.shareText, url: b.dataset.shareUrl }).catch(() => {}));
  });
  $$("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));
  // Close open menus when clicking elsewhere or pressing Escape.
  document.addEventListener("click", (e) => $$("details.account-menu[open], details.mobile-nav[open]").forEach((d) => !d.contains(e.target) && d.removeAttribute("open")));
  document.addEventListener("keydown", (e) => e.key === "Escape" && $$("details.account-menu[open], details.mobile-nav[open]").forEach((d) => d.removeAttribute("open")));

  // ───── Offline-tolerant progress queue ─────
  const QUEUE = "aca_progress_queue_v1";
  async function flushQueue() {
    const q = store.get(QUEUE, []);
    if (!q.length || !navigator.onLine) return;
    try {
      await post("/api/progress", { reports: q.slice(0, 50) });
      store.set(QUEUE, q.slice(50));
    } catch {
      /* keep the queue for the next attempt */
    }
  }
  function sendProgress(report, { keepalive = false } = {}) {
    const r = { ...report, clientAt: new Date().toISOString() };
    return post("/api/progress", r, { keepalive }).catch(() => {
      const q = store.get(QUEUE, []).filter((x) => !(x.lessonId === r.lessonId && !x.complete));
      q.push(r);
      store.set(QUEUE, q.slice(-200));
    });
  }
  const pill = $("[data-offline]");
  if (pill) pill.hidden = navigator.onLine;
  addEventListener("online", () => {
    if (pill) pill.hidden = true;
    flushQueue();
  });
  addEventListener("offline", () => pill && (pill.hidden = false));
  flushQueue();

  // ───── Header fit ─────
  // Labels differ in length between languages, so the header switches to the
  // compact menu when its row actually overflows, not at a fixed width.
  const header = $(".site-header");
  const row = header && $(".header-row", header);
  if (row) {
    const fit = () => {
      header.classList.remove("nav-compact", "tools-compact");
      if (row.scrollWidth > row.clientWidth + 1) header.classList.add("nav-compact");
      if (row.scrollWidth > row.clientWidth + 1) header.classList.add("tools-compact");
    };
    let frame = 0;
    addEventListener("resize", () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    });
    document.fonts?.ready.then(fit);
    fit();
  }

  // ───── Classroom ─────
  const root = $("[data-lesson-root]");
  if (root) {
    const lessonId = root.dataset.lessonId;
    const tracking = root.dataset.track === "1";
    const sidebar = $("[data-sidebar]");
    const toggle = $("[data-sidebar-toggle]");
    let scrim;
    const setSidebar = (open) => {
      sidebar.classList.toggle("open", open);
      toggle?.setAttribute("aria-expanded", String(open));
      if (open) {
        scrim = document.createElement("div");
        scrim.className = "scrim";
        scrim.addEventListener("click", () => setSidebar(false));
        document.body.appendChild(scrim);
        sidebar.querySelector("a[aria-current]")?.focus();
      } else scrim?.remove();
    };
    toggle?.addEventListener("click", () => setSidebar(!sidebar.classList.contains("open")));
    document.addEventListener("keydown", (e) => e.key === "Escape" && sidebar?.classList.contains("open") && setSidebar(false));

    // Tabs
    const tabs = $$('[role="tab"]');
    const select = (tab) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        const panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const dir = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (!dir) return;
        const next = tabs[(i + (document.dir === "rtl" ? -dir : dir) + tabs.length) % tabs.length];
        select(next);
        next.focus();
      });
    });
    const hashTab = tabs.find((t) => `#${t.getAttribute("aria-controls")}` === location.hash);
    if (hashTab) select(hashTab);

    // Video player
    const player = $("[data-player]");
    // Protected lessons play in Cloudflare Stream's player; its SDK exposes the
    // same properties and events as a <video> element, so the heartbeat,
    // resume, speed and bookmark code below drives either.
    const frame = player?.querySelector("iframe");
    const video = player?.querySelector("video") || (frame && typeof window.Stream === "function" ? window.Stream(frame) : null);
    if (frame && !video) $("[data-video-error]").hidden = false;
    const now = () => (video ? video.currentTime : 0);
    if (frame && video) {
      // Playback tokens are short-lived. When one has expired (a long pause, a
      // tab left open), fetch a fresh one and continue from the same moment.
      let renewing = false;
      video.addEventListener("error", async () => {
        if (renewing) return;
        // Not an expiry: tell the learner, who can continue with the lesson text.
        if (Date.parse(player.dataset.expires) - Date.now() > 60_000) return void ($("[data-video-error]").hidden = false);
        renewing = true;
        try {
          const out = await post("/api/video-token", { lessonId: player.dataset.lesson });
          const at = Math.floor(video.currentTime || 0);
          player.dataset.expires = out.expiresAt;
          frame.src = `${out.url}${at > 0 ? `&startTime=${at}s` : ""}`;
          $("[data-video-error]").hidden = true;
        } catch {
          $("[data-video-error]").hidden = false;
        } finally {
          renewing = false;
        }
      });
    }
    if (video) {
      const start = Number(player.dataset.start) || 0;
      // Position before the current seek; the resume jump starts from the saved position, not 0.
      let before = 0;
      const resume = () => {
        if (start > 5 && start < video.duration - 5) video.currentTime = before = start;
      };
      // Cached media can load its metadata before this script runs (e.g. on reload).
      if (video.readyState >= 1) resume();
      else video.addEventListener("loadedmetadata", resume, { once: true });
      if (!frame) video.addEventListener("error", () => ($("[data-video-error]").hidden = false), true);
      $("[data-speed]")?.addEventListener("change", (e) => (video.playbackRate = Number(e.target.value)));
      const captions = () => {
        const tracks = [...(video.textTracks || [])];
        if (!tracks.length) return;
        const on = tracks.some((t) => t.mode === "showing");
        tracks.forEach((t, i) => (t.mode = !on && i === 0 ? "showing" : "disabled"));
      };
      $("[data-captions-toggle]")?.addEventListener("click", captions);
      const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : (player.requestFullscreen || video.webkitEnterFullscreen)?.call(player.requestFullscreen ? player : video));
      $("[data-fullscreen]")?.addEventListener("click", fullscreen);
      document.addEventListener("keydown", (e) => {
        if (e.target.closest("input, textarea, select, button, [contenteditable]") || e.ctrlKey || e.metaKey || e.altKey) return;
        const k = e.key.toLowerCase();
        const acts = {
          k: () => (video.paused ? video.play() : video.pause()),
          " ": () => (video.paused ? video.play() : video.pause()),
          j: () => (video.currentTime -= 10),
          l: () => (video.currentTime += 10),
          arrowleft: () => (video.currentTime -= 5),
          arrowright: () => (video.currentTime += 5),
          f: fullscreen,
          c: captions,
          m: () => (video.muted = !video.muted),
        };
        if (acts[k]) {
          e.preventDefault();
          acts[k]();
        }
      });
      if (tracking) {
        // Heartbeats: the server times them and credits only playback that
        // was possible between two beats, so beats go out every few seconds
        // while playing and at every play, pause, seek and end.
        let last = 0;
        const report = (playing, position = video.currentTime, opts) => {
          last = Date.now();
          return sendProgress({ lessonId, position, duration: video.duration || null, playing }, opts);
        };
        video.addEventListener("timeupdate", () => {
          if (!video.seeking) before = video.currentTime;
          if (Date.now() - last > 5000 && !video.paused) report(true);
        });
        video.addEventListener("play", () => report(true));
        video.addEventListener("pause", () => report(false));
        video.addEventListener("seeking", () => report(false, before));
        // After a seek, a playing heartbeat restarts the run. A paused state here
        // may be stale (play() pending); the "play" event reports that case.
        video.addEventListener("seeked", () => !video.paused && report(true));
        video.addEventListener("ended", () => report(false));
        addEventListener("pagehide", () => report(false, video.currentTime, { keepalive: true }));
      }
      $$("[data-seek]").forEach((b) => b.addEventListener("click", () => ((video.currentTime = Number(b.dataset.seek)), video.play())));
    }
    if (tracking && !video) {
      // Text lessons: remember reading position (completion is explicit).
      let maxScroll = 0;
      addEventListener("scroll", () => {
        const h = document.documentElement.scrollHeight - innerHeight;
        if (h > 0) maxScroll = Math.max(maxScroll, Math.round((scrollY / h) * 100));
      }, { passive: true });
      sendProgress({ lessonId, position: 0, scroll: 0 });
      addEventListener("pagehide", () => maxScroll && sendProgress({ lessonId, position: 0, scroll: maxScroll }, { keepalive: true }));
    }

    // Notes and bookmarks without page reloads
    const noteForm = $("[data-note-form]");
    noteForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (video) noteForm.querySelector("[data-note-position]").value = Math.floor(now());
      try {
        const out = await post(noteForm.action, new URLSearchParams(new FormData(noteForm)).toString(), { json: false });
        const list = $("[data-notes-list]");
        list.querySelector("[data-empty]")?.remove();
        list.insertAdjacentHTML("afterbegin", out.html);
        noteForm.reset();
        toast("✓");
      } catch {
        noteForm.submit();
      }
    });
    $("[data-notes-list]")?.addEventListener("submit", async (e) => {
      if (!e.target.matches("[data-note-delete]") || e.defaultPrevented) return;
      e.preventDefault();
      try {
        await post(e.target.action, new URLSearchParams(new FormData(e.target)).toString(), { json: false });
        e.target.closest("[data-note]").remove();
      } catch {
        e.target.submit();
      }
    });
    const bmForm = $("[data-bookmark-form]");
    const addBookmark = async () => {
      bmForm.querySelector("[data-bookmark-position]").value = Math.floor(now());
      try {
        const out = await post(bmForm.action, new URLSearchParams(new FormData(bmForm)).toString(), { json: false });
        const li = document.createElement("li");
        const b = document.createElement("button");
        b.type = "button";
        b.className = "link-btn";
        b.textContent = out.time;
        b.addEventListener("click", () => video && ((video.currentTime = out.position), video.play()));
        li.append(b, ` ${out.label}`);
        $("[data-bookmarks-list]").append(li);
        bmForm.reset();
        toast("✓");
      } catch {
        bmForm.submit();
      }
    };
    bmForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      addBookmark();
    });
    $("[data-bookmark-add]")?.addEventListener("click", addBookmark);

    // Local-only checklists
    $$("[data-local-check]").forEach((cb) => {
      const key = `aca_check_${cb.dataset.localCheck}`;
      cb.checked = store.get(key, false);
      cb.addEventListener("change", () => store.set(key, cb.checked));
    });
  }

  // ───── Exams ─────
  const exam = $("[data-exam]");
  if (exam) {
    const form = $("[data-exam-form]");
    const attemptId = exam.dataset.attempt;
    const state = $("[data-save-state]");
    const answered = $("[data-answered]");
    const questions = $$("[data-question]", form);
    let dirty = false;
    let timer;
    let saving = false;

    const isAnswered = (q) =>
      [...q.querySelectorAll("input[type=radio], input[type=checkbox]")].some((i) => i.checked) ||
      [...q.querySelectorAll("textarea")].some((t) => t.value.trim()) ||
      [...q.querySelectorAll(".match-row select")].some((s) => s.value) ||
      q.querySelector("[data-order-list]") !== null;
    const count = () => (answered.textContent = questions.filter(isAnswered).length);
    count();

    const serialize = () => {
      const fd = new FormData(form);
      fd.delete("_csrf");
      return new URLSearchParams(fd).toString();
    };
    async function save() {
      if (saving || !dirty) return;
      saving = true;
      dirty = false;
      state.textContent = state.dataset.saving || "…";
      try {
        await post(`/api/attempts/${attemptId}/save`, serialize(), { json: false });
        state.textContent = `✓ ${new Date().toLocaleTimeString(document.documentElement.lang, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
      } catch {
        dirty = true;
        state.textContent = "⚠︎";
      } finally {
        saving = false;
      }
    }
    form.addEventListener("change", (e) => {
      // Ordering: choosing a position swaps with the item that held it.
      const sel = e.target.closest("[data-order-list] select");
      if (sel) {
        const list = sel.closest("[data-order-list]");
        const selects = $$("select", list);
        const want = sel.value;
        const old = String(selects.indexOf(sel) + 1);
        selects.forEach((s) => s !== sel && s.value === want && (s.value = old));
        const items = $$("li", list).sort((a, b) => Number($("select", a).value) - Number($("select", b).value));
        items.forEach((li) => list.appendChild(li));
        sel.focus();
      }
      dirty = true;
      count();
      clearTimeout(timer);
      timer = setTimeout(save, 1200);
    });
    form.addEventListener("input", (e) => {
      if (e.target.tagName !== "TEXTAREA") return;
      dirty = true;
      count();
      clearTimeout(timer);
      timer = setTimeout(save, 2500);
    });
    setInterval(save, 20000);
    form.addEventListener("submit", () => {
      clearTimeout(timer);
      dirty = false;
    });
    addEventListener("pagehide", () => dirty && post(`/api/attempts/${attemptId}/save`, serialize(), { json: false, keepalive: true }).catch(() => {}));

    const deadline = exam.dataset.deadline ? Date.parse(exam.dataset.deadline) : null;
    if (deadline) {
      const skew = exam.dataset.serverNow ? Date.parse(exam.dataset.serverNow) - Date.now() : 0;
      const box = $("[data-timer]");
      const text = $("[data-timer-text]");
      let submitted = false;
      const tick = () => {
        const left = Math.max(0, Math.floor((deadline - (Date.now() + skew)) / 1000));
        const h = Math.floor(left / 3600);
        const m = Math.floor((left % 3600) / 60);
        const s = left % 60;
        text.textContent = `${h ? `${h}:` : ""}${String(m).padStart(h ? 2 : 1, "0")}:${String(s).padStart(2, "0")}`;
        box.classList.toggle("low", left <= 120);
        if (left === 300 || left === 60) box.setAttribute("aria-live", "assertive");
        if (left <= 0 && !submitted) {
          submitted = true;
          form.querySelectorAll("[data-confirm]").forEach((b) => delete b.dataset.confirm);
          form.requestSubmit ? form.requestSubmit() : form.submit();
        }
      };
      tick();
      setInterval(tick, 1000);
    }
  }
})();
