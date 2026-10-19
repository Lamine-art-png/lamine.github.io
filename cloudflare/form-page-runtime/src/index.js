const MARKETING_ORIGIN = "https://agroai-343.pages.dev";
const RUNTIME_PATH = "/agroai-forms-runtime.js";

const runtimeSource = String.raw`(() => {
  if (window.__AGROAI_FORMS_RUNTIME__) return;
  window.__AGROAI_FORMS_RUNTIME__ = true;

  const normalizedPath = window.location.pathname.replace(/\/+$/, "") || "/";
  const isCareers =
    normalizedPath === "/careers" ||
    normalizedPath.startsWith("/careers/") ||
    normalizedPath === "/apply" ||
    normalizedPath.startsWith("/apply/");
  const isDemo = normalizedPath === "/book-a-demo" || normalizedPath.startsWith("/book-a-demo/");
  if (!isCareers && !isDemo) return;

  const clean = (value) => String(value == null ? "" : value).trim();
  const validEmail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean(value));

  const fieldValue = (field) => {
    if (!field) return "";
    if (field instanceof RadioNodeList) return clean(field.value);
    if (field instanceof HTMLInputElement && field.type === "checkbox") {
      return field.checked ? clean(field.value || "yes") : "";
    }
    if (field instanceof HTMLInputElement && field.type === "radio") {
      return field.checked ? clean(field.value) : "";
    }
    return clean(field.value);
  };

  const fieldByKey = (form, key) => {
    const named = form.elements.namedItem(key);
    if (named) return named;
    for (const field of form.querySelectorAll("input,textarea,select")) {
      if (field.id === key) return field;
    }
    return null;
  };

  const value = (form, keys) => {
    for (const key of keys) {
      const candidate = fieldValue(fieldByKey(form, key));
      if (candidate) return candidate;
    }
    return "";
  };

  const selectorValue = (form, selector) => fieldValue(form.querySelector(selector));

  const firstTextValue = (form) => {
    const fields = form.querySelectorAll(
      'input:not([type]), input[type="text"], input[type="search"], textarea',
    );
    for (const field of fields) {
      const candidate = fieldValue(field);
      if (candidate) return candidate;
    }
    return "";
  };

  const collectFields = (form) => {
    const output = {};
    const fields = form.querySelectorAll("input,textarea,select");
    fields.forEach((field, index) => {
      if (
        field instanceof HTMLInputElement &&
        (field.type === "submit" || field.type === "button" || field.type === "reset" || field.type === "file")
      ) {
        return;
      }
      if (
        field instanceof HTMLInputElement &&
        (field.type === "checkbox" || field.type === "radio") &&
        !field.checked
      ) {
        return;
      }
      const key = clean(field.name || field.id || ("field_" + (index + 1)));
      const next = fieldValue(field);
      if (!key || !next) return;
      output[key] = output[key] ? output[key] + "; " + next : next;
    });
    return output;
  };

  const setBusy = (form, busy) => {
    const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach((button) => {
      button.disabled = busy;
      if (button instanceof HTMLButtonElement) {
        if (!button.dataset.agroaiOriginalText) {
          button.dataset.agroaiOriginalText = button.textContent || "Submit";
        }
        button.textContent = busy ? "Submitting..." : button.dataset.agroaiOriginalText;
      }
    });
  };

  const statusNode = (form) => {
    let node = form.querySelector('[data-agroai-form-status]');
    if (!node) {
      node = document.createElement("div");
      node.setAttribute("data-agroai-form-status", "true");
      node.setAttribute("role", "status");
      node.style.marginTop = "16px";
      node.style.padding = "14px 16px";
      node.style.borderRadius = "12px";
      node.style.fontSize = "14px";
      node.style.lineHeight = "1.5";
      node.style.display = "none";
      form.appendChild(node);
    }
    return node;
  };

  const showStatus = (form, message, ok) => {
    const node = statusNode(form);
    node.textContent = message;
    node.style.display = "block";
    node.style.border = ok ? "1px solid #86efac" : "1px solid #fca5a5";
    node.style.background = ok ? "#f0fdf4" : "#fef2f2";
    node.style.color = ok ? "#14532d" : "#991b1b";
  };

  const showSuccess = (form, heading, detail) => {
    const wrapper = document.createElement("section");
    wrapper.setAttribute("data-agroai-form-success", "true");
    wrapper.style.padding = "32px";
    wrapper.style.border = "1px solid #bbf7d0";
    wrapper.style.borderRadius = "20px";
    wrapper.style.background = "#f0fdf4";
    wrapper.style.textAlign = "center";
    wrapper.innerHTML =
      '<div style="font-size:36px;margin-bottom:12px">✓</div>' +
      '<h2 style="font-size:26px;font-weight:800;color:#14532d;margin:0 0 12px">' +
      heading +
      '</h2>' +
      '<p style="font-size:16px;line-height:1.6;color:#365314;margin:0">' +
      detail +
      '</p>';
    form.replaceWith(wrapper);
    wrapper.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  // The demo lead must be durably accepted before scheduling is offered.
  // Calendly owns availability, meeting creation, invites, and time zones.
  const DEMO_CALENDLY_URL = "https://calendly.com/contact-agroai-pilot/30min";

  const showDemoScheduling = (form, details) => {
    const wrapper = document.createElement("section");
    wrapper.setAttribute("data-agroai-form-success", "true");
    wrapper.setAttribute("data-agroai-demo-scheduling", "true");
    wrapper.style.cssText =
      "padding:24px 16px;border:1px solid #bbf7d0;border-radius:20px;background:#f6fdf7;max-width:100%;box-sizing:border-box";

    const heading = document.createElement("h2");
    heading.textContent = "Demo request received";
    heading.style.cssText = "font-size:26px;line-height:1.2;font-weight:800;color:#14532d;margin:0 0 12px";
    const intro = document.createElement("p");
    intro.textContent = details.notificationPending
      ? "Your demo request is saved. The team email notification is delayed, but you can select your 30-minute meeting now."
      : "Your demo request was saved and the team notification was sent. Choose an available 30-minute slot below to confirm your demo immediately.";
    intro.style.cssText = "font-size:16px;line-height:1.6;color:#365314;margin:0 0 16px";
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = "Step 2 of 2: Select your date and time.";
    status.style.cssText = "font-size:14px;font-weight:700;color:#14532d;margin:0 0 12px";

    const calendar = document.createElement("div");
    calendar.setAttribute("data-agroai-calendar", "true");
    calendar.style.cssText =
      "width:100%;min-width:0;height:730px;min-height:730px;background:#fff;border-radius:12px;overflow:hidden";

    const fallback = document.createElement("p");
    fallback.style.cssText = "font-size:14px;line-height:1.5;text-align:center;margin:12px 0 0";
    const link = document.createElement("a");
    link.href = DEMO_CALENDLY_URL;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Open the booking calendar in a new tab";
    link.style.cssText = "color:#176b45;font-weight:700;text-decoration:underline";
    fallback.appendChild(link);

    wrapper.append(heading, intro, status, fallback, calendar);
    form.replaceWith(wrapper);
    wrapper.scrollIntoView({ behavior: "smooth", block: "start" });

    const onBooking = (event) => {
      if (event.origin !== "https://calendly.com") return;
      if (!event.data || event.data.event !== "calendly.event_scheduled") return;
      status.textContent =
        "Your demo is booked. Please check your inbox for the calendar invitation and meeting details.";
      wrapper.setAttribute("data-agroai-demo-booked", "true");
      window.removeEventListener("message", onBooking);
    };
    window.addEventListener("message", onBooking);

    const startCalendar = () => {
      if (!window.Calendly || typeof window.Calendly.initInlineWidget !== "function") {
        status.textContent = "The calendar could not load here. Use the booking link above.";
        return;
      }
      try {
        window.Calendly.initInlineWidget({
          url: DEMO_CALENDLY_URL,
          parentElement: calendar,
          prefill: {
            name: clean(details.fullName).slice(0, 180),
            email: clean(details.email).slice(0, 240),
          },
          utm: {
            utmSource: "agroai-website",
            utmMedium: "demo-form",
            utmCampaign: "instant-demo-booking",
            utmContent: clean(details.requestId).slice(0, 100),
          },
        });
      } catch {
        status.textContent = "The calendar could not load here. Use the booking link above.";
      }
    };

    if (window.Calendly && typeof window.Calendly.initInlineWidget === "function") {
      startCalendar();
    } else {
      const script = document.createElement("script");
      script.src = "https://assets.calendly.com/assets/external/widget.js";
      script.async = true;
      script.onload = startCalendar;
      script.onerror = () => {
        status.textContent = "The calendar could not load here. Use the booking link above.";
      };
      document.head.appendChild(script);
    }
  };

  const parseJson = async (response) => {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { message: text };
    }
  };

  const hasEmailField = (form) =>
    !!form.querySelector(
      'input[type="email"], input[name="email"], input[name="emailAddress"], input[name="email_address"], #email',
    );

  const isTargetForm = (form) => {
    if (!(form instanceof HTMLFormElement) || !hasEmailField(form)) return false;
    if (isDemo) return true;
    return !!form.querySelector(
      'input[type="file"], select[name="role"], [name="whyAgroAi"]',
    );
  };

  // Make the new instant-booking flow visible before visitors submit anything.
  // Qualification and notification remain in the original form; no direct
  // Calendly bypass is offered because it would lose the CRM lead details.
  const ensureDemoBookingSteps = (form) => {
    if (form.querySelector('[data-agroai-booking-steps="true"]')) return;
    const panel = document.createElement("section");
    panel.setAttribute("data-agroai-booking-steps", "true");
    panel.setAttribute("aria-label", "Instant demo booking process");
    panel.style.cssText =
      "box-sizing:border-box;width:100%;margin:0 0 24px;padding:22px 20px;" +
      "border:1px solid #bbdfbd;border-radius:16px;background:#f4faf4;" +
      "color:#153e2a;text-align:left";

    const eyebrow = document.createElement("div");
    eyebrow.textContent = "LIVE CALENDAR BOOKING";
    eyebrow.style.cssText =
      "font-size:11px;font-weight:800;letter-spacing:.12em;color:#26714b;margin-bottom:8px";
    const heading = document.createElement("h2");
    heading.textContent = "Choose your demo time immediately";
    heading.style.cssText =
      "font-size:clamp(19px,2.5vw,24px);font-weight:800;line-height:1.25;" +
      "color:#123b29;margin:0 0 12px";
    const description = document.createElement("p");
    description.textContent =
      "A 30-minute meeting with AGRO-AI, booked directly on this page. No waiting for us to email you available dates.";
    description.style.cssText =
      "margin:0 0 14px;font-size:14px;line-height:1.6;color:#315b43";

    const steps = document.createElement("div");
    steps.style.cssText =
      "display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px";
    for (const [number, title, detail] of [
      ["01", "Tell us about your operation", "Complete the short form below."],
      ["02", "Pick a live calendar slot", "Select your exact date and time immediately after submitting."],
    ]) {
      const item = document.createElement("div");
      item.style.cssText =
        "background:#fff;border:1px solid #dbe9dd;border-radius:11px;padding:12px";
      const strong = document.createElement("strong");
      strong.textContent = number + "  " + title;
      strong.style.cssText = "display:block;font-size:13px;color:#154c31;margin-bottom:4px";
      const sub = document.createElement("span");
      sub.textContent = detail;
      sub.style.cssText = "font-size:12px;line-height:1.5;color:#4b6556";
      item.append(strong, sub);
      steps.appendChild(item);
    }
    panel.append(eyebrow, heading, description, steps);
    form.insertBefore(panel, form.firstChild);
  };

  const prepareForms = () => {
    document.querySelectorAll("form").forEach((form) => {
      if (isTargetForm(form)) {
        form.noValidate = true;
        form.setAttribute("data-agroai-authoritative-form", isDemo ? "demo" : "careers");
        if (isDemo) ensureDemoBookingSteps(form);
      }
    });
  };

  prepareForms();
  const observer = new MutationObserver(prepareForms);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener(
    "submit",
    async (event) => {
      const form = event.target;
      if (!isTargetForm(form)) return;

      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }

      if (form.dataset.agroaiSubmitting === "true") return;
      form.dataset.agroaiSubmitting = "true";
      setBusy(form, true);
      showStatus(form, "Securely submitting your information...", true);

      try {
        if (isCareers) {
          const data = new FormData(form);
          const response = await fetch("/api/apply", {
            method: "POST",
            body: data,
            headers: { "X-AGROAI-Form-Source": "careers-browser-runtime" },
            credentials: "same-origin",
          });
          const result = await parseJson(response);
          if (!response.ok || response.headers.get("x-agroai-notification") !== "delivered") {
            throw new Error(
              clean(result.message || result.error) ||
                "Application delivery could not be confirmed.",
            );
          }
          showSuccess(
            form,
            "Application received",
            "Your application and résumé were received, and the AGRO-AI team notification was confirmed.",
          );
          return;
        }

        const originalFields = collectFields(form);
        const email =
          value(form, ["email", "emailAddress", "email_address", "workEmail"]) ||
          selectorValue(form, 'input[type="email"]');
        const fullName =
          value(form, [
            "fullName",
            "full_name",
            "name",
            "contactName",
            "contact_name",
            "firstName",
          ]) ||
          firstTextValue(form) ||
          "Website demo request";
        const acreageText = value(form, ["acreage", "acres", "farmSize", "farm_size"]);
        const acreageNumber = Number(String(acreageText).replace(/[^0-9.]/g, ""));

        if (!validEmail(email)) {
          throw new Error("Please enter a valid email address.");
        }

        const payload = {
          fullName,
          email,
          phone:
            value(form, ["phone", "phoneNumber", "phone_number"]) ||
            selectorValue(form, 'input[type="tel"]'),
          farmName: value(form, [
            "farmName",
            "farm_name",
            "company",
            "organization",
            "businessName",
            "business_name",
          ]),
          location: value(form, [
            "location",
            "region",
            "city",
            "state",
            "country",
          ]),
          acreage: Number.isFinite(acreageNumber) ? acreageNumber : 0,
          cropTypes: value(form, [
            "cropTypes",
            "crop_types",
            "crops",
            "system",
            "currentSystems",
            "current_systems",
          ]),
          currentIrrigation: value(form, [
            "currentIrrigation",
            "current_irrigation",
            "irrigationSystem",
            "irrigation_system",
            "system",
          ]),
          mainChallenges: value(form, [
            "mainChallenges",
            "main_challenges",
            "primaryGoal",
            "primary_goal",
            "goal",
            "notes",
            "message",
            "challenge",
          ]),
          preferredCallTime: value(form, [
            "preferredCallTime",
            "preferred_call_time",
            "preferredTime",
            "preferred_time",
            "timing",
          ]),
          status: "pending",
          source: "book-a-demo-browser-runtime",
          originalFields,
          runtimeVersion: "2026-08-03.3",
        };

        const response = await fetch("/api/demo-request", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-AGROAI-Form-Source": "book-a-demo-browser-runtime",
          },
          body: JSON.stringify(payload),
          credentials: "same-origin",
        });
        const result = await parseJson(response);
        const notificationState = response.headers.get("x-agroai-notification");
        const requestId = clean(
          result.id || response.headers.get("x-agroai-notification-request-id") || "",
        );
        const saved = response.ok && !!requestId &&
          (notificationState === "delivered" ||
            (notificationState === "pending" &&
              response.headers.get("x-agroai-lead-persisted") === "true" &&
              result.saved === true));
        if (!saved) {
          throw new Error(
            clean(result.message || result.error) ||
              "The demo request could not be confirmed as saved.",
          );
        }
        showDemoScheduling(form, {
          fullName,
          email,
          requestId,
          notificationPending: notificationState === "pending",
        });
      } catch (error) {
        delete form.dataset.agroaiSubmitting;
        setBusy(form, false);
        const message = error instanceof Error ? error.message : "Submission failed.";
        showStatus(
          form,
          message + " Please email contact@agroai-pilot.com if the problem continues.",
          false,
        );
      }
    },
    true,
  );
})();`;

function runtimeResponse() {
  return new Response(runtimeSource, {
    status: 200,
    headers: {
      "content-type": "application/javascript; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-agroai-forms-runtime": "active",
    },
  });
}

function injectRuntime(response) {
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-agroai-forms-runtime", "active");
  return new HTMLRewriter()
    .on("head", {
      element(element) {
        element.append(`<script src="${RUNTIME_PATH}" defer></script>`, { html: true });
      },
    })
    .transform(
      new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      }),
    );
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === RUNTIME_PATH) return runtimeResponse();

    const normalized = url.pathname.replace(/\/+$/, "") || "/";
    const isCareersPage =
      normalized === "/careers" ||
      normalized.startsWith("/careers/") ||
      normalized === "/apply" ||
      normalized.startsWith("/apply/");
    const isDemoPage =
      normalized === "/book-a-demo" || normalized.startsWith("/book-a-demo/");
    if (!isCareersPage && !isDemoPage) {
      return new Response("Not found", { status: 404 });
    }

    const originUrl = new URL(url.pathname + url.search, MARKETING_ORIGIN);
    const originHeaders = new Headers(request.headers);
    originHeaders.delete("host");
    originHeaders.delete("cf-connecting-ip");
    originHeaders.delete("cf-ipcountry");
    originHeaders.delete("cf-ray");

    const response = await fetch(
      new Request(originUrl, {
        method: request.method,
        headers: originHeaders,
        redirect: "follow",
      }),
    );

    const contentType = response.headers.get("content-type") || "";
    if (!response.ok || !contentType.includes("text/html")) return response;
    return injectRuntime(response);
  },
};
