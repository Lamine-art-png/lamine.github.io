(() => {
  "use strict";

  const intentConfig = {
    operations: {
      title: "Open a verified AGRO-AI workspace.",
      copy: "Create an organization account, enter the Enterprise Portal, and start with Command Center so priorities, decisions, tasks, and follow-through stay in one operating loop.",
      cta: "Create your account",
      href: "https://app.agroai-pilot.com/?mode=register",
      secondary: "Need procurement or enterprise rollout? Book a demo.",
      secondaryHref: "/book-a-demo"
    },
    field: {
      title: "Start from what is happening in the field.",
      copy: "Create a verified Portal account and use Field Intelligence to bring field observations, media, voice context, documents, and issue signals into the same operating environment.",
      cta: "Start with Field Intelligence",
      href: "https://app.agroai-pilot.com/?mode=register",
      secondary: "See the Enterprise Portal guide.",
      secondaryHref: "/guides/enterprise-portal/"
    },
    water: {
      title: "Make water decisions with the surrounding operation in view.",
      copy: "Bring irrigation context, field conditions, recommendations, scheduling visibility, and verification together without asking the operation to replace the infrastructure already in place.",
      cta: "Start with WaterOps",
      href: "https://app.agroai-pilot.com/?mode=register",
      secondary: "Planning a larger water deployment? Book a demo.",
      secondaryHref: "/book-a-demo"
    },
    evidence: {
      title: "Turn operational claims into traceable records.",
      copy: "Use Assurance, Evidence, and Reports to organize requirements, review gaps, preserve provenance, and keep proof connected to the work that produced it.",
      cta: "Start with Assurance",
      href: "https://app.agroai-pilot.com/?mode=register",
      secondary: "Review AGRO-AI data governance.",
      secondaryHref: "/trust/data-governance"
    },
    api: {
      title: "Put AGRO-AI inside your product.",
      copy: "Create a verified developer organization and enter the Platform API experience for projects, service accounts, keys, developer tooling, usage controls, and agricultural intelligence APIs.",
      cta: "Create a developer account",
      href: "https://platform.agroai-pilot.com/?mode=register",
      secondary: "Explore the Platform API first.",
      secondaryHref: "/platform-api/"
    }
  };

  const portalConfig = {
    command: {
      kicker: "Command Center",
      title: "Put the next important decision in front of the team.",
      copy: "Bring operational priorities, recommendations, tasks, field context, evidence gaps, and follow-through into one place so work does not disappear between systems.",
      flow: ["Signals", "Priority", "Decision", "Follow-through"]
    },
    field: {
      kicker: "Field Intelligence",
      title: "Let the field enter the operating picture while the work is happening.",
      copy: "Capture observations, media, voice context, files, and location-aware field signals so the rest of the organization can work from fresher context instead of delayed summaries.",
      flow: ["Observe", "Capture", "Interpret", "Act"]
    },
    assurance: {
      kicker: "Assurance",
      title: "Make readiness, review, and proof part of the workflow.",
      copy: "Organize requirements, evidence gaps, review, field follow-up, and proof packages around the operational work instead of reconstructing the story after the fact.",
      flow: ["Requirement", "Evidence", "Review", "Proof"]
    },
    evidence: {
      kicker: "Evidence",
      title: "Keep important decisions attached to the records that support them.",
      copy: "Preserve source context, provenance, uploads, field capture, and connected records so operational claims can be reviewed without relying on memory or scattered screenshots.",
      flow: ["Source", "Context", "Record", "Trace"]
    },
    reports: {
      kicker: "Reports",
      title: "Turn operating context into something leadership can actually use.",
      copy: "Bring decisions, execution visibility, evidence, and exceptions into management and compliance-support reporting without rebuilding the same story across disconnected files.",
      flow: ["Operation", "Evidence", "Exception", "Report"]
    },
    connectors: {
      kicker: "Connectors",
      title: "Use the systems already installed across the operation.",
      copy: "Bring customer-authorized machinery, irrigation, cloud files, documents, water data, and partner systems into the AGRO-AI operating layer rather than forcing a rip-and-replace.",
      flow: ["Authorize", "Connect", "Normalize", "Use"]
    },
    ask: {
      kicker: "Ask AGRO-AI",
      title: "Move from searching through systems to asking the operation.",
      copy: "Use conversational access to operational context, reports, evidence, reasoning, and workflow actions while preserving organization boundaries and human review where required.",
      flow: ["Ask", "Context", "Reason", "Action"]
    }
  };

  const header = document.querySelector("[data-site-header]");
  const mobileToggle = document.querySelector("[data-mobile-toggle]");
  const primaryNav = document.querySelector("[data-primary-nav]");

  const setMenu = (open) => {
    if (!(mobileToggle instanceof HTMLButtonElement) || !(primaryNav instanceof HTMLElement)) return;
    mobileToggle.setAttribute("aria-expanded", String(open));
    primaryNav.classList.toggle("is-open", open);
    document.body.classList.toggle("no-scroll", open && window.innerWidth <= 900);
  };

  mobileToggle?.addEventListener("click", () => {
    setMenu(mobileToggle.getAttribute("aria-expanded") !== "true");
  });

  primaryNav?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setMenu(false));
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) setMenu(false);
  });

  const syncHeader = () => {
    header?.classList.toggle("is-scrolled", window.scrollY > 18);
  };
  syncHeader();
  window.addEventListener("scroll", syncHeader, { passive: true });

  const applyIntent = (key, focus = false) => {
    const config = intentConfig[key];
    if (!config) return;

    document.querySelectorAll("[data-intent]").forEach((node) => {
      node.classList.toggle("is-active", node.getAttribute("data-intent") === key);
    });

    const title = document.querySelector("[data-intent-title]");
    const copy = document.querySelector("[data-intent-copy]");
    const cta = document.querySelector("[data-intent-cta]");
    const secondary = document.querySelector("[data-intent-secondary]");

    if (title) title.textContent = config.title;
    if (copy) copy.textContent = config.copy;
    if (cta instanceof HTMLAnchorElement) {
      cta.textContent = config.cta + " ↗";
      cta.href = config.href;
      cta.dataset.intentSelected = key;
    }
    if (secondary instanceof HTMLAnchorElement) {
      secondary.textContent = config.secondary;
      secondary.href = config.secondaryHref;
    }
    if (focus) document.querySelector("[data-intent-panel]")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  document.querySelectorAll("[data-intent]").forEach((button) => {
    button.addEventListener("click", () => applyIntent(button.getAttribute("data-intent") || "operations"));
  });

  document.querySelectorAll("[data-intent-jump]").forEach((link) => {
    link.addEventListener("click", () => {
      const key = link.getAttribute("data-intent-jump") || "operations";
      window.setTimeout(() => applyIntent(key, window.innerWidth < 760), 120);
    });
  });

  const renderFlow = (items) => {
    const flow = document.querySelector("[data-portal-flow]");
    if (!flow) return;
    flow.replaceChildren();
    items.forEach((item, index) => {
      const span = document.createElement("span");
      span.textContent = item;
      flow.appendChild(span);
      if (index < items.length - 1) {
        const arrow = document.createElement("b");
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "→";
        flow.appendChild(arrow);
      }
    });
  };

  const applyPortal = (key) => {
    const config = portalConfig[key];
    if (!config) return;
    document.querySelectorAll("[data-portal-tab]").forEach((node) => {
      node.classList.toggle("is-active", node.getAttribute("data-portal-tab") === key);
    });
    const kicker = document.querySelector("[data-portal-kicker]");
    const title = document.querySelector("[data-portal-title]");
    const copy = document.querySelector("[data-portal-copy]");
    if (kicker) kicker.textContent = config.kicker;
    if (title) title.textContent = config.title;
    if (copy) copy.textContent = config.copy;
    renderFlow(config.flow);
  };

  document.querySelectorAll("[data-portal-tab]").forEach((button) => {
    button.addEventListener("click", () => applyPortal(button.getAttribute("data-portal-tab") || "command"));
  });

  const conversionBar = document.querySelector("[data-mobile-conversion]");
  const heroStart = document.querySelector('[data-conversion="hero-start"]');

  if ("IntersectionObserver" in window && conversionBar && heroStart) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.some((entry) => entry.isIntersecting);
      conversionBar.toggleAttribute("data-hero-visible", visible);
    }, { threshold: 0.15 });
    observer.observe(heroStart);
  }
})();