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
      const key = clean(field.name || field.id || `field_${index + 1}`);
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

  const prepareForms = () => {
    document.querySelectorAll("form").forEach((form) => {
      if (isTargetForm(form)) {
        form.noValidate = true;
        form.setAttribute("data-agroai-authoritative-form", isDemo ? "demo" : "careers");
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
        if (!response.ok || response.headers.get("x-agroai-notification") !== "delivered") {
          throw new Error(
            clean(result.message || result.error) ||
              "Demo request delivery could not be confirmed.",
          );
        }
        showSuccess(
          form,
          "Demo request received",
          "Your request was received, and the AGRO-AI team notification was confirmed. We will follow up directly.",
        );
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
