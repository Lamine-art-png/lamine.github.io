const APPLICATION_ORIGIN = "__APPLICATION_ORIGIN__";
const SALES_NOTIFICATION_URL = "https://api.agroai-pilot.com/v1/sales/contact";
const MAX_TEXT_LENGTH = 4000;
const MAX_REQUEST_BYTES = 12 * 1024 * 1024;

function bounded(value, limit = MAX_TEXT_LENGTH) {
  return String(value ?? "").replace(/\u0000/g, "").trim().slice(0, limit);
}

function applicantFields(form) {
  const text = {};
  const files = [];
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") {
      text[key] = bounded(value);
    } else if (value && value.name) {
      files.push({
        field: bounded(key, 100),
        name: bounded(value.name, 240),
        type: bounded(value.type || "application/octet-stream", 120),
        size: Number(value.size || 0),
      });
    }
  }
  return { text, files };
}

function notificationPayload(form) {
  const { text, files } = applicantFields(form);
  const name = bounded(text.name || text.fullName || "Career applicant", 160);
  const email = bounded(text.email || "", 240);
  const role = bounded(text.role || text.position || "General application", 160);
  const lines = Object.entries(text).map(([key, value]) => `${key}: ${value || "Not provided"}`);
  for (const file of files) {
    lines.push(`${file.field}: ${file.name} (${file.type}, ${file.size} bytes)`);
  }
  return {
    type: "sales",
    priority: "high",
    name,
    email,
    company: "Career applicant",
    role,
    subject: `Career application: ${role} — ${name}`.slice(0, 180),
    message: lines.join("\n").slice(0, MAX_TEXT_LENGTH),
    source_page: "careers-application-notification-bridge",
    metadata: {
      notification_bridge: true,
      application_origin: new URL(APPLICATION_ORIGIN).hostname,
      file_count: files.length,
    },
  };
}

async function sendNotification(form) {
  const payload = notificationPayload(form);
  let lastReason = "notification_failed";
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(SALES_NOTIFICATION_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json",
          "x-agroai-source": "careers-notification-bridge",
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (
        response.ok &&
        result.status === "received" &&
        result.notification_status === "emailed:contact@agroai-pilot.com"
      ) {
        return { ok: true, requestId: result.request_id || null };
      }
      lastReason = bounded(result.notification_status || result.detail || `http_${response.status}`, 240);
    } catch (error) {
      lastReason = bounded(error instanceof Error ? error.message : "network_error", 240);
    }
    if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, attempt * 250));
  }
  return { ok: false, reason: lastReason };
}

function proxyRequest(request, bodyBytes = null) {
  const incoming = new URL(request.url);
  const target = new URL(`${incoming.pathname}${incoming.search}`, APPLICATION_ORIGIN);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.set("x-agroai-careers-bridge", "1");
  return new Request(target, {
    method: request.method,
    headers,
    body: bodyBytes ? bodyBytes.slice(0) : undefined,
    redirect: "manual",
  });
}

function bridged(response, notificationStatus = null) {
  const headers = new Headers(response.headers);
  headers.set("x-agroai-careers-bridge", "active");
  headers.set("cache-control", "no-store");
  if (notificationStatus) headers.set("x-agroai-careers-notification", notificationStatus);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function bodyTooLarge() {
  return new Response(JSON.stringify({ ok: false, error: "application_too_large" }), {
    status: 413,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-agroai-careers-bridge": "active",
    },
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/apply") {
      return new Response("Not found", {
        status: 404,
        headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" },
      });
    }

    let bodyBytes = null;
    if (request.method === "POST") {
      const declaredLength = Number(request.headers.get("content-length") || 0);
      if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) return bodyTooLarge();
      bodyBytes = await request.arrayBuffer();
      if (bodyBytes.byteLength > MAX_REQUEST_BYTES) return bodyTooLarge();
    }

    const upstream = await fetch(proxyRequest(request, bodyBytes));
    if (request.method !== "POST" || !upstream.ok || !bodyBytes) return bridged(upstream);

    const applicationResult = await upstream.clone().json().catch(() => null);
    if (!applicationResult || applicationResult.ok !== true) return bridged(upstream);

    let form;
    try {
      const contentType = request.headers.get("content-type") || "";
      const formRequest = new Request("https://careers-bridge.invalid/api/apply", {
        method: "POST",
        headers: { "content-type": contentType },
        body: bodyBytes.slice(0),
      });
      form = await formRequest.formData();
    } catch {
      return bridged(upstream);
    }

    const notification = await sendNotification(form);
    if (notification.ok) return bridged(upstream, "delivered");

    return new Response(
      JSON.stringify({
        ...applicationResult,
        emailNotification: {
          sent: false,
          reason: "Application saved, but AGRO-AI notification delivery failed.",
        },
        notificationBridge: {
          sent: false,
          reason: notification.reason,
        },
      }),
      {
        status: 502,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "no-store",
          "x-agroai-careers-bridge": "active",
          "x-agroai-careers-notification": "failed",
        },
      },
    );
  },
};
