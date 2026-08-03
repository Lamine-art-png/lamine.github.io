const UPSTREAM_ORIGIN = "https://402f33dd.agroai-343.pages.dev";
const NOTIFICATION_URL = "https://api.agroai-pilot.com/v1/sales/contact";
const MAX_REQUEST_BYTES = 12 * 1024 * 1024;
const MAX_MESSAGE_CHARS = 7000;

const ROUTES = new Map([
  ["/api/apply", "career_application"],
  ["/api/apply/", "career_application"],
  ["/api/consultation-requests", "demo_request"],
  ["/api/consultation-requests/", "demo_request"],
  ["/api/demo-request", "demo_request"],
  ["/api/demo-request/", "demo_request"],
]);

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-agroai-form-gateway": "active",
      ...headers,
    },
  });
}

function bounded(value, limit = 1000) {
  return String(value ?? "").replace(/\u0000/g, "").trim().slice(0, limit);
}

function validEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

async function parseSubmission(request, bytes) {
  const contentType = request.headers.get("content-type") || "";
  const fields = {};
  const files = [];

  if (contentType.includes("application/json")) {
    const text = new TextDecoder().decode(bytes);
    const payload = JSON.parse(text || "{}");
    for (const [key, value] of Object.entries(payload)) {
      if (value === null || value === undefined) continue;
      if (typeof value === "object") {
        fields[key] = bounded(JSON.stringify(value), 2500);
      } else {
        fields[key] = bounded(value, 2500);
      }
    }
    return { fields, files };
  }

  const formRequest = new Request("https://form-gateway.invalid/submit", {
    method: "POST",
    headers: { "content-type": contentType },
    body: bytes.slice(0),
  });
  const form = await formRequest.formData();
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") {
      fields[key] = bounded(value, 2500);
    } else {
      files.push({
        field: bounded(key, 100),
        filename: bounded(value.name || "attachment", 240),
        contentType: bounded(value.type || "application/octet-stream", 120),
        size: Number(value.size || 0),
      });
    }
  }
  return { fields, files };
}

function identity(fields) {
  const name = bounded(
    fields.fullName || fields.name || fields.full_name || fields.contactName || fields.contact_name || "Website submission",
    180,
  );
  const email = bounded(fields.email || fields.emailAddress || fields.email_address || "", 240);
  const company = bounded(
    fields.farmName || fields.company || fields.organization || fields.farm_name || "Website lead",
    180,
  );
  const role = bounded(fields.role || fields.position || fields.jobTitle || "General application", 180);
  return { name, email, company, role };
}

function notificationPayload(kind, route, fields, files) {
  const { name, email, company, role } = identity(fields);
  const fieldLines = Object.entries(fields).map(([key, value]) => `${key}: ${value || "Not provided"}`);
  for (const file of files) {
    fieldLines.push(`${file.field}: ${file.filename} (${file.contentType}, ${file.size} bytes)`);
  }

  const isCareer = kind === "career_application";
  const subject = isCareer
    ? `Career application: ${role} — ${name}`
    : `Book a Demo request: ${company !== "Website lead" ? company : name}`;

  return {
    type: "sales",
    priority: "high",
    name,
    email,
    company,
    role: isCareer ? role : "Demo request",
    subject: subject.slice(0, 180),
    message: [
      `Submission route: ${route}`,
      `Submission type: ${kind}`,
      "",
      ...fieldLines,
    ].join("\n").slice(0, MAX_MESSAGE_CHARS),
    source_page: isCareer ? "careers-application" : "book-a-demo",
    metadata: {
      form_notification_gateway: true,
      route,
      submission_type: kind,
      file_count: files.length,
    },
  };
}

async function notify(payload) {
  try {
    const response = await fetch(NOTIFICATION_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "x-agroai-source": "form-notification-gateway",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    const delivered =
      response.ok &&
      result.status === "received" &&
      typeof result.notification_status === "string" &&
      result.notification_status.startsWith("emailed:");
    return {
      delivered,
      requestId: bounded(result.request_id || "", 120),
      reason: delivered
        ? "delivered"
        : bounded(result.notification_status || result.detail || `http_${response.status}`, 240),
    };
  } catch (error) {
    return {
      delivered: false,
      requestId: "",
      reason: bounded(error instanceof Error ? error.message : "notification_network_error", 240),
    };
  }
}

function upstreamRequest(request, bytes) {
  const incoming = new URL(request.url);
  const target = new URL(`${incoming.pathname}${incoming.search}`, UPSTREAM_ORIGIN);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.delete("cf-connecting-ip");
  headers.delete("cf-ipcountry");
  headers.delete("cf-ray");
  headers.set("x-agroai-form-gateway", "1");
  return new Request(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : bytes.slice(0),
    redirect: "manual",
  });
}

function withGatewayHeaders(response, notification, requestId = "") {
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store");
  headers.set("x-agroai-form-gateway", "active");
  headers.set("x-agroai-notification", notification);
  if (requestId) headers.set("x-agroai-notification-request-id", requestId);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const kind = ROUTES.get(url.pathname);
    if (!kind) return json({ ok: false, error: "not_found" }, 404);

    if (request.method === "GET" && kind === "career_application") {
      return json({
        ok: true,
        endpoint: "/api/apply",
        status: "AGRO-AI form notification gateway is live.",
        notification_recipient: "contact@agroai-pilot.com",
      });
    }

    if (request.method !== "POST") {
      return json({ ok: false, error: "method_not_allowed" }, 405, { allow: "POST" });
    }

    const declaredLength = Number(request.headers.get("content-length") || 0);
    if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
      return json({ ok: false, error: "submission_too_large" }, 413);
    }

    let bytes;
    try {
      bytes = await request.arrayBuffer();
    } catch {
      return json({ ok: false, error: "invalid_request_body" }, 400);
    }
    if (bytes.byteLength > MAX_REQUEST_BYTES) {
      return json({ ok: false, error: "submission_too_large" }, 413);
    }

    let parsed;
    try {
      parsed = await parseSubmission(request, bytes);
    } catch {
      return json({ ok: false, error: "invalid_submission" }, 400);
    }

    const { name, email } = identity(parsed.fields);
    if (!name || !validEmail(email)) {
      return json({ ok: false, error: "name_and_valid_email_required" }, 400);
    }

    let upstream;
    try {
      upstream = await fetch(upstreamRequest(request, bytes));
    } catch (error) {
      return json(
        {
          ok: false,
          error: "submission_storage_unavailable",
          detail: bounded(error instanceof Error ? error.message : "upstream_network_error", 240),
        },
        502,
        { "x-agroai-notification": "not_attempted" },
      );
    }

    if (!upstream.ok) {
      return withGatewayHeaders(upstream, "not_attempted");
    }

    const payload = notificationPayload(kind, url.pathname, parsed.fields, parsed.files);
    const notification = await notify(payload);
    if (!notification.delivered) {
      return json(
        {
          ok: false,
          saved: true,
          error: "notification_delivery_failed",
          message:
            "Your submission was saved, but AGRO-AI did not receive the inbox notification. Please email contact@agroai-pilot.com.",
          reason: notification.reason,
        },
        502,
        { "x-agroai-notification": "failed" },
      );
    }

    return withGatewayHeaders(upstream, "delivered", notification.requestId);
  },
};
