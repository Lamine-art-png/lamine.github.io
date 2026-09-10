interface Env {
  RESEND_API_KEY?: string;
  FROM_EMAIL?: string;
}

interface PagesContext {
  request: Request;
  env: Env;
}

const NOTIFICATION_EMAIL = "contact@agroai-pilot.com";
const ALLOWED_INTERESTS = new Set(["Minha fazenda", "Sindicato ou cooperativa", "Ambos"]);

function json(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function clean(value: unknown, maxLength = 500): string {
  return String(value ?? "")
    .replace(/\u0000/g, "")
    .trim()
    .slice(0, maxLength);
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizeWhatsApp(value: string): string {
  const compact = value.replace(/[^\d+]/g, "");
  return compact.startsWith("+") ? compact : value.trim();
}

export async function onRequestPost({ request, env }: PagesContext): Promise<Response> {
  if (!env.RESEND_API_KEY) {
    console.error("FAEP form email delivery is not configured: RESEND_API_KEY missing");
    return json({ ok: false, error: "email_delivery_not_configured" }, 503);
  }

  let payload: Record<string, unknown>;
  try {
    const contentType = request.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = (await request.json()) as Record<string, unknown>;
    } else {
      const form = await request.formData();
      payload = Object.fromEntries(
        Array.from(form.entries()).map(([key, value]) => [key, typeof value === "string" ? value : ""]),
      );
    }
  } catch {
    return json({ ok: false, error: "invalid_submission" }, 400);
  }

  // Honeypot: bots tend to fill hidden fields. Return success without sending mail.
  if (clean(payload.website, 120)) {
    return json({ ok: true, message: "Recebido." }, 201);
  }

  const nome = clean(payload.nome, 120);
  const whatsapp = normalizeWhatsApp(clean(payload.whatsapp, 60));
  const atividade = clean(payload.atividade, 120);
  const area = clean(payload.area, 80) || "Não informado";
  const problema = clean(payload.problema, 1200);
  const interesse = clean(payload.interesse, 80);
  const consentimento = clean(payload.consentimento, 20);

  if (!nome || !whatsapp || !atividade || !problema || !interesse || !consentimento) {
    return json({ ok: false, error: "missing_required_fields" }, 400);
  }
  if (!ALLOWED_INTERESTS.has(interesse)) {
    return json({ ok: false, error: "invalid_interest" }, 400);
  }
  if (whatsapp.replace(/\D/g, "").length < 10) {
    return json({ ok: false, error: "invalid_whatsapp" }, 400);
  }

  const submittedAt = new Date().toISOString();
  const subject = `FAEP Paraná — ${nome} — ${atividade}`;
  const text = [
    "Novo interesse — Delegação Sistema FAEP / AGRO-AI",
    "",
    `Nome: ${nome}`,
    `WhatsApp: ${whatsapp}`,
    `Principal atividade: ${atividade}`,
    `Área aproximada: ${area}`,
    `Interesse: ${interesse}`,
    "",
    "Principal problema que gostaria de melhorar:",
    problema,
    "",
    `Consentimento para contato: ${consentimento}`,
    `Enviado em: ${submittedAt}`,
    "Origem: agroai-pilot.com/faep",
  ].join("\n");

  const html = `
    <div style="font-family:Arial,sans-serif;line-height:1.55;color:#172219;max-width:680px">
      <h2 style="color:#234224;margin-bottom:20px">Novo interesse — Delegação Sistema FAEP</h2>
      <p><strong>Nome:</strong> ${escapeHtml(nome)}</p>
      <p><strong>WhatsApp:</strong> ${escapeHtml(whatsapp)}</p>
      <p><strong>Principal atividade:</strong> ${escapeHtml(atividade)}</p>
      <p><strong>Área aproximada:</strong> ${escapeHtml(area)}</p>
      <p><strong>Interesse:</strong> ${escapeHtml(interesse)}</p>
      <div style="margin:24px 0;padding:18px;border-left:4px solid #2c6400;background:#f5f8f3">
        <strong>Principal problema que gostaria de melhorar</strong>
        <p style="margin:8px 0 0">${escapeHtml(problema).replaceAll("\n", "<br>")}</p>
      </div>
      <p><strong>Consentimento para contato:</strong> ${escapeHtml(consentimento)}</p>
      <p style="font-size:12px;color:#657166;margin-top:28px">Enviado em ${escapeHtml(submittedAt)} · agroai-pilot.com/faep</p>
    </div>`;

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from: env.FROM_EMAIL || "AGRO-AI FAEP <contact@agroai-pilot.com>",
      to: [NOTIFICATION_EMAIL],
      subject,
      text,
      html,
    }),
  });

  if (!response.ok) {
    const providerMessage = (await response.text()).slice(0, 500);
    console.error("FAEP interest email failed", response.status, providerMessage);
    return json({ ok: false, error: "email_delivery_failed" }, 502);
  }

  return json({
    ok: true,
    message: "Recebemos suas informações. A equipe AGRO-AI entrará em contato pelo WhatsApp.",
  }, 201);
}

export async function onRequest(context: PagesContext): Promise<Response> {
  if (context.request.method === "POST") return onRequestPost(context);
  return json({ ok: false, error: "method_not_allowed" }, 405);
}
