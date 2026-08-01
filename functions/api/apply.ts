interface Env {
  RESEND_API_KEY?: string;
  FROM_EMAIL?: string;
}

interface PagesContext {
  request: Request;
  env: Env;
}

const APPLICATION_NOTIFICATION_EMAIL = "contact@agroai-pilot.com";
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

function json(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function parseSubmission(request: Request): Promise<{
  fields: Record<string, string>;
  attachments: Array<{ filename: string; content: string }>;
}> {
  const contentType = request.headers.get("content-type") || "";
  const fields: Record<string, string> = {};
  const attachments: Array<{ filename: string; content: string }> = [];

  if (contentType.includes("application/json")) {
    const payload = (await request.json()) as Record<string, unknown>;
    for (const [key, value] of Object.entries(payload)) {
      if (value !== null && value !== undefined && typeof value !== "object") {
        fields[key] = String(value).trim();
      }
    }
    return { fields, attachments };
  }

  const form = await request.formData();
  let totalAttachmentBytes = 0;
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") {
      fields[key] = value.trim();
      continue;
    }

    if (!value.size) continue;
    totalAttachmentBytes += value.size;
    if (totalAttachmentBytes > MAX_ATTACHMENT_BYTES) {
      throw new Error("attachments_too_large");
    }
    const bytes = new Uint8Array(await value.arrayBuffer());
    attachments.push({
      filename: value.name || `${key}.bin`,
      content: bytesToBase64(bytes),
    });
  }

  return { fields, attachments };
}

export async function onRequestPost({ request, env }: PagesContext): Promise<Response> {
  if (!env.RESEND_API_KEY) {
    return json({ ok: false, error: "email_delivery_not_configured" }, 503);
  }

  let submission: Awaited<ReturnType<typeof parseSubmission>>;
  try {
    submission = await parseSubmission(request);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "invalid_submission";
    return json({ ok: false, error: reason }, reason === "attachments_too_large" ? 413 : 400);
  }

  const { fields, attachments } = submission;
  const applicantName = fields.name || fields.fullName || fields.full_name || "Applicant";
  const applicantEmail = fields.email || fields.emailAddress || fields.email_address || "";
  const role = fields.role || fields.position || fields.job || fields.jobTitle || "General application";

  const fieldLines = Object.entries(fields)
    .map(([key, value]) => `${key}: ${value || "Not provided"}`)
    .join("\n");
  const fieldHtml = Object.entries(fields)
    .map(
      ([key, value]) =>
        `<p><strong>${escapeHtml(key)}:</strong> ${escapeHtml(value || "Not provided")}</p>`,
    )
    .join("");

  const payload: Record<string, unknown> = {
    from: env.FROM_EMAIL || "AGRO-AI Careers <contact@agroai-pilot.com>",
    to: [APPLICATION_NOTIFICATION_EMAIL],
    subject: `AGRO-AI career application: ${role} - ${applicantName}`,
    text: `New AGRO-AI career application\n\n${fieldLines}`,
    html: `<h2>New AGRO-AI career application</h2>${fieldHtml}`,
  };

  if (isEmail(applicantEmail)) {
    payload.reply_to = applicantEmail;
  }
  if (attachments.length) {
    payload.attachments = attachments;
  }

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const providerMessage = (await response.text()).slice(0, 500);
    console.error("Career application email failed", response.status, providerMessage);
    return json({ ok: false, error: "email_delivery_failed" }, 502);
  }

  return json({ ok: true, message: "Application received." });
}

export async function onRequest(context: PagesContext): Promise<Response> {
  if (context.request.method === "POST") {
    return onRequestPost(context);
  }
  return json({ ok: false, error: "method_not_allowed" }, 405);
}
